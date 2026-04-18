---
name: wiki-maintain
description: "GitHub Wiki maintenance — broken links, missing metadata, near-duplicate merges, confidence upgrades, freshness-tier staleness, concept synthesis. Use on: 'wiki maintenance', 'wiki cleanup', 'fix wiki', 'wiki health', 'check wiki', 'consolidate wiki'."
---

# Wiki Maintain

Comprehensive maintenance of the target repo's GitHub Wiki: lint, deduplicate, upgrade confidence, flag stale pages, rebuild the sidebar.

All writes go through `bin/wiki_repo.py` — commits, sidebar rebuild, and push are handled there.

## Arguments

- **`/wiki-maintain`** — run every step below
- **`/wiki-maintain lint`** — only fix broken links, missing metadata, orphans
- **`/wiki-maintain dedup`** — only flag near-duplicate pages

## Full Maintenance Steps

### 1. Lint

Launch `wiki-auditor` to:
- Find `[[wiki-links]]` pointing to non-existent pages — report to user (no auto-stubs).
- Fix missing metadata fields (add defaults via `frontmatter_fmt.update_meta`).
- Find orphan pages (no incoming `[[links]]`) — report.
- Fix `updated:` on pages whose git commit date is newer than the metadata timestamp.

### 2. Deduplicate

Find pages with >60% slug token overlap (Jaccard on hyphen-split words):
- Report pairs for human review.
- Do NOT auto-merge — merge is a judgment call.

### 3. Confidence Upgrade

Pages with 3+ independent sources in their metadata:
- `low` → `medium` (≥2 sources)
- `medium` → `high` (≥3 corroborating sources)

Write the reason into the commit message on the upgrade.

### 4. Stale Detection (Freshness Tiers)

Pages are evaluated against an intelligent freshness system — not a flat threshold.

| Tier | TTL | Examples |
|------|-----|----------|
| `live` | 15 min | stock prices, live scores, server status |
| `breaking` | 1–6 hours | breaking news, incident updates |
| `current` | 1–3 days | news articles, current events |
| `fast` | 1–4 weeks | AI/LLM/MCP, API changes, model benchmarks |
| `moderate` | 1–3 months | software versions, frameworks, libraries |
| `standard` | 6 months | general knowledge, how-to guides (default) |
| `academic` | 1 year | research papers, studies, formal publications |
| `evergreen` | 5 years | history, biographies, foundational concepts |
| `permanent` | never | personal notes, ideas, journal entries |

Resolution order:
1. Explicit `freshness_tier:` in page metadata (user override).
2. Explicit `ttl:` in metadata (custom duration like `ttl: 30m` or `ttl: 2d`).
3. Auto-classification from tags, type, and content keywords.

For stale pages: set `stale: true` in metadata and suggest `/wiki-write --refresh-stale` or `/wiki-read` to refresh.

### 5. Concept Auto-Generation

Find groups of 3+ pages that share 3+ common `[[wiki-link]]` targets. For each cluster, suggest a synthesis article. If the user approves, hand off to `wiki-writer`.

### 6. Rebuild Sidebar

Call `wiki_repo.rebuild_sidebar()` to regenerate `_Sidebar.md` (grouped by `type`, alphabetical within each group) and `_Footer.md` (last-updated timestamp). Pushed as a single commit if anything changed.

### 7. Report

Print summary: broken links found, metadata filled, duplicates flagged, confidence upgrades, stale flags set, concepts suggested, sidebar rebuilt.
