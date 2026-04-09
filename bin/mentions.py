#!/usr/bin/env python3
"""mentions.py — Find unlinked mentions of wiki page titles.

Usage:
    python3 mentions.py scan <pages_dir>               — Scan all pages for unlinked mentions
    python3 mentions.py page <pages_dir> <slug>        — Find mentions of a specific page
    python3 mentions.py link <pages_dir> <source> <target> <line>  — Convert mention to [[link]]

Detects places where a page title appears in another page's text but isn't
wrapped in [[wiki-links]]. This is one of Obsidian's most beloved features.
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

from wiki_logging import get_logger

logger = get_logger(__name__)


class MentionsFinder:
    """Finds unlinked mentions of wiki page titles across all pages."""

    # Pattern to detect existing wiki links (to exclude from mention detection)
    WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

    def __init__(self, pages_dir: Path):
        self.pages_dir = Path(pages_dir)
        self.cache_dir = self.pages_dir.parent / "cache"
        self.cache_dir.mkdir(exist_ok=True)
        self.db_path = self.cache_dir / "mentions.db"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mentions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_slug TEXT NOT NULL,
                target_slug TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                context TEXT NOT NULL,
                UNIQUE(source_slug, target_slug, line_number)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mentions_target ON mentions(target_slug)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mentions_source ON mentions(source_slug)")
        conn.commit()
        conn.close()

    def _get_page_titles(self) -> dict[str, str]:
        """Get all page slugs and their titles."""
        titles = {}
        for md_file in self.pages_dir.glob("*.md"):
            slug = md_file.stem
            content = md_file.read_text(encoding="utf-8")
            # Extract title from frontmatter
            match = re.search(r"^---\s*\n.*?^title:\s*[\"']?([^\n\"']+)", content, re.MULTILINE | re.DOTALL)
            if match:
                titles[slug] = match.group(1).strip()
            else:
                # Fallback to slug-based title
                titles[slug] = " ".join(w.capitalize() for w in slug.split("-"))
        return titles

    def _find_existing_links(self, content: str) -> set[str]:
        """Find all slugs already linked via [[...]] in content."""
        linked = set()
        for match in self.WIKI_LINK_RE.finditer(content):
            link_text = match.group(1)
            # Handle [[slug|display]], [[slug#section]], [[slug#section|display]]
            slug = link_text.split("|")[0].split("#")[0].strip()
            linked.add(slug)
        return linked

    def scan(self) -> list[dict]:
        """Scan all pages for unlinked mentions. Returns list of mention dicts."""
        titles = self._get_page_titles()
        all_mentions = []

        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM mentions")

        for md_file in self.pages_dir.glob("*.md"):
            source_slug = md_file.stem
            content = md_file.read_text(encoding="utf-8")

            # Get existing links to skip
            existing_links = self._find_existing_links(content)

            # Strip frontmatter for line counting
            body = content
            fm_end = 0
            if content.startswith("---"):
                end_match = re.search(r"\n---\n", content[3:])
                if end_match:
                    fm_end = end_match.end() + 3
                    body = content[fm_end:]

            lines = body.split("\n")

            for target_slug, title in titles.items():
                if target_slug == source_slug:
                    continue
                if target_slug in existing_links:
                    continue

                # Build regex for title match (case-insensitive, word boundaries)
                # Match both the title and the slug (hyphenated form)
                patterns = []
                if len(title) >= 3:
                    escaped = re.escape(title)
                    patterns.append(re.compile(r"\b" + escaped + r"\b", re.IGNORECASE))

                slug_as_words = target_slug.replace("-", " ")
                if slug_as_words != title.lower() and len(slug_as_words) >= 3:
                    escaped = re.escape(slug_as_words)
                    patterns.append(re.compile(r"\b" + escaped + r"\b", re.IGNORECASE))

                for line_idx, line in enumerate(lines):
                    # Skip headings and code blocks
                    stripped = line.strip()
                    if stripped.startswith("#") or stripped.startswith("```"):
                        continue
                    # Skip lines that are inside wiki links
                    if "[[" in line and "]]" in line:
                        # Check if the mention would be inside a link
                        pass

                    for pattern in patterns:
                        match = pattern.search(line)
                        if match:
                            # Verify not inside a [[...]] bracket
                            pos = match.start()
                            before = line[:pos]
                            after = line[pos:]
                            # Count unmatched [[ before this position
                            open_count = before.count("[[") - before.count("]]")
                            if open_count > 0:
                                continue  # Inside a wiki link

                            context = line.strip()[:200]
                            actual_line = line_idx + fm_end // max(1, len(content.split("\n")[0])) + 1

                            mention = {
                                "source_slug": source_slug,
                                "target_slug": target_slug,
                                "line_number": line_idx + 1,
                                "context": context,
                            }
                            all_mentions.append(mention)

                            try:
                                conn.execute(
                                    """INSERT OR IGNORE INTO mentions
                                       (source_slug, target_slug, line_number, context)
                                       VALUES (?, ?, ?, ?)""",
                                    (source_slug, target_slug, line_idx + 1, context),
                                )
                            except sqlite3.IntegrityError:
                                pass

                            break  # One mention per target per line is enough

        conn.commit()
        conn.close()
        return all_mentions

    def get_mentions_for(self, slug: str) -> list[dict]:
        """Get all unlinked mentions of a specific page."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """SELECT source_slug, line_number, context FROM mentions
               WHERE target_slug = ? ORDER BY source_slug""",
            (slug,),
        )
        results = [
            {"source_slug": row[0], "line_number": row[1], "context": row[2]}
            for row in cursor.fetchall()
        ]
        conn.close()
        return results

    def link_mention(self, source_slug: str, target_slug: str, line_number: int) -> bool:
        """Convert an unlinked mention to a [[wiki-link]]."""
        md_file = self.pages_dir / f"{source_slug}.md"
        if not md_file.exists():
            return False

        content = md_file.read_text(encoding="utf-8")
        lines = content.split("\n")

        titles = self._get_page_titles()
        title = titles.get(target_slug, target_slug.replace("-", " ").title())

        # Find the line (1-indexed)
        if line_number < 1 or line_number > len(lines):
            return False

        line = lines[line_number - 1]

        # Replace first occurrence of title (case-insensitive) with [[link]]
        pattern = re.compile(re.escape(title), re.IGNORECASE)
        match = pattern.search(line)
        if match:
            original = match.group(0)
            if original.lower() == title.lower():
                replacement = f"[[{target_slug}]]"
            else:
                replacement = f"[[{target_slug}|{original}]]"
            lines[line_number - 1] = line[: match.start()] + replacement + line[match.end() :]

            md_file.write_text("\n".join(lines), encoding="utf-8")

            # Remove from mentions DB
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "DELETE FROM mentions WHERE source_slug = ? AND target_slug = ? AND line_number = ?",
                (source_slug, target_slug, line_number),
            )
            conn.commit()
            conn.close()
            return True

        return False


def main():
    parser = argparse.ArgumentParser(
        description="Find unlinked mentions of wiki page titles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_p = subparsers.add_parser("scan", help="Scan all pages for unlinked mentions")
    scan_p.add_argument("pages_dir")

    page_p = subparsers.add_parser("page", help="Find mentions of a specific page")
    page_p.add_argument("pages_dir")
    page_p.add_argument("slug")

    link_p = subparsers.add_parser("link", help="Convert mention to [[wiki-link]]")
    link_p.add_argument("pages_dir")
    link_p.add_argument("source_slug")
    link_p.add_argument("target_slug")
    link_p.add_argument("line_number", type=int)

    args = parser.parse_args()
    finder = MentionsFinder(args.pages_dir)

    if args.command == "scan":
        mentions = finder.scan()
        print(json.dumps(mentions, indent=2))
        logger.info("Scan complete", extra={"mentions_found": len(mentions)})

    elif args.command == "page":
        mentions = finder.get_mentions_for(args.slug)
        print(json.dumps(mentions, indent=2))

    elif args.command == "link":
        success = finder.link_mention(args.source_slug, args.target_slug, args.line_number)
        if success:
            logger.info("Mention linked", extra={"source": args.source_slug, "target": args.target_slug, "line": args.line_number})
            print(f"Linked: {args.source_slug} -> [[{args.target_slug}]] at line {args.line_number}")
        else:
            logger.error("Failed to link mention", extra={"source": args.source_slug, "target": args.target_slug, "line": args.line_number})
            sys.exit(1)


if __name__ == "__main__":
    main()
