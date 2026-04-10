#!/usr/bin/env python3
"""cache.py — Multi-layer search result cache.

Usage:
    python3 wiki-cache.py check <channel> <query> [--cache-db <path>]
    python3 wiki-cache.py store <channel> <query> <results_json> [--cache-db <path>]
    python3 wiki-cache.py write-merged <queries_json> <results_json> [--cache-db <path>]
    python3 wiki-cache.py read-merged <queries_json> [--cache-db <path>]
    python3 wiki-cache.py stats [--cache-db <path>]
    python3 wiki-cache.py clear [<channel>] [--cache-db <path>]
    python3 wiki-cache.py purge-stale [--cache-db <path>]

Layer 2 (search_cache): per-channel search results. TTL varies by channel.
Layer 3 (merged_cache): search-merger ranked output. TTL 3 days.

Channels: web, academic, code, docs, wikipedia
TTLs: web=7d, academic=30d, code=3d, docs=7d, wikipedia=30d
Default cache-db: state/wiki/cache/search.db
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from wiki_logging import get_logger
from exceptions import CacheError, CacheMissError

logger = get_logger(__name__)

# Channel TTLs in days
CHANNEL_TTLS = {
    "web": 7,
    "academic": 30,
    "code": 3,
    "docs": 7,
    "wikipedia": 30,
}

# Topic-aware TTLs for cache entries (maps freshness tier to cache TTL in days)
TOPIC_TTLS = {
    "live": 0.01,       # ~15 min
    "breaking": 0.25,   # ~6 hours
    "current": 1,       # 1 day
    "fast": 3,          # 3 days
    "moderate": 7,      # 1 week
    "standard": 7,      # 1 week (default)
    "academic": 30,     # 1 month
    "evergreen": 30,    # 1 month
    "permanent": 30,    # 1 month
}


def get_topic_ttl(freshness_tier: str) -> int:
    """Get cache TTL in days for a given freshness tier.

    Args:
        freshness_tier: One of live, breaking, current, fast, moderate, standard, academic, evergreen, permanent

    Returns:
        TTL in days for cache entries related to this topic type.
    """
    return TOPIC_TTLS.get(freshness_tier, TOPIC_TTLS["standard"])


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
            "write-merged",
            "read-merged",
            "stats",
            "clear",
            "purge-stale",
        ],
        help="Cache command",
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
        logger.debug("Database connection established", extra={"db_path": db_path})
        return conn
    except (sqlite3.Error, OSError) as e:
        logger.error("Database connection failed", extra={"db_path": db_path, "error": str(e)})
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
        logger.debug("Database schema initialized")
    except sqlite3.Error as e:
        logger.error("Database initialization failed", extra={"error": str(e)})
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
            logger.debug("Cache miss", extra={"channel": channel, "query_hash": query_hash})
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
                logger.info("Cache stale-while-revalidate hit", extra={"channel": channel, "query_hash": query_hash})
                print(results_json, end="")
                sys.exit(0)

            # Fully expired
            logger.debug("Cache expired", extra={"channel": channel, "query_hash": query_hash})
            sys.exit(1)

        # Hit found and not expired
        cursor.execute(
            "UPDATE search_cache SET hit_count = hit_count + 1 WHERE channel = ? AND query_hash = ?",
            (channel, query_hash),
        )
        conn.commit()

        logger.info("Cache hit", extra={"channel": channel, "query_hash": query_hash, "hit_count": hit_count + 1})
        print(results_json, end="")
        sys.exit(0)
    except sqlite3.Error as e:
        logger.error("Cache check failed", extra={"channel": channel, "query_hash": query_hash, "error": str(e)})
        sys.exit(1)


def command_store(conn, channel, query, results_json):
    """Store results in cache."""
    validate_channel(channel)
    query_hash = compute_query_hash(query)

    # Validate JSON
    try:
        json.loads(results_json)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in results", extra={"channel": channel, "query": query})
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
        logger.info("Cache stored", extra={"channel": channel, "query_hash": query_hash, "ttl_days": ttl_days})
        sys.exit(0)
    except sqlite3.Error as e:
        logger.error("Cache store failed", extra={"channel": channel, "query_hash": query_hash, "error": str(e)})
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

        # Layer 3: merged_cache
        cursor.execute("SELECT COUNT(*) FROM merged_cache")
        merged_count = cursor.fetchone()[0]
        print(f"\n=== Merged Cache (Layer 3) === {merged_count} entries")

        logger.debug("Cache stats retrieved", extra={"search_entries": sum(r[1] for r in rows) if rows else 0, "merged_entries": merged_count})
        sys.exit(0)
    except sqlite3.Error as e:
        logger.error("Cache stats retrieval failed", extra={"error": str(e)})
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
        logger.info("Cache cleared", extra={"channel": channel, "rows_deleted": cursor.rowcount})
        sys.exit(0)
    except sqlite3.Error as e:
        logger.error("Cache clear failed", extra={"channel": channel, "error": str(e)})
        sys.exit(1)


def command_write_merged(conn, queries_json, results_json):
    """Cache merged search results."""
    try:
        queries = json.loads(queries_json)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in queries")
        sys.exit(1)
    try:
        json.loads(results_json)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in results")
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
        logger.info("Merged results cached", extra={"query_hash": query_hash, "num_queries": len(queries)})
        sys.exit(0)
    except sqlite3.Error as e:
        logger.error("Merged cache write failed", extra={"query_hash": query_hash, "error": str(e)})
        sys.exit(1)


def command_read_merged(conn, queries_json):
    """Read cached merged results. Exit 0 if hit, 1 if miss/expired."""
    try:
        queries = json.loads(queries_json)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in queries")
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
            logger.debug("Merged cache miss", extra={"query_hash": query_hash})
            sys.exit(1)

        results, created_at, ttl_days = row
        created_dt = parse_iso_datetime(created_at)
        if datetime.now(UTC) > created_dt + timedelta(days=ttl_days):
            logger.debug("Merged cache expired", extra={"query_hash": query_hash})
            sys.exit(1)

        logger.info("Merged cache hit", extra={"query_hash": query_hash})
        print(results, end="")
        sys.exit(0)
    except sqlite3.Error as e:
        logger.error("Merged cache read failed", extra={"query_hash": query_hash, "error": str(e)})
        sys.exit(1)


def command_purge_stale(conn):
    """Delete expired entries from all cache layers."""
    try:
        cursor = conn.cursor()
        now_iso = datetime.now(UTC).isoformat() + "Z"

        cursor.execute("DELETE FROM search_cache WHERE expires_at < datetime('now')")
        search_purged = cursor.rowcount

        cursor.execute(
            "DELETE FROM merged_cache WHERE datetime(created_at, '+' || ttl_days || ' days') < ?",
            (now_iso,),
        )
        merged_purged = cursor.rowcount

        conn.commit()
        logger.info("Cache purged", extra={"search_purged": search_purged, "merged_purged": merged_purged})
        sys.exit(0)
    except sqlite3.Error as e:
        logger.error("Cache purge failed", extra={"error": str(e)})
        sys.exit(1)


def main():
    """Main entry point."""
    args = parse_arguments()

    # Ensure cache directory exists
    db_path = args.cache_db
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    except (OSError, IOError) as e:
        logger.error("Failed to create cache directory", extra={"db_path": db_path, "error": str(e)})
        sys.exit(1)

    # Connect to database
    conn = get_db_connection(db_path)
    init_database(conn)

    try:
        if args.command == "check":
            if not args.channel or not args.query:
                logger.error("check requires <channel> <query>")
                sys.exit(1)
            command_check(conn, args.channel, args.query)

        elif args.command == "store":
            if not args.channel or not args.query or not args.results_json:
                logger.error("store requires <channel> <query> <results_json>")
                sys.exit(1)
            command_store(conn, args.channel, args.query, args.results_json)

        elif args.command == "write-merged":
            # Positional reuse: args.channel=queries_json, args.query=results_json
            if not args.channel or not args.query:
                logger.error("write-merged requires <queries_json> <results_json>")
                sys.exit(1)
            command_write_merged(conn, args.channel, args.query)

        elif args.command == "read-merged":
            # Positional reuse: args.channel=queries_json
            if not args.channel:
                logger.error("read-merged requires <queries_json>")
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
