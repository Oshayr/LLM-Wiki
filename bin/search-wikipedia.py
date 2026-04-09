#!/usr/bin/env python3
"""search-wikipedia.py — Wikipedia article search via MediaWiki Action API.

Usage:
    python3 search-wikipedia.py search <query> [--top N] [--lang CODE]
    python3 search-wikipedia.py summary <title> [--lang CODE]
    python3 search-wikipedia.py extract <title> [--lang CODE]   # alias for summary

API: MediaWiki Action API (no key required)
Source type: wikipedia
Credibility tier: 2 (reputable, not peer-reviewed)
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from typing import Any

# Configuration
USER_AGENT = "llm-wiki/1.0 (https://github.com/Oshayr/llm-wiki)"
API_DELAY_MS = 500  # conservative — within Wikipedia bot guidelines
DEDUP_THRESHOLD = 0.85
CREDIBILITY_TIER = 2


class WikipediaSearcher:
    """Search Wikipedia articles via the MediaWiki Action API."""

    def __init__(self, lang: str = "en"):
        self.lang = lang
        self.last_api_call_time: dict[str, float] = {}

    def _base_url(self) -> str:
        return f"https://{self.lang}.wikipedia.org/w/api.php"

    def _rate_limit(self, api_name: str = "wikipedia") -> None:
        """Enforce rate limiting between API calls."""
        if api_name in self.last_api_call_time:
            elapsed = (time.time() - self.last_api_call_time[api_name]) * 1000
            if elapsed < API_DELAY_MS:
                time.sleep((API_DELAY_MS - elapsed) / 1000)
        self.last_api_call_time[api_name] = time.time()

    def _fetch_url(self, url: str) -> dict[str, Any] | None:
        """Fetch a Wikipedia API URL and return parsed JSON."""
        self._rate_limit()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"Warning: Wikipedia API error: {e}", file=sys.stderr)
            return None
        except (json.JSONDecodeError, Exception) as e:
            print(f"Warning: Wikipedia API error: {e}", file=sys.stderr)
            return None

    def _fetch_extracts(self, titles: list[str]) -> dict[str, dict[str, Any]]:
        """Batch-fetch intro extracts and page info for up to 50 titles.

        Returns a dict mapping page title → {pageid, title, url, extract}.
        """
        if not titles:
            return {}

        # Wikipedia allows up to 50 titles per request
        batch = titles[:50]
        params = urllib.parse.urlencode(
            {
                "action": "query",
                "prop": "extracts|info",
                "exintro": "1",
                "explaintext": "1",
                "inprop": "url",
                "titles": "|".join(batch),
                "format": "json",
                "formatversion": "2",
            }
        )
        url = f"{self._base_url()}?{params}"
        data = self._fetch_url(url)
        if not data:
            return {}

        results: dict[str, dict[str, Any]] = {}
        for page in data.get("query", {}).get("pages", []):
            # formatversion=2 returns pages as a list, not a dict
            if page.get("missing"):
                continue
            title = page.get("title", "")
            results[title] = {
                "pageid": page.get("pageid"),
                "title": title,
                "url": page.get("fullurl", f"https://{self.lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"),
                "extract": page.get("extract", ""),
            }
        return results

    def search_wikipedia(self, query: str, top: int = 10) -> list[dict[str, Any]]:
        """Two-step search: list search → batch extract.

        Step 1: action=query&list=search to get matching titles.
        Step 2: batch _fetch_extracts for all titles.
        """
        params = urllib.parse.urlencode(
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": min(top, 50),
                "format": "json",
                "formatversion": "2",
            }
        )
        url = f"{self._base_url()}?{params}"
        data = self._fetch_url(url)
        if not data:
            return []

        search_hits = data.get("query", {}).get("search", [])
        if not search_hits:
            return []

        # Collect titles and snippets from search
        titles = [hit["title"] for hit in search_hits]
        snippets = {hit["title"]: hit.get("snippet", "") for hit in search_hits}

        # Batch-fetch extracts
        extracts = self._fetch_extracts(titles)

        results = []
        for hit in search_hits:
            title = hit["title"]
            page_data = extracts.get(title, {})

            # Clean snippet (remove HTML tags from search snippet)
            raw_snippet = snippets.get(title, "")
            snippet = self._strip_html(raw_snippet)

            # Use extract intro (first 500 chars) as a richer snippet if available
            extract = page_data.get("extract", "")
            extract_snippet = extract[:500].strip() if extract else snippet

            result = {
                "title": title,
                "url": page_data.get(
                    "url",
                    f"https://{self.lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                ),
                "snippet": snippet or extract_snippet[:200],
                "source_type": "wikipedia",
                "credibility_tier": CREDIBILITY_TIER,
                "pageid": page_data.get("pageid") or hit.get("pageid"),
                "lang": self.lang,
                "extract": extract_snippet,
            }
            results.append(result)

        return results[:top]

    def get_summary(self, title: str) -> dict[str, Any] | None:
        """Fetch the intro extract for a specific article title."""
        extracts = self._fetch_extracts([title])
        if not extracts:
            return None

        # Try exact match first, then case-insensitive
        page_data = extracts.get(title)
        if not page_data:
            title_lower = title.lower()
            for k, v in extracts.items():
                if k.lower() == title_lower:
                    page_data = v
                    break

        if not page_data:
            return None

        extract = page_data.get("extract", "")
        return {
            "title": page_data["title"],
            "url": page_data["url"],
            "snippet": extract[:200].strip(),
            "source_type": "wikipedia",
            "credibility_tier": CREDIBILITY_TIER,
            "pageid": page_data.get("pageid"),
            "lang": self.lang,
            "extract": extract,
        }

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags from text (Wikipedia search snippets contain <span> tags)."""
        import re
        return re.sub(r"<[^>]+>", "", text).strip()

    def _title_similarity(self, t1: str, t2: str) -> float:
        return SequenceMatcher(None, t1.lower().strip(), t2.lower().strip()).ratio()

    def _deduplicate(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Deduplicate by pageid or title similarity."""
        seen_ids: set[int] = set()
        deduped: list[dict[str, Any]] = []
        for result in results:
            pid = result.get("pageid")
            if pid and pid in seen_ids:
                continue
            if pid:
                seen_ids.add(pid)

            is_dup = any(
                self._title_similarity(result["title"], ex["title"]) > DEDUP_THRESHOLD
                for ex in deduped
            )
            if not is_dup:
                deduped.append(result)

        return deduped


def main() -> int:
    # Ensure UTF-8 output on Windows consoles
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Search Wikipedia via MediaWiki Action API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # search
    sp = subparsers.add_parser("search", help="Search Wikipedia articles")
    sp.add_argument("query", help="Search query")
    sp.add_argument("--top", type=int, default=10, help="Max results (default: 10)")
    sp.add_argument("--lang", default="en", help="Wikipedia language code (default: en)")

    # summary / extract (aliases)
    for cmd in ("summary", "extract"):
        ep = subparsers.add_parser(cmd, help="Get article intro extract by title")
        ep.add_argument("title", help="Exact article title")
        ep.add_argument("--lang", default="en", help="Wikipedia language code (default: en)")

    args = parser.parse_args()
    lang = getattr(args, "lang", "en")
    searcher = WikipediaSearcher(lang=lang)

    if args.command == "search":
        results = searcher.search_wikipedia(args.query, top=args.top)
        results = searcher._deduplicate(results)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0

    elif args.command in ("summary", "extract"):
        result = searcher.get_summary(args.title)
        if result:
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        else:
            print(json.dumps({"error": f"Article '{args.title}' not found"}), file=sys.stderr)
            return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
