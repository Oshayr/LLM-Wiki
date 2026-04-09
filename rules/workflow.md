# LLM Wiki — Workflow Rules

## Ingest behavior
- Ingest is autonomous — never pause for user confirmation when creating new pages
- Update is autonomous — applies changes directly, same as ingest. No confirmation needed.
- Backlinks are mandatory — every new page must update related pages' `related:` field
- Contradictions are flagged, never silently overwritten — if new content conflicts with existing, note both views

## Quality standards
- Every page must have complete YAML frontmatter (title, type, confidence, sources, related, created, updated)
- Confidence tiers: low (single source or speculation), medium (2+ sources), high (3+ corroborating sources)
- Sources must include URLs where possible
- [[wiki-links]] connect concepts — aim for 3+ outgoing links per page

## Maintenance
- Run `/wiki-maintain` periodically to fix broken links, merge duplicates, upgrade confidence
- Stale pages are flagged based on their freshness tier:
  - **live** (15 min): stock prices, server status, deployment state
  - **breaking** (1-6 hours): breaking news, incident updates, release announcements
  - **current** (1-3 days): news articles, current events, trending topics
  - **fast** (1-4 weeks): AI/LLM/MCP, API changes, model benchmarks
  - **moderate** (1-3 months): software versions, frameworks, libraries
  - **standard** (6 months): general knowledge, how-to guides (default)
  - **academic** (1 year): research papers, studies, publications
  - **evergreen** (5 years): history, foundational concepts, laws, theorems
  - **permanent** (never): personal notes, ideas, memories, journal entries
  - Resolution: explicit `freshness_tier:` frontmatter > explicit `ttl:` > auto-classification from tags/type/content
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
- `.wiki/` location follows the plugin install scope:
  - **User-level install** (`~/.claude/plugins/llm-wiki`) → `.wiki/` at `~/.wiki/`
  - **Project-level install** (`.claude/plugins/llm-wiki`) → `.wiki/` at project root (next to `.git/`)
- Resolved from `${PLUGIN_ROOT}` — if under home `~/.claude/`, use `~/.wiki/`; otherwise use project root
- If `.wiki/` doesn't exist when a write operation is needed, create it at the resolved location
