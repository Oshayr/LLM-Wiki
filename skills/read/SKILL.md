---
name: wiki-read
description: "Search and query the target project's GitHub Wiki — cited answers, with automatic research when knowledge is missing. Three depth modes. Use when: 'check wiki', 'what do we know about', 'look up', 'find in wiki', 'search wiki', 'search for', 'find information about', 'do we have notes on', 'wiki context', 'existing knowledge', 'research', 'look into', 'find out about', 'investigate', 'what is', 'how does X work'."
---

# Wiki Read

Ask the target repo's GitHub Wiki a question and get a cited answer. If the wiki doesn't cover the topic, automatically researches via `WebSearch` / `WebFetch` (plus any MCP search tools), ingests the findings via `wiki-writer`, and answers from the new pages.

All reads go through `bin/wiki_repo.py` — the plugin maintains a local git clone under `${CLAUDE_PLUGIN_DATA}/wiki-cache/`, which is auto-pulled before any read.

## Arguments

- **`/wiki-read <question>`** — standard: search wiki first, research if needed, answer with citations
- **`/wiki-read quick <question>`** — sidebar/list scan only, no research fallback (fastest)
- **`/wiki-read deep <question>`** — full wiki search + broader multi-source research (most thorough)

## Process

Launch the `wiki-reader` agent with the question and depth level.

### Standard depth (default)
1. `wiki_repo.list_pages()` and `bin/search-fulltext.py` for ranked results.
2. Read the 2–4 most relevant pages via `wiki_read` / `wiki_repo.read_page`.
3. Synthesize a cited answer with `[[slug]]` references.
4. **If not found or insufficient**: research inline using whatever tools are available:
   - `WebSearch`, `WebFetch`, any MCP search tools (Perplexity, Exa, Tavily, etc.).
   - `bin/fetch.py` for content extraction.
   - Hand findings to `wiki-writer` (mode: `ingest`) to push new pages to the GitHub Wiki.
   - Answer from the newly created pages with `[[slug]]` citations.
   - Note: "Researched fresh and saved to the wiki."
5. Offer to save the synthesis as a wiki page if the answer is substantial.

### Quick depth
- Read `_Sidebar.md` / `wiki_repo.list_pages()` only.
- Text-match candidate slugs/titles.
- Return: list of relevant pages with one-line descriptions. No page content read, no research fallback — fastest response.
- If not found, suggest running standard `/wiki-read`.

### Deep depth
Standard plus:
- Broader multi-source web research (iterative `WebSearch` + `WebFetch`).
- Cross-reference multiple sources.
- Uses more context but gives higher-confidence answers.

## Tool Discovery

This skill works with **whatever tools the user has configured**. No hardcoded channels.
- `WebSearch` / `WebFetch` — built-in.
- `bin/fetch.py` — extraction chain (Jina → trafilatura → WebFetch).
- Any MCP search tools present at runtime.
- Used opportunistically — `wiki-reader` picks whichever is available.

## Bootstrap error

If the wiki repo has not been initialized on GitHub yet, the tool exits with code 10 and prompts you to create the first page at `https://github.com/<owner>/<repo>/wiki` in the browser.
