#!/usr/bin/env python3
"""claims.py — Claim extraction and verification tracking.

Usage:
    python3 claims.py extract <pages_dir> <slug>     — Extract verifiable claims
    python3 claims.py check <claim_id>               — Mark a claim as checked
    python3 claims.py report <pages_dir> <slug>      — Verification report for a page
    python3 claims.py stats                          — Overall verification statistics

Extracts factual claims from wiki pages and tracks their verification status.
Used by the fact-checker agent.
"""

import argparse
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from wiki_logging import get_logger

logger = get_logger(__name__)


class ClaimsDB:
    """Manages factual claim extraction and verification tracking."""

    def __init__(self, cache_dir: Path = None):
        if cache_dir is None:
            cache_dir = Path(".wiki/cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / "claims.db"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL,
                claim_text TEXT NOT NULL,
                claim_type TEXT DEFAULT 'factual',
                status TEXT DEFAULT 'unverified',
                sources_for TEXT DEFAULT '[]',
                sources_against TEXT DEFAULT '[]',
                last_checked TEXT,
                extracted_at TEXT NOT NULL,
                UNIQUE(slug, claim_text)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_slug ON claims(slug)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status)")
        conn.commit()
        conn.close()

    def extract_claims(self, pages_dir: Path, slug: str) -> list[dict]:
        """Extract verifiable factual claims from a wiki page."""
        md_file = Path(pages_dir) / f"{slug}.md"
        if not md_file.exists():
            logger.warning("Page not found", extra={"slug": slug})
            return [{"error": f"Page '{slug}' not found"}]

        content = md_file.read_text(encoding="utf-8")

        # Strip frontmatter
        body = content
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                body = parts[2]

        claims = []
        sentences = re.split(r'(?<=[.!?])\s+', body)

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20 or len(sentence) > 500:
                continue

            # Skip headings, list markers, code blocks
            if sentence.startswith("#") or sentence.startswith("```"):
                continue
            if sentence.startswith("- [ ]") or sentence.startswith("- [x]"):
                continue

            claim_type = self._classify_claim(sentence)
            if claim_type:
                claims.append({
                    "claim_text": sentence[:400],
                    "claim_type": claim_type,
                })

        # Store in DB
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(UTC).isoformat()
        stored = 0

        for claim in claims[:20]:  # Cap at 20 claims per page
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO claims
                       (slug, claim_text, claim_type, extracted_at)
                       VALUES (?, ?, ?, ?)""",
                    (slug, claim["claim_text"], claim["claim_type"], now),
                )
                stored += 1
            except sqlite3.IntegrityError:
                pass

        conn.commit()
        conn.close()

        return claims[:20]

    def _classify_claim(self, sentence: str) -> str | None:
        """Classify whether a sentence contains a verifiable claim.

        Returns claim type or None if not claim-worthy.
        """
        # Contains numbers/percentages/dates
        if re.search(r'\d+(?:\.\d+)?%|\d{4}|\d+(?:,\d{3})+|\$[\d,.]+', sentence):
            return "quantitative"

        # Named entity claims (X does/is/has Y)
        if re.search(r'(?:^|\s)[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:is|are|was|were|has|have|does|did|can|will|supports?|provides?|uses?|implements?)', sentence):
            return "entity"

        # Comparative claims
        if re.search(r'\b(?:faster|slower|better|worse|larger|smaller|more|fewer|higher|lower|outperforms?|exceeds?)\b', sentence, re.IGNORECASE):
            return "comparative"

        # Definitive/absolute claims
        if re.search(r'\b(?:always|never|all|none|every|no one|impossible|guaranteed|proven|confirmed)\b', sentence, re.IGNORECASE):
            return "absolute"

        return None

    def update_claim(self, claim_id: int, status: str, sources_for: list = None, sources_against: list = None) -> dict:
        """Update a claim's verification status."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(UTC).isoformat()

        updates = ["status = ?", "last_checked = ?"]
        params = [status, now]

        if sources_for is not None:
            updates.append("sources_for = ?")
            params.append(json.dumps(sources_for))

        if sources_against is not None:
            updates.append("sources_against = ?")
            params.append(json.dumps(sources_against))

        params.append(claim_id)
        conn.execute(
            f"UPDATE claims SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        conn.close()
        return {"claim_id": claim_id, "status": status}

    def get_report(self, slug: str) -> dict:
        """Get verification report for a page."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, claim_text, claim_type, status, sources_for, sources_against, last_checked FROM claims WHERE slug = ? ORDER BY id",
            (slug,),
        )

        claims = []
        status_counts = {}
        for row in cursor.fetchall():
            status = row[3]
            status_counts[status] = status_counts.get(status, 0) + 1
            claims.append({
                "id": row[0],
                "claim_text": row[1],
                "claim_type": row[2],
                "status": row[3],
                "sources_for": json.loads(row[4]) if row[4] else [],
                "sources_against": json.loads(row[5]) if row[5] else [],
                "last_checked": row[6],
            })

        conn.close()
        return {
            "slug": slug,
            "total_claims": len(claims),
            "status_counts": status_counts,
            "claims": claims,
        }

    def stats(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM claims")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT status, COUNT(*) FROM claims GROUP BY status")
        by_status = {r[0]: r[1] for r in cursor.fetchall()}

        cursor.execute("SELECT claim_type, COUNT(*) FROM claims GROUP BY claim_type")
        by_type = {r[0]: r[1] for r in cursor.fetchall()}

        cursor.execute("SELECT COUNT(DISTINCT slug) FROM claims")
        pages_with_claims = cursor.fetchone()[0]

        conn.close()
        return {
            "total_claims": total,
            "pages_with_claims": pages_with_claims,
            "by_status": by_status,
            "by_type": by_type,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Claim extraction and verification tracking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    ext_p = subparsers.add_parser("extract", help="Extract claims from a page")
    ext_p.add_argument("pages_dir")
    ext_p.add_argument("slug")

    check_p = subparsers.add_parser("check", help="Update claim status")
    check_p.add_argument("claim_id", type=int)
    check_p.add_argument("--status", default="verified", choices=["verified", "unverified", "disputed", "outdated"])

    report_p = subparsers.add_parser("report", help="Verification report for a page")
    report_p.add_argument("pages_dir")
    report_p.add_argument("slug")

    stats_p = subparsers.add_parser("stats", help="Overall statistics")

    args = parser.parse_args()
    cdb = ClaimsDB()

    if args.command == "extract":
        claims = cdb.extract_claims(args.pages_dir, args.slug)
        print(json.dumps(claims, indent=2))

    elif args.command == "check":
        result = cdb.update_claim(args.claim_id, args.status)
        print(json.dumps(result, indent=2))

    elif args.command == "report":
        report = cdb.get_report(args.slug)
        print(json.dumps(report, indent=2))

    elif args.command == "stats":
        stats = cdb.stats()
        print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
