---
name: wiki-write
description: "Add or update wiki content — autonomous ingest from URL, file, or text; autonomous update of existing pages. Auto-creates .wiki/ on first use. Use when: 'save to wiki', 'remember this', 'note this', 'store this', 'add to knowledge base', 'save findings', 'save research', 'save idea', 'write to wiki', 'ingest', 'add page', 'update page'."
---

# Wiki Write

Add or update content in the wiki. Auto-creates `.wiki/` if it doesn't exist.

Resolve `.wiki/` from plugin install scope. Auto-create if missing.

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
- **`/wiki-write --update <slug>`** — update an existing page autonomously
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
3. Runs contradiction sweep against high-confidence pages
4. Applies changes directly — same autonomous behavior as ingest
5. Updates index.md and log.md

## Refresh Stale (`--refresh-stale`)

Finds pages past their freshness tier TTL (see freshness tiers in `/wiki-maintain`).
For each: searches for fresh sources → applies updates autonomously.

## Batch (`--batch`)

Sequentially ingest each file in the directory. Report progress.

## Custom Page Types

Users can define custom page types by creating template files in `.wiki/templates/`. Each template is a markdown file with YAML frontmatter that defines default fields and placeholder content.

**Creating a custom page type:**

1. Create a file in `.wiki/templates/<type-name>.md`
2. Add YAML frontmatter with default fields (title, type, confidence, dates, custom fields)
3. Add markdown body content with placeholders (e.g., `{{title}}`, `{{date}}`)

**Using a custom page type:**

When using `/wiki-write` with `type: custom-type-name`, the write operation will:
- Look for `.wiki/templates/custom-type-name.md`
- Use the template's frontmatter and body as the page skeleton
- Replace placeholders with actual values (dates, title, etc.)
- Proceed with normal page creation

**Placeholder variables:**
- `{{title}}` — Page title
- `{{date}}` — Current date (YYYY-MM-DD)
- `{{created}}` — Creation timestamp (ISO 8601)
- `{{updated}}` — Update timestamp (ISO 8601)
