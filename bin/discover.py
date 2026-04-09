#!/usr/bin/env python3
"""discover.py — Relationship discovery via embedding similarity.

Usage:
    python3 discover.py related <pages_dir> <slug> [--top N]   — Find similar unlinked pages
    python3 discover.py all <pages_dir> [--threshold 0.7]      — All suggested connections
    python3 discover.py clusters <pages_dir> [--n 10]          — Page clusters

Uses page-level embeddings from embed.py to find implicit relationships
between pages that aren't yet linked.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def _get_linked_slugs(pages_dir: Path, slug: str) -> set[str]:
    """Get slugs that are already linked from a page."""
    import re

    md_file = pages_dir / f"{slug}.md"
    if not md_file.exists():
        return set()

    content = md_file.read_text(encoding="utf-8")
    pattern = r"\[\[([^\]|#]+)"
    return set(re.findall(pattern, content))


def find_related(pages_dir: Path, slug: str, top: int = 10) -> list[dict]:
    """Find pages similar to slug but not yet linked."""
    sys.path.insert(0, str(Path(__file__).parent))
    from embed import EmbeddingIndex

    idx = EmbeddingIndex(pages_dir)
    linked = _get_linked_slugs(pages_dir, slug)
    linked.add(slug)  # Exclude self

    results = idx.find_similar_pages(slug, top=top + len(linked), exclude_linked=linked)
    return results[:top]


def find_all_suggestions(pages_dir: Path, threshold: float = 0.7) -> list[dict]:
    """Find all page pairs with high similarity but no link between them."""
    sys.path.insert(0, str(Path(__file__).parent))
    from embed import EmbeddingIndex, bytes_to_embed

    import numpy as np

    idx = EmbeddingIndex(pages_dir)

    # Load all page embeddings
    conn = sqlite3.connect(idx.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT slug, embedding FROM page_embeddings")
    rows = cursor.fetchall()
    conn.close()

    if len(rows) < 2:
        return []

    slugs = [r[0] for r in rows]
    embeddings = np.array([bytes_to_embed(r[1]) for r in rows], dtype=np.float32)

    # Build existing link set
    all_linked = {}
    for slug in slugs:
        all_linked[slug] = _get_linked_slugs(pages_dir, slug)

    # Compute pairwise similarities
    similarity_matrix = np.dot(embeddings, embeddings.T)

    suggestions = []
    for i in range(len(slugs)):
        for j in range(i + 1, len(slugs)):
            sim = float(similarity_matrix[i][j])
            if sim >= threshold:
                # Check if already linked in either direction
                if slugs[j] not in all_linked.get(slugs[i], set()) and \
                   slugs[i] not in all_linked.get(slugs[j], set()):
                    suggestions.append({
                        "page_a": slugs[i],
                        "page_b": slugs[j],
                        "similarity": round(sim, 4),
                    })

    suggestions.sort(key=lambda x: x["similarity"], reverse=True)
    return suggestions


def find_clusters(pages_dir: Path, n_clusters: int = 10) -> list[dict]:
    """Cluster pages by embedding similarity."""
    sys.path.insert(0, str(Path(__file__).parent))
    from embed import EmbeddingIndex

    idx = EmbeddingIndex(pages_dir)
    return idx.cluster_pages(n_clusters)


def main():
    parser = argparse.ArgumentParser(
        description="Relationship discovery via embedding similarity",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    rel_p = subparsers.add_parser("related", help="Find similar unlinked pages")
    rel_p.add_argument("pages_dir")
    rel_p.add_argument("slug")
    rel_p.add_argument("--top", type=int, default=10)

    all_p = subparsers.add_parser("all", help="All suggested connections")
    all_p.add_argument("pages_dir")
    all_p.add_argument("--threshold", type=float, default=0.7)

    clust_p = subparsers.add_parser("clusters", help="Page clusters")
    clust_p.add_argument("pages_dir")
    clust_p.add_argument("--n", type=int, default=10)

    args = parser.parse_args()

    if args.command == "related":
        results = find_related(args.pages_dir, args.slug, args.top)
        print(json.dumps(results, indent=2))

    elif args.command == "all":
        results = find_all_suggestions(args.pages_dir, args.threshold)
        print(json.dumps(results, indent=2))
        print(f"\n{len(results)} suggested connections", file=sys.stderr)

    elif args.command == "clusters":
        results = find_clusters(args.pages_dir, args.n)
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
