"""slug_title.py — Deterministic conversion between wiki slugs, titles, and GitHub Wiki filenames.

GitHub Wiki filename convention:
    "Machine Learning"        ->  "Machine-Learning.md"
    "API and Architecture"    ->  "API-and-Architecture.md"     (stopwords stay lowercase)
    "what-is-this"            ->  "What-Is-This.md"

A "slug" is the lowercase-hyphenated identifier used inside [[wiki-links]] and in
page metadata (e.g. "machine-learning"). The slug is the canonical identifier.
The filename is a rendering of the slug for GitHub Wiki; the title is for humans.
"""

from __future__ import annotations

import re


STOPWORDS = {
    "a", "an", "and", "the",
    "or", "of", "in", "on", "to", "with", "for", "at", "by", "from", "as",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def title_to_slug(title: str) -> str:
    """Normalize a human title to a lowercase-hyphen slug.

    >>> title_to_slug("Machine Learning")
    'machine-learning'
    >>> title_to_slug("API and Architecture!")
    'api-and-architecture'
    """
    s = title.strip().lower()
    s = _SLUG_RE.sub("-", s)
    return s.strip("-")


def slug_to_title(slug: str) -> str:
    """Convert a slug to a Title Case title, preserving stopwords as lowercase.

    >>> slug_to_title("machine-learning")
    'Machine Learning'
    >>> slug_to_title("api-and-architecture")
    'API and Architecture'
    """
    words = slug.split("-")
    if not words:
        return ""
    out = []
    for i, w in enumerate(words):
        if not w:
            continue
        if i > 0 and w in STOPWORDS:
            out.append(w)
        elif w.isupper() or (len(w) <= 4 and w.upper() == w.lower().upper() and w.isalpha() and w == w.lower() and _looks_like_acronym(w)):
            out.append(w.upper())
        else:
            out.append(w[0].upper() + w[1:])
    return " ".join(out)


def _looks_like_acronym(word: str) -> bool:
    return word.lower() in {"api", "url", "ui", "html", "css", "js", "ml", "ai", "sql", "cli", "cpu", "gpu", "ram", "rss", "mcp", "llm", "http", "json", "yaml", "csv"}


def slug_to_filename(slug: str) -> str:
    """Convert a slug to a GitHub Wiki filename (Title-Case-Hyphens.md).

    Stopwords stay lowercase after the first word.

    >>> slug_to_filename("machine-learning")
    'Machine-Learning.md'
    >>> slug_to_filename("api-and-architecture")
    'API-and-Architecture.md'
    """
    words = slug.split("-")
    if not words:
        raise ValueError("Empty slug")
    out = []
    for i, w in enumerate(words):
        if not w:
            continue
        if i > 0 and w in STOPWORDS:
            out.append(w)
        elif _looks_like_acronym(w):
            out.append(w.upper())
        else:
            out.append(w[0].upper() + w[1:])
    return "-".join(out) + ".md"


def filename_to_slug(filename: str) -> str:
    """Convert a GitHub Wiki filename back to a slug.

    >>> filename_to_slug("Machine-Learning.md")
    'machine-learning'
    >>> filename_to_slug("API-and-Architecture.md")
    'api-and-architecture'
    """
    stem = filename[:-3] if filename.endswith(".md") else filename
    return stem.lower()


def slug_to_wiki_url(owner: str, repo: str, slug: str) -> str:
    """Return the canonical GitHub Wiki URL for a page.

    >>> slug_to_wiki_url("octocat", "hello", "machine-learning")
    'https://github.com/octocat/hello/wiki/Machine-Learning'
    """
    stem = slug_to_filename(slug)[:-3]
    return f"https://github.com/{owner}/{repo}/wiki/{stem}"


if __name__ == "__main__":
    import doctest
    doctest.testmod(verbose=True)
