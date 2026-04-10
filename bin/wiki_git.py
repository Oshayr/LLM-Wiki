#!/usr/bin/env python3
"""wiki_git.py — Git integration for wiki operations.

Usage:
    python3 wiki_git.py commit <wiki_dir> <slug> "<message>" [--agent <name>]
    python3 wiki_git.py undo <wiki_dir> <slug>
    python3 wiki_git.py log <wiki_dir> <slug> [--format json|text] [--limit N]
    python3 wiki_git.py blame <wiki_dir> <slug>
    python3 wiki_git.py init <wiki_dir>

Auto-commits wiki changes with attribution trailers.
Supports undo (revert last commit for a page) and structured log output.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from wiki_logging import get_logger
from exceptions import GitError

logger = get_logger(__name__)


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    """Run a git command."""
    try:
        return subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
    except Exception as e:
        logger.error("Git command failed", extra={"args": args, "cwd": cwd, "error": str(e)}, exc_info=True)
        raise GitError(f"Git command failed: {e}")


def init_repo(wiki_dir: str) -> dict:
    """Initialize a git repo in the wiki directory if needed."""
    wiki_dir = Path(wiki_dir)

    # Check if already a git repo
    result = _git(["status"], str(wiki_dir))
    if result.returncode == 0:
        return {"status": "already_initialized"}

    # Initialize
    _git(["init"], str(wiki_dir))
    _git(["add", "."], str(wiki_dir))
    _git(["commit", "-m", "wiki: initial commit"], str(wiki_dir))
    return {"status": "initialized"}


def commit_page(wiki_dir: str, slug: str, message: str, agent: str = "user") -> dict:
    """Commit changes to a specific page with attribution."""
    wiki_dir = Path(wiki_dir)
    page_path = wiki_dir / "pages" / f"{slug}.md"

    if not page_path.exists():
        logger.error("Page not found", extra={"slug": slug, "path": str(page_path)})
        return {"error": f"Page '{slug}' not found"}

    # Check for changes
    result = _git(["status", "--porcelain", str(page_path)], str(wiki_dir))
    if not result.stdout.strip():
        return {"status": "no_changes", "slug": slug}

    # Stage the file
    _git(["add", str(page_path)], str(wiki_dir))

    # Also stage index.md and log.md if changed
    for extra in ["index.md", "log.md", "overview.md"]:
        extra_path = wiki_dir / extra
        if extra_path.exists():
            check = _git(["status", "--porcelain", str(extra_path)], str(wiki_dir))
            if check.stdout.strip():
                _git(["add", str(extra_path)], str(wiki_dir))

    # Commit with attribution
    commit_msg = f"{message}\n\nWiki-Agent: {agent}\nWiki-Page: {slug}"
    result = _git(["commit", "-m", commit_msg], str(wiki_dir))

    if result.returncode != 0:
        logger.error("Git commit failed", extra={"slug": slug, "error": result.stderr.strip()})
        return {"error": result.stderr.strip(), "slug": slug}

    # Get commit hash
    hash_result = _git(["rev-parse", "--short", "HEAD"], str(wiki_dir))
    commit_hash = hash_result.stdout.strip()

    logger.info("Page committed", extra={"slug": slug, "hash": commit_hash, "agent": agent})
    return {"status": "committed", "slug": slug, "hash": commit_hash, "message": message}


def undo_page(wiki_dir: str, slug: str) -> dict:
    """Revert the last commit that touched a specific page."""
    wiki_dir = Path(wiki_dir)
    page_path = wiki_dir / "pages" / f"{slug}.md"

    # Find the last commit for this page
    result = _git(
        ["log", "--pretty=format:%H", "-1", "--", str(page_path)],
        str(wiki_dir),
    )

    if not result.stdout.strip():
        logger.warning("No commits found for page", extra={"slug": slug})
        return {"error": f"No commits found for '{slug}'"}

    last_commit = result.stdout.strip()

    # Get the commit message for confirmation
    msg_result = _git(["log", "--pretty=format:%s", "-1", last_commit], str(wiki_dir))
    commit_msg = msg_result.stdout.strip()

    # Revert
    result = _git(["revert", "--no-edit", last_commit], str(wiki_dir))

    if result.returncode != 0:
        logger.error("Git revert failed", extra={"slug": slug, "error": result.stderr.strip()})
        return {"error": result.stderr.strip(), "slug": slug}

    logger.info("Page reverted", extra={"slug": slug, "commit": last_commit[:8]})
    return {
        "status": "reverted",
        "slug": slug,
        "reverted_commit": last_commit[:8],
        "reverted_message": commit_msg,
    }


def log_page(wiki_dir: str, slug: str, fmt: str = "json", limit: int = 20) -> list[dict] | str:
    """Get git log for a specific page."""
    wiki_dir = Path(wiki_dir)
    page_path = wiki_dir / "pages" / f"{slug}.md"

    result = _git(
        ["log", f"--pretty=format:%H|%ai|%an|%s", f"-{limit}", "--", str(page_path)],
        str(wiki_dir),
    )

    if not result.stdout.strip():
        return [] if fmt == "json" else "No history found."

    entries = []
    for line in result.stdout.strip().split("\n"):
        if "|" not in line:
            continue
        parts = line.split("|", 3)
        entries.append({
            "hash": parts[0][:8],
            "date": parts[1],
            "author": parts[2],
            "message": parts[3],
        })

    if fmt == "json":
        return entries
    else:
        lines = []
        for e in entries:
            lines.append(f"{e['hash']} {e['date'][:10]} {e['message']}")
        return "\n".join(lines)


def blame_page(wiki_dir: str, slug: str) -> list[dict]:
    """Show attribution per section of a page."""
    wiki_dir = Path(wiki_dir)
    page_path = wiki_dir / "pages" / f"{slug}.md"

    if not page_path.exists():
        return [{"error": f"Page '{slug}' not found"}]

    result = _git(
        ["blame", "--line-porcelain", str(page_path)],
        str(wiki_dir),
    )

    if result.returncode != 0:
        logger.error("Git blame failed", extra={"slug": slug, "error": result.stderr.strip()})
        return [{"error": "Git blame failed"}]

    # Parse blame output to find agents per section
    sections = []
    current_section = "intro"
    section_agents = {}

    content = page_path.read_text(encoding="utf-8")
    import re
    for line in content.split("\n"):
        heading_match = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading_match:
            current_section = heading_match.group(2).strip()

    # Simplified: get last author per section from git log
    lines = content.split("\n")
    for i, line in enumerate(lines):
        heading_match = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading_match:
            section_name = heading_match.group(2).strip()
            # Get last commit that touched lines near this heading
            line_result = _git(
                ["log", "-1", "--pretty=format:%an|%s", f"-L{i+1},{min(i+5, len(lines))}:{page_path}"],
                str(wiki_dir),
            )
            agent = "unknown"
            message = ""
            if line_result.stdout.strip():
                for bl in line_result.stdout.strip().split("\n"):
                    if "|" in bl:
                        parts = bl.split("|", 1)
                        agent = parts[0]
                        message = parts[1]
                        break

            sections.append({
                "section": section_name,
                "last_author": agent,
                "last_message": message,
            })

    return sections


def main():
    parser = argparse.ArgumentParser(
        description="Git integration for wiki operations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    commit_p = subparsers.add_parser("commit", help="Commit a page change")
    commit_p.add_argument("wiki_dir")
    commit_p.add_argument("slug")
    commit_p.add_argument("message")
    commit_p.add_argument("--agent", default="user")

    undo_p = subparsers.add_parser("undo", help="Undo last commit for a page")
    undo_p.add_argument("wiki_dir")
    undo_p.add_argument("slug")

    log_p = subparsers.add_parser("log", help="Git log for a page")
    log_p.add_argument("wiki_dir")
    log_p.add_argument("slug")
    log_p.add_argument("--format", choices=["json", "text"], default="json")
    log_p.add_argument("--limit", type=int, default=20)

    blame_p = subparsers.add_parser("blame", help="Attribution per section")
    blame_p.add_argument("wiki_dir")
    blame_p.add_argument("slug")

    init_p = subparsers.add_parser("init", help="Initialize git repo")
    init_p.add_argument("wiki_dir")

    args = parser.parse_args()

    if args.command == "commit":
        result = commit_page(args.wiki_dir, args.slug, args.message, getattr(args, "agent", "user"))
        print(json.dumps(result, indent=2))

    elif args.command == "undo":
        result = undo_page(args.wiki_dir, args.slug)
        print(json.dumps(result, indent=2))

    elif args.command == "log":
        result = log_page(args.wiki_dir, args.slug, args.format, args.limit)
        if isinstance(result, list):
            print(json.dumps(result, indent=2))
        else:
            print(result)

    elif args.command == "blame":
        result = blame_page(args.wiki_dir, args.slug)
        print(json.dumps(result, indent=2))

    elif args.command == "init":
        result = init_repo(args.wiki_dir)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
