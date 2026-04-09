#!/usr/bin/env python3
"""backlinks.py — Backlink index for wiki pages.

Usage:
    python3 backlinks.py build <pages_dir>           — Full rebuild of backlink index
    python3 backlinks.py update <pages_dir> <slug>   — Update links for one page (O(k) not O(n))
    python3 backlinks.py query <pages_dir> <slug>    — Get all pages that link to <slug>
    python3 backlinks.py verify <pages_dir> <slug>   — Check bidirectional link consistency
    python3 backlinks.py stats <pages_dir>           — Link statistics (orphans, most-linked, etc.)
    python3 backlinks.py missing <pages_dir>         — List all [[links]] to non-existent pages
"""

import argparse
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from wiki_logging import get_logger
from exceptions import PageNotFoundError

logger = get_logger(__name__)


class BacklinkDB:
    """Manages wiki backlink index in SQLite."""

    LINK_PATTERN = re.compile(r"\[\[([a-z0-9-]+)(?:#([a-z0-9-]+))?(?:\|([^\]]+))?\]\]")
    RELATIONSHIP_TYPES = {"extends", "contradicts", "prerequisite", "see-also"}
    SENTENCE_SPLIT = re.compile(r"[.!?]+")
    STOP_WORDS = set()

    def __init__(self, pages_dir: Path):
        self.pages_dir = Path(pages_dir)
        self.cache_dir = self.pages_dir.parent / "cache"
        self.cache_dir.mkdir(exist_ok=True)
        self.db_path = self.cache_dir / "backlinks.db"
        self._init_db()

    def _init_db(self):
        """Initialize or connect to database."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS links (
                from_slug TEXT NOT NULL,
                to_slug TEXT NOT NULL,
                to_section TEXT DEFAULT '',
                link_type TEXT DEFAULT 'see-also',
                context TEXT,
                UNIQUE(from_slug, to_slug)
            )
        """)
        # Migration: add to_section column if missing
        try:
            conn.execute("ALTER TABLE links ADD COLUMN to_section TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pages_meta (
                slug TEXT PRIMARY KEY,
                last_indexed TEXT,
                link_count INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_from ON links(from_slug)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_to ON links(to_slug)")
        conn.commit()
        conn.close()

    def _get_md_files(self) -> dict[str, Path]:
        """Get all .md files as dict {slug: path}."""
        files = {}
        for md_file in self.pages_dir.glob("**/*.md"):
            slug = md_file.stem
            files[slug] = md_file
        return files

    def _extract_links(self, content: str) -> list[tuple[str, str, str, str]]:
        """Extract all links from markdown content.

        Returns: list of (to_slug, to_section, link_type, context)
        """
        links = []
        sentences = self.SENTENCE_SPLIT.split(content)

        for match in self.LINK_PATTERN.finditer(content):
            to_slug = match.group(1)
            to_section = match.group(2) or ""
            type_or_text = match.group(3)

            # Determine link type
            if type_or_text and type_or_text.strip() in self.RELATIONSHIP_TYPES:
                link_type = type_or_text.strip()
            else:
                link_type = "see-also"

            # Extract context (sentence containing the link)
            link_text = match.group(0)
            context = ""
            for sentence in sentences:
                if link_text in sentence:
                    context = sentence.strip()[:200]
                    break

            links.append((to_slug, to_section, link_type, context))

        return links

    def build(self) -> None:
        """Full rebuild of backlink index."""
        md_files = self._get_md_files()

        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM links")
        conn.execute("DELETE FROM pages_meta")

        total_links = 0
        now = datetime.now(UTC).isoformat()

        for slug, file_path in md_files.items():
            try:
                content = file_path.read_text(encoding="utf-8")
                links = self._extract_links(content)

                for to_slug, to_section, link_type, context in links:
                    try:
                        conn.execute(
                            """INSERT OR REPLACE INTO links
                               (from_slug, to_slug, to_section, link_type, context)
                               VALUES (?, ?, ?, ?, ?)""",
                            (slug, to_slug, to_section, link_type, context),
                        )
                        total_links += 1
                    except sqlite3.IntegrityError:
                        pass

                # Update metadata
                link_count = len(links)
                conn.execute(
                    """INSERT OR REPLACE INTO pages_meta
                       (slug, last_indexed, link_count)
                       VALUES (?, ?, ?)""",
                    (slug, now, link_count),
                )
            except Exception as e:
                logger.error("Error processing page", extra={"slug": slug, "error": str(e)}, exc_info=True)

        conn.commit()
        conn.close()

        logger.info("Built backlink index", extra={"pages": len(md_files), "links": total_links})

    def update(self, slug: str) -> None:
        """Update links for a single page (O(k) not O(n))."""
        md_files = self._get_md_files()

        if slug not in md_files:
            raise PageNotFoundError(slug)

        file_path = md_files[slug]
        content = file_path.read_text(encoding="utf-8")
        new_links = self._extract_links(content)

        conn = sqlite3.connect(self.db_path)

        # Delete old outgoing links
        conn.execute("DELETE FROM links WHERE from_slug = ?", (slug,))

        # Insert new links
        now = datetime.now(UTC).isoformat()
        for to_slug, to_section, link_type, context in new_links:
            try:
                conn.execute(
                    """INSERT INTO links (from_slug, to_slug, to_section, link_type, context)
                       VALUES (?, ?, ?, ?, ?)""",
                    (slug, to_slug, to_section, link_type, context),
                )
            except sqlite3.IntegrityError:
                pass

        # Update metadata
        conn.execute(
            """INSERT OR REPLACE INTO pages_meta
               (slug, last_indexed, link_count)
               VALUES (?, ?, ?)""",
            (slug, now, len(new_links)),
        )

        conn.commit()
        conn.close()

        logger.info("Updated page", extra={"slug": slug, "links": len(new_links)})

    def query(self, slug: str) -> None:
        """Get all pages that link to <slug>."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """SELECT from_slug, link_type, context FROM links
               WHERE to_slug = ? ORDER BY from_slug""",
            (slug,),
        )

        results = []
        for from_slug, link_type, context in cursor.fetchall():
            results.append(
                {"from": from_slug, "type": link_type, "context": context or ""}
            )

        conn.close()

        print(json.dumps(results, indent=2))

    def verify(self, slug: str) -> None:
        """Check bidirectional link consistency."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get outgoing links (from this slug)
        cursor.execute("SELECT to_slug FROM links WHERE from_slug = ?", (slug,))
        outgoing = {row[0] for row in cursor.fetchall()}

        # Get incoming links (to this slug)
        cursor.execute("SELECT from_slug FROM links WHERE to_slug = ?", (slug,))
        incoming = {row[0] for row in cursor.fetchall()}

        conn.close()

        # Categorize
        bidirectional = outgoing & incoming
        one_way_out = outgoing - incoming
        one_way_in = incoming - outgoing

        result = {
            "bidirectional": sorted(list(bidirectional)),
            "one_way_out": sorted(list(one_way_out)),
            "one_way_in": sorted(list(one_way_in)),
        }

        print(json.dumps(result, indent=2))

    def stats(self) -> None:
        """Print link statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Total counts
        cursor.execute("SELECT COUNT(*) FROM links")
        total_links = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM pages_meta")
        total_pages = cursor.fetchone()[0]

        # Orphan pages (no incoming links)
        cursor.execute("""
            SELECT COUNT(*) FROM pages_meta p
            WHERE NOT EXISTS (
                SELECT 1 FROM links WHERE to_slug = p.slug
            )
        """)
        orphan_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT slug FROM pages_meta p
            WHERE NOT EXISTS (
                SELECT 1 FROM links WHERE to_slug = p.slug
            )
            ORDER BY slug
        """)
        orphans = [row[0] for row in cursor.fetchall()]

        # Most-linked pages
        cursor.execute("""
            SELECT to_slug, COUNT(*) as count FROM links
            GROUP BY to_slug ORDER BY count DESC LIMIT 10
        """)
        most_linked = [(row[0], row[1]) for row in cursor.fetchall()]

        # Most-linking pages
        cursor.execute("""
            SELECT from_slug, COUNT(*) as count FROM links
            GROUP BY from_slug ORDER BY count DESC LIMIT 10
        """)
        most_linking = [(row[0], row[1]) for row in cursor.fetchall()]

        # Link type distribution
        cursor.execute("""
            SELECT link_type, COUNT(*) as count FROM links
            GROUP BY link_type ORDER BY count DESC
        """)
        type_dist = {row[0]: row[1] for row in cursor.fetchall()}

        conn.close()

        # Output stats
        logger.info("Link statistics", extra={
            "total_links": total_links,
            "total_pages": total_pages,
            "orphans": orphan_count,
            "most_linked": most_linked,
            "most_linking": most_linking,
            "type_distribution": type_dist
        })
        print(f"Total links: {total_links}")
        print(f"Total pages indexed: {total_pages}")
        print(f"Orphan pages: {orphan_count}")

        if orphans:
            print(f"\nOrphans: {', '.join(orphans[:20])}")
            if len(orphans) > 20:
                print(f"  ... and {len(orphans) - 20} more")

        print("\nMost-linked pages (top 10):")
        for slug, count in most_linked:
            print(f"  {slug}: {count} backlinks")

        print("\nMost-linking pages (top 10):")
        for slug, count in most_linking:
            print(f"  {slug}: {count} outgoing links")

        print("\nLink type distribution:")
        for link_type, count in sorted(type_dist.items()):
            print(f"  {link_type}: {count}")

    def missing(self) -> None:
        """List all [[links]] to non-existent pages."""
        md_files = self._get_md_files()
        existing_slugs = set(md_files.keys())

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT to_slug, COUNT(*) as count FROM links
            GROUP BY to_slug ORDER BY count DESC
        """)

        missing = []
        for to_slug, count in cursor.fetchall():
            if to_slug not in existing_slugs:
                missing.append({"slug": to_slug, "references": count})

        conn.close()

        print(json.dumps(missing, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="Wiki backlink index management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # build
    build_parser = subparsers.add_parser("build", help="Full rebuild of backlink index")
    build_parser.add_argument("pages_dir")

    # update
    update_parser = subparsers.add_parser("update", help="Update links for one page")
    update_parser.add_argument("pages_dir")
    update_parser.add_argument("slug")

    # query
    query_parser = subparsers.add_parser(
        "query", help="Get all pages that link to <slug>"
    )
    query_parser.add_argument("pages_dir")
    query_parser.add_argument("slug")

    # verify
    verify_parser = subparsers.add_parser(
        "verify", help="Check bidirectional link consistency"
    )
    verify_parser.add_argument("pages_dir")
    verify_parser.add_argument("slug")

    # stats
    stats_parser = subparsers.add_parser("stats", help="Link statistics")
    stats_parser.add_argument("pages_dir")

    # missing
    missing_parser = subparsers.add_parser("missing", help="List broken links")
    missing_parser.add_argument("pages_dir")

    args = parser.parse_args()

    try:
        db = BacklinkDB(args.pages_dir)

        if args.command == "build":
            db.build()
        elif args.command == "update":
            db.update(args.slug)
        elif args.command == "query":
            db.query(args.slug)
        elif args.command == "verify":
            db.verify(args.slug)
        elif args.command == "stats":
            db.stats()
        elif args.command == "missing":
            db.missing()
    except PageNotFoundError as e:
        logger.error("Page not found", extra={"slug": e.slug})
        sys.exit(1)


if __name__ == "__main__":
    main()
