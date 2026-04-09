#!/usr/bin/env python3
"""search-academic.py — Search academic papers across multiple free APIs.

Searches Semantic Scholar, OpenAlex, CrossRef, and arXiv. Returns normalized
JSON arrays. Deduplicates results and provides citation formatting (APA, BibTeX).
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from typing import Any

# Configuration
USER_AGENT = "LLM-Wiki/1.0 (https://github.com/Oshayr/llm-wiki)"
API_DELAY_MS = 100  # milliseconds between API calls to same service
DEDUP_THRESHOLD = 0.85  # title similarity threshold for deduplication


class AcademicSearcher:
    """Search academic papers across multiple free APIs."""

    def __init__(self):
        self.last_api_call_time = {}

    def _rate_limit(self, api_name: str) -> None:
        """Enforce rate limiting between API calls."""
        key = f"api_{api_name}"
        if key in self.last_api_call_time:
            elapsed = (time.time() - self.last_api_call_time[key]) * 1000
            if elapsed < API_DELAY_MS:
                time.sleep((API_DELAY_MS - elapsed) / 1000)
        self.last_api_call_time[key] = time.time()

    def _fetch_url(self, url: str, api_name: str) -> str | None:
        """Fetch URL content with error handling."""
        self._rate_limit(api_name)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"Warning: {api_name} API error: {e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Warning: {api_name} API error: {e}", file=sys.stderr)
            return None

    def search_semantic_scholar(
        self, query: str, top: int, year_min: int | None, year_max: int | None
    ) -> list[dict[str, Any]]:
        """Search Semantic Scholar API."""
        url = (
            f"https://api.semanticscholar.org/graph/v1/paper/search?"
            f"query={urllib.parse.quote(query)}&limit={top}"
            f"&fields=title,authors,year,citationCount,abstract,externalIds,url,venue,isOpenAccess"
        )
        content = self._fetch_url(url, "semantic_scholar")
        if not content:
            return []

        try:
            data = json.loads(content)
            results = []
            for paper in data.get("data", []):
                year = paper.get("year")
                if year_min and year < year_min:
                    continue
                if year_max and year > year_max:
                    continue

                ext_ids = paper.get("externalIds", {})
                result = {
                    "title": paper.get("title", ""),
                    "authors": [a.get("name", "") for a in paper.get("authors", [])],
                    "year": year,
                    "doi": ext_ids.get("DOI"),
                    "url": paper.get("url"),
                    "abstract": paper.get("abstract"),
                    "citations": paper.get("citationCount", 0),
                    "source_api": "semantic_scholar",
                    "venue": paper.get("venue"),
                    "open_access": paper.get("isOpenAccess", False),
                }
                results.append(result)
            return results
        except json.JSONDecodeError:
            print("Warning: semantic_scholar returned invalid JSON", file=sys.stderr)
            return []

    def search_openalex(
        self, query: str, top: int, year_min: int | None, year_max: int | None
    ) -> list[dict[str, Any]]:
        """Search OpenAlex API."""
        url = (
            f"https://api.openalex.org/works?"
            f"search={urllib.parse.quote(query)}&per_page={top}"
            f"&sort=cited_by_count:desc"
            f"&select=id,display_name,authorships,publication_year,doi,cited_by_count,open_access,primary_location"
        )
        content = self._fetch_url(url, "openalex")
        if not content:
            return []

        try:
            data = json.loads(content)
            results = []
            for work in data.get("results", []):
                year = work.get("publication_year")
                if year_min and year < year_min:
                    continue
                if year_max and year > year_max:
                    continue

                authors = [
                    auth.get("author", {}).get("display_name", "")
                    for auth in work.get("authorships", [])
                ]
                open_access = work.get("open_access", {})
                result = {
                    "title": work.get("display_name", ""),
                    "authors": authors,
                    "year": year,
                    "doi": work.get("doi"),
                    "url": work.get("id"),
                    "abstract": None,  # OpenAlex doesn't return abstract in list view
                    "citations": work.get("cited_by_count", 0),
                    "source_api": "openalex",
                    "venue": work.get("primary_location", {})
                    .get("source", {})
                    .get("display_name"),
                    "open_access": (
                        open_access.get("is_oa", False)
                        if isinstance(open_access, dict)
                        else False
                    ),
                }
                results.append(result)
            return results
        except json.JSONDecodeError:
            print("Warning: openalex returned invalid JSON", file=sys.stderr)
            return []

    def search_crossref(
        self, query: str, top: int, year_min: int | None, year_max: int | None
    ) -> list[dict[str, Any]]:
        """Search CrossRef API."""
        url = (
            f"https://api.crossref.org/works?"
            f"query={urllib.parse.quote(query)}&rows={top}"
            f"&sort=is-referenced-by-count&order=desc"
            f"&select=DOI,title,author,published-print,is-referenced-by-count,abstract,URL"
        )
        content = self._fetch_url(url, "crossref")
        if not content:
            return []

        try:
            data = json.loads(content)
            results = []
            for item in data.get("message", {}).get("items", []):
                published = item.get("published-print", {})
                year = (
                    published.get("date-parts", [[None]])[0][0]
                    if published.get("date-parts")
                    else None
                )
                if year_min and year and year < year_min:
                    continue
                if year_max and year and year > year_max:
                    continue

                authors = [
                    f"{a.get('given', '')} {a.get('family', '')}".strip()
                    for a in item.get("author", [])
                ]
                result = {
                    "title": (
                        item.get("title", [""])[0]
                        if isinstance(item.get("title"), list)
                        else item.get("title", "")
                    ),
                    "authors": authors,
                    "year": year,
                    "doi": item.get("DOI"),
                    "url": item.get("URL"),
                    "abstract": item.get("abstract"),
                    "citations": item.get("is-referenced-by-count", 0),
                    "source_api": "crossref",
                    "venue": (
                        item.get("container-title", [None])[0]
                        if isinstance(item.get("container-title"), list)
                        else item.get("container-title")
                    ),
                    "open_access": None,  # CrossRef doesn't provide this
                }
                results.append(result)
            return results
        except json.JSONDecodeError:
            print("Warning: crossref returned invalid JSON", file=sys.stderr)
            return []

    def search_arxiv(
        self, query: str, top: int, year_min: int | None, year_max: int | None
    ) -> list[dict[str, Any]]:
        """Search arXiv API."""
        url = (
            f"http://export.arxiv.org/api/query?"
            f"search_query=all:{urllib.parse.quote(query)}&max_results={top}"
            f"&sortBy=relevance&sortOrder=descending"
        )
        content = self._fetch_url(url, "arxiv")
        if not content:
            return []

        try:
            root = ET.fromstring(content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            results = []

            for entry in root.findall("atom:entry", ns):
                title_elem = entry.find("atom:title", ns)
                title = (
                    title_elem.text.strip()
                    if title_elem is not None and title_elem.text
                    else ""
                )

                authors = [
                    author.find("atom:name", ns).text
                    for author in entry.findall("atom:author", ns)
                    if author.find("atom:name", ns) is not None
                ]

                published_elem = entry.find("atom:published", ns)
                published_str = (
                    published_elem.text
                    if published_elem is not None and published_elem.text
                    else ""
                )
                year = int(published_str[:4]) if len(published_str) >= 4 else None

                if year_min and year and year < year_min:
                    continue
                if year_max and year and year > year_max:
                    continue

                arxiv_id_elem = entry.find("atom:id", ns)
                arxiv_id = (
                    arxiv_id_elem.text.split("/abs/")[-1]
                    if arxiv_id_elem is not None
                    else ""
                )

                summary_elem = entry.find("atom:summary", ns)
                abstract = (
                    summary_elem.text.strip()
                    if summary_elem is not None and summary_elem.text
                    else None
                )

                result = {
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "doi": None,
                    "url": f"https://arxiv.org/abs/{arxiv_id}",
                    "abstract": abstract,
                    "citations": 0,  # arXiv doesn't provide citation counts
                    "source_api": "arxiv",
                    "venue": "arXiv",
                    "open_access": True,
                }
                results.append(result)
            return results
        except ET.ParseError:
            print("Warning: arxiv returned invalid XML", file=sys.stderr)
            return []

    def _title_similarity(self, title1: str, title2: str) -> float:
        """Calculate title similarity using sequence matching."""
        t1 = title1.lower().strip()
        t2 = title2.lower().strip()
        return SequenceMatcher(None, t1, t2).ratio()

    def _deduplicate(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Deduplicate results by DOI or title similarity."""
        seen_dois = set()
        deduped = []

        for result in results:
            doi = result.get("doi")
            if doi and doi in seen_dois:
                continue
            if doi:
                seen_dois.add(doi)

            # Check title similarity with existing results
            is_duplicate = False
            for existing in deduped:
                if (
                    self._title_similarity(
                        result.get("title", ""), existing.get("title", "")
                    )
                    > DEDUP_THRESHOLD
                ):
                    is_duplicate = True
                    break

            if not is_duplicate:
                deduped.append(result)

        return deduped

    def search(
        self,
        query: str,
        top: int = 10,
        year_min: int | None = None,
        year_max: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search all APIs and merge results."""
        all_results = []

        # Try each API in order
        all_results.extend(self.search_semantic_scholar(query, top, year_min, year_max))
        all_results.extend(self.search_openalex(query, top, year_min, year_max))
        all_results.extend(self.search_crossref(query, top, year_min, year_max))
        all_results.extend(self.search_arxiv(query, top, year_min, year_max))

        # Deduplicate
        deduped = self._deduplicate(all_results)

        # Sort by citation count (descending)
        deduped.sort(key=lambda x: x.get("citations", 0), reverse=True)

        # Return top N
        return deduped[:top]

    def cite(self, doi_or_title: str) -> dict[str, Any] | None:
        """Get citation metadata for a paper."""
        # Try Semantic Scholar first
        if doi_or_title.startswith("10."):  # Looks like a DOI
            url = f"https://api.semanticscholar.org/graph/v1/paper/{urllib.parse.quote(doi_or_title)}?fields=title,authors,year,venue,externalIds,citationCount,abstract"
            content = self._fetch_url(url, "semantic_scholar")
            if content:
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    pass

        # Try CrossRef with DOI
        if doi_or_title.startswith("10."):
            url = f"https://api.crossref.org/works/{urllib.parse.quote(doi_or_title)}"
            content = self._fetch_url(url, "crossref")
            if content:
                try:
                    data = json.loads(content)
                    return data.get("message")
                except json.JSONDecodeError:
                    pass

        # Try searching by title
        results = self.search_semantic_scholar(
            doi_or_title, top=1, year_min=None, year_max=None
        )
        if results:
            return results[0]

        results = self.search_crossref(
            doi_or_title, top=1, year_min=None, year_max=None
        )
        if results:
            return results[0]

        return None

    def _format_apa_citation(self, paper: dict[str, Any]) -> str:
        """Format paper as APA citation."""
        authors = paper.get("authors", [])
        if not authors:
            authors = ["Unknown Author"]

        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += ", et al."

        year = paper.get("year", "n.d.")
        title = paper.get("title", "Unknown Title")
        venue = paper.get("venue", "Unknown Venue")

        return f"{author_str} ({year}). {title}. {venue}."

    def _format_bibtex_citation(self, paper: dict[str, Any]) -> str:
        """Format paper as BibTeX citation."""
        authors = paper.get("authors", [])
        if not authors:
            authors = ["Unknown"]

        author_str = " and ".join(authors)
        year = paper.get("year", "n.d.")
        title = paper.get("title", "Unknown Title")
        venue = paper.get("venue", "Unknown Venue")
        doi = paper.get("doi", "")
        url = paper.get("url", "")

        # Create a key from first author and year
        key = (
            f"{authors[0].split()[-1].lower()}{year}" if authors[0] else f"paper{year}"
        )

        bibtex = f"@article{{{key},\n"
        bibtex += f"  author = {{{author_str}}},\n"
        bibtex += f"  title = {{{title}}},\n"
        bibtex += f"  journal = {{{venue}}},\n"
        bibtex += f"  year = {{{year}}}"

        if doi:
            bibtex += f",\n  doi = {{{doi}}}"
        if url:
            bibtex += f",\n  url = {{{url}}}"

        bibtex += "\n}"
        return bibtex

    def download(self, doi_or_url: str, output_path: str) -> bool:
        """Download paper PDF if available."""
        # Check Semantic Scholar for open access PDF
        if doi_or_url.startswith("10."):
            url = f"https://api.semanticscholar.org/graph/v1/paper/{urllib.parse.quote(doi_or_url)}?fields=openAccessPdf"
            content = self._fetch_url(url, "semantic_scholar")
            if content:
                try:
                    data = json.loads(content)
                    pdf_url = data.get("openAccessPdf", {}).get("url")
                    if pdf_url:
                        return self._download_file(pdf_url, output_path)
                except json.JSONDecodeError:
                    pass

        # Check if URL is directly a PDF
        if doi_or_url.endswith(".pdf"):
            return self._download_file(doi_or_url, output_path)

        # Try arXiv PDF if it looks like an arXiv ID
        if "arxiv" in doi_or_url.lower():
            arxiv_id = doi_or_url.split("/")[-1]
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            return self._download_file(pdf_url, output_path)

        return False

    def _download_file(self, url: str, output_path: str) -> bool:
        """Download file from URL to disk."""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as response:
                with open(output_path, "wb") as f:
                    f.write(response.read())
            return True
        except Exception as e:
            print(f"Warning: Failed to download {url}: {e}", file=sys.stderr)
            return False


def main():
    parser = argparse.ArgumentParser(
        description="Search academic papers across multiple free APIs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Search command
    search_parser = subparsers.add_parser("search", help="Search for papers")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument(
        "--top", type=int, default=10, help="Number of results (default: 10)"
    )
    search_parser.add_argument("--year-min", type=int, help="Minimum publication year")
    search_parser.add_argument("--year-max", type=int, help="Maximum publication year")

    # Cite command
    cite_parser = subparsers.add_parser("cite", help="Get citation formats for a paper")
    cite_parser.add_argument("doi_or_title", help="DOI or paper title")

    # Download command
    download_parser = subparsers.add_parser("download", help="Download paper PDF")
    download_parser.add_argument("doi_or_url", help="DOI or arXiv URL")
    download_parser.add_argument("--output", required=True, help="Output file path")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    searcher = AcademicSearcher()

    if args.command == "search":
        results = searcher.search(
            args.query, top=args.top, year_min=args.year_min, year_max=args.year_max
        )
        print(json.dumps(results, indent=2))
        return 0

    elif args.command == "cite":
        paper = searcher.cite(args.doi_or_title)
        if paper:
            apa = searcher._format_apa_citation(paper)
            bibtex = searcher._format_bibtex_citation(paper)
            print("APA:")
            print(apa)
            print("\nBibTeX:")
            print(bibtex)
            return 0
        else:
            print("Error: Paper not found", file=sys.stderr)
            return 1

    elif args.command == "download":
        if searcher.download(args.doi_or_url, args.output):
            print(f"Downloaded to {args.output}")
            return 0
        else:
            print("Error: Could not download paper", file=sys.stderr)
            return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
