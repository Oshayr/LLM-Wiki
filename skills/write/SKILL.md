---
name: write
description: "Add or update wiki content — autonomous ingest from URL, file, or text; update existing pages with diff preview. Auto-creates .wiki/ on first use. Use when: 'save to wiki', 'remember this', 'note this', 'store this', 'add to knowledge base', 'save findings', 'save research', 'save idea', 'write to wiki', 'ingest', 'add page', 'update page'."
---

# Write

Add or update content in the wiki. Auto-creates `.wiki/` if it doesn't exist.

Find the `.wiki/` directory by walking up from working directory. If not found, create it at project root (next to `.git/` if present, otherwise CWD).

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

- **`/write <url>`** — fetch and ingest a web page or paper
- **`/write <file-path>`** — ingest a local file (text, markdown, PDF)
- **`/write "text..."`** — ingest pasted text
- **`/write --batch <dir>`** — ingest all `.md` files in a directory
- **`/write --update <slug>`** — update an existing page (shows diff, requires confirmation)
- **`/write --update <slug> <url>`** — update page with content from URL
- **`/write --refresh-stale`** — find and refresh pages >90 days old on fast-moving topics

## Ingest (default — no `--update` flag)

Launch the `wiki-writer` agent with `mode: ingest`:
- Fetches content (via `bin/fetch.py` chain: cache → Jina → trafilatura → WebFetch)
- Saves raw source to `.wiki/raw/`
- Writes source summary page and entity/concept pages to `.wiki/pages/`
- Runs backlink audit via `bin/tools.py --cmd backlinks`
- Updates `.wiki/index.md`, `.wiki/overview.md`, `.wiki/log.md`
- **No confirmation pause** — runs end-to-end autonomously

Report: pages written, pages updated, confidence assigned.

## Update (`--update`)

Launch the `wiki-writer` agent with `mode: update`:
1. Reads current page
2. Generates proposed changes
3. **Shows diff and waits for confirmation** — updates are destructive
4. Checks downstream pages for impact
5. Runs contradiction sweep against high-confidence pages
6. Applies changes after confirmation
7. Updates index.md and log.md

## Refresh Stale (`--refresh-stale`)

Finds pages where `updated` >90 days old on fast-moving topics (`ai`, `llm`, `api`, `cloud`, `mcp`).
For each: searches for fresh sources → shows diff → waits for confirmation → updates.

## Batch (`--batch`)

Sequentially ingest each file in the directory. Report progress.
