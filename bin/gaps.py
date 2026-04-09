#!/usr/bin/env python3
"""gaps.py — Multi-dimensional content gap analysis.

Usage:
    python3 gaps.py analyze <pages_dir>       — Full gap analysis
    python3 gaps.py structural <pages_dir>    — Structural gaps (missing inter-cluster links)
    python3 gaps.py depth <pages_dir>         — Depth gaps (shallow high-traffic pages)
    python3 gaps.py freshness <pages_dir>     — Freshness gaps (stale pages)

Goes beyond basic orphan detection: finds structural holes between topic clusters,
shallow-but-referenced pages, and fast-moving content that's gone stale.
"""

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


FAST_MOVING_KEYWORDS = {"ai", "llm", "gpt", "claude", "mcp", "agent", "api", "sdk"}


def _load_pages(pages_dir: Path) -> list[dict]:
    """Load all page metadata."""
    pages = []
    for md_file in sorted(pages_dir.glob("*.md")):
        slug = md_file.stem
        content = md_file.read_text(encoding="utf-8")

        # Parse frontmatter
        fm = {}
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].strip().split("\n"):
                    if ":" in line:
                        k, v = line.split(":", 1)
                        fm[k.strip()] = v.strip().strip('"').strip("'")
                body = parts[2]
            else:
                body = content
        else:
            body = content

        # Extract links
        links = set(re.findall(r"\[\[([^\]|#]+)", content))

        # Count words
        word_count = len(body.split())

        pages.append({
            "slug": slug,
            "title": fm.get("title", slug),
            "type": fm.get("type", ""),
            "confidence": fm.get("confidence", ""),
            "updated": fm.get("updated", ""),
            "word_count": word_count,
            "links_out": links,
            "content_lower": content.lower(),
        })

    return pages


def analyze_structural(pages_dir: Path) -> list[dict]:
    """Find structural gaps — topic clusters with no connecting pages."""
    pages = _load_pages(pages_dir)
    if len(pages) < 4:
        return []

    # Try to use embedding clusters
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from embed import EmbeddingIndex
        idx = EmbeddingIndex(pages_dir)
        clusters = idx.cluster_pages(min(10, len(pages) // 2))
    except Exception:
        # Fallback: group by type
        type_groups = {}
        for p in pages:
            t = p.get("type", "unknown")
            type_groups.setdefault(t, []).append(p["slug"])
        clusters = [
            {"cluster_id": i, "pages": slugs}
            for i, (_, slugs) in enumerate(type_groups.items())
        ]

    # Build link map
    all_links = {}
    for p in pages:
        all_links[p["slug"]] = p["links_out"]

    # Find cluster pairs with no inter-cluster links
    gaps = []
    for i, c1 in enumerate(clusters):
        for j, c2 in enumerate(clusters):
            if j <= i:
                continue
            s1 = set(c1["pages"])
            s2 = set(c2["pages"])

            # Count inter-cluster links
            inter_links = 0
            for slug in s1:
                inter_links += len(all_links.get(slug, set()) & s2)
            for slug in s2:
                inter_links += len(all_links.get(slug, set()) & s1)

            if inter_links == 0 and len(s1) >= 2 and len(s2) >= 2:
                gaps.append({
                    "type": "structural_hole",
                    "cluster_a": list(s1)[:5],
                    "cluster_b": list(s2)[:5],
                    "suggestion": f"No links between these {len(s1)}+{len(s2)} page clusters — consider creating a bridging page",
                })

    return gaps


def analyze_depth(pages_dir: Path) -> list[dict]:
    """Find depth gaps — pages with many incoming links but low word count."""
    pages = _load_pages(pages_dir)

    # Count incoming links
    incoming = {}
    for p in pages:
        for link in p["links_out"]:
            incoming[link] = incoming.get(link, 0) + 1

    gaps = []
    for p in pages:
        in_count = incoming.get(p["slug"], 0)
        wc = p["word_count"]

        # High traffic (3+ incoming links) but shallow (< 200 words)
        if in_count >= 3 and wc < 200:
            gaps.append({
                "type": "shallow_hub",
                "slug": p["slug"],
                "title": p["title"],
                "incoming_links": in_count,
                "word_count": wc,
                "suggestion": f"Referenced by {in_count} pages but only {wc} words — needs expansion",
            })
        # No outgoing links (isolated content)
        elif len(p["links_out"]) == 0 and wc > 100:
            gaps.append({
                "type": "isolated_page",
                "slug": p["slug"],
                "title": p["title"],
                "word_count": wc,
                "suggestion": "No outgoing links — add [[wiki-links]] to connect with related content",
            })

    gaps.sort(key=lambda g: g.get("incoming_links", 0), reverse=True)
    return gaps


def analyze_freshness(pages_dir: Path) -> list[dict]:
    """Find freshness gaps — stale pages, especially in fast-moving topics."""
    pages = _load_pages(pages_dir)
    now = datetime.now()
    gaps = []

    for p in pages:
        updated = p.get("updated", "")
        if not updated:
            continue

        try:
            updated_dt = datetime.strptime(updated, "%Y-%m-%d")
        except ValueError:
            continue

        age_days = (now - updated_dt).days

        # Check if fast-moving topic
        is_fast = any(kw in p["content_lower"] for kw in FAST_MOVING_KEYWORDS)
        threshold = 30 if is_fast else 90

        if age_days > threshold:
            gaps.append({
                "type": "stale_content",
                "slug": p["slug"],
                "title": p["title"],
                "updated": updated,
                "age_days": age_days,
                "fast_moving": is_fast,
                "suggestion": f"Last updated {age_days}d ago"
                + (" (fast-moving topic)" if is_fast else ""),
            })

    gaps.sort(key=lambda g: g["age_days"], reverse=True)
    return gaps


def analyze_all(pages_dir: Path) -> dict:
    """Run all gap analyses."""
    pages_dir = Path(pages_dir)
    structural = analyze_structural(pages_dir)
    depth = analyze_depth(pages_dir)
    freshness = analyze_freshness(pages_dir)

    # Broken links (pages linked but don't exist)
    pages = _load_pages(pages_dir)
    existing = {p["slug"] for p in pages}
    broken = {}
    for p in pages:
        for link in p["links_out"]:
            if link not in existing:
                broken.setdefault(link, []).append(p["slug"])

    missing = [
        {
            "type": "missing_page",
            "slug": slug,
            "referenced_by": refs[:5],
            "reference_count": len(refs),
            "suggestion": f"Linked from {len(refs)} pages but doesn't exist",
        }
        for slug, refs in sorted(broken.items(), key=lambda x: len(x[1]), reverse=True)
    ]

    return {
        "structural_gaps": structural,
        "depth_gaps": depth,
        "freshness_gaps": freshness,
        "missing_pages": missing,
        "summary": {
            "structural_holes": len(structural),
            "shallow_hubs": sum(1 for g in depth if g["type"] == "shallow_hub"),
            "isolated_pages": sum(1 for g in depth if g["type"] == "isolated_page"),
            "stale_pages": len(freshness),
            "missing_pages": len(missing),
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Content gap analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    all_p = subparsers.add_parser("analyze", help="Full gap analysis")
    all_p.add_argument("pages_dir")

    struct_p = subparsers.add_parser("structural", help="Structural gaps")
    struct_p.add_argument("pages_dir")

    depth_p = subparsers.add_parser("depth", help="Depth gaps")
    depth_p.add_argument("pages_dir")

    fresh_p = subparsers.add_parser("freshness", help="Freshness gaps")
    fresh_p.add_argument("pages_dir")

    args = parser.parse_args()
    pages_dir = Path(args.pages_dir)

    if args.command == "analyze":
        results = analyze_all(pages_dir)
        print(json.dumps(results, indent=2))

    elif args.command == "structural":
        results = analyze_structural(pages_dir)
        print(json.dumps(results, indent=2))

    elif args.command == "depth":
        results = analyze_depth(pages_dir)
        print(json.dumps(results, indent=2))

    elif args.command == "freshness":
        results = analyze_freshness(pages_dir)
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
