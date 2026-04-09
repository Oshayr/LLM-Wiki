#!/usr/bin/env python3
"""search-code.py — Search code repositories and packages across multiple sources.

Searches GitHub repos, npm/PyPI packages, and Stack Overflow Q&A. Returns
normalized JSON arrays with repository metadata, package info, and answers.
"""

import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Configuration
USER_AGENT = "LLM-Wiki/1.0 (https://github.com/Oshayr/llm-wiki)"
GITHUB_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/vnd.github.v3+json",
}


class CodeSearcher:
    """Search code repositories and packages across multiple sources."""

    def __init__(self):
        self.last_api_call_time = {}

    def _rate_limit(self, api_name: str, delay_ms: int = 100) -> None:
        """Enforce rate limiting between API calls."""
        key = f"api_{api_name}"
        if key in self.last_api_call_time:
            elapsed = (time.time() - self.last_api_call_time[key]) * 1000
            if elapsed < delay_ms:
                time.sleep((delay_ms - elapsed) / 1000)
        self.last_api_call_time[key] = time.time()

    def _fetch_url(
        self, url: str, api_name: str, headers: dict[str, str] | None = None
    ) -> str | None:
        """Fetch URL content with error handling."""
        self._rate_limit(api_name)
        try:
            if headers is None:
                headers = {"User-Agent": USER_AGENT}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = response.read()
                # Handle gzip compression
                if response.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data.decode("utf-8")
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"Warning: {api_name} API error: {e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Warning: {api_name} API error: {e}", file=sys.stderr)
            return None

    def search_github(self, query: str, top: int) -> list[dict[str, Any]]:
        """Search GitHub repositories."""
        url = (
            f"https://api.github.com/search/repositories?"
            f"q={urllib.parse.quote(query)}&sort=stars&per_page={top}"
        )
        content = self._fetch_url(url, "github", headers=GITHUB_HEADERS)
        if not content:
            return []

        try:
            data = json.loads(content)
            results = []
            for repo in data.get("items", []):
                result = {
                    "name": repo.get("name", ""),
                    "full_name": repo.get("full_name", ""),
                    "description": repo.get("description"),
                    "stars": repo.get("stargazers_count", 0),
                    "language": repo.get("language"),
                    "url": repo.get("html_url", ""),
                    "updated": repo.get("updated_at"),
                    "license": (
                        repo.get("license", {}).get("name")
                        if repo.get("license")
                        else None
                    ),
                    "source_type": "repos",
                }
                results.append(result)
            return results
        except json.JSONDecodeError:
            print("Warning: github returned invalid JSON", file=sys.stderr)
            return []

    def search_npm(self, query: str, top: int) -> list[dict[str, Any]]:
        """Search npm packages."""
        url = (
            f"https://registry.npmjs.org/-/v1/search?"
            f"text={urllib.parse.quote(query)}&size={top}"
        )
        content = self._fetch_url(url, "npm")
        if not content:
            return []

        try:
            data = json.loads(content)
            results = []
            for package in data.get("objects", []):
                pkg = package.get("package", {})
                result = {
                    "name": pkg.get("name", ""),
                    "version": pkg.get("version", ""),
                    "description": pkg.get("description"),
                    "registry": "npm",
                    "url": pkg.get("links", {}).get("npm", ""),
                    "downloads": None,  # npm search API doesn't provide downloads
                    "source_type": "packages",
                }
                results.append(result)
            return results
        except json.JSONDecodeError:
            print("Warning: npm returned invalid JSON", file=sys.stderr)
            return []

    def search_pypi(self, query: str, top: int) -> list[dict[str, Any]]:
        """Search PyPI packages."""
        results = []

        # Try exact match first
        url = f"https://pypi.org/pypi/{urllib.parse.quote(query)}/json"
        content = self._fetch_url(url, "pypi")
        if content:
            try:
                data = json.loads(content)
                info = data.get("info", {})
                result = {
                    "name": info.get("name", ""),
                    "version": info.get("version", ""),
                    "description": info.get("summary"),
                    "registry": "pypi",
                    "url": info.get("project_url")
                    or info.get("home_page")
                    or f"https://pypi.org/project/{info.get('name')}/",
                    "downloads": None,
                    "source_type": "packages",
                }
                results.append(result)
                return results[:top]
            except json.JSONDecodeError:
                pass

        # Fallback: try variants or simple approach
        # Note: PyPI removed public search API, so we use a simple heuristic
        variants = [query, query.replace("_", "-"), query.replace("-", "_")]
        for variant in variants:
            if len(results) >= top:
                break
            url = f"https://pypi.org/pypi/{urllib.parse.quote(variant)}/json"
            content = self._fetch_url(url, "pypi")
            if content:
                try:
                    data = json.loads(content)
                    info = data.get("info", {})
                    result = {
                        "name": info.get("name", ""),
                        "version": info.get("version", ""),
                        "description": info.get("summary"),
                        "registry": "pypi",
                        "url": info.get("project_url")
                        or info.get("home_page")
                        or f"https://pypi.org/project/{info.get('name')}/",
                        "downloads": None,
                        "source_type": "packages",
                    }
                    if result not in results:
                        results.append(result)
                except json.JSONDecodeError:
                    pass

        return results[:top]

    def search_stackoverflow(self, query: str, top: int) -> list[dict[str, Any]]:
        """Search Stack Overflow Q&A."""
        url = (
            f"https://api.stackexchange.com/2.3/search/advanced?"
            f"q={urllib.parse.quote(query)}&site=stackoverflow"
            f"&sort=votes&pagesize={top}&filter=withbody"
        )
        content = self._fetch_url(url, "stackoverflow")
        if not content:
            return []

        try:
            data = json.loads(content)
            results = []
            for question in data.get("items", []):
                result = {
                    "title": question.get("title", ""),
                    "url": question.get("link", ""),
                    "score": question.get("score", 0),
                    "answers": question.get("answer_count", 0),
                    "accepted": question.get("is_answered", False),
                    "tags": question.get("tags", []),
                    "source_type": "qa",
                }
                results.append(result)
            return results
        except json.JSONDecodeError:
            print("Warning: stackoverflow returned invalid JSON", file=sys.stderr)
            return []

    def search(
        self, query: str, top: int = 10, search_type: str = "all"
    ) -> list[dict[str, Any]]:
        """Search across selected sources."""
        results = []

        if search_type in ("repos", "all"):
            results.extend(self.search_github(query, top))

        if search_type in ("packages", "all"):
            results.extend(self.search_npm(query, top))
            results.extend(self.search_pypi(query, top))

        if search_type in ("qa", "all"):
            results.extend(self.search_stackoverflow(query, top))

        # Sort by stars/score descending, then return top N
        results.sort(key=lambda r: r.get("stars", r.get("score", 0)), reverse=True)
        return results[:top]

    def get_npm_info(self, package_name: str) -> dict[str, Any] | None:
        """Get detailed npm package information."""
        url = f"https://registry.npmjs.org/{urllib.parse.quote(package_name)}"
        content = self._fetch_url(url, "npm")
        if not content:
            return None

        try:
            data = json.loads(content)
            latest = data.get("dist-tags", {}).get("latest", "")
            version_info = data.get("versions", {}).get(latest, {})

            result = {
                "name": data.get("name", ""),
                "version": latest,
                "description": data.get("description"),
                "license": data.get("license"),
                "homepage": data.get("homepage"),
                "repository": (
                    data.get("repository", {}).get("url")
                    if isinstance(data.get("repository"), dict)
                    else data.get("repository")
                ),
                "dependencies": version_info.get("dependencies", {}),
                "downloads_last_month": None,  # npm registry API doesn't provide this in simple endpoint
            }
            return result
        except json.JSONDecodeError:
            print("Warning: npm returned invalid JSON", file=sys.stderr)
            return None

    def get_pypi_info(self, package_name: str) -> dict[str, Any] | None:
        """Get detailed PyPI package information."""
        url = f"https://pypi.org/pypi/{urllib.parse.quote(package_name)}/json"
        content = self._fetch_url(url, "pypi")
        if not content:
            return None

        try:
            data = json.loads(content)
            info = data.get("info", {})
            requires = data.get("info", {}).get("requires_dist", [])

            # Parse dependencies
            dependencies = {}
            if requires:
                for req in requires:
                    # Simple parsing of "package (>=version)" format
                    pkg_name = req.split(";")[0].split("(")[0].split("[")[0].strip()
                    if pkg_name and ";" not in pkg_name:
                        dependencies[pkg_name] = req

            result = {
                "name": info.get("name", ""),
                "version": info.get("version", ""),
                "description": info.get("summary"),
                "license": info.get("license"),
                "homepage": info.get("home_page"),
                "repository": info.get("project_urls", {}).get("Repository")
                or info.get("project_urls", {}).get("repository"),
                "dependencies": dependencies,
                "downloads_last_month": None,  # PyPI doesn't provide this via API
            }
            return result
        except json.JSONDecodeError:
            print("Warning: pypi returned invalid JSON", file=sys.stderr)
            return None

    def get_info(
        self, package_name: str, registry: str | None = None
    ) -> dict[str, Any] | None:
        """Get package information from specified or auto-detected registry."""
        if registry == "npm" or (registry is None):
            result = self.get_npm_info(package_name)
            if result:
                return result

        if registry == "pypi" or (registry is None):
            result = self.get_pypi_info(package_name)
            if result:
                return result

        return None


def main():
    parser = argparse.ArgumentParser(
        description="Search code repositories and packages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Search command
    search_parser = subparsers.add_parser(
        "search", help="Search for repositories, packages, or Q&A"
    )
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument(
        "--top", type=int, default=10, help="Number of results (default: 10)"
    )
    search_parser.add_argument(
        "--type",
        choices=["repos", "packages", "qa", "all"],
        default="all",
        help="Search type (default: all)",
    )

    # Info command
    info_parser = subparsers.add_parser("info", help="Get detailed package information")
    info_parser.add_argument("package_name", help="Package name")
    info_parser.add_argument(
        "--registry",
        choices=["npm", "pypi"],
        help="Package registry (auto-detect if not specified)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    searcher = CodeSearcher()

    if args.command == "search":
        results = searcher.search(args.query, top=args.top, search_type=args.type)
        print(json.dumps(results, indent=2))
        return 0

    elif args.command == "info":
        info = searcher.get_info(args.package_name, registry=args.registry)
        if info:
            print(json.dumps(info, indent=2))
            return 0
        else:
            print("Error: Package not found", file=sys.stderr)
            return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
