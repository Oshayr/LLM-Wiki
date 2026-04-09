#!/usr/bin/env python3
"""tools.py — Deterministic wiki utilities that replace LLM calls for token savings.

Usage:
    python3 tools.py --cmd dedup < results.json     Deduplicate search results
    python3 tools.py --cmd similar <slug> <dir>     Find similar pages by TF-IDF
    python3 tools.py --cmd summarize <file>         Extract first paragraph as summary
"""

import argparse
import json
import re
import sys
from pathlib import Path

from wiki_logging import get_logger

logger = get_logger(__name__)


def cmd_dedup(args):
    """Deduplicate and rank search results deterministically.

    Reads JSON array from stdin: [{title, url, snippet, source_type, credibility_tier}, ...]
    Outputs deduplicated, ranked JSON array.

    Replaces haiku search-merger agent (~1500 tokens/call → 0 tokens).
    """
    data = json.load(sys.stdin)
    if not isinstance(data, list):
        print(json.dumps(data))
        return

    seen_urls = set()
    seen_titles = set()
    unique = []

    for item in data:
        url = (item.get("url") or "").strip().rstrip("/")
        title = (item.get("title") or "").strip().lower()

        # URL dedup
        if url and url in seen_urls:
            continue
        # DOI dedup
        doi = item.get("doi", "")
        if doi and any(r.get("doi") == doi for r in unique):
            continue
        # Title similarity dedup (>85% word overlap)
        title_words = set(re.findall(r"\w+", title))
        is_dup = False
        for seen_t in seen_titles:
            seen_words = set(re.findall(r"\w+", seen_t))
            if title_words and seen_words:
                overlap = len(title_words & seen_words) / max(
                    len(title_words | seen_words), 1
                )
                if overlap > 0.85:
                    is_dup = True
                    break
        if is_dup:
            continue

        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title)
        unique.append(item)

    # Score and rank
    for item in unique:
        tier = item.get("credibility_tier", 3)
        score = {1: 100, 2: 50, 3: 10}.get(tier, 10)

        # Title relevance bonus (if query provided via args)
        if args.query:
            query_words = set(re.findall(r"\w+", args.query.lower()))
            title_words = set(re.findall(r"\w+", (item.get("title") or "").lower()))
            if query_words and title_words:
                overlap = len(query_words & title_words) / max(len(query_words), 1)
                score += int(overlap * 30)

        # Citation bonus
        citations = item.get("citation_count", 0)
        if citations and int(citations) > 50:
            score += 20

        item["score"] = score

    unique.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Return top N
    top_n = args.top if hasattr(args, "top") and args.top else 20
    print(json.dumps(unique[:top_n], indent=2))


def cmd_similar(args):
    """Find similar pages using TF-IDF-like token overlap.

    Reads all .md files in the pages directory and compares against the query slug.
    """
    slug = args.slug
    pages_dir = Path(args.pages_dir)

    slug_tokens = set(slug.replace("-", " ").replace("_", " ").lower().split())
    if not slug_tokens:
        logger.warning("No tokens extracted from slug", extra={"slug": slug})
        print(json.dumps({"match": None, "score": 0}))
        return

    best = None
    best_score = 0.0

    for page_file in pages_dir.glob("*.md"):
        page_slug = page_file.stem
        if page_slug == slug or page_slug == "index":
            continue
        page_tokens = set(page_slug.replace("-", " ").replace("_", " ").lower().split())
        if not page_tokens:
            continue

        intersection = slug_tokens & page_tokens
        union = slug_tokens | page_tokens
        score = len(intersection) / len(union) if union else 0

        if score > best_score:
            best_score = score
            best = page_slug

    # Check prefix containment too
    if best_score < 0.6:
        for page_file in pages_dir.glob("*.md"):
            ps = page_file.stem
            if ps == slug or ps == "index":
                continue
            if ps.startswith(slug) or slug.startswith(ps):
                shorter = min(len(slug), len(ps))
                longer = max(len(slug), len(ps))
                if shorter / longer >= 0.6:
                    best = ps
                    best_score = shorter / longer
                    break

    threshold = 0.6
    if best_score >= threshold:
        print(json.dumps({"match": best, "score": round(best_score, 3)}))
    else:
        print(json.dumps({"match": None, "score": round(best_score, 3)}))


def cmd_summarize(args):
    """Extract first meaningful paragraph from a wiki page as a summary.

    Saves tokens by pre-computing page summaries instead of sending full content to LLM.
    """
    try:
        content = Path(args.file).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.error("Failed to read file", extra={"file": args.file, "error": str(e)}, exc_info=True)
        print("(failed to read file)")
        return

    # Strip frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3 :].strip()

    # Find first non-heading, non-empty paragraph
    lines = content.split("\n")
    paragraph = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if paragraph:
                break
            continue
        if stripped.startswith("#"):
            if paragraph:
                break
            continue
        paragraph.append(stripped)

    summary = " ".join(paragraph)[:300]
    print(summary if summary else "(no summary available)")


def main():
    parser = argparse.ArgumentParser(description="Wiki tools — deterministic utilities")
    parser.add_argument(
        "--cmd", required=True, choices=["dedup", "similar", "summarize"]
    )
    parser.add_argument(
        "--query", default="", help="Search query for relevance scoring (dedup)"
    )
    parser.add_argument("--top", type=int, default=20, help="Top N results (dedup)")
    parser.add_argument("--slug", default="", help="Slug to check similarity for")
    parser.add_argument("--pages-dir", default=".wiki/pages", help="Pages directory")
    parser.add_argument("--file", default="", help="File path (summarize)")

    args = parser.parse_args()

    if args.cmd == "dedup":
        cmd_dedup(args)
    elif args.cmd == "similar":
        cmd_similar(args)
    elif args.cmd == "summarize":
        cmd_summarize(args)


if __name__ == "__main__":
    main()
