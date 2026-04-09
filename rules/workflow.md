# LLM Wiki — Workflow Rules

## Ingest behavior
- Ingest is autonomous — never pause for user confirmation when creating new pages
- Update is autonomous — applies changes directly, same as ingest
- Backlinks are mandatory — every new page must update related pages' `related:` field
- Contradictions are flagged, never silently overwritten — if new content conflicts with existing, note both views

## Quality standards
- Every page must have complete YAML frontmatter (title, type, confidence, sources, related, created, updated)
- Confidence tiers: low (single source or speculation), medium (2+ sources), high (3+ corroborating sources)
- Sources must include URLs where possible
- [[wiki-links]] connect concepts — aim for 3+ outgoing links per page

## Freshness tiers

Pages have a content-aware TTL rather than a flat threshold:

| Tier | TTL | Examples |
|------|-----|----------|
| `live` | 15 min | stock prices, live scores, server status, deployment state |
| `breaking` | 1-6 hours | breaking news, incident updates, release announcements |
| `current` | 1-3 days | news articles, current events, trending topics |
| `fast` | 1-4 weeks | AI/LLM/MCP, API changes, model benchmarks |
| `moderate` | 1-3 months | software versions, frameworks, libraries, tools |
| `standard` | 6 months | general knowledge, how-to guides (default) |
| `academic` | 1 year | research papers, studies, formal publications |
| `evergreen` | 5 years | history, biographies, foundational concepts, laws, theorems |
| `permanent` | never | personal notes, ideas, memories, journal entries |

Resolution: explicit `freshness_tier:` > explicit `ttl:` > auto-classification from tags/type/content.

## Maintenance
- Run `/wiki-maintain` periodically to fix broken links, merge duplicates, upgrade confidence
- Stale pages (past their freshness tier TTL) get flagged
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
- Resolve `.wiki/` location from the plugin's install scope:
  - Plugin installed at **user level** (`~/.claude/plugins/llm-wiki`) → `.wiki/` at `~/.wiki/`
  - Plugin installed at **project level** (`.claude/plugins/llm-wiki`) → `.wiki/` at project root (next to `.git/`)
- The path is derived from `${PLUGIN_ROOT}` — if it's under `~/.claude/`, it's user-level; if it's under the project dir, it's project-level
- No walking up directories, no hardcoded paths
