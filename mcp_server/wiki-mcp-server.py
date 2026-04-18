#!/usr/bin/env python3
"""FastMCP server exposing GitHub-Wiki-backed operations as MCP tools.

Tools: wiki_search, wiki_read, wiki_write, wiki_list, wiki_stats, wiki_url, wiki_sync.

The server is a thin wrapper over bin/wiki_repo.py — all storage I/O goes
through that module, so the MCP surface and the in-Claude skills/agents use
identical code paths.
"""

import json
import sys
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

import wiki_repo
from exceptions import WikiRepoError, WikiBootstrapRequired

PLUGIN_ROOT = Path(__file__).parent.parent
BIN_DIR = PLUGIN_ROOT / "bin"

mcp = FastMCP(
    "LLM Wiki (GitHub)",
    instructions="GitHub-Wiki-backed knowledge base — search, read, write, sync pages on the target repo's wiki.",
)


def _run_bin(script: str, args: list[str]) -> str:
    import subprocess

    cmd = [sys.executable, str(BIN_DIR / script)] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0 and result.stderr:
        return json.dumps({"error": result.stderr[:500]})
    return result.stdout


def _err(e: Exception) -> str:
    return json.dumps({"error": str(e), "exit_code": getattr(e, "exit_code", 1)})


@mcp.tool()
def wiki_search(query: str, limit: int = 10) -> str:
    """Search the wiki using TF-IDF full-text search.

    Args:
        query: Search query
        limit: Maximum results (default 10)
    """
    try:
        path = wiki_repo.ensure_clone()
        wiki_repo.pull_if_stale()
    except WikiRepoError as e:
        return _err(e)
    return _run_bin("search-fulltext.py", [str(path), query, "--top", str(limit), "--json"])


@mcp.tool()
def wiki_read(slug: str) -> str:
    """Read a wiki page by slug. Returns the full markdown content.

    Args:
        slug: Page slug (e.g., 'machine-learning')
    """
    try:
        data = wiki_repo.read_page(slug)
    except WikiRepoError as e:
        return _err(e)
    if data is None:
        return json.dumps({"error": f"Page '{slug}' not found"})
    return data.decode("utf-8")


@mcp.tool()
def wiki_write(slug: str, content: str, message: str = "", agent: str = "mcp") -> str:
    """Create or update a wiki page. Pulls, writes, rebuilds sidebar, commits, and pushes.

    Args:
        slug: Page slug
        content: Full markdown content (body + HTML-comment metadata block)
        message: Commit message (defaults to a generic update message)
        agent: Attribution for the Wiki-Agent: commit trailer
    """
    try:
        result = wiki_repo.write_page(
            slug=slug,
            content=content,
            message=message or f"Update {slug}",
            agent=agent,
        )
        return json.dumps(result)
    except WikiRepoError as e:
        return _err(e)


@mcp.tool()
def wiki_list(type_filter: str = "", limit: int = 50) -> str:
    """List wiki pages, optionally filtered by type.

    Args:
        type_filter: Filter by page type (e.g., 'concept', 'source', 'entity')
        limit: Maximum results
    """
    try:
        pages = wiki_repo.list_pages()
    except WikiRepoError as e:
        return _err(e)
    if type_filter:
        pages = [p for p in pages if p.get("type") == type_filter]
    return json.dumps(pages[:limit])


@mcp.tool()
def wiki_stats() -> str:
    """Get wiki statistics: total pages and counts per type."""
    try:
        pages = wiki_repo.list_pages()
    except WikiRepoError as e:
        return _err(e)
    counts: dict[str, int] = {}
    for p in pages:
        t = p.get("type") or "untyped"
        counts[t] = counts.get(t, 0) + 1
    return json.dumps({"total": len(pages), "by_type": counts})


@mcp.tool()
def wiki_url(slug: str) -> str:
    """Return the GitHub Wiki browse URL for a page slug.

    Args:
        slug: Page slug
    """
    try:
        return wiki_repo.page_url(slug)
    except WikiRepoError as e:
        return _err(e)


@mcp.tool()
def wiki_sync() -> str:
    """Force-pull the local wiki clone and return the HEAD commit hash."""
    try:
        return json.dumps(wiki_repo.sync())
    except WikiRepoError as e:
        return _err(e)


@mcp.resource("wiki://index")
def wiki_index() -> str:
    """The wiki's _Sidebar.md — authoritative listing, auto-rebuilt on every write."""
    try:
        path = wiki_repo.ensure_clone()
        wiki_repo.pull_if_stale()
    except WikiRepoError as e:
        return f"(error: {e})"
    sidebar = path / "_Sidebar.md"
    if sidebar.exists():
        return sidebar.read_text(encoding="utf-8")
    return "(no _Sidebar.md; wiki may be empty)"


@mcp.resource("wiki://pages/{slug}")
def wiki_page_resource(slug: str) -> str:
    """Read a specific wiki page by slug."""
    try:
        data = wiki_repo.read_page(slug)
    except WikiRepoError as e:
        return f"(error: {e})"
    if data is None:
        return f"Page '{slug}' not found."
    return data.decode("utf-8")


if __name__ == "__main__":
    mcp.run()
