---
name: wiki-write
description: "Add or update wiki content — autonomous ingest from URL, file, or text; update existing pages. Auto-creates .wiki/ on first use. Use when: 'save to wiki', 'remember this', 'note this', 'store this', 'add to knowledge base', 'save findings', 'save research', 'save idea', 'write to wiki', 'ingest', 'add page', 'update page'."
---

# Wiki Write

Add or update content in the wiki. Auto-creates `.wiki/` if it doesn't exist.

Resolve `.wiki/` from plugin install scope (user-level → `~/.wiki/`, project-level → project root). Auto-create if missing.

## Auto-Init

If `.wiki/` doesn't exist, create it automatically before proceeding:

```
.wiki/
  pages/
  index.md        (empty: "# Wiki Index\n\nNo pages yet.\n")
  overview.md     (empty: "# Overview\n\nNo content yet.\n")
  log.md          (empty: "# Activity Log\n")
  SCHEMA.md       (evaluation rules — see below)
  config.yaml     (empty)
  cache/
  raw/
    web/ papers/ notes/ transcripts/ code/ feeds/ assets/
```

## Arguments

- **`/wiki-write <url>`** — fetch and ingest a web page or paper
- **`/wiki-write <file-path>`** — ingest a local file (text, markdown, PDF)
- **`/wiki-write "text..."`** — ingest pasted text
- **`/wiki-write --batch <dir>`** — ingest all `.md` files in a directory
- **`/wiki-write --update <slug>`** — update an existing page
- **`/wiki-write --update <slug> <url>`** — update page with content from URL
- **`/wiki-write --refresh-stale`** — find and refresh stale pages based on freshness tier

## Ingest (default — no `--update` flag)

Launch the `wiki-writer` agent with `mode: ingest`:
- Fetches content (via `bin/fetch.py` chain: cache → Jina → trafilatura → WebFetch)
- Saves raw source to `.wiki/raw/`
- Writes source summary page and entity/concept pages to `.wiki/pages/`
- Runs backlink audit via `bin/backlinks.py update .wiki/pages`
- Updates `.wiki/index.md`, `.wiki/overview.md`, `.wiki/log.md`
- **No confirmation pause** — runs end-to-end autonomously

Report: pages written, pages updated, confidence assigned.

## Update (`--update`)

Launch the `wiki-writer` agent with `mode: update`:
1. Reads current page
2. Generates proposed changes
3. Checks downstream pages for impact
4. Runs contradiction sweep against high-confidence pages
5. Applies changes directly — autonomous, same as ingest
6. Updates index.md and log.md

## Refresh Stale (`--refresh-stale`)

Finds stale pages based on their freshness tier (see Freshness Tiers in workflow rules).
For each: searches for fresh sources → applies updates autonomously.

## Batch (`--batch`)

Sequentially ingest each file in the directory. Report progress.
