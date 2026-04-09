#!/usr/bin/env python3
"""maturity.py — Progressive summarization and note maturity tracking.

Usage:
    python3 maturity.py assess <pages_dir>        — Assess maturity of all pages
    python3 maturity.py page <pages_dir> <slug>   — Assess single page maturity
    python3 maturity.py upgrade <pages_dir>       — Suggest maturity upgrades

Maturity levels: seed → growing → mature → evergreen
Computed from: age, edit count (git), source count, incoming links, word count.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from wiki_logging import get_logger

logger = get_logger(__name__)


def _get_git_edit_count(pages_dir: Path, slug: str) -> int:
    """Get number of git commits for a page."""
    page_path = pages_dir / f"{slug}.md"
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--", str(page_path)],
            capture_output=True, text=True, cwd=str(pages_dir),
        )
        return len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
    except Exception as e:
        logger.debug(f"Could not get git edit count for {slug}: {e}")
        return 0


def _count_incoming_links(pages_dir: Path, slug: str) -> int:
    """Count pages that link to this slug."""
    count = 0
    pattern = re.compile(r"\[\[" + re.escape(slug) + r"(?:[#|]|\]\])")
    for md_file in pages_dir.glob("*.md"):
        if md_file.stem == slug:
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            if pattern.search(content):
                count += 1
        except Exception as e:
            logger.debug(f"Could not read file {md_file.stem}: {e}")
    return count


def assess_page(pages_dir: Path, slug: str) -> dict:
    """Assess maturity of a single page."""
    md_file = pages_dir / f"{slug}.md"
    if not md_file.exists():
        return {"slug": slug, "error": "not found"}

    content = md_file.read_text(encoding="utf-8")

    # Parse frontmatter
    fm = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"').strip("'")
            body = parts[2]

    word_count = len(body.split())
    source_count = len(re.findall(r"sources?:\s*\[([^\]]*)\]", content, re.IGNORECASE))
    # Also count source URLs in frontmatter
    sources_lines = [l for l in content.split("\n") if l.strip().startswith("- http")]
    source_count += len(sources_lines)
    if fm.get("sources"):
        source_count = max(source_count, 1)

    incoming_links = _count_incoming_links(pages_dir, slug)
    outgoing_links = len(re.findall(r"\[\[([^\]]+)\]\]", content))
    edit_count = _get_git_edit_count(pages_dir, slug)

    # Calculate age
    created = fm.get("created", "")
    age_days = 0
    if created:
        try:
            created_dt = datetime.strptime(created, "%Y-%m-%d")
            age_days = (datetime.now() - created_dt).days
        except ValueError:
            pass

    # Has bold text (Layer 2 progressive summarization)
    has_bold = "**" in body
    # Has highlights (Layer 3)
    has_highlights = "==" in body
    # Has summary callout (Layer 4)
    has_summary = bool(re.search(r">\s*\[!summary\]", body, re.IGNORECASE))

    # Determine maturity level
    if word_count >= 1000 and source_count >= 3 and incoming_links >= 3 and age_days >= 14:
        maturity = "evergreen"
    elif word_count >= 500 and source_count >= 2 and incoming_links >= 1:
        maturity = "mature"
    elif word_count >= 200 and (source_count >= 1 or edit_count >= 2):
        maturity = "growing"
    else:
        maturity = "seed"

    # Current maturity from frontmatter
    current_maturity = fm.get("maturity", "")

    return {
        "slug": slug,
        "title": fm.get("title", slug),
        "maturity": maturity,
        "current_maturity": current_maturity,
        "needs_update": current_maturity != maturity,
        "metrics": {
            "word_count": word_count,
            "source_count": source_count,
            "incoming_links": incoming_links,
            "outgoing_links": outgoing_links,
            "edit_count": edit_count,
            "age_days": age_days,
        },
        "summarization": {
            "layer_2_bold": has_bold,
            "layer_3_highlights": has_highlights,
            "layer_4_summary": has_summary,
        },
    }


def assess_all(pages_dir: Path) -> list[dict]:
    """Assess maturity of all pages."""
    pages_dir = Path(pages_dir)
    results = []
    for md_file in sorted(pages_dir.glob("*.md")):
        slug = md_file.stem
        if slug.startswith("daily-") or slug in ("index", "overview", "log"):
            continue
        results.append(assess_page(pages_dir, slug))
    return results


def suggest_upgrades(pages_dir: Path) -> list[dict]:
    """Suggest maturity upgrades."""
    assessments = assess_all(pages_dir)
    suggestions = []

    for a in assessments:
        if a.get("error"):
            continue
        if not a["needs_update"]:
            continue

        current = a.get("current_maturity", "")
        target = a["maturity"]

        # Only suggest upgrades, not downgrades
        levels = {"": 0, "seed": 1, "growing": 2, "mature": 3, "evergreen": 4}
        if levels.get(target, 0) > levels.get(current, 0):
            suggestions.append({
                "slug": a["slug"],
                "title": a["title"],
                "current": current or "(none)",
                "suggested": target,
                "reason": _upgrade_reason(a),
            })

    return suggestions


def _upgrade_reason(assessment: dict) -> str:
    """Generate a human-readable reason for a maturity upgrade."""
    m = assessment["metrics"]
    mat = assessment["maturity"]

    if mat == "evergreen":
        return f"{m['word_count']} words, {m['source_count']} sources, {m['incoming_links']} incoming links, {m['age_days']}d old"
    elif mat == "mature":
        return f"{m['word_count']} words, {m['source_count']} sources, {m['incoming_links']} incoming links"
    elif mat == "growing":
        return f"{m['word_count']} words, {m['edit_count']} edits"
    return f"New page, {m['word_count']} words"


def main():
    parser = argparse.ArgumentParser(
        description="Note maturity tracking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    assess_p = subparsers.add_parser("assess", help="Assess maturity of all pages")
    assess_p.add_argument("pages_dir")

    page_p = subparsers.add_parser("page", help="Assess single page")
    page_p.add_argument("pages_dir")
    page_p.add_argument("slug")

    upgrade_p = subparsers.add_parser("upgrade", help="Suggest maturity upgrades")
    upgrade_p.add_argument("pages_dir")

    args = parser.parse_args()

    if args.command == "assess":
        results = assess_all(args.pages_dir)
        print(json.dumps(results, indent=2))

    elif args.command == "page":
        result = assess_page(Path(args.pages_dir), args.slug)
        print(json.dumps(result, indent=2))

    elif args.command == "upgrade":
        results = suggest_upgrades(Path(args.pages_dir))
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
