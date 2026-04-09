#!/usr/bin/env python3
"""cache.py — Multi-layer search result cache.

Usage:
    python3 wiki-cache.py check <channel> <query> [--cache-db <path>]
    python3 wiki-cache.py store <channel> <query> <results_json> [--cache-db <path>]
    python3 wiki-cache.py write-response <query> <response> [--source-pages <json>] [--cache-db <path>]
    python3 wiki-cache.py read-response <query> [--cache-db <path>]
    python3 wiki-cache.py write-merged <queries_json> <results_json> [--cache-db <path>]
    python3 wiki-cache.py read-merged <queries_json> [--cache-db <path>]
    python3 wiki-cache.py stats [--cache-db <path>]
    python3 wiki-cache.py clear [<channel>] [--cache-db <path>]
    python3 wiki-cache.py purge-stale [--cache-db <path>]

Layer 1 (response_cache): wiki-query answers. TTL 1 day.
Layer 2 (search_cache): per-channel search results. TTL varies by channel.
Layer 3 (merged_cache): search-merger ranked output. TTL 3 days.

Channels: web, academic, code, docs
TTLs: web=7d, academic=30d, code=3d, docs=7d
Default cache-db: state/wiki/cache/search.db
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Channel TTLs in days
CHANNEL_TTLS = {
    "web": 7,
    "academic": 30,
    "code": 3,
    "docs": 7,
}

# Topic-aware TTL overrides (keywords → days)
# If a query matches these keywords, use a shorter/longer cache TTL
TOPIC_TTL_OVERRIDES = {
    1: {"breaking", "incident", "outage", "live", "score"},          # 1 day
    3: {"news", "current", "trending", "announcement", "release"},   # 3 days
    7: {"ai", "llm", "mcp", "claude", "gpt", "api", "benchmark"},   # 7 days (default web)
    14: {"version", "framework", "library", "tool", "software"},     # 14 days
    60: {"paper", "research", "study", "algorithm", "theorem"},      # 60 days
}


def get_topic_ttl(query: str, channel: str = "web") -> int:
    """Get a topic-aware TTL in days for a search cache entry.

    Checks query keywords against topic overrides, falls back to channel default.
    """
    query_lower = query.lower()
    for ttl_days, keywords in sorted(TOPIC_TTL_OVERRIDES.items()):
        if any(kw in query_lower for kw in keywords):
            return ttl_days
    return CHANNEL_TTLS.get(channel, 7)


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Search result cache with per-channel TTLs"
    )
    parser.add_argument(
        "command",
        choices=[
            "check",
            "store",
            "write-response",
            "read-response",
            "write-merged",
            "read-merged",
            "stats",
            "clear",
            "purge-stale",
        ],
        help="Cache command",
    )
    parser.add_argument(
        "--source-pages",
        help="JSON array of source page slugs (for write-response)",
        default="[]",
    )
    parser.add_argument(
        "channel", nargs="?", help="Channel (web, academic, code, docs)"
    )
    parser.add_argument("query", nargs="?", help="Search query")
    parser.add_argument(
        "results_json", nargs="?", help="Results as JSON string (for store)"
    )
    parser.add_argument(
        "--cache-db",
        help="Cache database path",
        default=".wiki/cache/search.db",
    )
    return parser.parse_args()


def validate_channel(channel):
    """Validate channel name."""
    if channel not in CHANNEL_TTLS:
        print(
            f"Error: Invalid channel '{channel}'. Must be one of: {', '.join(CHANNEL_TTLS.keys())}",
            file=sys.stderr,
        )
        sys.exit(1)


def compute_query_hash(query):
    """Compute SHA256 hash of normalized query (first 16 chars)."""
    normalized = query.lower().strip()
    hash_obj = hashlib.sha256(normalized.encode("utf-8"))
    return hash_obj.hexdigest()[:16]


def parse_iso_datetime(iso_string):
    """Parse ISO 8601 datetime string and return as timezone-aware UTC datetime."""
    # Remove Z suffix and replace with +00:00
    if iso_string.endswith("Z"):
        iso_string = iso_string[:-1] + "+00:00"

    # Handle timezone offset — strip and assume UTC
    if "+" in iso_string[10:]:
        iso_string = iso_string.split("+")[0] + "+00:00"
    elif iso_string.count("-") > 2:  # Has timezone offset like -08:00
        iso_string = iso_string.rsplit("-", 1)[0] + "+00:00"
    else:
        # No timezone info — assume UTC
        iso_string = iso_string + "+00:00"

    return datetime.fromisoformat(iso_string)


def get_db_connection(db_path):
    """Get SQLite connection."""
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}", file=sys.stderr)
        sys.exit(1)


def init_database(conn):
    """Initialize database schema if not exists."""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                query TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                results TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                hit_count INTEGER DEFAULT 0,
                UNIQUE(channel, query_hash)
            )
            """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS response_cache (
                query_hash TEXT PRIMARY KEY,
                query_text TEXT NOT NULL,
                response TEXT NOT NULL,
                source_pages TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                ttl_days INTEGER DEFAULT 1
            )
            """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS merged_cache (
                query_hash TEXT PRIMARY KEY,
                queries TEXT NOT NULL,
                results TEXT NOT NULL,
                created_at TEXT NOT NULL,
                ttl_days INTEGER DEFAULT 3
            )
            """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS revalidation_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                query TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                queued_at TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                UNIQUE(channel, query_hash)
            )
            """)
        conn.commit()
    except Exception as e:
        print(f"Error initializing database: {e}", file=sys.stderr)
        sys.exit(1)


def command_check(conn, channel, query):
    """Check cache for query. Return results if found and not expired.

    Supports stale-while-revalidate: if expired but within 25% grace window,
    returns stale result and queues a background revalidation.

    Supports adaptive TTL: if hit_count > 5, entry gets double TTL.
    """
    validate_channel(channel)
    query_hash = compute_query_hash(query)

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT results, expires_at, hit_count FROM search_cache
            WHERE channel = ? AND query_hash = ?
            """,
            (channel, query_hash),
        )
        row = cursor.fetchone()

        if not row:
            sys.exit(1)

        results_json, expires_at, hit_count = row
        expires_dt = parse_iso_datetime(expires_at)
        now = datetime.now(UTC)

        if now > expires_dt:
            # Check stale-while-revalidate grace period (25% of TTL)
            ttl_days = CHANNEL_TTLS[channel]
            # Adaptive TTL: double if frequently accessed
            if hit_count and hit_count > 5:
                ttl_days *= 2
            grace_seconds = ttl_days * 24 * 3600 * 0.25
            grace_dt = expires_dt + timedelta(seconds=grace_seconds)

            if now <= grace_dt:
                # Within grace period — return stale, queue revalidation
                cursor.execute(
                    "UPDATE search_cache SET hit_count = hit_count + 1 WHERE channel = ? AND query_hash = ?",
                    (channel, query_hash),
                )
                # Queue for background revalidation
                try:
                    cursor.execute(
                        """INSERT OR IGNORE INTO revalidation_queue
                           (channel, query, query_hash, queued_at)
                           VALUES (?, ?, ?, ?)""",
                        (channel, query, query_hash, now.isoformat() + "Z"),
                    )
                except sqlite3.OperationalError:
                    pass  # revalidation_queue table may not exist yet
                conn.commit()
                print(results_json, end="")
                sys.exit(0)

            # Fully expired
            sys.exit(1)

        # Hit found and not expired
        cursor.execute(
            "UPDATE search_cache SET hit_count = hit_count + 1 WHERE channel = ? AND query_hash = ?",
            (channel, query_hash),
        )
        conn.commit()

        print(results_json, end="")
        sys.exit(0)
    except sqlite3.Error as e:
        print(f"Error checking cache: {e}", file=sys.stderr)
        sys.exit(1)


def command_store(conn, channel, query, results_json):
    """Store results in cache."""
    validate_channel(channel)
    query_hash = compute_query_hash(query)

    # Validate JSON
    try:
        json.loads(results_json)
    except json.JSONDecodeError:
        print("Error: Invalid JSON in results", file=sys.stderr)
        sys.exit(1)

    # Compute TTL
    ttl_days = CHANNEL_TTLS[channel]
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=ttl_days)

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO search_cache (channel, query, query_hash, results, created_at, expires_at, hit_count)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(channel, query_hash) DO UPDATE SET
                results = excluded.results,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at,
                hit_count = 0
            """,
            (
                channel,
                query,
                query_hash,
                results_json,
                now.isoformat() + "Z",
                expires_at.isoformat() + "Z",
            ),
        )
        conn.commit()
        print(f"Cached: {channel}/{query_hash}", file=sys.stderr)
        sys.exit(0)
    except sqlite3.Error as e:
        print(f"Error storing cache: {e}", file=sys.stderr)
        sys.exit(1)


def command_stats(conn):
    """Print cache statistics for all layers."""
    try:
        cursor = conn.cursor()

        # Layer 2: search_cache
        cursor.execute("""
            SELECT
                channel,
                COUNT(*) as entries,
                SUM(hit_count) as hits,
                SUM(CASE WHEN expires_at < datetime('now') THEN 1 ELSE 0 END) as expired_count
            FROM search_cache
            GROUP BY channel
            ORDER BY channel
            """)
        rows = cursor.fetchall()

        print("=== Search Cache (Layer 2) ===")
        if rows:
            print("Channel       Entries  Hits      Expired")
            print("-" * 50)
            for channel, entries, hits, expired in rows:
                print(f"{channel:13} {entries or 0:7}  {hits or 0:9}  {expired or 0:7}")
        else:
            print("  (empty)")

        # Layer 1: response_cache
        cursor.execute("SELECT COUNT(*) FROM response_cache")
        resp_count = cursor.fetchone()[0]
        print(f"\n=== Response Cache (Layer 1) === {resp_count} entries")

        # Layer 3: merged_cache
        cursor.execute("SELECT COUNT(*) FROM merged_cache")
        merged_count = cursor.fetchone()[0]
        print(f"\n=== Merged Cache (Layer 3) === {merged_count} entries")

        sys.exit(0)
    except sqlite3.Error as e:
        print(f"Error getting stats: {e}", file=sys.stderr)
        sys.exit(1)


def command_clear(conn, channel=None):
    """Delete all entries or entries for specific channel."""
    try:
        cursor = conn.cursor()

        if channel:
            validate_channel(channel)
            cursor.execute("DELETE FROM search_cache WHERE channel = ?", (channel,))
        else:
            cursor.execute("DELETE FROM search_cache")

        conn.commit()
        print(f"Deleted {cursor.rowcount} entries", file=sys.stderr)
        sys.exit(0)
    except sqlite3.Error as e:
        print(f"Error clearing cache: {e}", file=sys.stderr)
        sys.exit(1)


def command_write_response(conn, query, response, source_pages="[]"):
    """Cache a wiki-query response."""
    query_hash = compute_query_hash(query)
    now = datetime.now(UTC)
    try:
        json.loads(source_pages)
    except json.JSONDecodeError:
        source_pages = "[]"

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO response_cache (query_hash, query_text, response, source_pages, created_at, ttl_days)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(query_hash) DO UPDATE SET
                response = excluded.response,
                source_pages = excluded.source_pages,
                created_at = excluded.created_at
            """,
            (query_hash, query, response, source_pages, now.isoformat() + "Z"),
        )
        conn.commit()
        print(f"Cached response: {query_hash}", file=sys.stderr)
        sys.exit(0)
    except sqlite3.Error as e:
        print(f"Error writing response cache: {e}", file=sys.stderr)
        sys.exit(1)


def command_read_response(conn, query):
    """Read a cached wiki-query response. Exit 0 if hit, 1 if miss/expired."""
    query_hash = compute_query_hash(query)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT response, source_pages, created_at, ttl_days FROM response_cache WHERE query_hash = ?",
            (query_hash,),
        )
        row = cursor.fetchone()
        if not row:
            sys.exit(1)

        response, source_pages, created_at, ttl_days = row
        created_dt = parse_iso_datetime(created_at)
        if datetime.now(UTC) > created_dt + timedelta(days=ttl_days):
            sys.exit(1)

        result = {
            "response": response,
            "source_pages": json.loads(source_pages),
            "cached_at": created_at,
        }
        print(json.dumps(result), end="")
        sys.exit(0)
    except sqlite3.Error as e:
        print(f"Error reading response cache: {e}", file=sys.stderr)
        sys.exit(1)


def command_write_merged(conn, queries_json, results_json):
    """Cache merged search results."""
    try:
        queries = json.loads(queries_json)
    except json.JSONDecodeError:
        print("Error: Invalid JSON in queries", file=sys.stderr)
        sys.exit(1)
    try:
        json.loads(results_json)
    except json.JSONDecodeError:
        print("Error: Invalid JSON in results", file=sys.stderr)
        sys.exit(1)

    # Hash the sorted query set for stable keys
    normalized = json.dumps(sorted(q.lower().strip() for q in queries))
    query_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    now = datetime.now(UTC)

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO merged_cache (query_hash, queries, results, created_at, ttl_days)
            VALUES (?, ?, ?, ?, 3)
            ON CONFLICT(query_hash) DO UPDATE SET
                results = excluded.results,
                created_at = excluded.created_at
            """,
            (query_hash, queries_json, results_json, now.isoformat() + "Z"),
        )
        conn.commit()
        print(f"Cached merged: {query_hash}", file=sys.stderr)
        sys.exit(0)
    except sqlite3.Error as e:
        print(f"Error writing merged cache: {e}", file=sys.stderr)
        sys.exit(1)


def command_read_merged(conn, queries_json):
    """Read cached merged results. Exit 0 if hit, 1 if miss/expired."""
    try:
        queries = json.loads(queries_json)
    except json.JSONDecodeError:
        print("Error: Invalid JSON in queries", file=sys.stderr)
        sys.exit(1)

    normalized = json.dumps(sorted(q.lower().strip() for q in queries))
    query_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT results, created_at, ttl_days FROM merged_cache WHERE query_hash = ?",
            (query_hash,),
        )
        row = cursor.fetchone()
        if not row:
            sys.exit(1)

        results, created_at, ttl_days = row
        created_dt = parse_iso_datetime(created_at)
        if datetime.now(UTC) > created_dt + timedelta(days=ttl_days):
            sys.exit(1)

        print(results, end="")
        sys.exit(0)
    except sqlite3.Error as e:
        print(f"Error reading merged cache: {e}", file=sys.stderr)
        sys.exit(1)


def command_purge_stale(conn):
    """Delete expired entries from all cache layers."""
    try:
        cursor = conn.cursor()
        now_iso = datetime.now(UTC).isoformat() + "Z"

        cursor.execute("DELETE FROM search_cache WHERE expires_at < datetime('now')")
        search_purged = cursor.rowcount

        cursor.execute(
            "DELETE FROM response_cache WHERE datetime(created_at, '+' || ttl_days || ' days') < ?",
            (now_iso,),
        )
        response_purged = cursor.rowcount

        cursor.execute(
            "DELETE FROM merged_cache WHERE datetime(created_at, '+' || ttl_days || ' days') < ?",
            (now_iso,),
        )
        merged_purged = cursor.rowcount

        conn.commit()
        print(
            f"Purged: search={search_purged}, response={response_purged}, merged={merged_purged}",
            file=sys.stderr,
        )
        sys.exit(0)
    except sqlite3.Error as e:
        print(f"Error purging stale: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """Main entry point."""
    args = parse_arguments()

    # Ensure cache directory exists
    db_path = args.cache_db
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Error creating cache directory: {e}", file=sys.stderr)
        sys.exit(1)

    # Connect to database
    conn = get_db_connection(db_path)
    init_database(conn)

    try:
        if args.command == "check":
            if not args.channel or not args.query:
                print("Error: check requires <channel> <query>", file=sys.stderr)
                sys.exit(1)
            command_check(conn, args.channel, args.query)

        elif args.command == "store":
            if not args.channel or not args.query or not args.results_json:
                print(
                    "Error: store requires <channel> <query> <results_json>",
                    file=sys.stderr,
                )
                sys.exit(1)
            command_store(conn, args.channel, args.query, args.results_json)

        elif args.command == "write-response":
            if not args.channel or not args.query:
                print(
                    "Error: write-response requires <query> <response>",
                    file=sys.stderr,
                )
                sys.exit(1)
            command_write_response(conn, args.channel, args.query, args.source_pages)

        elif args.command == "read-response":
            if not args.channel:
                print("Error: read-response requires <query>", file=sys.stderr)
                sys.exit(1)
            command_read_response(conn, args.channel)

        elif args.command == "write-merged":
            if not args.channel or not args.query:
                print(
                    "Error: write-merged requires <queries_json> <results_json>",
                    file=sys.stderr,
                )
                sys.exit(1)
            command_write_merged(conn, args.channel, args.query)

        elif args.command == "read-merged":
            if not args.channel:
                print(
                    "Error: read-merged requires <queries_json>",
                    file=sys.stderr,
                )
                sys.exit(1)
            command_read_merged(conn, args.channel)

        elif args.command == "stats":
            command_stats(conn)

        elif args.command == "clear":
            command_clear(conn, args.channel)

        elif args.command == "purge-stale":
            command_purge_stale(conn)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
