"""
Custom exception hierarchy for llm-wiki-github.

All wiki-specific exceptions inherit from WikiError so callers can catch the
whole family with a single `except WikiError`.
"""


class WikiError(Exception):
    """Base exception for all wiki operations."""
    pass


# ── Fetch & Network ──────────────────────────────────────────────────────────

class FetchError(WikiError):
    """Failed to retrieve content from a URL."""
    def __init__(self, message: str, url: str = "", status_code: int = 0):
        self.url = url
        self.status_code = status_code
        super().__init__(message)


# ── Search ────────────────────────────────────────────────────────────────────

class SearchError(WikiError):
    """Search operation failed."""
    pass


# ── Wiki Data ─────────────────────────────────────────────────────────────────

class PageNotFoundError(WikiError):
    """Requested wiki page slug does not exist."""
    def __init__(self, slug: str):
        self.slug = slug
        super().__init__(f"Page not found: {slug}")


class FrontmatterError(WikiError):
    """Invalid or missing metadata in a wiki page."""
    def __init__(self, slug: str, field: str = "", message: str = ""):
        self.slug = slug
        self.field = field
        super().__init__(message or f"Bad metadata in {slug}" + (f": missing {field}" if field else ""))


# ── Git / Repo ────────────────────────────────────────────────────────────────

class GitError(WikiError):
    """A git subprocess failed."""
    pass


class WikiRepoError(WikiError):
    """A failure in the git-wiki I/O chokepoint. Carries a shell exit code hint."""
    def __init__(self, message: str, exit_code: int = 1):
        self.exit_code = exit_code
        super().__init__(message)


class WikiPushConflictError(WikiRepoError):
    """Push rejected — remote has advanced; caller should pull-rebase and retry."""
    def __init__(self, slug: str, message: str = ""):
        self.slug = slug
        super().__init__(message or f"Push conflict on {slug}", exit_code=1)


class WikiBootstrapRequired(WikiRepoError):
    """The GitHub Wiki for the target repo has not been initialized yet."""
    pass
