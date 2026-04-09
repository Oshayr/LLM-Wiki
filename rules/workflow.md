# LLM Wiki — Workflow Rules

## Ingest behavior
- Ingest is autonomous — never pause for user confirmation when creating new pages
- Update is autonomous — never pause for user confirmation when overwriting existing content
- Backlinks are mandatory — every new page must update related pages' `related:` field
- Contradictions are flagged, never silently overwritten — if new content conflicts with existing, note both views

## Quality standards
- Every page must have complete YAML frontmatter (title, type, confidence, sources, related, created, updated)
- Confidence tiers: low (single source or speculation), medium (2+ sources), high (3+ corroborating sources)
- Sources must include URLs where possible
- [[wiki-links]] connect concepts — aim for 3+ outgoing links per page

## Maintenance
- Run `/wiki-maintain` periodically to fix broken links, merge duplicates, upgrade confidence
- Stale pages (>90 days without update) get flagged
- Near-duplicate pages (>60% slug token overlap) get flagged for merge

## Auto-init
- If `.wiki/` doesn't exist when any wiki operation is needed, create it automatically:
  - `pages/` directory
  - `index.md` (empty index)
  - `log.md` (empty log)
  - `overview.md` (empty overview)
  - `SCHEMA.md` (evaluation rules)
  - `templates/` directory (for custom page type templates)
  - `cache/` directory
  - `raw/` directory with subdirs (assets, code, feeds, notes, papers, transcripts, web)

Custom page types are loaded from `.wiki/templates/<type-name>.md`. Users can define their own page types by placing template files in this directory.

## Path discovery
- Uses `.wiki/` in the current working directory (project root)
- Users can override with a custom path if needed
- No directory tree walking — uses default Claude Code data location
