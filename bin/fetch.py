#!/usr/bin/env python3
"""fetch.py — Fetch URL and convert to clean Markdown.

Usage:
    python3 wiki-fetch.py <url> [--output <path>] [--cache-dir <dir>] [--timeout <secs>]

Extraction chain (tries each, falls back to next):
    1. Jina Reader API (r.jina.ai) — best quality, free tier
    2. Trafilatura — local extraction, good fallback
    3. Raw HTTP + html2text — last resort

Outputs clean markdown to stdout (or --output file).
"""

import argparse
import hashlib
import html
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Fetch URL and convert to clean Markdown"
    )
    parser.add_argument("url", help="URL to fetch")
    parser.add_argument(
        "--output", help="Output file path (default: stdout)", default=None
    )
    parser.add_argument(
        "--cache-dir",
        help="Cache directory path",
        default=None,
    )
    parser.add_argument(
        "--timeout", type=int, help="Request timeout in seconds", default=30
    )
    return parser.parse_args()


def validate_url(url):
    """Validate URL format."""
    try:
        result = urlparse(url)
        if not result.scheme:
            url = "https://" + url
            result = urlparse(url)
        if not result.scheme or not result.netloc:
            return None
        return url
    except Exception:
        return None


def compute_url_hash(url):
    """Compute SHA256 hash of URL (first 16 chars)."""
    hash_obj = hashlib.sha256(url.encode("utf-8"))
    return hash_obj.hexdigest()[:16]


def get_cache_path(cache_dir, url):
    """Get cache file path for URL."""
    url_hash = compute_url_hash(url)
    return Path(cache_dir) / f"{url_hash}.md"


def load_from_cache(cache_dir, url):
    """Load markdown from cache if exists and < 7 days old."""
    if not cache_dir:
        return None

    cache_path = get_cache_path(cache_dir, url)
    if not cache_path.exists():
        return None

    try:
        stat_info = cache_path.stat()
        age_seconds = (
            datetime.now() - datetime.fromtimestamp(stat_info.st_mtime)
        ).total_seconds()
        if age_seconds > 7 * 24 * 3600:  # 7 days
            return None

        with open(cache_path, encoding="utf-8") as f:
            return f.read(), "cache"
    except Exception:
        return None


def save_to_cache(cache_dir, url, content):
    """Save markdown to cache."""
    if not cache_dir:
        return

    try:
        cache_path = get_cache_path(cache_dir, url)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        pass


def fetch_with_jina(url, timeout):
    """Fetch URL using Jina Reader API."""
    try:
        jina_url = f"https://r.jina.ai/{url}"
        req = urllib.request.Request(jina_url, headers={"Accept": "text/markdown"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode("utf-8")
            return content, "jina"
    except Exception:
        return None, None


def fetch_with_trafilatura(url, timeout):
    """Fetch URL using Trafilatura library."""
    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(url, timeout=timeout)
        if not downloaded:
            return None, None

        markdown_content = trafilatura.extract(downloaded, output_format="markdown")
        if not markdown_content:
            return None, None

        return markdown_content, "trafilatura"
    except ImportError:
        return None, None
    except Exception:
        return None, None


def fetch_raw_and_convert(url, timeout):
    """Fetch URL and convert HTML to markdown."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode("utf-8", errors="replace")
            markdown = html_to_markdown(content)
            return markdown, "raw"
    except Exception:
        return None, None


def html_to_markdown(html_content):
    """Convert HTML to basic markdown."""
    # Remove script and style elements
    html_content = re.sub(
        r"<script[^>]*>.*?</script>", "", html_content, flags=re.DOTALL | re.IGNORECASE
    )
    html_content = re.sub(
        r"<style[^>]*>.*?</style>", "", html_content, flags=re.DOTALL | re.IGNORECASE
    )

    # Convert headers
    html_content = re.sub(
        r"<h1[^>]*>([^<]+)</h1>", r"# \1", html_content, flags=re.IGNORECASE
    )
    html_content = re.sub(
        r"<h2[^>]*>([^<]+)</h2>", r"## \1", html_content, flags=re.IGNORECASE
    )
    html_content = re.sub(
        r"<h3[^>]*>([^<]+)</h3>", r"### \1", html_content, flags=re.IGNORECASE
    )
    html_content = re.sub(
        r"<h4[^>]*>([^<]+)</h4>", r"#### \1", html_content, flags=re.IGNORECASE
    )
    html_content = re.sub(
        r"<h5[^>]*>([^<]+)</h5>", r"##### \1", html_content, flags=re.IGNORECASE
    )
    html_content = re.sub(
        r"<h6[^>]*>([^<]+)</h6>", r"###### \1", html_content, flags=re.IGNORECASE
    )

    # Convert paragraphs
    html_content = re.sub(
        r"<p[^>]*>([^<]+)</p>", r"\1\n\n", html_content, flags=re.IGNORECASE
    )

    # Convert links
    html_content = re.sub(
        r'<a[^>]*href="([^"]*)"[^>]*>([^<]+)</a>',
        r"[\2](\1)",
        html_content,
        flags=re.IGNORECASE,
    )

    # Convert line breaks
    html_content = re.sub(r"<br\s*/?>\s*", "\n", html_content, flags=re.IGNORECASE)

    # Convert list items
    html_content = re.sub(
        r"<li[^>]*>([^<]+)</li>", r"- \1", html_content, flags=re.IGNORECASE
    )

    # Convert emphasis
    html_content = re.sub(
        r"<strong[^>]*>([^<]+)</strong>", r"**\1**", html_content, flags=re.IGNORECASE
    )
    html_content = re.sub(
        r"<b[^>]*>([^<]+)</b>", r"**\1**", html_content, flags=re.IGNORECASE
    )
    html_content = re.sub(
        r"<em[^>]*>([^<]+)</em>", r"*\1*", html_content, flags=re.IGNORECASE
    )
    html_content = re.sub(
        r"<i[^>]*>([^<]+)</i>", r"*\1*", html_content, flags=re.IGNORECASE
    )

    # Remove remaining HTML tags
    html_content = re.sub(r"<[^>]+>", "", html_content)

    # Decode HTML entities
    html_content = html.unescape(html_content)

    # Clean up whitespace
    lines = [line.rstrip() for line in html_content.split("\n")]
    lines = [line for line in lines if line.strip()]
    markdown = "\n\n".join(lines)

    return markdown


def create_metadata_header(url, method):
    """Create metadata header comment."""
    now = datetime.now(UTC).isoformat() + "Z"
    return f"<!-- Source: {url} | Fetched: {now} | Method: {method} -->\n\n"


def fetch_url(url, timeout, cache_dir):
    """Fetch URL using extraction chain."""
    # Check cache first
    if cache_dir:
        cached = load_from_cache(cache_dir, url)
        if cached:
            content, method = cached
            return content, method

    # Try Jina Reader first
    content, method = fetch_with_jina(url, timeout)
    if content:
        save_to_cache(cache_dir, url, content)
        return content, method

    # Try Trafilatura
    content, method = fetch_with_trafilatura(url, timeout)
    if content:
        save_to_cache(cache_dir, url, content)
        return content, method

    # Fall back to raw HTTP
    content, method = fetch_raw_and_convert(url, timeout)
    if content:
        save_to_cache(cache_dir, url, content)
        return content, method

    return None, None


def main():
    """Main entry point."""
    args = parse_arguments()

    # Validate URL
    url = validate_url(args.url)
    if not url:
        print("Error: Invalid URL format", file=sys.stderr)
        sys.exit(2)

    # Fetch content
    content, method = fetch_url(url, args.timeout, args.cache_dir)
    if not content or not method:
        print("Error: All extraction methods failed", file=sys.stderr)
        sys.exit(1)

    # Add metadata header
    output = create_metadata_header(url, method) + content

    # Write output
    if args.output:
        try:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
        except Exception as e:
            print(f"Error writing to {args.output}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(output, end="")

    sys.exit(0)


if __name__ == "__main__":
    main()
