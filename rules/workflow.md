# llm-wiki-github — Workflow Rules

## Ingest behavior
- Ingest is autonomous — never pause for user confirmation when creating new pages.
- Update is autonomous — applies changes directly, same as ingest.
- `[[wiki-links]]` are native GitHub Wiki links; the plugin doesn't maintain a separate backlink index. GitHub renders the graph itself.
- Contradictions are flagged, never silently overwritten — if new content conflicts with existing, both views are kept with sources.

## Quality standards
- Every page has an HTML-comment metadata block (see `bin/frontmatter_fmt.py`) with `title`, `slug`, `type`, `confidence`, `sources`, `related`, `created`, `updated`, plus optional `tags`, `freshness_tier`, `has_contradictions`, `stale`.
- Confidence tiers: low (single source or speculation), medium (2+ sources), high (3+ corroborating sources).
- Sources must include URLs where possible.
- `[[wiki-links]]` connect concepts — aim for 3+ outgoing links per page.

## Freshness tiers

Pages have a content-aware TTL rather than a flat threshold:

| Tier | TTL | Examples |
|------|-----|----------|
| `live` | 15 min | stock prices, live scores, server status, deployment state |
| `breaking` | 1–6 hours | breaking news, incident updates, release announcements |
| `current` | 1–3 days | news articles, current events, trending topics |
| `fast` | 1–4 weeks | AI/LLM/MCP, API changes, model benchmarks |
| `moderate` | 1–3 months | software versions, frameworks, libraries, tools |
| `standard` | 6 months | general knowledge, how-to guides (default) |
| `academic` | 1 year | research papers, studies, formal publications |
| `evergreen` | 5 years | history, biographies, foundational concepts, laws, theorems |
| `permanent` | never | personal notes, ideas, memories, journal entries |

Resolution: explicit `freshness_tier:` > explicit `ttl:` > auto-classification from tags/type/content.

## Maintenance
- Run `/wiki-maintain` periodically to fix broken links, flag duplicates, upgrade confidence, rebuild `_Sidebar.md`.
- Stale pages (past their freshness tier TTL) get flagged with `stale: true` in metadata.
- Near-duplicate pages (>60% slug token overlap) get flagged for human merge review.

## Repo targeting

The plugin determines which GitHub Wiki to read/write using the following precedence:

1. **Env var** `LLM_WIKI_TARGET=<owner>/<repo>` (highest priority — useful for scripting against a specific wiki).
2. **Config file** `${CLAUDE_PLUGIN_DATA}/config.yaml` with `owner:` and `repo:` keys.
3. **Autodetect** from the current working directory — parse `git remote get-url origin`, walking up to ancestor `.git/` directories if needed.

If none resolves, `wiki_repo` exits with code `12` and a message explaining how to configure the target.

## Clone & sync

On first use, the plugin clones `<owner>/<repo>.wiki.git` into `${CLAUDE_PLUGIN_DATA}/wiki-cache/<owner>__<repo>/`. Subsequent operations reuse the same clone.

- Reads call `pull_if_stale(ttl=300)` — pulls from origin if >5 min has passed since the last pull.
- Writes always pull first (ff-only, falling back to `fetch + reset --hard origin/<branch>` on non-ff), then write, commit with trailers, and push.
- Push conflicts (remote advanced mid-write) trigger automatic pull-rebase + retry up to 3 times with exponential backoff (1s, 2s, 4s).
- Exit codes: `10` wiki-not-initialized on GitHub, `11` network failure, `12` no-target-configured, `13` auth failure.

## Commit attribution

Every commit pushed by the plugin includes two git trailers for auditability:

```
<Commit subject>

Wiki-Agent: wiki-writer        # or wiki-auditor, mcp, etc.
Wiki-Page: <slug>
```

This makes it easy to grep history for "what did the wiki-writer agent do to page X".

## Bootstrap

GitHub requires the first page of a wiki to be created via the web UI before `git clone` works. If the user runs `/wiki-write` or `/wiki-read` before that, the plugin exits with code `10` and points them at `https://github.com/<owner>/<repo>/wiki` to do the one-time setup.
