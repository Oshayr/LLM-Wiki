---
name: research
description: "Multi-channel web research — scan, deep-dive, academic, code, auto-loop. All findings saved to wiki automatically. Use when: 'research', 'look into', 'find out about', 'investigate', 'what is', 'how does X work', 'search the web for', 'deep dive', 'learn about', 'explore topic'."
---

# Research

Multi-channel parallel search → autonomous wiki ingest. All findings are saved to the wiki.

Find `.wiki/` by walking up from working directory. If not found, auto-create it.

## Arguments

- **`/research <topic>`** — alias for `/research scan <topic>`
- **`/research scan <topic>`** — parallel multi-channel search → auto wiki ingest
- **`/research academic <topic>`** — Semantic Scholar + arXiv → PDF download → wiki ingest
- **`/research code <topic|repo>`** — GitHub + npm/PyPI + Stack Overflow → wiki ingest
- **`/research deep-dive <topic>`** — generates program → runs 3 auto-iterations → comprehensive wiki coverage
- **`/research refresh <slug>`** — re-investigate stale wiki page with fresh sources
- **`/research cache stats`** — search cache hit rates and size
- **`/research cache clear`** — clear search cache

## Scan

Multi-channel parallel search → autonomous wiki ingest.

1. Launch `search-orchestrator` agent with topic → fans out to web/docs/code channels in parallel
2. Each channel checks search cache first (TTL: web=7d, docs=7d, code=3d)
3. Orchestrator deduplicates and ranks by credibility tier (or uses `bin/tools.py --cmd dedup` for token savings)
4. `bin/fetch.py` extracts full content from top results
5. `wiki-writer` agent (mode: ingest) writes source, entity, concept pages — no confirmation
6. Report: pages written, open questions added to `.wiki/overview.md`

## Academic

Academic-channel search → PDF download → wiki ingest.

1. Launch `search-channel` agent with `channel: academic`
2. Queries Semantic Scholar, arXiv, OpenAlex, CrossRef in parallel
3. Downloads top paper PDFs via `bin/search-academic.py download`
4. `wiki-writer` agent creates source pages with citation counts, abstract, key findings
5. Report: papers ingested, downloads in `.wiki/raw/papers/`

## Code

Code-channel search → GitHub + npm/PyPI + Stack Overflow → wiki ingest.

1. Launch `search-channel` agent with `channel: code`
2. Queries GitHub repos, npm/PyPI packages, Stack Overflow Q&A
3. `wiki-writer` agent creates entity pages per repo/package, concept pages for patterns
4. Report: repos ingested, comparison page slug

## Deep Dive

Generates research program → runs auto-iteration loop → comprehensive wiki coverage.

1. Generate `.wiki/raw/notes/program-<slug>.md` with seed questions and search strategy
2. Confirm program with user (show questions, estimated ~5-7 min)
3. Launch `research-loop` agent — up to 3 iterations of search → ingest → evaluate → commit/revert
4. Write deep-dive summary page: wiki coverage, confidence assessment, open questions
5. Report: questions answered, pages added, deep-dive page slug

## Refresh

Re-investigate stale wiki page with fresh sources.

1. Read the page, identify findings older than 30 days
2. For each stale finding, construct targeted search query
3. Launch `search-orchestrator` → `wiki-writer` focused on stale content only
4. Update page: mark confirmed findings as still-valid, replace outdated ones
5. Update `updated:` date in frontmatter

## Cache

- `/research cache stats` — reads `.wiki/cache/search.db` → `bin/cache.py stats`
- `/research cache clear` — `bin/cache.py clear` (confirms with user first)
