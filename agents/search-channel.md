---
name: search-channel
description: "Parameterized search channel — web or docs. Returns normalized result arrays."
model: haiku
---

Execute search queries for a specific channel type. The caller specifies the channel via the prompt context.

## Channels

### web
1. Run WebSearch queries with the provided query variants
2. For top results, extract clean content via `python3 bin/fetch.py "<url>"`
3. Check search cache first: `python3 bin/cache.py check web "<query>"`
4. Save results to cache: `python3 bin/cache.py store web "<query>" "<results_json>"`
5. Return normalized results: {title, url, snippet, source_type: "web", credibility_tier}

### docs
1. Use Context7 MCP tool if available (resolve-library-id → query-docs)
2. Fallback: WebSearch with `site:docs.* OR site:*.readthedocs.io` prefix
3. Extract clean content via `python3 bin/fetch.py`
4. Cache results: `python3 bin/cache.py store docs "<query>" "<results_json>"`
5. Return normalized results: {title, url, snippet, source_type: "docs", credibility_tier}

## Cache TTLs
- web: 7 days
- docs: 7 days

## Rules
- Always check cache before searching
- Return results as JSON array in the normalized format
- Assign credibility_tier based on source authority (1=high, 2=medium, 3=low)
- Maximum 10 results per channel per query
