# LLM Wiki — Workflow Rules

## Ingest behavior
- Ingest is autonomous — never pause for user confirmation when creating new pages
- Update is cautious — always show diff and wait for confirmation before overwriting existing content
- Backlinks are mandatory — every new page must update related pages' `related:` field
- Contradictions are flagged, never silently overwritten — if new content conflicts with existing, note both views

## Quality standards
- Every page must have complete YAML frontmatter (title, type, confidence, sources, related, created, updated)
- Confidence tiers: low (single source or speculation), medium (2+ sources), high (3+ corroborating sources)
- Sources must include URLs where possible
- [[wiki-links]] connect concepts — aim for 3+ outgoing links per page

## Maintenance
- Run `/maintain` periodically to fix broken links, merge duplicates, upgrade confidence
- Stale pages (>90 days without update) get flagged
- Near-duplicate pages (>60% slug token overlap) get flagged for merge

## Auto-init
- If `.wiki/` doesn't exist when any wiki operation is needed, create it automatically:
  - `pages/` directory
  - `index.md` (empty index)
  - `log.md` (empty log)
  - `overview.md` (empty overview)
  - `SCHEMA.md` (evaluation rules)
  - `cache/` directory
  - `raw/` directory with subdirs (assets, code, feeds, notes, papers, transcripts, web)

## Path discovery
- Find `.wiki/` by walking up from working directory (like git finds `.git/`)
- If not found anywhere, create at project root (where `.git/` lives, or CWD)
