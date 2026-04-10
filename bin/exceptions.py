"""
Custom exception hierarchy for LLM-Wiki.

All wiki-specific exceptions inherit from WikiError so callers can
catch the whole family with a single `except WikiError`.

Usage:
    from exceptions import FetchError, CacheError, SearchError

    try:
        content = fetch_url(url)
    except FetchError as e:
        logger.error("Fetch failed", extra={"url": e.url, "reason": str(e)})
"""


class WikiError(Exception):
    """Base exception for all LLM-Wiki operations."""
    pass


# ── Fetch & Network ──────────────────────────────────────────────────────────

class FetchError(WikiError):
    """Failed to retrieve content from a URL."""
    def __init__(self, message: str, url: str = "", status_code: int = 0):
        self.url = url
        self.status_code = status_code
        super().__init__(message)


class CircuitOpenError(WikiError):
    """Call rejected because the circuit breaker is open for this endpoint."""
    def __init__(self, endpoint: str, retry_after: float = 0):
        self.endpoint = endpoint
        self.retry_after = retry_after
        super().__init__(f"Circuit open for {endpoint}, retry after {retry_after:.0f}s")


# ── Cache ─────────────────────────────────────────────────────────────────────

class CacheError(WikiError):
    """Cache read/write failure."""
    pass


class CacheMissError(CacheError):
    """Requested key not found in cache."""
    def __init__(self, key: str, layer: str = ""):
        self.key = key
        self.layer = layer
        super().__init__(f"Cache miss: {key}" + (f" (layer={layer})" if layer else ""))


# ── Search ────────────────────────────────────────────────────────────────────

class SearchError(WikiError):
    """Search operation failed."""
    pass


class IndexError(SearchError):
    """Search index is missing or corrupt."""
    pass


# ── Wiki Data ─────────────────────────────────────────────────────────────────

class WikiNotFoundError(WikiError):
    """No .wiki/ directory found at the expected location."""
    pass


class PageNotFoundError(WikiError):
    """Requested wiki page slug does not exist."""
    def __init__(self, slug: str):
        self.slug = slug
        super().__init__(f"Page not found: {slug}")


class PageConflictError(WikiError):
    """Write conflict — page was modified concurrently."""
    def __init__(self, slug: str, message: str = ""):
        self.slug = slug
        super().__init__(message or f"Write conflict on {slug}")


class FrontmatterError(WikiError):
    """Invalid or missing YAML frontmatter in a wiki page."""
    def __init__(self, slug: str, field: str = "", message: str = ""):
        self.slug = slug
        self.field = field
        super().__init__(message or f"Bad frontmatter in {slug}" + (f": missing {field}" if field else ""))


# ── Research ──────────────────────────────────────────────────────────────────

class ResearchError(WikiError):
    """Research pipeline failure."""
    pass


class RateLimitError(ResearchError):
    """External API rate limit exceeded."""
    def __init__(self, service: str, retry_after: float = 0):
        self.service = service
        self.retry_after = retry_after
        super().__init__(f"Rate limited by {service}" + (f", retry after {retry_after}s" if retry_after else ""))


class ProviderUnavailableError(ResearchError):
    """External research provider is down or unreachable."""
    def __init__(self, provider: str, reason: str = ""):
        self.provider = provider
        super().__init__(f"{provider} unavailable" + (f": {reason}" if reason else ""))


# ── Git ───────────────────────────────────────────────────────────────────────

class GitError(WikiError):
    """Git operation failed."""
    pass
