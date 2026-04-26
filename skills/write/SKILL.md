---
name: wiki-write
description: "Add or update pages on the target project's GitHub Wiki — autonomous ingest from URL/file/text, autonomous update of existing pages. Use when: 'save to wiki', 'remember this', 'note this', 'store this', 'add to knowledge base', 'save findings', 'save research', 'save idea', 'write to wiki', 'ingest', 'add page', 'update page'."
---

# Wiki Write

Ingest content into the target repo's GitHub Wiki. Storage is the wiki itself — there is no local `.wiki/` directory; the plugin maintains a git clone under `${CLAUDE_PLUGIN_DATA}/wiki-cache/<owner>__<repo>/` behind the scenes.

## Auto-clone

On first use, the plugin auto-clones the target's GitHub Wiki (`<owner>/<repo>.wiki.git`). If the wiki has not been initialized on GitHub yet, the tool exits with code `10` and instructs you to create the first page in the browser at `https://github.com/<owner>/<repo>/wiki` — GitHub requires this one-time bootstrap via the web UI.

Target resolution (first match wins):
1. Env var `WIKI_GITHUB_TARGET=<owner>/<repo>`
2. `${CLAUDE_PLUGIN_DATA}/config.yaml` (`owner:` and `repo:`)
3. Autodetected from the current git repo's `origin` remote

## Arguments

- **`/wiki-write <url>`** — fetch and ingest a web page or paper
- **`/wiki-write <file-path>`** — ingest a local file (text, markdown, PDF)
- **`/wiki-write "text..."`** — ingest pasted text
- **`/wiki-write --batch <dir>`** — ingest all `.md` files in a directory
- **`/wiki-write --update <slug>`** — update an existing page autonomously
- **`/wiki-write --update <slug> <url>`** — update with content from URL
- **`/wiki-write --refresh-stale`** — find and refresh pages past their freshness tier TTL

## Ingest (default)

Launch the `wiki-writer` agent with `mode: ingest`:
- Fetches content via `bin/fetch.py` (Jina → trafilatura → WebFetch chain).
- Compiles a source-summary page and any entity/concept pages.
- Renders the HTML-comment metadata block via `frontmatter_fmt.render`.
- Rewrites `![[slug]]` transclusions to plain `[[slug]]` links (GitHub Wiki native).
- Pushes via `wiki_repo.write_page` — which pulls first, rebuilds `_Sidebar.md` / `_Footer.md`, commits with `Wiki-Agent:` / `Wiki-Page:` trailers, and pushes with rebase-on-conflict retry.
- **No confirmation pause** — runs end-to-end autonomously.

Report: pages written, pages updated, confidence assigned, commit SHAs, and public wiki URLs.

## Update (`--update`)

Launch `wiki-writer` with `mode: update`:
1. Reads current page via `wiki_repo.read_page`.
2. Generates proposed changes.
3. Runs a contradiction sweep against other high-confidence pages.
4. Bumps `updated` metadata and writes back via `wiki_repo.write_page` — same autonomous push.

## Refresh Stale (`--refresh-stale`)

Finds pages past their freshness tier TTL (see `/wiki-maintain` for tiers). For each, searches for fresh sources and applies an update autonomously.

## Batch (`--batch`)

Sequentially ingests each `.md` file in the directory. Reports progress after each push.

## Custom Page Types

Custom page templates ship with the plugin under `${CLAUDE_PLUGIN_ROOT}/templates/`. To add a template, drop a `.md` file into that directory with placeholder content (e.g. `{{title}}`, `{{date}}`, `{{created}}`, `{{updated}}`) — ingest uses it as the page skeleton when the caller requests `type: <template-name>`.

## Authentication

Push uses your system `git` credentials:
- If you've authenticated with `gh auth login`, the git credential helper picks it up transparently.
- Otherwise configure an HTTPS token or SSH key for `github.com` as you would for any other repo.

No `GITHUB_TOKEN` env var is required.
