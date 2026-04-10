#!/usr/bin/env python3
"""query.py — Frontmatter query language for wiki pages (Dataview-like).

Usage:
    python3 query.py exec <pages_dir> "<query>"        — Execute a query
    python3 query.py index <pages_dir>                 — Rebuild frontmatter index
    python3 query.py fields <pages_dir>                — List all known frontmatter fields

Query syntax:
    SELECT title, type, confidence FROM pages
        WHERE type = "concept" AND confidence = "high"
        SORT BY updated DESC
        LIMIT 10

    COUNT type FROM pages WHERE confidence != "low"

    LIST FROM pages WHERE tags CONTAINS "research"
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

from wiki_logging import get_logger

logger = get_logger(__name__)


class FrontmatterQuery:
    """Query engine for wiki page frontmatter."""

    def __init__(self, pages_dir: Path):
        self.pages_dir = Path(pages_dir)
        self.cache_dir = self.pages_dir.parent / "cache"
        self.cache_dir.mkdir(exist_ok=True)
        self.db_path = self.cache_dir / "frontmatter.db"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS page_meta (
                slug TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                UNIQUE(slug, key)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_key ON page_meta(key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_slug ON page_meta(slug)")

        # Implicit metadata table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS page_implicit (
                slug TEXT PRIMARY KEY,
                file_size INTEGER,
                word_count INTEGER,
                link_count INTEGER,
                created_at TEXT,
                modified_at TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _parse_frontmatter(self, content: str) -> dict:
        """Parse YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return {}

        lines = content.split("\n", 1)
        if len(lines) < 2:
            return {}

        rest = lines[1]
        if "\n---\n" not in rest and not rest.endswith("\n---"):
            return {}

        fm_text = rest.split("\n---")[0]
        result = {}
        current_key = None
        list_values = []

        for line in fm_text.strip().split("\n"):
            # List item continuation
            if line.strip().startswith("- ") and current_key:
                val = line.strip()[2:].strip().strip('"').strip("'")
                list_values.append(val)
                result[current_key] = list_values
                continue

            if ":" not in line:
                continue

            # Save previous list
            current_key = None
            list_values = []

            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            # Remove quotes
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]

            # Inline list [a, b, c]
            if value.startswith("[") and value.endswith("]"):
                items = value[1:-1].split(",")
                value = [i.strip().strip('"').strip("'") for i in items if i.strip()]
                result[key] = value
                continue

            # Empty value with possible list continuation
            if not value:
                current_key = key
                list_values = []
                result[key] = ""
                continue

            result[key] = value

        return result

    def index(self) -> dict:
        """Rebuild frontmatter index from all pages."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM page_meta")
        conn.execute("DELETE FROM page_implicit")

        stats = {"pages": 0, "fields": 0}

        for md_file in sorted(self.pages_dir.glob("*.md")):
            slug = md_file.stem
            content = md_file.read_text(encoding="utf-8")
            fm = self._parse_frontmatter(content)

            # Store frontmatter fields
            for key, value in fm.items():
                if isinstance(value, list):
                    value_str = json.dumps(value)
                else:
                    value_str = str(value)

                conn.execute(
                    "INSERT OR REPLACE INTO page_meta (slug, key, value) VALUES (?, ?, ?)",
                    (slug, key, value_str),
                )
                stats["fields"] += 1

            # Store implicit metadata
            stat = md_file.stat()
            body = content
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    body = parts[2]

            word_count = len(body.split())
            link_count = len(re.findall(r"\[\[", content))

            conn.execute(
                """INSERT OR REPLACE INTO page_implicit
                   (slug, file_size, word_count, link_count, created_at, modified_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    slug,
                    stat.st_size,
                    word_count,
                    link_count,
                    fm.get("created", ""),
                    fm.get("updated", ""),
                ),
            )
            stats["pages"] += 1

        conn.commit()
        conn.close()
        return stats

    def execute(self, query_str: str) -> list[dict]:
        """Execute a frontmatter query."""
        query_str = query_str.strip()

        # Parse query type
        upper = query_str.upper()

        if upper.startswith("COUNT"):
            return self._exec_count(query_str)
        elif upper.startswith("LIST"):
            return self._exec_list(query_str)
        elif upper.startswith("SELECT") or upper.startswith("TABLE"):
            return self._exec_select(query_str)
        else:
            # Default: treat as WHERE clause
            return self._exec_select(f"SELECT * FROM pages WHERE {query_str}")

    def _parse_where(self, where_clause: str) -> tuple[str, list]:
        """Parse WHERE clause into SQL conditions and parameters."""
        if not where_clause:
            return "1=1", []

        conditions = []
        params = []

        # Split by AND/OR (simple parser)
        parts = re.split(r"\b(AND|OR)\b", where_clause, flags=re.IGNORECASE)

        for part in parts:
            part = part.strip()
            if part.upper() in ("AND", "OR"):
                conditions.append(part.upper())
                continue

            # Parse condition: field op value
            match = re.match(
                r'(\w+(?:\.\w+)?)\s*(=|!=|>|<|>=|<=|CONTAINS|LIKE)\s*["\']?([^"\']*)["\']?',
                part,
                re.IGNORECASE,
            )
            if not match:
                continue

            field, op, value = match.group(1), match.group(2).upper(), match.group(3)

            # Handle implicit fields (file.*)
            if field.startswith("file."):
                implicit_field = field.split(".")[1]
                field_map = {
                    "size": "file_size",
                    "words": "word_count",
                    "links": "link_count",
                    "created": "created_at",
                    "modified": "modified_at",
                    "name": "slug",
                }
                col = field_map.get(implicit_field, implicit_field)
                if op == "CONTAINS":
                    conditions.append(f"pi.{col} LIKE ?")
                    params.append(f"%{value}%")
                else:
                    sql_op = {"=": "=", "!=": "!=", ">": ">", "<": "<", ">=": ">=", "<=": "<=", "LIKE": "LIKE"}
                    conditions.append(f"pi.{col} {sql_op.get(op, '=')} ?")
                    params.append(value)
            else:
                # Frontmatter field
                if op == "CONTAINS":
                    conditions.append(
                        f"EXISTS (SELECT 1 FROM page_meta pm2 WHERE pm2.slug = pm.slug AND pm2.key = ? AND pm2.value LIKE ?)"
                    )
                    params.extend([field, f"%{value}%"])
                else:
                    sql_op = {"=": "=", "!=": "!=", ">": ">", "<": "<", ">=": ">=", "<=": "<=", "LIKE": "LIKE"}
                    conditions.append(
                        f"EXISTS (SELECT 1 FROM page_meta pm2 WHERE pm2.slug = pm.slug AND pm2.key = ? AND pm2.value {sql_op.get(op, '=')} ?)"
                    )
                    params.extend([field, value])

        return " ".join(conditions) if conditions else "1=1", params

    def _exec_select(self, query_str: str) -> list[dict]:
        """Execute a SELECT/TABLE query."""
        # Parse: SELECT fields FROM pages WHERE ... SORT BY ... LIMIT N
        match = re.match(
            r"(?:SELECT|TABLE)\s+(.+?)\s+FROM\s+\w+(?:\s+WHERE\s+(.+?))?(?:\s+SORT\s+BY\s+(\w+)(?:\s+(ASC|DESC))?)?\s*(?:\s+LIMIT\s+(\d+))?\s*$",
            query_str,
            re.IGNORECASE,
        )

        if not match:
            # Simpler format: just conditions
            where_sql, params = self._parse_where(query_str)
            fields = ["*"]
            sort_field = None
            sort_dir = "ASC"
            limit = 50
        else:
            fields_str = match.group(1).strip()
            fields = [f.strip() for f in fields_str.split(",")] if fields_str != "*" else ["*"]
            where_clause = match.group(2) or ""
            sort_field = match.group(3)
            sort_dir = (match.group(4) or "ASC").upper()
            limit = int(match.group(5) or 50)
            where_sql, params = self._parse_where(where_clause)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get all matching slugs
        sql = f"""
            SELECT DISTINCT pm.slug FROM page_meta pm
            LEFT JOIN page_implicit pi ON pm.slug = pi.slug
            WHERE {where_sql}
        """
        cursor.execute(sql, params)
        slugs = [row[0] for row in cursor.fetchall()]

        # Fetch requested fields for each slug
        results = []
        for slug in slugs:
            row = {"slug": slug}

            if "*" in fields:
                # Get all fields
                cursor.execute("SELECT key, value FROM page_meta WHERE slug = ?", (slug,))
                for key, value in cursor.fetchall():
                    row[key] = value
                cursor.execute("SELECT word_count, link_count FROM page_implicit WHERE slug = ?", (slug,))
                imp = cursor.fetchone()
                if imp:
                    row["file.words"] = imp[0]
                    row["file.links"] = imp[1]
            else:
                for field in fields:
                    if field.startswith("file."):
                        col = field.split(".")[1]
                        col_map = {"size": "file_size", "words": "word_count", "links": "link_count"}
                        cursor.execute(f"SELECT {col_map.get(col, col)} FROM page_implicit WHERE slug = ?", (slug,))
                        val = cursor.fetchone()
                        row[field] = val[0] if val else None
                    else:
                        cursor.execute("SELECT value FROM page_meta WHERE slug = ? AND key = ?", (slug, field))
                        val = cursor.fetchone()
                        row[field] = val[0] if val else None

            results.append(row)

        conn.close()

        # Sort
        if sort_field:
            results.sort(
                key=lambda r: r.get(sort_field, "") or "",
                reverse=(sort_dir == "DESC"),
            )

        return results[:limit]

    def _exec_count(self, query_str: str) -> list[dict]:
        """Execute a COUNT query."""
        match = re.match(
            r"COUNT\s+(\w+)\s+FROM\s+\w+(?:\s+WHERE\s+(.+))?\s*$",
            query_str,
            re.IGNORECASE,
        )

        if not match:
            return [{"error": "Invalid COUNT syntax"}]

        group_field = match.group(1)
        where_clause = match.group(2) or ""
        where_sql, params = self._parse_where(where_clause)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            f"""
            SELECT pm_group.value, COUNT(DISTINCT pm_group.slug)
            FROM page_meta pm_group
            JOIN page_meta pm ON pm.slug = pm_group.slug
            LEFT JOIN page_implicit pi ON pm.slug = pi.slug
            WHERE pm_group.key = ? AND {where_sql}
            GROUP BY pm_group.value
            ORDER BY COUNT(DISTINCT pm_group.slug) DESC
            """,
            [group_field] + params,
        )

        results = [{"value": row[0], "count": row[1]} for row in cursor.fetchall()]
        conn.close()
        return results

    def _exec_list(self, query_str: str) -> list[dict]:
        """Execute a LIST query."""
        match = re.match(
            r"LIST\s+FROM\s+\w+(?:\s+WHERE\s+(.+))?\s*$",
            query_str,
            re.IGNORECASE,
        )

        if not match:
            return self._exec_select(query_str.replace("LIST", "SELECT slug, title", 1))

        where_clause = match.group(1) or ""
        return self._exec_select(f"SELECT slug, title FROM pages WHERE {where_clause}")

    def get_fields(self) -> list[dict]:
        """List all known frontmatter fields and their value counts."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT key, COUNT(DISTINCT slug) as page_count, COUNT(DISTINCT value) as unique_values
            FROM page_meta
            GROUP BY key
            ORDER BY page_count DESC
        """)
        results = [
            {"field": row[0], "pages_with_field": row[1], "unique_values": row[2]}
            for row in cursor.fetchall()
        ]
        conn.close()
        return results


def main():
    parser = argparse.ArgumentParser(
        description="Frontmatter query language for wiki pages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    exec_p = subparsers.add_parser("exec", help="Execute a query")
    exec_p.add_argument("pages_dir")
    exec_p.add_argument("query", help="Query string")

    index_p = subparsers.add_parser("index", help="Rebuild frontmatter index")
    index_p.add_argument("pages_dir")

    fields_p = subparsers.add_parser("fields", help="List all frontmatter fields")
    fields_p.add_argument("pages_dir")

    args = parser.parse_args()
    fq = FrontmatterQuery(args.pages_dir)

    if args.command == "exec":
        # Auto-index if database is empty
        conn = sqlite3.connect(fq.db_path)
        count = conn.execute("SELECT COUNT(*) FROM page_meta").fetchone()[0]
        conn.close()
        if count == 0:
            fq.index()
        results = fq.execute(args.query)
        print(json.dumps(results, indent=2))

    elif args.command == "index":
        stats = fq.index()
        logger.info("Index rebuilt", extra={"pages": stats['pages'], "fields": stats['fields']})
        print(f"Indexed {stats['pages']} pages, {stats['fields']} fields")

    elif args.command == "fields":
        # Auto-index if database is empty
        conn = sqlite3.connect(fq.db_path)
        count = conn.execute("SELECT COUNT(*) FROM page_meta").fetchone()[0]
        conn.close()
        if count == 0:
            fq.index()
        results = fq.get_fields()
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
