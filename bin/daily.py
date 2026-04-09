#!/usr/bin/env python3
"""daily.py — Daily notes and journal workflows.

Usage:
    python3 daily.py today <pages_dir>                — Create/show today's daily note
    python3 daily.py week <pages_dir>                 — Weekly rollup summary
    python3 daily.py search <pages_dir> <start> [end] — Search daily notes by date range
    python3 daily.py list <pages_dir> [--limit N]     — List recent daily notes

Creates journal pages at .wiki/pages/daily-YYYY-MM-DD.md with template
frontmatter. Supports weekly rollup summaries.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from wiki_logging import get_logger

logger = get_logger(__name__)


DAILY_TEMPLATE = """---
title: "Daily Note — {date_display}"
type: daily-note
date: {date}
created: {date}
updated: {date}
tags: [journal, daily]
---

## Notes



## Links Discovered



## Questions



## Tasks

- [ ]

"""

WEEKLY_TEMPLATE = """---
title: "Week of {week_start} — Weekly Rollup"
type: weekly-rollup
date: {today}
created: {today}
updated: {today}
tags: [journal, weekly]
sources: [{daily_sources}]
---

## Weekly Summary

{summary}

## Daily Notes This Week

{daily_links}

## Key Themes



## Open Questions



"""


def get_daily_slug(date: datetime) -> str:
    """Generate slug for a daily note."""
    return f"daily-{date.strftime('%Y-%m-%d')}"


def create_daily(pages_dir: Path, date: datetime = None) -> dict:
    """Create today's daily note if it doesn't exist."""
    if date is None:
        date = datetime.now()

    slug = get_daily_slug(date)
    page_path = pages_dir / f"{slug}.md"

    if page_path.exists():
        return {"status": "exists", "slug": slug, "path": str(page_path)}

    content = DAILY_TEMPLATE.format(
        date=date.strftime("%Y-%m-%d"),
        date_display=date.strftime("%A, %B %d, %Y"),
    )

    page_path.write_text(content, encoding="utf-8")
    return {"status": "created", "slug": slug, "path": str(page_path)}


def create_weekly(pages_dir: Path) -> dict:
    """Create a weekly rollup from this week's daily notes."""
    today = datetime.now()
    # Find Monday of this week
    monday = today - timedelta(days=today.weekday())

    daily_notes = []
    daily_links = []
    daily_sources = []

    for i in range(7):
        date = monday + timedelta(days=i)
        slug = get_daily_slug(date)
        page_path = pages_dir / f"{slug}.md"

        if page_path.exists():
            content = page_path.read_text(encoding="utf-8")
            daily_notes.append({"date": date, "slug": slug, "content": content})
            daily_links.append(f"- [[{slug}]] — {date.strftime('%A, %B %d')}")
            daily_sources.append(f'"{slug}"')

    if not daily_notes:
        return {"status": "no_notes", "message": "No daily notes found for this week"}

    week_slug = f"weekly-{monday.strftime('%Y-%m-%d')}"
    page_path = pages_dir / f"{week_slug}.md"

    if page_path.exists():
        return {"status": "exists", "slug": week_slug}

    summary = f"Week of {monday.strftime('%B %d')} — {len(daily_notes)} daily notes recorded."

    content = WEEKLY_TEMPLATE.format(
        week_start=monday.strftime("%B %d, %Y"),
        today=today.strftime("%Y-%m-%d"),
        daily_sources=", ".join(daily_sources),
        summary=summary,
        daily_links="\n".join(daily_links) if daily_links else "No daily notes this week.",
    )

    page_path.write_text(content, encoding="utf-8")
    return {"status": "created", "slug": week_slug, "daily_count": len(daily_notes)}


def search_daily(pages_dir: Path, start_date: str, end_date: str = None) -> list[dict]:
    """Search daily notes within a date range."""
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        logger.warning("Invalid date format", extra={"date": start_date})
        return [{"error": f"Invalid date format: {start_date}. Use YYYY-MM-DD."}]

    if end_date:
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            logger.warning("Invalid date format", extra={"date": end_date})
            return [{"error": f"Invalid date format: {end_date}. Use YYYY-MM-DD."}]
    else:
        end = datetime.now()

    results = []
    current = start
    while current <= end:
        slug = get_daily_slug(current)
        page_path = pages_dir / f"{slug}.md"
        if page_path.exists():
            content = page_path.read_text(encoding="utf-8")
            # Extract summary (skip frontmatter, get first non-empty paragraph)
            body = content
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    body = parts[2]

            summary = ""
            for line in body.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("-"):
                    summary = line[:150]
                    break

            results.append({
                "slug": slug,
                "date": current.strftime("%Y-%m-%d"),
                "summary": summary,
            })
        current += timedelta(days=1)

    return results


def list_daily(pages_dir: Path, limit: int = 20) -> list[dict]:
    """List recent daily notes."""
    daily_files = sorted(
        pages_dir.glob("daily-*.md"),
        key=lambda f: f.stem,
        reverse=True,
    )[:limit]

    results = []
    for f in daily_files:
        slug = f.stem
        date_str = slug.replace("daily-", "")
        results.append({"slug": slug, "date": date_str})

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Daily notes and journal workflows",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    today_p = subparsers.add_parser("today", help="Create/show today's daily note")
    today_p.add_argument("pages_dir")

    week_p = subparsers.add_parser("week", help="Weekly rollup summary")
    week_p.add_argument("pages_dir")

    search_p = subparsers.add_parser("search", help="Search daily notes by date range")
    search_p.add_argument("pages_dir")
    search_p.add_argument("start", help="Start date (YYYY-MM-DD)")
    search_p.add_argument("end", nargs="?", help="End date (YYYY-MM-DD)")

    list_p = subparsers.add_parser("list", help="List recent daily notes")
    list_p.add_argument("pages_dir")
    list_p.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    pages_dir = Path(args.pages_dir)

    if args.command == "today":
        result = create_daily(pages_dir)
        print(json.dumps(result, indent=2))

    elif args.command == "week":
        result = create_weekly(pages_dir)
        print(json.dumps(result, indent=2))

    elif args.command == "search":
        results = search_daily(pages_dir, args.start, args.end)
        print(json.dumps(results, indent=2))

    elif args.command == "list":
        results = list_daily(pages_dir, args.limit)
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
