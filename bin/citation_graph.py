#!/usr/bin/env python3
"""citation_graph.py — Build and query citation graphs via academic APIs.

Uses Semantic Scholar and OpenAlex to trace forward/backward citations and
snowball through citation chains. Stores results in SQLite for reuse.
"""

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


class CitationGraph:
    """Builds and queries citation graphs via academic APIs."""

    S2_BASE = "https://api.semanticscholar.org/graph/v1"
    OPENALEX_BASE = "https://api.openalex.org"

    def __init__(self, cache_dir: Path = None):
        if cache_dir is None:
            cache_dir = Path(".wiki/cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / "citations.db"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS papers (
                paper_id TEXT PRIMARY KEY,
                doi TEXT,
                title TEXT,
                year INTEGER,
                authors TEXT,
                abstract TEXT,
                citation_count INTEGER DEFAULT 0,
                venue TEXT,
                url TEXT,
                fetched_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS cites (
                citing_id TEXT NOT NULL,
                cited_id TEXT NOT NULL,
                UNIQUE(citing_id, cited_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cites_citing ON cites(citing_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cites_cited ON cites(cited_id)")
        conn.commit()
        conn.close()

    def _api_get(self, url: str, _retries: int = 0) -> dict | None:
        """Make a GET request with rate limiting."""
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "llm-wiki/1.0 (https://github.com/Oshayr/llm-wiki)")
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and _retries < 3:
                wait = 5 * (2 ** _retries)
                print(f"Rate limited, waiting {wait}s (retry {_retries + 1}/3)...", file=sys.stderr)
                time.sleep(wait)
                return self._api_get(url, _retries=_retries + 1)
            print(f"API error {e.code}: {url}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Request failed: {e}", file=sys.stderr)
            return None

    def _resolve_paper_id(self, identifier: str) -> str | None:
        """Resolve a DOI or URL to a Semantic Scholar paper ID."""
        # If it looks like a DOI
        if identifier.startswith("10."):
            data = self._api_get(
                f"{self.S2_BASE}/paper/DOI:{identifier}?fields=paperId,title,year,authors,citationCount,venue,abstract,externalIds"
            )
        elif identifier.startswith("http"):
            data = self._api_get(
                f"{self.S2_BASE}/paper/URL:{identifier}?fields=paperId,title,year,authors,citationCount,venue,abstract,externalIds"
            )
        else:
            data = self._api_get(
                f"{self.S2_BASE}/paper/{identifier}?fields=paperId,title,year,authors,citationCount,venue,abstract,externalIds"
            )

        if data and "paperId" in data:
            self._store_paper(data)
            return data["paperId"]
        return None

    def _store_paper(self, data: dict):
        """Store paper metadata in the database."""
        from datetime import datetime, UTC

        paper_id = data.get("paperId", "")
        doi = ""
        if "externalIds" in data and data["externalIds"]:
            doi = data["externalIds"].get("DOI", "")
        elif "doi" in data:
            doi = data.get("doi", "")

        authors = ", ".join(
            a.get("name", "") for a in (data.get("authors") or [])[:10]
        )

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT OR REPLACE INTO papers
               (paper_id, doi, title, year, authors, abstract, citation_count, venue, url, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                paper_id,
                doi,
                data.get("title", ""),
                data.get("year"),
                authors,
                (data.get("abstract") or "")[:1000],
                data.get("citationCount", 0),
                data.get("venue", ""),
                data.get("url", ""),
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
        conn.close()

    def forward(self, identifier: str, limit: int = 50) -> list[dict]:
        """Get papers that cite this paper (forward snowball)."""
        paper_id = self._resolve_paper_id(identifier)
        if not paper_id:
            return [{"error": f"Could not resolve: {identifier}"}]

        data = self._api_get(
            f"{self.S2_BASE}/paper/{paper_id}/citations?fields=paperId,title,year,authors,citationCount,venue,externalIds&limit={limit}"
        )

        if not data or "data" not in data:
            return []

        results = []
        conn = sqlite3.connect(self.db_path)

        for item in data["data"]:
            citing = item.get("citingPaper", {})
            if not citing.get("paperId"):
                continue

            self._store_paper(citing)

            conn.execute(
                "INSERT OR IGNORE INTO cites (citing_id, cited_id) VALUES (?, ?)",
                (citing["paperId"], paper_id),
            )

            doi = ""
            if citing.get("externalIds"):
                doi = citing["externalIds"].get("DOI", "")

            results.append({
                "paper_id": citing["paperId"],
                "doi": doi,
                "title": citing.get("title", ""),
                "year": citing.get("year"),
                "citation_count": citing.get("citationCount", 0),
            })

        conn.commit()
        conn.close()
        return results

    def backward(self, identifier: str, limit: int = 50) -> list[dict]:
        """Get papers referenced by this paper (backward snowball)."""
        paper_id = self._resolve_paper_id(identifier)
        if not paper_id:
            return [{"error": f"Could not resolve: {identifier}"}]

        data = self._api_get(
            f"{self.S2_BASE}/paper/{paper_id}/references?fields=paperId,title,year,authors,citationCount,venue,externalIds&limit={limit}"
        )

        if not data or "data" not in data:
            return []

        results = []
        conn = sqlite3.connect(self.db_path)

        for item in data["data"]:
            cited = item.get("citedPaper", {})
            if not cited.get("paperId"):
                continue

            self._store_paper(cited)

            conn.execute(
                "INSERT OR IGNORE INTO cites (citing_id, cited_id) VALUES (?, ?)",
                (paper_id, cited["paperId"]),
            )

            doi = ""
            if cited.get("externalIds"):
                doi = cited["externalIds"].get("DOI", "")

            results.append({
                "paper_id": cited["paperId"],
                "doi": doi,
                "title": cited.get("title", ""),
                "year": cited.get("year"),
                "citation_count": cited.get("citationCount", 0),
            })

        conn.commit()
        conn.close()
        return results

    def snowball(self, identifier: str, depth: int = 2, limit_per_level: int = 20) -> dict:
        """Recursive snowball: forward + backward at each level."""
        visited = set()
        all_papers = []
        queue = [(identifier, 0)]

        while queue:
            current_id, level = queue.pop(0)

            if level >= depth:
                continue
            if current_id in visited:
                continue
            visited.add(current_id)

            print(f"  Level {level}: snowballing {current_id[:20]}...", file=sys.stderr)

            # Forward citations
            fwd = self.forward(current_id, limit=limit_per_level)
            for p in fwd:
                if "error" not in p:
                    all_papers.append(p)
                    if p["paper_id"] not in visited:
                        queue.append((p["paper_id"], level + 1))

            time.sleep(1)  # Rate limiting

            # Backward references
            bwd = self.backward(current_id, limit=limit_per_level)
            for p in bwd:
                if "error" not in p:
                    all_papers.append(p)
                    if p["paper_id"] not in visited:
                        queue.append((p["paper_id"], level + 1))

            time.sleep(1)

        # Deduplicate
        seen_ids = set()
        unique = []
        for p in all_papers:
            if p["paper_id"] not in seen_ids:
                seen_ids.add(p["paper_id"])
                unique.append(p)

        return {
            "seed": identifier,
            "depth": depth,
            "papers_found": len(unique),
            "papers": sorted(unique, key=lambda p: p.get("citation_count", 0), reverse=True),
        }

    def export_graph(self) -> dict:
        """Export the full citation graph as nodes + edges."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT paper_id, title, year, citation_count FROM papers")
        nodes = [
            {"id": row[0], "title": row[1], "year": row[2], "citations": row[3]}
            for row in cursor.fetchall()
        ]

        cursor.execute("SELECT citing_id, cited_id FROM cites")
        edges = [
            {"source": row[0], "target": row[1]}
            for row in cursor.fetchall()
        ]

        conn.close()
        return {"nodes": nodes, "edges": edges}

    def stats(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM papers")
        papers = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM cites")
        citations = cursor.fetchone()[0]
        conn.close()
        return {"papers": papers, "citation_edges": citations}


def main():
    parser = argparse.ArgumentParser(
        description="Citation graph building via snowballing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    fwd_p = subparsers.add_parser("forward", help="Papers citing this one")
    fwd_p.add_argument("identifier", help="DOI, URL, or Semantic Scholar ID")

    bwd_p = subparsers.add_parser("backward", help="Papers referenced by this one")
    bwd_p.add_argument("identifier")

    snow_p = subparsers.add_parser("snowball", help="Recursive snowball")
    snow_p.add_argument("identifier")
    snow_p.add_argument("--depth", type=int, default=2)

    graph_p = subparsers.add_parser("graph", help="Export citation graph")

    stats_p = subparsers.add_parser("stats", help="Citation DB statistics")

    args = parser.parse_args()

    # Determine cache dir
    wiki_cache = Path(".wiki/cache")
    if not wiki_cache.exists():
        wiki_cache.mkdir(parents=True, exist_ok=True)
    cg = CitationGraph(wiki_cache)

    if args.command == "forward":
        results = cg.forward(args.identifier)
        print(json.dumps(results, indent=2))

    elif args.command == "backward":
        results = cg.backward(args.identifier)
        print(json.dumps(results, indent=2))

    elif args.command == "snowball":
        results = cg.snowball(args.identifier, depth=args.depth)
        print(json.dumps(results, indent=2))

    elif args.command == "graph":
        graph = cg.export_graph()
        print(json.dumps(graph, indent=2))

    elif args.command == "stats":
        stats = cg.stats()
        print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
