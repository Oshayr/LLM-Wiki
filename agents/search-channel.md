---
name: search-channel
description: "Parameterized search channel — web, academic, code, docs, or wikipedia. Returns normalized result arrays."
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

### wikipedia
1. Check search cache first: `python3 bin/cache.py check wikipedia "<query>"`
2. Use `python3 bin/search-wikipedia.py search "<query>" --top 5`
3. Optionally pass `--lang <code>` for non-English queries (e.g. `--lang de`)
4. Save results to cache: `python3 bin/cache.py store wikipedia "<query>" "<results_json>"`
5. Return normalized results: {title, url, snippet, source_type: "wikipedia", credibility_tier: 2, pageid, lang, extract}

Use for: factual/encyclopedic topics — history, science, biographies, concepts, geography, technology overviews.
Avoid for: very recent events (Wikipedia lags real-time), niche technical code questions.

### academic
1. Check search cache first: `python3 bin/cache.py check academic "<query>"`
2. Use `python3 bin/search-academic.py search "<query>" --top 5`
3. Optionally pass `--year-min` / `--year-max` for date filtering
4. Save results to cache: `python3 bin/cache.py store academic "<query>" "<results_json>"`
5. Return normalized results: {title, url, snippet, source_type: "academic", credibility_tier: 1, year, authors, doi}

Use for: research papers, scientific topics, formal publications, technical surveys.
Avoid for: recent news, code/libraries, general knowledge.

### code
1. Check search cache first: `python3 bin/cache.py check code "<query>"`
2. Use `python3 bin/search-code.py search "<query>" --top 5`
3. Optionally pass `--type repos|packages|qa|all` to narrow search
4. Save results to cache: `python3 bin/cache.py store code "<query>" "<results_json>"`
5. Return normalized results: {title, url, snippet, source_type: "code", credibility_tier, stars, language}

Use for: libraries, frameworks, code examples, package info, Stack Overflow Q&A.
Avoid for: academic papers, general knowledge, news.

## Cache TTLs
- web: 7 days
- academic: 30 days
- code: 3 days
- docs: 7 days
- wikipedia: 30 days

## Rules
- Always check cache before searching
- Return results as JSON array in the normalized format
- Assign credibility_tier based on source authority (1=high, 2=medium, 3=low)
- Maximum 10 results per channel per query
