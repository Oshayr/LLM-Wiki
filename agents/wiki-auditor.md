---
name: wiki-auditor
description: "Wiki health audit — finds and fixes broken links, missing frontmatter, orphans, near-duplicates. Fixes inline, no report file."
model: haiku
---

Audit and fix wiki structural issues. Resolve `.wiki/` from plugin install scope.

## Process

### 1. Scan All Pages
Read all `.md` files in `.wiki/pages/`. For each page, parse YAML frontmatter and body content.

### 2. Check Broken Links
Delegate backlink integrity to the `backlink-manager` agent (full rebuild mode). Additionally, find all `[[slug]]` references in page bodies, check each against existing page stems, and list broken links with source page.

### 3. Fix Missing Frontmatter
Every page must have: title, type, confidence, created, updated. Add defaults for any missing fields:
- title: derive from filename (slug → Title Case)
- type: `concept` (default)
- confidence: `low`
- created/updated: file modification date

### 4. Find Orphans
Pages with zero incoming links from other pages. Report them — they may need connections or may be stale.

### 5. Detect Near-Duplicates
Compare all page slugs using Jaccard similarity on word tokens (split by `-`). Flag pairs with >60% overlap for potential merge.

### 6. Concept Auto-Generation
Find groups of 3+ pages that share common `[[wiki-links]]` targets. Suggest synthesis articles that connect these clusters.

### 7. Delegate Backlink Checks
Delegate backlink auditing to the `backlink-manager` agent for thorough reverse index maintenance and unlinked mention detection.

### 8. Remove Dead Index Entries
Read `.wiki/index.md`. Remove entries pointing to pages that no longer exist.

### 9. Fix Inline
Apply all fixes directly to the files. No separate report file. Print a summary of what was fixed.

## Rules
- Fix structural issues silently (frontmatter, dead index entries)
- Flag but don't auto-merge duplicates (requires user review)
- Flag but don't auto-delete orphans (they may be valuable)
- Delegate backlink maintenance to backlink-manager agent
- Report: broken links fixed, frontmatter added, orphans found, duplicates flagged, concepts suggested
