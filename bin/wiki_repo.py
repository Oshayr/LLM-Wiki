"""wiki_repo.py — Single chokepoint for every git-wiki I/O operation.

All reads and writes to the GitHub Wiki flow through this module. It handles:
- Target (owner/repo) resolution from env, config, or git remote
- Local clone of <owner>/<repo>.wiki.git under ${CLAUDE_PLUGIN_DATA}/wiki-cache/
- File locking (fcntl) for cross-process safety
- Pull-before-write, push-with-retry-rebase, commit attribution via trailers
- Sidebar + footer auto-rebuild on every write

Exit codes (when raised via CLI entry points):
    10 — wiki repository has not been initialized on GitHub yet (404 on clone)
    11 — network failure
    12 — no target repository configured
    13 — auth failure (push rejected, unable to authenticate)
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from wiki_logging import get_logger
from exceptions import (
    WikiRepoError,
    WikiPushConflictError,
    WikiBootstrapRequired,
    GitError,
)
from slug_title import slug_to_filename, filename_to_slug, slug_to_wiki_url
import frontmatter_fmt

logger = get_logger(__name__)


EXIT_BOOTSTRAP_REQUIRED = 10
EXIT_NETWORK = 11
EXIT_NO_TARGET = 12
EXIT_AUTH = 13

DEFAULT_PULL_TTL_SECONDS = 300
SIDEBAR_FILENAME = "_Sidebar.md"
FOOTER_FILENAME = "_Footer.md"

_REMOTE_RE = re.compile(
    r"(?:git@github\.com[:/]|https?://github\.com/)(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?/?$"
)

_process_lock = threading.Lock()


@dataclass(frozen=True)
class Target:
    owner: str
    repo: str

    @property
    def key(self) -> str:
        return f"{self.owner}__{self.repo}"

    @property
    def wiki_clone_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}.wiki.git"

    @property
    def wiki_browse_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/wiki"


# ── Data dir / cache dir ──────────────────────────────────────────────────────


def _data_root() -> Path:
    """Root directory for plugin data (clones, locks, sidecars)."""
    env = os.environ.get("CLAUDE_PLUGIN_DATA")
    if env:
        return Path(env)
    return Path.home() / ".local" / "share" / "llm-wiki-github"


def _cache_root() -> Path:
    root = _data_root() / "wiki-cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def cache_path(target: Optional[Target] = None) -> Path:
    """Local clone directory for the resolved target."""
    t = target or resolve_target()
    return _cache_root() / t.key


def _lock_path(target: Target) -> Path:
    return _cache_root() / f"{target.key}.lock"


def _meta_path(target: Target) -> Path:
    return _cache_root() / f"{target.key}.meta.json"


# ── Target resolution ────────────────────────────────────────────────────────


def _parse_remote_url(url: str) -> Optional[Target]:
    m = _REMOTE_RE.search(url.strip())
    if not m:
        return None
    return Target(owner=m.group("owner"), repo=m.group("repo"))


def _target_from_git_remote(start: Path) -> Optional[Target]:
    candidate = start.resolve()
    while True:
        if (candidate / ".git").exists():
            try:
                out = subprocess.run(
                    ["git", "-C", str(candidate), "remote", "get-url", "origin"],
                    capture_output=True, text=True, check=True, timeout=5,
                )
                t = _parse_remote_url(out.stdout)
                if t:
                    return t
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
                pass
        if candidate == candidate.parent:
            return None
        candidate = candidate.parent


def _target_from_config() -> Optional[Target]:
    config_path = _data_root() / "config.yaml"
    if not config_path.exists():
        return None
    owner = repo = None
    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or not line or ":" not in line:
                continue
            k, _, v = line.partition(":")
            v = v.strip().strip('"').strip("'")
            if k.strip() == "owner":
                owner = v
            elif k.strip() == "repo":
                repo = v
    except OSError:
        return None
    if owner and repo:
        return Target(owner=owner, repo=repo)
    return None


def resolve_target() -> Target:
    """Resolve the target <owner>/<repo> using the documented precedence.

    1. env LLM_WIKI_TARGET=owner/repo
    2. ${CLAUDE_PLUGIN_DATA}/config.yaml with owner: / repo:
    3. Parse `git remote get-url origin` from CWD (walks up to .git ancestors)

    Raises WikiRepoError with exit-code hint 12 if unresolved.
    """
    env = os.environ.get("LLM_WIKI_TARGET")
    if env and "/" in env:
        owner, repo = env.split("/", 1)
        if owner and repo:
            return Target(owner=owner.strip(), repo=repo.strip())

    t = _target_from_config()
    if t:
        return t

    t = _target_from_git_remote(Path.cwd())
    if t:
        return t

    raise WikiRepoError(
        "No target wiki repository resolved. Set LLM_WIKI_TARGET=owner/repo, "
        "configure owner/repo in config.yaml, or run from a git repo whose "
        "origin points to github.com.",
        exit_code=EXIT_NO_TARGET,
    )


# ── Locks ─────────────────────────────────────────────────────────────────────


@contextmanager
def _flock(target: Target, exclusive: bool):
    path = _lock_path(target)
    path.touch(exist_ok=True)
    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    with _process_lock:
        fd = os.open(str(path), os.O_RDWR)
        try:
            fcntl.flock(fd, mode)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


# ── Git primitives ────────────────────────────────────────────────────────────


def _git(*args: str, cwd: Path, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["git", *args]
    logger.debug("git %s (cwd=%s)", " ".join(args), cwd)
    try:
        return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                              timeout=timeout, check=check)
    except subprocess.CalledProcessError as e:
        raise GitError(f"git {' '.join(args)} failed: {e.stderr.strip() or e.stdout.strip()}") from e
    except subprocess.TimeoutExpired as e:
        raise GitError(f"git {' '.join(args)} timed out") from e
    except FileNotFoundError as e:
        raise GitError("git is not installed or not on PATH") from e


def _head_branch(cwd: Path) -> str:
    r = _git("symbolic-ref", "--short", "HEAD", cwd=cwd, check=False)
    if r.returncode == 0:
        return r.stdout.strip()
    # Wiki may default to "master" on older wikis
    return "master"


def _load_sidecar(target: Target) -> dict:
    p = _meta_path(target)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_sidecar(target: Target, data: dict) -> None:
    _meta_path(target).write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Public API ────────────────────────────────────────────────────────────────


def ensure_clone(target: Optional[Target] = None) -> Path:
    """Ensure the target's wiki clone exists locally. Returns the clone path.

    Raises WikiBootstrapRequired (exit 10) if the wiki has not been initialized
    on GitHub — the user must create the first page manually via the web UI.
    """
    t = target or resolve_target()
    path = cache_path(t)
    with _flock(t, exclusive=True):
        if (path / ".git").exists():
            return path
        path.mkdir(parents=True, exist_ok=True)
        logger.info("Cloning wiki", extra={"url": t.wiki_clone_url, "dest": str(path)})
        try:
            _git("clone", t.wiki_clone_url, str(path), cwd=_cache_root(), timeout=120)
        except GitError as e:
            msg = str(e).lower()
            if "not found" in msg or "404" in msg or "repository" in msg and "does not exist" in msg:
                raise WikiBootstrapRequired(
                    f"GitHub Wiki for {t.owner}/{t.repo} is not initialized. "
                    f"Create the first page at {t.wiki_browse_url} in the browser, then retry.",
                    exit_code=EXIT_BOOTSTRAP_REQUIRED,
                ) from e
            if "could not resolve host" in msg or "network" in msg or "connection" in msg:
                raise WikiRepoError(f"Network error cloning wiki: {e}", exit_code=EXIT_NETWORK) from e
            if "authentication" in msg or "denied" in msg or "permission" in msg:
                raise WikiRepoError(f"Authentication failed: {e}", exit_code=EXIT_AUTH) from e
            raise
        _save_sidecar(t, {
            "schema_version": 1,
            "origin_url": t.wiki_clone_url,
            "last_pull_ts": time.time(),
        })
        return path


def pull_if_stale(ttl: int = DEFAULT_PULL_TTL_SECONDS, target: Optional[Target] = None) -> bool:
    """Pull from origin if the last pull was more than `ttl` seconds ago.

    Returns True if a pull was performed.
    """
    t = target or resolve_target()
    path = ensure_clone(t)
    sidecar = _load_sidecar(t)
    last = sidecar.get("last_pull_ts", 0)
    if time.time() - last < ttl:
        return False
    with _flock(t, exclusive=True):
        return _force_pull(t, path, sidecar)


def _force_pull(target: Target, path: Path, sidecar: dict) -> bool:
    """Pull from origin. Caller MUST hold the exclusive flock for `target`."""
    branch = _head_branch(path)
    try:
        _git("pull", "--ff-only", "origin", branch, cwd=path, timeout=60)
    except GitError as e:
        logger.warning("ff-only pull failed, falling back to fetch+reset", extra={"error": str(e)})
        _git("fetch", "origin", cwd=path, timeout=60)
        _git("reset", "--hard", f"origin/{branch}", cwd=path)
    sidecar["last_pull_ts"] = time.time()
    _save_sidecar(target, sidecar)
    return True


def read_page(slug: str, target: Optional[Target] = None) -> Optional[bytes]:
    """Return the raw file bytes for `slug`, or None if the page does not exist."""
    t = target or resolve_target()
    path = ensure_clone(t)
    pull_if_stale(target=t)
    file_path = path / slug_to_filename(slug)
    with _flock(t, exclusive=False):
        if not file_path.exists():
            return None
        return file_path.read_bytes()


def write_page(
    slug: str,
    content: str,
    message: str,
    agent: str = "wiki-writer",
    target: Optional[Target] = None,
) -> dict:
    """Write, commit, and push a page. Returns {slug, url, commit, action}."""
    t = target or resolve_target()
    path = ensure_clone(t)
    file_path = path / slug_to_filename(slug)
    action = "updated" if file_path.exists() else "created"

    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            with _flock(t, exclusive=True):
                _force_pull(t, path, _load_sidecar(t))
                file_path.write_text(content, encoding="utf-8")
                _rebuild_sidebar(t, path)
                _rebuild_footer(t, path)
                _git("add", file_path.name, SIDEBAR_FILENAME, FOOTER_FILENAME,
                     cwd=path, check=False)
                trailers = f"\n\nWiki-Agent: {agent}\nWiki-Page: {slug}"
                _git("commit", "-m", message + trailers, cwd=path, check=False)
                _push(t, path)
                commit = _git("rev-parse", "HEAD", cwd=path).stdout.strip()
            return {
                "slug": slug,
                "url": slug_to_wiki_url(t.owner, t.repo, slug),
                "commit": commit,
                "action": action,
            }
        except WikiPushConflictError as e:
            last_err = e
            backoff = 2 ** attempt
            logger.warning("Push conflict, retrying", extra={"attempt": attempt, "backoff": backoff})
            time.sleep(backoff)
            continue
        except GitError as e:
            last_err = e
            break
    raise WikiRepoError(f"Failed to write {slug}: {last_err}") from last_err


def _push(target: Target, path: Path) -> None:
    branch = _head_branch(path)
    r = _git("push", "origin", branch, cwd=path, timeout=60, check=False)
    if r.returncode == 0:
        return
    err = (r.stderr + r.stdout).lower()
    if "non-fast-forward" in err or "rejected" in err:
        raise WikiPushConflictError(path.name, "Push rejected; remote has newer commits")
    if "authentication" in err or "permission" in err or "denied" in err:
        raise WikiRepoError(f"Auth failed pushing wiki: {r.stderr.strip()}", exit_code=EXIT_AUTH)
    raise GitError(f"git push failed: {r.stderr.strip() or r.stdout.strip()}")


def list_pages(target: Optional[Target] = None) -> list[dict]:
    """Return a list of {slug, title, type, filename} for every wiki page."""
    t = target or resolve_target()
    path = ensure_clone(t)
    pull_if_stale(target=t)
    pages = []
    with _flock(t, exclusive=False):
        for md in sorted(path.glob("*.md")):
            if md.name.startswith("_"):
                continue
            slug = filename_to_slug(md.name)
            meta = frontmatter_fmt.parse(md.read_text(encoding="utf-8"))
            pages.append({
                "slug": meta.get("slug", slug),
                "title": meta.get("title", slug),
                "type": meta.get("type", ""),
                "filename": md.name,
            })
    return pages


def rebuild_sidebar(target: Optional[Target] = None) -> None:
    """Public entry to regenerate _Sidebar.md (and _Footer.md), commit, and push."""
    t = target or resolve_target()
    path = ensure_clone(t)
    with _flock(t, exclusive=True):
        _force_pull(t, path, _load_sidecar(t))
        changed = _rebuild_sidebar(t, path) | _rebuild_footer(t, path)
        if not changed:
            return
        _git("add", SIDEBAR_FILENAME, FOOTER_FILENAME, cwd=path, check=False)
        _git("commit", "-m", "chore: rebuild sidebar/footer\n\nWiki-Agent: wiki_repo",
             cwd=path, check=False)
        _push(t, path)


def _rebuild_sidebar(target: Target, path: Path) -> bool:
    by_type: dict[str, list[tuple[str, str]]] = {}
    for md in sorted(path.glob("*.md")):
        if md.name.startswith("_") or md.name == "Home.md":
            continue
        meta = frontmatter_fmt.parse(md.read_text(encoding="utf-8"))
        ptype = meta.get("type") or "other"
        title = meta.get("title") or md.stem.replace("-", " ")
        stem = md.stem
        by_type.setdefault(ptype, []).append((title, stem))

    lines = ["# Wiki", ""]
    for ptype in sorted(by_type):
        label = ptype[0].upper() + ptype[1:] + "s"
        lines.append(f"## {label}")
        for title, stem in sorted(by_type[ptype]):
            lines.append(f"- [[{title}|{stem}]]")
        lines.append("")
    new_content = "\n".join(lines).rstrip() + "\n"

    sidebar = path / SIDEBAR_FILENAME
    old = sidebar.read_text(encoding="utf-8") if sidebar.exists() else ""
    if old == new_content:
        return False
    sidebar.write_text(new_content, encoding="utf-8")
    return True


def _rebuild_footer(target: Target, path: Path) -> bool:
    footer = path / FOOTER_FILENAME
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    new_content = f"_Last updated {ts} by llm-wiki-github_\n"
    old = footer.read_text(encoding="utf-8") if footer.exists() else ""
    if old == new_content:
        return False
    footer.write_text(new_content, encoding="utf-8")
    return True


def page_url(slug: str, target: Optional[Target] = None) -> str:
    t = target or resolve_target()
    return slug_to_wiki_url(t.owner, t.repo, slug)


def sync(target: Optional[Target] = None) -> dict:
    """Force-pull and return {head, pulled} for diagnostics."""
    t = target or resolve_target()
    path = ensure_clone(t)
    with _flock(t, exclusive=True):
        _force_pull(t, path, _load_sidecar(t))
    head = _git("rev-parse", "HEAD", cwd=path).stdout.strip()
    return {"target": f"{t.owner}/{t.repo}", "head": head, "cache": str(path)}


# ── CLI for quick diagnostics ────────────────────────────────────────────────


def _cli():
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("resolve")
    sub.add_parser("ensure")
    sub.add_parser("sync")
    sub.add_parser("list")
    rp = sub.add_parser("read"); rp.add_argument("slug")
    up = sub.add_parser("url"); up.add_argument("slug")
    args = p.parse_args()

    try:
        if args.cmd == "resolve":
            t = resolve_target()
            print(json.dumps({"owner": t.owner, "repo": t.repo, "cache": str(cache_path(t))}))
        elif args.cmd == "ensure":
            print(str(ensure_clone()))
        elif args.cmd == "sync":
            print(json.dumps(sync()))
        elif args.cmd == "list":
            print(json.dumps(list_pages(), indent=2))
        elif args.cmd == "read":
            data = read_page(args.slug)
            if data is None:
                raise SystemExit(f"Page not found: {args.slug}")
            print(data.decode("utf-8"))
        elif args.cmd == "url":
            print(page_url(args.slug))
    except WikiRepoError as e:
        print(f"error: {e}", flush=True)
        raise SystemExit(getattr(e, "exit_code", 1))


if __name__ == "__main__":
    _cli()
