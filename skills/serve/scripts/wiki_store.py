"""
WikiStore — Data layer for local wiki web server.

Reads markdown wiki pages from disk, indexes them in SQLite with FTS5 for search,
and watches for file changes using watchdog.

The wiki pages live in: {wiki_dir}/pages/*.md
Each page has YAML frontmatter: title, type, confidence, sources, related

Provides:
- Full-text search via SQLite FTS5
- Backlink tracking (what pages link to each page)
- Missing page detection (linked-to but don't exist)
- Automatic file watching and re-indexing
- Statistics and metadata queries
"""

import logging
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

# Valid page types for validation
VALID_TYPES = {
    "source",
    "entity",
    "concept",
    "idea",
    "brainstorming",
    "status",
    "rules",
    "config",
    "skill",
    "memory",
    "reference",
    "analysis",
    "comparison",
    "research-scan",
    "deep-dive",
    "timeline",
    "landscape",
    "decision",
    "documentation",
    "automation",
    "lint",
    "daily-note",
}


class FileLock:
    """Context manager for file-based locking (simple implementation)."""

    def __init__(self, path, timeout=10):
        """
        Initialize file lock.

        Args:
            path: Path to file being locked
            timeout: Max seconds to wait for lock acquisition
        """
        self.lock_path = Path(str(path) + ".lock")
        self.timeout = timeout
        self.start_time = None

    def __enter__(self):
        """Acquire lock by creating lockfile."""
        self.start_time = time.time()
        while True:
            try:
                # Try to create lock file exclusively
                self.lock_path.touch(exist_ok=False)
                return self
            except FileExistsError:
                if time.time() - self.start_time > self.timeout:
                    raise TimeoutError(
                        f"Could not acquire lock on {self.lock_path} after {self.timeout}s"
                    )
                time.sleep(0.1)

    def __exit__(self, *args):
        """Release lock by removing lockfile."""
        try:
            self.lock_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Error removing lock file {self.lock_path}: {e}")


class WikiStore:
    """
    In-memory + SQLite-backed wiki index.

    Reads all .md files from wiki_dir/pages/, parses frontmatter and content,
    builds FTS5 search index, and watches for file changes.
    """

    def __init__(self, wiki_dir: str, db_path: str | None = None):
        """
        Initialize the wiki store.

        Args:
            wiki_dir: Path to .wiki directory
            db_path: Optional SQLite database path. If None, uses /tmp/wiki-serve-cache.db
        """
        self.wiki_dir = Path(wiki_dir)
        self.pages_dir = self.wiki_dir / "pages"

        if db_path is None:
            db_path = "/tmp/wiki-serve-cache.db"
        self.db_path = db_path

        self.db = None
        self.lock = threading.RLock()

        # Initialize database and build index
        self._init_db()
        self._refresh_all_internal()

        # Start file watcher
        self.observer = Observer()
        self.observer.schedule(
            _WikiPageHandler(self), str(self.pages_dir), recursive=False
        )
        self.observer.start()

        logger.info(f"WikiStore initialized: {self.pages_dir} → {self.db_path}")

    def _init_db(self):
        """Initialize SQLite database with schema."""
        self.db = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
        self.db.row_factory = sqlite3.Row
        cursor = self.db.cursor()

        # Create tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                slug TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                type TEXT,
                confidence TEXT,
                content_md TEXT NOT NULL,
                content_html TEXT,
                summary TEXT,
                updated_at TEXT,
                status TEXT DEFAULT 'ready'
            )
            """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS links (
                from_slug TEXT NOT NULL,
                to_slug TEXT NOT NULL,
                relationship TEXT DEFAULT 'reference',
                UNIQUE(from_slug, to_slug),
                FOREIGN KEY(from_slug) REFERENCES pages(slug)
            )
            """)

        # Migration: add relationship column to existing links tables
        try:
            cursor.execute(
                "ALTER TABLE links ADD COLUMN relationship TEXT DEFAULT 'reference'"
            )
        except Exception as e:
            logger.debug(f"relationship column migration: {e}")  # Column already exists

        # FTS5 virtual table for full-text search
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
                slug, title, content_md,
                content='pages',
                content_rowid='rowid'
            )
            """)

        # Annotations table for user comments, questions, corrections
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_slug TEXT NOT NULL,
                start_offset INTEGER,
                end_offset INTEGER,
                annotation_type TEXT DEFAULT 'comment',
                content TEXT NOT NULL,
                created_at TEXT,
                resolved INTEGER DEFAULT 0,
                FOREIGN KEY(page_slug) REFERENCES pages(slug)
            )
            """)

        self.db.commit()

    def _refresh_all_internal(self):
        """Scan all .md files and rebuild index. Internal, must hold lock."""
        if not self.pages_dir.exists():
            logger.warning(f"Pages directory does not exist: {self.pages_dir}")
            return

        # Clear existing data
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM pages_fts")
        cursor.execute("DELETE FROM links")
        cursor.execute("DELETE FROM pages")
        self.db.commit()

        # Scan and index all markdown files
        md_files = sorted(self.pages_dir.glob("*.md"))
        for md_file in md_files:
            self._index_page_file(md_file)

        # Rebuild FTS5 index to ensure content-sync consistency
        cursor.execute("INSERT INTO pages_fts(pages_fts) VALUES('rebuild')")
        self.db.commit()

        logger.info(f"Indexed {len(md_files)} pages")

    def _index_page_file(self, md_file: Path):
        """Parse and index a single markdown file."""
        try:
            slug = md_file.stem
            content_md = md_file.read_text(encoding="utf-8")

            # Parse frontmatter
            frontmatter, body = self._parse_frontmatter(content_md)

            title = frontmatter.get("title", slug)
            page_type = frontmatter.get("type", "")

            # Validate page type
            if page_type and page_type not in VALID_TYPES:
                logger.warning(
                    f"Invalid page type '{page_type}' for {slug}; setting to 'unknown'"
                )
                page_type = "unknown"

            confidence = frontmatter.get("confidence", "")

            # Render HTML (without wiki link transformation — that's the renderer's job)
            content_html = self._render_html(body)

            # Extract summary (first paragraph)
            summary = self._extract_summary(body)

            # Prefer frontmatter updated: date; fall back to filesystem mtime
            fm_updated = frontmatter.get("updated", "")
            if fm_updated:
                try:
                    updated_at = datetime.strptime(fm_updated, "%Y-%m-%d").isoformat()
                except ValueError:
                    stat = md_file.stat()
                    updated_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
            else:
                stat = md_file.stat()
                updated_at = datetime.fromtimestamp(stat.st_mtime).isoformat()

            # Store in database
            cursor = self.db.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO pages
                (slug, title, type, confidence, content_md, content_html, summary, updated_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    slug,
                    title,
                    page_type,
                    confidence,
                    content_md,
                    content_html,
                    summary,
                    updated_at,
                    "ready",
                ),
            )

            # Index in FTS5
            cursor.execute(
                """
                INSERT INTO pages_fts (rowid, slug, title, content_md)
                SELECT rowid, slug, title, content_md FROM pages WHERE slug = ?
                """,
                (slug,),
            )

            # Extract and store wiki links
            links = self._extract_wiki_links(content_md)
            for link_slug in links:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO links (from_slug, to_slug)
                    VALUES (?, ?)
                    """,
                    (slug, link_slug),
                )

            self.db.commit()
            logger.debug(f"Indexed page: {slug}")

        except Exception as e:
            logger.error(f"Error indexing {md_file}: {e}", exc_info=True)

    def _parse_frontmatter(self, content: str) -> tuple[dict[str, Any], str]:
        """
        Parse YAML frontmatter from markdown.

        Returns: (frontmatter_dict, body_text)
        """
        if not content.startswith("---"):
            return {}, content

        try:
            # Find the closing --- delimiter
            lines = content.split("\n", 1)
            if len(lines) < 2:
                return {}, content

            rest = lines[1]
            if "\n---\n" not in rest:
                return {}, content

            fm_text, body = rest.split("\n---\n", 1)

            # Simple YAML frontmatter parsing (handles basic cases)
            frontmatter = {}
            for line in fm_text.strip().split("\n"):
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()

                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]

                frontmatter[key] = value

            return frontmatter, body

        except Exception as e:
            logger.warning(f"Error parsing frontmatter: {e}", exc_info=True)
            return {}, content

    def _render_html(self, markdown_text: str) -> str:
        """Render markdown to HTML (without wiki link transformation)."""
        try:
            md = MarkdownIt()
            html = md.render(markdown_text)
            return html
        except Exception as e:
            logger.error(f"Error rendering markdown: {e}", exc_info=True)
            return f"<p>{markdown_text}</p>"

    def _extract_summary(self, markdown_text: str) -> str:
        """Extract summary (first non-empty paragraph) from markdown."""
        for line in markdown_text.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                # Remove markdown formatting for plain text
                line = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", line)  # Remove links
                line = re.sub(r"[*_]", "", line)  # Remove emphasis
                return line[:200]  # Limit to 200 chars
        return ""

    def _extract_wiki_links(self, content: str) -> set:
        """
        Extract all wiki links from markdown content.

        Matches patterns: [[slug]], [[slug|Display Text]], [[slug#section]],
        [[slug#section|Display Text]], ![[slug#section]] (transclusion)
        Returns set of base slugs (without section anchors).
        """
        # Match both [[...]] and ![[...]] patterns
        pattern = r"!?\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]"
        matches = re.findall(pattern, content)
        return set(m.strip() for m in matches)

    def get_page_section(self, slug: str, heading: str) -> str | None:
        """
        Get the content of a specific section from a wiki page.

        Args:
            slug: Page slug
            heading: Heading text to match (case-insensitive)

        Returns:
            Markdown content of the section (between matching heading and next same-level heading),
            or None if not found.
        """
        page = self.get_page(slug)
        if not page:
            return None

        content_md = page.get("content_md", "")

        # Strip frontmatter
        if content_md.startswith("---"):
            end = content_md.find("---", 3)
            if end != -1:
                content_md = content_md[end + 3:].strip()

        lines = content_md.split("\n")
        target_level = 0
        capturing = False
        section_lines = []

        heading_lower = heading.lower().replace("-", " ")

        for line in lines:
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading_match:
                level = len(heading_match.group(1))
                text = heading_match.group(2).strip()
                text_normalized = text.lower().replace("-", " ")

                # Also match slug-style headings
                slug_style = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

                if not capturing and (text_normalized == heading_lower or slug_style == heading_lower):
                    target_level = level
                    capturing = True
                    section_lines.append(line)
                    continue
                elif capturing and level <= target_level:
                    break  # Next same-or-higher level heading

            if capturing:
                section_lines.append(line)

        if section_lines:
            return "\n".join(section_lines)
        return None

    def get_page(self, slug: str) -> dict[str, Any] | None:
        """
        Get a single page by slug.

        Returns dict with keys: slug, title, type, confidence, content_md, content_html, summary, updated_at, status
        Returns None if not found.
        """
        with self.lock:
            cursor = self.db.cursor()
            cursor.execute("SELECT * FROM pages WHERE slug = ?", (slug,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def delete_page(self, slug: str) -> bool:
        """
        Delete a page from the database and its markdown file from disk.

        Removes the page from all tables (pages, pages_fts, links, annotations)
        and deletes the .md file from wiki/pages/.

        Args:
            slug: Page slug to delete

        Returns:
            True if page existed and was deleted, False if not found
        """
        with self.lock:
            cursor = self.db.cursor()

            # Check if exists
            cursor.execute("SELECT slug FROM pages WHERE slug = ?", (slug,))
            if not cursor.fetchone():
                return False

            # Remove from FTS index
            cursor.execute("DELETE FROM pages_fts WHERE slug = ?", (slug,))

            # Remove links (both directions)
            cursor.execute(
                "DELETE FROM links WHERE from_slug = ? OR to_slug = ?", (slug, slug)
            )

            # Remove annotations
            try:
                cursor.execute("DELETE FROM annotations WHERE slug = ?", (slug,))
            except Exception as e:
                logger.debug(f"Error deleting annotations for {slug}: {e}")  # annotations table may not exist

            # Remove from pages table
            cursor.execute("DELETE FROM pages WHERE slug = ?", (slug,))

            self.db.commit()

        # Delete the markdown file (validate slug to prevent path traversal)
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", slug) or ".." in slug:
            return False
        md_path = self.wiki_dir / "pages" / f"{slug}.md"
        if md_path.exists():
            md_path.unlink()

        return True

    def search(self, query: str, limit: int = 20) -> list[dict[str, str]]:
        """
        Full-text search using FTS5.

        Returns list of {slug, title, type, snippet} dicts.
        """
        if not query.strip():
            return []

        with self.lock:
            cursor = self.db.cursor()
            try:
                cursor.execute(
                    """
                    SELECT pages.slug, pages.title, pages.type,
                           snippet(pages_fts, 1, '<b>', '</b>', '...', 80) as snippet
                    FROM pages_fts
                    JOIN pages ON pages.slug = pages_fts.slug
                    WHERE pages_fts MATCH ?
                    LIMIT ?
                    """,
                    (query, limit),
                )
                results = []
                for row in cursor.fetchall():
                    results.append(
                        {
                            "slug": row[0],
                            "title": row[1],
                            "type": row[2],
                            "snippet": row[3],
                        }
                    )
                return results
            except Exception as e:
                logger.error(f"Search error: {e}", exc_info=True)
                return []

    def get_all_pages(self) -> list[dict[str, Any]]:
        """
        Get all pages (summary metadata only).

        Returns list of {slug, title, type, confidence} dicts.
        """
        with self.lock:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT slug, title, type, confidence
                FROM pages
                ORDER BY slug
                """)
            results = []
            for row in cursor.fetchall():
                results.append(
                    {
                        "slug": row[0],
                        "title": row[1],
                        "type": row[2],
                        "confidence": row[3],
                    }
                )
            return results

    def get_recent_pages(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get recently modified pages.

        Returns list of {slug, title, type, confidence, updated_at} dicts, sorted by updated_at descending.
        """
        with self.lock:
            cursor = self.db.cursor()
            cursor.execute(
                """
                SELECT slug, title, type, confidence, updated_at
                FROM pages
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            results = []
            for row in cursor.fetchall():
                results.append(
                    {
                        "slug": row[0],
                        "title": row[1],
                        "type": row[2],
                        "confidence": row[3],
                        "updated_at": row[4],
                    }
                )
            return results

    def get_missing_pages(self) -> list[str]:
        """
        Get slugs that are linked to but don't exist as pages.

        Returns list of slugs.
        """
        with self.lock:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT DISTINCT links.to_slug
                FROM links
                LEFT JOIN pages ON links.to_slug = pages.slug
                WHERE pages.slug IS NULL
                ORDER BY links.to_slug
                """)
            return [row[0] for row in cursor.fetchall()]

    def get_backlinks(self, slug: str) -> list[dict[str, str]]:
        """
        Get pages that link to this slug.

        Returns list of {slug, title} dicts.
        """
        with self.lock:
            cursor = self.db.cursor()
            cursor.execute(
                """
                SELECT pages.slug, pages.title
                FROM links
                JOIN pages ON links.from_slug = pages.slug
                WHERE links.to_slug = ?
                ORDER BY pages.slug
                """,
                (slug,),
            )
            results = []
            for row in cursor.fetchall():
                results.append({"slug": row[0], "title": row[1]})
            return results

    def get_stats(self) -> dict[str, Any]:
        """
        Get overall wiki statistics.

        Returns {total_pages, by_type: {type: count}, by_confidence: {conf: count}}
        """
        with self.lock:
            cursor = self.db.cursor()

            # Total pages
            cursor.execute("SELECT COUNT(*) FROM pages")
            total_pages = cursor.fetchone()[0]

            # By type
            cursor.execute("""
                SELECT type, COUNT(*) as count
                FROM pages
                WHERE type IS NOT NULL AND type != ''
                GROUP BY type
                ORDER BY count DESC
                """)
            by_type = {row[0]: row[1] for row in cursor.fetchall()}

            # By confidence
            cursor.execute("""
                SELECT confidence, COUNT(*) as count
                FROM pages
                WHERE confidence IS NOT NULL AND confidence != ''
                GROUP BY confidence
                ORDER BY count DESC
                """)
            by_confidence = {row[0]: row[1] for row in cursor.fetchall()}

            return {
                "total_pages": total_pages,
                "by_type": by_type,
                "by_confidence": by_confidence,
            }

    def refresh_page(self, slug: str) -> bool:
        """
        Re-read a single page from disk and update index.

        Returns True if successful, False if file not found.
        """
        with self.lock:
            md_file = self.pages_dir / f"{slug}.md"
            if not md_file.exists():
                logger.warning(f"Page file not found: {md_file}")
                return False

            self._index_page_file(md_file)
            return True

    def refresh_all(self):
        """Full re-index of all pages from disk."""
        with self.lock:
            self._refresh_all_internal()

    # Freshness tier keyword mapping for auto-classification
    FRESHNESS_TIERS = {
        "live": {"ttl_days": 0.01, "keywords": {"stock", "price", "live", "score", "deploy", "status", "uptime"}},
        "breaking": {"ttl_days": 0.25, "keywords": {"breaking", "incident", "outage", "release", "announcement"}},
        "current": {"ttl_days": 3, "keywords": {"news", "trending", "current", "today", "election", "event"}},
        "fast": {"ttl_days": 28, "keywords": {"ai", "llm", "gpt", "claude", "mcp", "agent", "api", "sdk", "benchmark", "model"}},
        "moderate": {"ttl_days": 90, "keywords": {"version", "framework", "library", "tool", "package", "software"}},
        "standard": {"ttl_days": 180, "keywords": set()},
        "academic": {"ttl_days": 365, "keywords": {"paper", "study", "journal", "peer-reviewed", "thesis", "arxiv"}},
        "evergreen": {"ttl_days": 1825, "keywords": {"history", "biography", "theorem", "law", "principle", "foundational"}},
        "permanent": {"ttl_days": float("inf"), "keywords": {"personal", "note", "idea", "memory", "journal", "diary"}},
    }

    def _classify_page_freshness(self, page: dict) -> tuple[str, float]:
        """Classify a page into a freshness tier. Returns (tier_name, ttl_days)."""
        content = page.get("content_md", "").lower()
        title = page.get("title", "").lower()
        combined = f"{content} {title}"

        def _has_keyword(kw: str) -> bool:
            return bool(re.search(r"\b" + re.escape(kw) + r"\b", combined))

        for tier_name in ["live", "breaking", "current", "fast", "moderate",
                          "academic", "evergreen", "permanent"]:
            tier = self.FRESHNESS_TIERS[tier_name]
            if tier["keywords"] and any(_has_keyword(kw) for kw in tier["keywords"]):
                return tier_name, tier["ttl_days"]

        return "standard", self.FRESHNESS_TIERS["standard"]["ttl_days"]

    def get_stale_pages(self, **kwargs) -> list[dict[str, Any]]:
        """
        Get pages past their freshness tier TTL.

        Uses intelligent freshness tiers instead of a flat threshold:
        live=15m, breaking=6h, current=3d, fast=4w, moderate=3mo,
        standard=6mo, academic=1y, evergreen=5y, permanent=never.

        Returns:
            List of stale pages with full metadata and freshness_tier info
        """
        with self.lock:
            cursor = self.db.cursor()
            cursor.execute("SELECT * FROM pages ORDER BY updated_at ASC")
            all_pages = [dict(row) for row in cursor.fetchall()]

            now = datetime.now()
            stale_pages = []
            for page in all_pages:
                updated_at = page.get("updated_at", "")
                if not updated_at:
                    continue

                try:
                    updated_dt = datetime.fromisoformat(updated_at)
                except (ValueError, TypeError):
                    continue

                tier_name, ttl_days = self._classify_page_freshness(page)

                # permanent tier never goes stale
                if ttl_days == float("inf"):
                    continue

                age_days = (now - updated_dt).total_seconds() / 86400
                if age_days > ttl_days:
                    page["freshness_tier"] = tier_name
                    page["ttl_days"] = ttl_days
                    page["age_days"] = round(age_days, 1)
                    stale_pages.append(page)

            return stale_pages

    def _classify_tier(self, page: dict) -> tuple[str, int | None]:
        """Classify a page into a freshness tier. Returns (tier_name, max_age_minutes)."""
        # Check explicit freshness_tier in frontmatter
        content = page.get("content_md", "")
        import re as _re
        fm_match = _re.search(r"^freshness_tier:\s*(\S+)", content, _re.MULTILINE)
        if fm_match:
            tier = fm_match.group(1).strip().strip('"').strip("'")
            if tier in self.FRESHNESS_TIERS:
                return tier, self.FRESHNESS_TIERS[tier][0]

        # Auto-classify from content
        text = f"{page.get('title', '')} {content}".lower()
        for tier_name, (max_age, keywords) in self.FRESHNESS_TIERS.items():
            if not keywords:
                continue
            if any(kw in text for kw in keywords):
                return tier_name, max_age

        return "standard", self.FRESHNESS_TIERS["standard"][0]

    def add_annotation(
        self,
        slug: str,
        annotation_type: str,
        content: str,
        start: int | None = None,
        end: int | None = None,
    ) -> int:
        """
        Add an annotation to a page.

        Args:
            slug: Page slug
            annotation_type: Type of annotation (comment, question, correction, todo)
            content: Annotation content
            start: Optional start offset in page content
            end: Optional end offset in page content

        Returns:
            Annotation ID
        """
        with self.lock:
            cursor = self.db.cursor()
            created_at = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO annotations (page_slug, annotation_type, content, start_offset, end_offset, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (slug, annotation_type, content, start, end, created_at),
            )
            self.db.commit()
            return cursor.lastrowid

    def get_annotations(self, slug: str) -> list[dict[str, Any]]:
        """
        Get all annotations for a page.

        Args:
            slug: Page slug

        Returns:
            List of annotation dicts
        """
        with self.lock:
            cursor = self.db.cursor()
            cursor.execute(
                """
                SELECT id, page_slug, start_offset, end_offset, annotation_type, content, created_at, resolved
                FROM annotations
                WHERE page_slug = ? AND resolved = 0
                ORDER BY created_at DESC
                """,
                (slug,),
            )
            results = []
            for row in cursor.fetchall():
                results.append(
                    {
                        "id": row[0],
                        "page_slug": row[1],
                        "start_offset": row[2],
                        "end_offset": row[3],
                        "annotation_type": row[4],
                        "content": row[5],
                        "created_at": row[6],
                        "resolved": row[7],
                    }
                )
            return results

    def resolve_annotation(self, annotation_id: int) -> bool:
        """
        Mark an annotation as resolved.

        Args:
            annotation_id: ID of annotation to resolve

        Returns:
            True if successful
        """
        with self.lock:
            cursor = self.db.cursor()
            cursor.execute(
                "UPDATE annotations SET resolved = 1 WHERE id = ?",
                (annotation_id,),
            )
            self.db.commit()
            return cursor.rowcount > 0

    @classmethod
    def smoke_test(cls):
        """
        Run a smoke test to catch import errors early.
        Tries to import all sibling modules and instantiate key classes.

        Raises:
            Exception if any import or instantiation fails
        """
        try:
            # Verify imports
            import importlib
            import sys

            current_module = sys.modules[__name__]
            module_dir = Path(current_module.__file__).parent

            # List of sibling modules to test
            sibling_modules = ["chat_manager"]  # Add more as needed

            for module_name in sibling_modules:
                try:
                    if __package__:
                        mod = importlib.import_module(
                            f".{module_name}", package=__package__
                        )
                    else:
                        mod = importlib.import_module(module_name)
                    logger.debug(f"✓ Imported {module_name}")
                except Exception as e:
                    logger.error(f"✗ Failed to import {module_name}: {e}")
                    raise

            logger.info("✓ Smoke test passed: all imports successful")
            return True

        except Exception as e:
            logger.error(f"✗ Smoke test failed: {e}", exc_info=True)
            raise

    def shutdown(self):
        """Gracefully shut down the wiki store (stop file watcher, close DB)."""
        self.observer.stop()
        self.observer.join()
        if self.db:
            self.db.close()
        logger.info("WikiStore shutdown complete")


class _WikiPageHandler(FileSystemEventHandler):
    """Watch for changes to .md files and refresh the index."""

    def __init__(self, wiki_store: WikiStore):
        self.wiki_store = wiki_store

    def on_modified(self, event):
        """Re-index when a markdown file is modified."""
        if event.is_directory:
            return
        if not event.src_path.endswith(".md"):
            return

        # Debounce: wait a bit to avoid double-indexing on rapid saves
        time.sleep(0.2)

        slug = Path(event.src_path).stem
        logger.debug(f"File changed, re-indexing: {slug}")
        self.wiki_store.refresh_page(slug)

    def on_created(self, event):
        """Index newly created markdown files."""
        if event.is_directory:
            return
        if not event.src_path.endswith(".md"):
            return

        slug = Path(event.src_path).stem
        logger.debug(f"New file, indexing: {slug}")
        self.wiki_store.refresh_page(slug)
