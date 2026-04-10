#!/usr/bin/env python3
"""provenance.py — Research provenance tracking (W3C PROV-inspired).

Usage:
    python3 provenance.py record <activity_type> <agent> <inputs> <outputs> [--cache-dir DIR]
    python3 provenance.py trace <slug> [--cache-dir DIR]
    python3 provenance.py export [--cache-dir DIR]
    python3 provenance.py stats [--cache-dir DIR]

Every wiki page traces back to its sources. Tracks activities (research, ingest,
edit), entities (pages, sources), and derivations (which activity created what
from what input).
"""

import argparse
import json
import sqlite3
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from wiki_logging import get_logger

logger = get_logger(__name__)


class ProvenanceDB:
    """W3C PROV-inspired provenance tracking for wiki content."""

    def __init__(self, cache_dir: Path = None):
        if cache_dir is None:
            cache_dir = Path(".wiki/cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / "provenance.db"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                agent TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                metadata TEXT DEFAULT '{}'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                slug TEXT NOT NULL,
                version_hash TEXT,
                entity_type TEXT DEFAULT 'page',
                created_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_slug ON entities(slug)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS derivations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                output_entity_id TEXT NOT NULL,
                activity_id TEXT NOT NULL,
                input_entity_id TEXT,
                derivation_type TEXT DEFAULT 'derived',
                FOREIGN KEY(output_entity_id) REFERENCES entities(id),
                FOREIGN KEY(activity_id) REFERENCES activities(id),
                FOREIGN KEY(input_entity_id) REFERENCES entities(id)
            )
        """)
        conn.commit()
        conn.close()

    def record(
        self,
        activity_type: str,
        agent: str,
        input_slugs: list[str],
        output_slugs: list[str],
        metadata: dict = None,
    ) -> str:
        """Record a provenance activity.

        Args:
            activity_type: e.g., 'ingest', 'research-scan', 'edit', 'synthesis'
            agent: e.g., 'wiki-writer', 'research-loop', 'user'
            input_slugs: Source page slugs
            output_slugs: Output page slugs
            metadata: Extra info (search queries, URLs, etc.)

        Returns:
            Activity ID
        """
        activity_id = str(uuid.uuid4())[:8]
        now = datetime.now(UTC).isoformat()

        conn = sqlite3.connect(self.db_path)

        conn.execute(
            "INSERT INTO activities (id, type, agent, started_at, ended_at, metadata) VALUES (?, ?, ?, ?, ?, ?)",
            (activity_id, activity_type, agent, now, now, json.dumps(metadata or {})),
        )

        # Create/get entities for inputs
        input_entity_ids = []
        for slug in input_slugs:
            entity_id = f"{slug}@{now[:10]}"
            conn.execute(
                "INSERT OR IGNORE INTO entities (id, slug, entity_type, created_at) VALUES (?, ?, 'source', ?)",
                (entity_id, slug, now),
            )
            input_entity_ids.append(entity_id)

        # Create entities for outputs and link derivations
        for slug in output_slugs:
            entity_id = f"{slug}@{now[:10]}"
            conn.execute(
                "INSERT OR REPLACE INTO entities (id, slug, entity_type, created_at) VALUES (?, ?, 'page', ?)",
                (entity_id, slug, now),
            )

            for input_eid in input_entity_ids:
                conn.execute(
                    "INSERT INTO derivations (output_entity_id, activity_id, input_entity_id) VALUES (?, ?, ?)",
                    (entity_id, activity_id, input_eid),
                )

            # If no inputs, record as self-generated
            if not input_entity_ids:
                conn.execute(
                    "INSERT INTO derivations (output_entity_id, activity_id) VALUES (?, ?)",
                    (entity_id, activity_id),
                )

        conn.commit()
        conn.close()
        return activity_id

    def trace(self, slug: str) -> list[dict]:
        """Trace the full provenance chain for a page."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Find all entities for this slug
        cursor.execute("SELECT id FROM entities WHERE slug = ? ORDER BY created_at DESC", (slug,))
        entity_ids = [row[0] for row in cursor.fetchall()]

        chain = []
        visited_activities = set()

        for entity_id in entity_ids:
            cursor.execute(
                """SELECT d.activity_id, d.input_entity_id, d.derivation_type,
                          a.type, a.agent, a.started_at, a.metadata
                   FROM derivations d
                   JOIN activities a ON d.activity_id = a.id
                   WHERE d.output_entity_id = ?
                   ORDER BY a.started_at DESC""",
                (entity_id,),
            )

            for row in cursor.fetchall():
                act_id = row[0]
                if act_id in visited_activities:
                    continue
                visited_activities.add(act_id)

                input_slug = ""
                if row[1]:
                    cursor.execute("SELECT slug FROM entities WHERE id = ?", (row[1],))
                    inp_row = cursor.fetchone()
                    input_slug = inp_row[0] if inp_row else ""

                chain.append({
                    "activity_id": act_id,
                    "activity_type": row[3],
                    "agent": row[4],
                    "timestamp": row[5],
                    "input_slug": input_slug,
                    "metadata": json.loads(row[6]) if row[6] else {},
                })

        conn.close()
        return chain

    def export(self) -> dict:
        """Export full provenance graph as PROV-JSON-like structure."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM activities ORDER BY started_at")
        activities = [
            {"id": r[0], "type": r[1], "agent": r[2], "started": r[3], "ended": r[4]}
            for r in cursor.fetchall()
        ]

        cursor.execute("SELECT * FROM entities ORDER BY created_at")
        entities = [
            {"id": r[0], "slug": r[1], "version": r[2], "type": r[3], "created": r[4]}
            for r in cursor.fetchall()
        ]

        cursor.execute("SELECT output_entity_id, activity_id, input_entity_id FROM derivations")
        derivations = [
            {"output": r[0], "activity": r[1], "input": r[2]}
            for r in cursor.fetchall()
        ]

        conn.close()
        return {"activities": activities, "entities": entities, "derivations": derivations}

    def stats(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM activities")
        acts = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM entities")
        ents = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM derivations")
        derivs = cursor.fetchone()[0]
        cursor.execute("SELECT type, COUNT(*) FROM activities GROUP BY type ORDER BY COUNT(*) DESC")
        by_type = {r[0]: r[1] for r in cursor.fetchall()}
        conn.close()
        return {"activities": acts, "entities": ents, "derivations": derivs, "by_type": by_type}


def main():
    parser = argparse.ArgumentParser(
        description="Research provenance tracking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    rec_p = subparsers.add_parser("record", help="Record a provenance activity")
    rec_p.add_argument("activity_type")
    rec_p.add_argument("agent")
    rec_p.add_argument("inputs", help="Comma-separated input slugs")
    rec_p.add_argument("outputs", help="Comma-separated output slugs")
    rec_p.add_argument("--cache-dir", default=".wiki/cache")

    trace_p = subparsers.add_parser("trace", help="Trace provenance for a page")
    trace_p.add_argument("slug")
    trace_p.add_argument("--cache-dir", default=".wiki/cache")

    export_p = subparsers.add_parser("export", help="Export provenance graph")
    export_p.add_argument("--cache-dir", default=".wiki/cache")

    stats_p = subparsers.add_parser("stats", help="Provenance statistics")
    stats_p.add_argument("--cache-dir", default=".wiki/cache")

    args = parser.parse_args()
    cache_dir = Path(getattr(args, "cache_dir", ".wiki/cache"))
    prov = ProvenanceDB(cache_dir)

    if args.command == "record":
        inputs = [s.strip() for s in args.inputs.split(",") if s.strip()]
        outputs = [s.strip() for s in args.outputs.split(",") if s.strip()]
        act_id = prov.record(args.activity_type, args.agent, inputs, outputs)
        logger.info("Recorded provenance activity", extra={"activity_id": act_id, "type": args.activity_type, "agent": args.agent})
        print(f"Recorded activity: {act_id}")

    elif args.command == "trace":
        chain = prov.trace(args.slug)
        print(json.dumps(chain, indent=2))

    elif args.command == "export":
        data = prov.export()
        print(json.dumps(data, indent=2))

    elif args.command == "stats":
        stats = prov.stats()
        print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
