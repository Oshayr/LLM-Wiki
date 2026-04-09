---
name: maintain
description: "Wiki maintenance — lint broken links, merge near-duplicates, upgrade confidence, flag stale pages, gap analysis, concept synthesis. Use on: 'wiki maintenance', 'wiki cleanup', 'fix wiki', 'wiki health', 'check wiki', 'consolidate wiki'."
---

# Maintain

Comprehensive wiki maintenance: lint, deduplicate, upgrade, and analyze.

Find `.wiki/` by walking up from working directory. If not found, say "No wiki found."

## Arguments

- **`/maintain`** — run full maintenance (all steps below)
- **`/maintain lint`** — only fix broken links, missing frontmatter, orphans
- **`/maintain dedup`** — only find and merge near-duplicate pages
- **`/maintain gaps`** — only analyze knowledge gaps and missing coverage

## Full Maintenance Steps

### 1. Lint

Launch `wiki-auditor` agent to:
- Find `[[wiki-links]]` that point to non-existent pages — list for user
- Fix missing frontmatter fields (add defaults)
- Find orphan pages (no incoming links) — suggest connections
- Remove dead index entries
- Fix stale `updated:` dates on pages that were modified but not date-bumped

### 2. Deduplicate

Find pages with >60% slug token overlap (Jaccard similarity on slug words split by `-`):
- Report pairs for review
- For confirmed duplicates: auto-merge into one page, update all backlinks, add redirect note to absorbed page

### 3. Confidence Upgrade

Pages with 3+ independent sources in frontmatter get upgraded:
- `low` → `medium` (if 2+ sources)
- `medium` → `high` (if 3+ corroborating sources)
- Write the reason in log.md

### 4. Stale Detection

Pages with `updated:` date >90 days old:
- Add `stale: true` to frontmatter
- Suggest running `/research refresh <slug>` for fast-moving topics

### 5. Concept Auto-Generation

Detect patterns spanning 3+ pages:
- Find groups of pages that share 3+ common `[[wiki-links]]` targets
- For each cluster: suggest a synthesis article that connects the concepts
- If user approves: generate the synthesis page via `wiki-writer` agent

### 6. Regenerate Index

Rebuild `.wiki/index.md` from all pages:
- Group by `type:` field (concept, entity, source, idea, status, etc.)
- Alphabetical within each group
- Include confidence badge and one-line description

### 7. Report

Print summary: broken links fixed, duplicates found, confidence upgrades, stale flags, concepts suggested, index updated.
