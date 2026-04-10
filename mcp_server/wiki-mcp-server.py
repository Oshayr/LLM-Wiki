#!/usr/bin/env python3
"""FastMCP server exposing wiki operations as MCP tools.

Tools: wiki_search, wiki_read, wiki_write, wiki_list, wiki_backlinks,
       wiki_stats, wiki_query, wiki_gaps, wiki_daily

Run: python3 wiki-mcp-server.py --wiki-dir <path-to-.wiki>
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Add bin/ directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "bin"))

from wiki_logging import get_logger

logger = get_logger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    logger.error("mcp package not installed. Install with: pip install mcp")
    sys.exit(1)


# Determine wiki directory from plugin install scope
PLUGIN_ROOT = Path(__file__).parent.parent
BIN_DIR = PLUGIN_ROOT / "bin"
WIKI_DIR = None

for arg in sys.argv:
    if arg.startswith("--wiki-dir="):
        WIKI_DIR = Path(arg.split("=", 1)[1])
    elif arg == "--wiki-dir" and sys.argv.index(arg) + 1 < len(sys.argv):
        WIKI_DIR = Path(sys.argv[sys.argv.index(arg) + 1])

if not WIKI_DIR:
    # Resolve from plugin install scope:
    # - If PLUGIN_ROOT is under ~/.claude/ → user-level → ~/.wiki/
    # - Otherwise → project-level → .wiki/ at project root (next to .git/)
    home_claude = Path.home() / ".claude"
    try:
        PLUGIN_ROOT.resolve().relative_to(home_claude.resolve())
        # User-level install
        WIKI_DIR = Path.home() / ".wiki"
    except ValueError:
        # Project-level install — .wiki/ at project root (PLUGIN_ROOT's ancestor with .git/)
        candidate = PLUGIN_ROOT.resolve()
        while candidate != candidate.parent:
            if (candidate / ".git").exists():
                WIKI_DIR = candidate / ".wiki"
                break
            candidate = candidate.parent
        if not WIKI_DIR:
            WIKI_DIR = Path.cwd() / ".wiki"

mcp = FastMCP(
    "LLM Wiki",
    instructions="Knowledge wiki with semantic search, research, and knowledge graph",
)


def _pages_dir() -> Path:
    """Get the pages directory."""
    if WIKI_DIR:
        return WIKI_DIR / "pages"
    return Path(".wiki/pages")


def _run_bin(script: str, args: list[str]) -> str:
    """Run a bin/ utility and return stdout."""
    import subprocess

    cmd = [sys.executable, str(BIN_DIR / script)] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0 and result.stderr:
        return json.dumps({"error": result.stderr[:500]})
    return result.stdout


@mcp.tool()
def wiki_search(query: str, limit: int = 10) -> str:
    """Search the wiki using TF-IDF full-text search.

    Args:
        query: Search query
        limit: Maximum results (default 10)
    """
    return _run_bin("search-fulltext.py", [str(_pages_dir()), query, "--top", str(limit), "--json"])


@mcp.tool()
def wiki_read(slug: str) -> str:
    """Read a wiki page by slug. Returns the full markdown content.

    Args:
        slug: Page slug (e.g., 'machine-learning', 'api-design')
    """
    page_path = _pages_dir() / f"{slug}.md"
    if not page_path.exists():
        return json.dumps({"error": f"Page '{slug}' not found"})
    return page_path.read_text(encoding="utf-8")


@mcp.tool()
def wiki_write(slug: str, content: str) -> str:
    """Create or update a wiki page.

    Args:
        slug: Page slug
        content: Full markdown content (including frontmatter)
    """
    pages_dir = _pages_dir()
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_path = pages_dir / f"{slug}.md"
    existed = page_path.exists()
    page_path.write_text(content, encoding="utf-8")
    return json.dumps({"status": "updated" if existed else "created", "slug": slug})


@mcp.tool()
def wiki_list(type_filter: str = "", limit: int = 50) -> str:
    """List wiki pages, optionally filtered by type.

    Args:
        type_filter: Filter by page type (e.g., 'concept', 'source', 'entity')
        limit: Maximum results
    """
    pages = []
    for md_file in sorted(_pages_dir().glob("*.md"))[:limit]:
        slug = md_file.stem
        content = md_file.read_text(encoding="utf-8")
        # Quick frontmatter parse
        title = slug
        ptype = ""
        match = re.search(r"^title:\s*(.+)$", content, re.MULTILINE)
        if match:
            title = match.group(1).strip().strip('"').strip("'")
        match = re.search(r"^type:\s*(.+)$", content, re.MULTILINE)
        if match:
            ptype = match.group(1).strip()

        if type_filter and ptype != type_filter:
            continue
        pages.append({"slug": slug, "title": title, "type": ptype})

    return json.dumps(pages[:limit])


@mcp.tool()
def wiki_backlinks(slug: str) -> str:
    """Get all pages that link to a given page, plus unlinked mentions.

    Args:
        slug: Page slug to find backlinks for
    """
    return _run_bin("backlinks.py", ["query", str(_pages_dir()), slug])


@mcp.tool()
def wiki_stats() -> str:
    """Get wiki statistics: page count, types, confidence distribution."""
    return _run_bin("backlinks.py", ["stats", str(_pages_dir())])


@mcp.tool()
def wiki_query(query: str) -> str:
    """Execute a frontmatter query (Dataview-like syntax).

    Example queries:
    - SELECT title, type FROM pages WHERE confidence = "high" SORT BY updated DESC
    - COUNT type FROM pages
    - LIST FROM pages WHERE tags CONTAINS "research"

    Args:
        query: Dataview-style query string
    """
    return _run_bin("query.py", ["exec", str(_pages_dir()), query])


@mcp.tool()
def wiki_gaps() -> str:
    """Analyze content gaps: missing pages, structural holes, stale content."""
    return _run_bin("gaps.py", ["analyze", str(_pages_dir())])


@mcp.tool()
def wiki_daily() -> str:
    """Create or get today's daily note."""
    return _run_bin("daily.py", ["today", str(_pages_dir())])


@mcp.tool()
def wiki_wikipedia_search(query: str, lang: str = "en", limit: int = 5) -> str:
    """Search Wikipedia articles via the MediaWiki Action API.

    Args:
        query: Search query (factual, encyclopedic, historical, or scientific topics)
        lang: Wikipedia language code (default: 'en'; use 'de', 'fr', 'es', etc.)
        limit: Maximum number of results to return (default: 5)
    """
    return _run_bin(
        "search-wikipedia.py",
        ["search", query, "--top", str(limit), "--lang", lang],
    )


@mcp.resource("wiki://index")
def wiki_index() -> str:
    """The wiki page index — list of all pages with metadata."""
    index_path = WIKI_DIR / "index.md" if WIKI_DIR else Path(".wiki/index.md")
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return "No index.md found."


@mcp.resource("wiki://pages/{slug}")
def wiki_page_resource(slug: str) -> str:
    """Read a specific wiki page by slug."""
    page_path = _pages_dir() / f"{slug}.md"
    if page_path.exists():
        return page_path.read_text(encoding="utf-8")
    return f"Page '{slug}' not found."


if __name__ == "__main__":
    mcp.run()
