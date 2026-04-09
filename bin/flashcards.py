#!/usr/bin/env python3
"""flashcards.py — Spaced repetition from wiki content via FSRS.

Usage:
    python3 flashcards.py generate <pages_dir> [<slug>]  — Generate cards from pages
    python3 flashcards.py due [--limit N]                — Get due cards
    python3 flashcards.py review <card_id> <rating>      — Record a review (1=again, 2=hard, 3=good, 4=easy)
    python3 flashcards.py stats                          — Review statistics
    python3 flashcards.py export [--format json|csv]     — Export all cards

Extracts flashcard-worthy content from wiki pages: question headings, definitions,
key facts, relationships. Uses FSRS (Free Spaced Repetition Scheduler) algorithm.
"""

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, UTC
from pathlib import Path

from wiki_logging import get_logger

logger = get_logger(__name__)


class FlashcardDB:
    """Manages spaced repetition flashcards from wiki content."""

    def __init__(self, cache_dir: Path = None):
        if cache_dir is None:
            cache_dir = Path(".wiki/cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / "flashcards.db"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL,
                card_type TEXT NOT NULL,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                difficulty REAL DEFAULT 0.3,
                stability REAL DEFAULT 1.0,
                due_date TEXT NOT NULL,
                last_review TEXT,
                reps INTEGER DEFAULT 0,
                lapses INTEGER DEFAULT 0,
                state TEXT DEFAULT 'new',
                created_at TEXT NOT NULL,
                UNIQUE(slug, front)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_slug ON cards(slug)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                reviewed_at TEXT NOT NULL,
                elapsed_days REAL,
                FOREIGN KEY(card_id) REFERENCES cards(id)
            )
        """)
        conn.commit()
        conn.close()

    def generate_cards(self, pages_dir: Path, slug: str = None) -> dict:
        """Extract flashcards from wiki pages."""
        pages_dir = Path(pages_dir)
        stats = {"cards_created": 0, "cards_skipped": 0, "pages_processed": 0}

        if slug:
            files = [pages_dir / f"{slug}.md"]
        else:
            files = sorted(pages_dir.glob("*.md"))

        conn = sqlite3.connect(self.db_path)
        now = datetime.now(UTC).isoformat()

        for md_file in files:
            if not md_file.exists():
                continue

            page_slug = md_file.stem
            # Skip daily notes, index pages, etc.
            if page_slug.startswith("daily-") or page_slug in ("index", "overview", "log"):
                continue

            content = md_file.read_text(encoding="utf-8")

            # Strip frontmatter
            body = content
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    body = parts[2]

            cards = self._extract_cards(body, page_slug)
            stats["pages_processed"] += 1

            for card in cards:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO cards
                           (slug, card_type, front, back, due_date, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (page_slug, card["type"], card["front"], card["back"], now, now),
                    )
                    if conn.total_changes:
                        stats["cards_created"] += 1
                    else:
                        stats["cards_skipped"] += 1
                except sqlite3.IntegrityError:
                    stats["cards_skipped"] += 1

        conn.commit()
        conn.close()
        return stats

    def _extract_cards(self, body: str, slug: str) -> list[dict]:
        """Extract flashcard-worthy content from markdown body."""
        cards = []
        lines = body.split("\n")

        # 1. Question headings → cards
        for i, line in enumerate(lines):
            if re.match(r"^#{2,4}\s+.*\?$", line):
                question = re.sub(r"^#{2,4}\s+", "", line).strip()
                # Collect answer (next paragraph)
                answer_lines = []
                for j in range(i + 1, min(i + 10, len(lines))):
                    if lines[j].strip().startswith("#"):
                        break
                    if lines[j].strip():
                        answer_lines.append(lines[j].strip())
                if answer_lines:
                    cards.append({
                        "type": "question",
                        "front": question,
                        "back": " ".join(answer_lines)[:500],
                    })

        # 2. Definitions ("X is ..." or "X are ...")
        for line in lines:
            match = re.match(
                r"^\*?\*?([A-Z][^.]{3,50})\*?\*?\s+(?:is|are)\s+(.{20,300})",
                line.strip(),
            )
            if match:
                term = match.group(1).strip("*").strip()
                definition = match.group(2).strip()
                cards.append({
                    "type": "definition",
                    "front": f"What is {term}?",
                    "back": f"{term} is {definition}",
                })

        # 3. Key Takeaways / Summary sections
        in_takeaway = False
        takeaway_items = []
        for line in lines:
            if re.match(r"^#{2,4}\s+(Key Takeaways?|Summary|Conclusion)", line, re.IGNORECASE):
                in_takeaway = True
                continue
            if in_takeaway:
                if line.strip().startswith("#"):
                    in_takeaway = False
                    continue
                if line.strip().startswith("- ") or line.strip().startswith("* "):
                    item = line.strip().lstrip("-* ").strip()
                    if len(item) > 20:
                        takeaway_items.append(item)

        for item in takeaway_items[:5]:
            cards.append({
                "type": "takeaway",
                "front": f"Key fact from {slug.replace('-', ' ').title()}:",
                "back": item[:300],
            })

        return cards

    def get_due_cards(self, limit: int = 20) -> list[dict]:
        """Get cards due for review."""
        now = datetime.now(UTC).isoformat()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """SELECT id, slug, card_type, front, back, difficulty, stability, reps, state
               FROM cards
               WHERE due_date <= ?
               ORDER BY due_date ASC
               LIMIT ?""",
            (now, limit),
        )

        results = [
            {
                "id": row[0],
                "slug": row[1],
                "card_type": row[2],
                "front": row[3],
                "back": row[4],
                "difficulty": row[5],
                "stability": row[6],
                "reps": row[7],
                "state": row[8],
            }
            for row in cursor.fetchall()
        ]
        conn.close()
        return results

    def review_card(self, card_id: int, rating: int) -> dict:
        """Record a review and update scheduling.

        Rating: 1=again, 2=hard, 3=good, 4=easy
        Uses simplified FSRS-like scheduling.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT difficulty, stability, reps, lapses, last_review FROM cards WHERE id = ?",
            (card_id,),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {"error": "Card not found"}

        difficulty, stability, reps, lapses, last_review = row
        now = datetime.now(UTC)

        # Calculate elapsed days
        elapsed = 0.0
        if last_review:
            try:
                last_dt = datetime.fromisoformat(last_review.replace("Z", "+00:00"))
                elapsed = (now - last_dt).total_seconds() / 86400
            except ValueError:
                pass

        # Simplified FSRS scheduling
        if rating == 1:  # Again
            lapses += 1
            stability = max(0.5, stability * 0.5)
            difficulty = min(1.0, difficulty + 0.1)
            interval = timedelta(minutes=10)
            state = "relearning"
        elif rating == 2:  # Hard
            interval = timedelta(days=max(1, stability * 0.8))
            stability = stability * 1.2
            difficulty = min(1.0, difficulty + 0.05)
            reps += 1
            state = "review"
        elif rating == 3:  # Good
            interval = timedelta(days=max(1, stability))
            stability = stability * 2.5
            difficulty = max(0.0, difficulty - 0.02)
            reps += 1
            state = "review"
        else:  # Easy (4)
            interval = timedelta(days=max(1, stability * 1.3))
            stability = stability * 3.5
            difficulty = max(0.0, difficulty - 0.05)
            reps += 1
            state = "review"

        due_date = now + interval

        # Update card
        conn.execute(
            """UPDATE cards SET
               difficulty = ?, stability = ?, reps = ?, lapses = ?,
               due_date = ?, last_review = ?, state = ?
               WHERE id = ?""",
            (difficulty, stability, reps, lapses, due_date.isoformat(), now.isoformat(), state, card_id),
        )

        # Record review
        conn.execute(
            "INSERT INTO reviews (card_id, rating, reviewed_at, elapsed_days) VALUES (?, ?, ?, ?)",
            (card_id, rating, now.isoformat(), elapsed),
        )

        conn.commit()
        conn.close()

        return {
            "card_id": card_id,
            "rating": rating,
            "next_due": due_date.isoformat(),
            "interval_days": interval.total_seconds() / 86400,
            "stability": round(stability, 2),
            "difficulty": round(difficulty, 2),
        }

    def stats(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM cards")
        total = cursor.fetchone()[0]

        now = datetime.now(UTC).isoformat()
        cursor.execute("SELECT COUNT(*) FROM cards WHERE due_date <= ?", (now,))
        due = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM reviews")
        reviews = cursor.fetchone()[0]

        cursor.execute("SELECT state, COUNT(*) FROM cards GROUP BY state")
        by_state = {r[0]: r[1] for r in cursor.fetchall()}

        cursor.execute("SELECT card_type, COUNT(*) FROM cards GROUP BY card_type")
        by_type = {r[0]: r[1] for r in cursor.fetchall()}

        conn.close()
        return {
            "total_cards": total,
            "due_now": due,
            "total_reviews": reviews,
            "by_state": by_state,
            "by_type": by_type,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Spaced repetition flashcards from wiki content",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    gen_p = subparsers.add_parser("generate", help="Generate cards from pages")
    gen_p.add_argument("pages_dir")
    gen_p.add_argument("slug", nargs="?")

    due_p = subparsers.add_parser("due", help="Get due cards")
    due_p.add_argument("--limit", type=int, default=20)

    rev_p = subparsers.add_parser("review", help="Record a review")
    rev_p.add_argument("card_id", type=int)
    rev_p.add_argument("rating", type=int, choices=[1, 2, 3, 4])

    stats_p = subparsers.add_parser("stats", help="Review statistics")

    args = parser.parse_args()
    fdb = FlashcardDB()

    if args.command == "generate":
        stats = fdb.generate_cards(args.pages_dir, args.slug)
        print(json.dumps(stats, indent=2))

    elif args.command == "due":
        cards = fdb.get_due_cards(args.limit)
        print(json.dumps(cards, indent=2))

    elif args.command == "review":
        result = fdb.review_card(args.card_id, args.rating)
        print(json.dumps(result, indent=2))

    elif args.command == "stats":
        stats = fdb.stats()
        print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
