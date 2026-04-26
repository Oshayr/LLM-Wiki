"""frontmatter_fmt.py — HTML-comment JSON metadata format for GitHub Wiki pages.

Canonical page layout on disk (and as rendered on github.com/.../wiki/<Slug>):

    # Page Title

    <body — sections, [[wiki links]], paragraphs...>

    <!-- wiki-meta
    {"title":"...","slug":"...","type":"concept",...}
    wiki-meta:end -->

The HTML-comment JSON block is the ONLY metadata format. It renders as invisible
HTML comment on GitHub, keeps the page clean for readers, and every metadata
change is a single-line JSON diff.

This module is the single source of truth for reading/writing that block.
"""

from __future__ import annotations

import json
import re
from typing import Any


META_START = "<!-- wiki-meta"
META_END = "wiki-meta:end -->"

_META_BLOCK_RE = re.compile(
    r"<!--\s*wiki-meta\s*\n(?P<json>.*?)\n\s*wiki-meta:end\s*-->",
    re.DOTALL,
)


def parse(content: str) -> dict[str, Any]:
    """Extract and parse the metadata block from a page. Returns {} if absent or invalid."""
    m = _META_BLOCK_RE.search(content)
    if not m:
        return {}
    try:
        data = json.loads(m.group("json").strip())
        if isinstance(data, dict):
            return data
        return {}
    except (json.JSONDecodeError, ValueError):
        return {}


def strip_meta_block(content: str) -> str:
    """Return the page body with the metadata block (and any trailing whitespace) removed."""
    stripped = _META_BLOCK_RE.sub("", content)
    return stripped.rstrip() + "\n"


def render(meta: dict[str, Any], body: str) -> str:
    """Render a full page: body followed by the metadata block.

    `body` is the markdown body (including the H1). Does not require a trailing newline.
    The metadata block is emitted with stable key ordering for diff-friendliness.
    """
    body = body.rstrip() + "\n"
    json_line = json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    block = f"{META_START}\n{json_line}\n{META_END}\n"
    return f"{body}\n{block}"


def update_meta(content: str, **changes: Any) -> str:
    """Return the page with the metadata block updated (keys in `changes` overwrite existing keys)."""
    meta = parse(content)
    meta.update(changes)
    body = strip_meta_block(content)
    return render(meta, body)


def split(content: str) -> tuple[str, dict[str, Any]]:
    """Convenience: return (body_without_meta, meta_dict)."""
    return strip_meta_block(content), parse(content)


if __name__ == "__main__":
    sample = render(
        {"title": "Machine Learning", "slug": "machine-learning", "type": "concept"},
        "# Machine Learning\n\nA field of study.\n",
    )
    print(sample)
    print("---")
    print("parsed:", parse(sample))
    print("body:", repr(strip_meta_block(sample)))
