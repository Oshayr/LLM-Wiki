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


# Freshness tiers: tier name → (max_age_minutes, keyword set)
# Resolution: explicit frontmatter > auto-classification from content keywords
FRESHNESS_TIERS = {
    "live":      (15,          {"stock", "price", "live", "score", "server-status", "deploy", "deployment"}),
    "breaking":  (360,         {"breaking", "incident", "outage", "announcement", "release-note"}),
    "current":   (3 * 1440,    {"news", "current-events", "trending", "election", "market"}),
    "fast":      (28 * 1440,   {"ai", "llm", "gpt", "claude", "mcp", "agent", "api", "sdk", "model", "benchmark"}),
    "moderate":  (90 * 1440,   {"version", "release", "software", "framework", "library", "tool", "package"}),
    "standard":  (180 * 1440,  set()),  # default — 6 months
    "academic":  (365 * 1440,  {"paper", "research", "study", "theorem", "proof", "algorithm", "journal"}),
    "evergreen": (1825 * 1440, {"history", "biography", "foundational", "principle", "law", "theory", "philosophy"}),
    "permanent": (None,        {"personal", "note", "idea", "memory", "journal", "diary", "dream"}),
}


def classify_freshness_tier(page: dict) -> tuple[str, int | None]:
    """Classify a page's freshness tier and return (tier_name, max_age_minutes).

    Resolution order:
    1. Explicit `freshness_tier:` in frontmatter
    2. Explicit `ttl:` in frontmatter (e.g. '30m', '2d', '1h')
    3. Auto-classification from tags, type, and content keywords
    """
    # 1. Explicit freshness_tier in frontmatter
    fm_tier = page.get("freshness_tier", "")
    if fm_tier and fm_tier in FRESHNESS_TIERS:
        max_age, _ = FRESHNESS_TIERS[fm_tier]
        return fm_tier, max_age

    # 2. Explicit ttl in frontmatter (e.g. '30m', '2d', '6h', '1y')
    ttl_str = page.get("ttl", "")
    if ttl_str:
        ttl_minutes = _parse_ttl(ttl_str)
        if ttl_minutes is not None:
            return "custom", ttl_minutes

    # 3. Auto-classify from content keywords
    content_lower = page.get("content_lower", "")
    page_type = page.get("type", "").lower()
    tags_str = page.get("tags", "").lower()
    text_to_scan = f"{content_lower} {page_type} {tags_str}"

    for tier_name, (max_age, keywords) in FRESHNESS_TIERS.items():
        if not keywords:
            continue  # skip 'standard' (no keywords — it's the default)
        if any(kw in text_to_scan for kw in keywords):
            return tier_name, max_age

    # Default: standard
    max_age, _ = FRESHNESS_TIERS["standard"]
    return "standard", max_age


def _parse_ttl(ttl_str: str) -> int | None:
    """Parse a TTL string like '30m', '2d', '6h', '1y' into minutes."""
    import re as _re
    m = _re.match(r"(\d+)\s*([mhdwy])", ttl_str.strip().lower())
    if not m:
        return None
    value = int(m.group(1))
    unit = m.group(2)
    multipliers = {"m": 1, "h": 60, "d": 1440, "w": 10080, "y": 525600}
    return value * multipliers.get(unit, 1440)


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
            "freshness_tier": fm.get("freshness_tier", ""),
            "ttl": fm.get("ttl", ""),
            "tags": fm.get("tags", ""),
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
    """Find freshness gaps — stale pages based on intelligent freshness tiers."""
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

        age_minutes = (now - updated_dt).total_seconds() / 60
        age_days = age_minutes / 1440

        tier_name, max_age_minutes = classify_freshness_tier(p)

        # permanent tier = never stale
        if max_age_minutes is None:
            continue

        if age_minutes > max_age_minutes:
            gaps.append({
                "type": "stale_content",
                "slug": p["slug"],
                "title": p["title"],
                "updated": updated,
                "age_days": round(age_days, 1),
                "freshness_tier": tier_name,
                "max_age_days": round(max_age_minutes / 1440, 1),
                "suggestion": f"Last updated {round(age_days)}d ago — tier '{tier_name}' (max {round(max_age_minutes / 1440)}d)",
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
