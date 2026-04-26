"""bootstrap.py — Cross-platform first-run setup for llm-wiki-github.

Invoked by the SessionStart hook. Idempotently installs Python dependencies
declared in requirements.txt when they have changed since the last run.

Works on Linux, macOS, and Windows (Claude Code CLI, Claude Desktop App).
Silent on no-op; logs a single line to stderr when work was performed.
Never raises — install failures degrade gracefully so a session can still start.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path


def _plugin_root() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env)
    # Fallback: assume we're running from bin/ inside the plugin
    return Path(__file__).resolve().parent.parent


def _data_root() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_DATA")
    if env:
        return Path(env)
    return Path.home() / ".local" / "share" / "llm-wiki-github"


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    plugin_root = _plugin_root()
    data_root = _data_root()
    req_file = plugin_root / "requirements.txt"
    if not req_file.exists():
        return 0

    try:
        data_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        # No writable data dir — skip silently
        return 0

    sentinel = data_root / "requirements.sha256"
    current = _hash_file(req_file)
    previous = sentinel.read_text(encoding="utf-8").strip() if sentinel.exists() else ""

    if current == previous:
        return 0

    # Run pip install. Use the same Python interpreter that runs this script.
    print("[llm-wiki-github] installing Python dependencies...", file=sys.stderr)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "--requirement", str(req_file)],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"[llm-wiki-github] dependency install skipped: {e}", file=sys.stderr)
        return 0

    if result.returncode != 0:
        # Don't fail the session — just report and move on.
        msg = (result.stderr or result.stdout or "").strip().splitlines()[-1:] or [""]
        print(f"[llm-wiki-github] pip install failed (continuing): {msg[0]}", file=sys.stderr)
        return 0

    try:
        sentinel.write_text(current, encoding="utf-8")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
