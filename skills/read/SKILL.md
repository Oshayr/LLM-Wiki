---
name: wiki-read
description: "Search and query the wiki — get cited answers from existing knowledge. Three depth levels. Use when: 'check wiki', 'what do we know about', 'look up', 'find in wiki', 'search wiki', 'search for', 'find information about', 'do we have notes on', 'wiki context', 'existing knowledge'."
---

# Wiki Read

Ask the wiki a question and get a cited answer. If the wiki doesn't have the answer, automatically researches using whatever tools are available, ingests the results, and answers from the new pages.

Uses `.wiki/` in the current working directory. Location can be overridden by the user. If not found, say "No wiki found. Use `/wiki-write` to create one."

## Arguments

- **`/wiki-read <question>`** — standard query (default depth)
- **`/wiki-read quick <question>`** — index scan only (fastest, no page reads)
- **`/wiki-read deep <question>`** — search articles + raw sources (most thorough)

## Process

Launch the `wiki-reader` agent with the question and depth level.

### Standard depth (default)
1. Read `.wiki/index.md`, identify 2-4 relevant pages
2. For >200 pages: use `bin/search-fulltext.py` for ranked results
3. Read the relevant pages, synthesize a cited answer with `[[slug]]` references
4. **If NOT found or insufficient**: automatically research using whatever tools are available:
   - Discover available tools at runtime (WebSearch, WebFetch, `wiki_wikipedia_search` for factual/encyclopedic topics, any MCP tools like Perplexity, Context7, etc.)
   - Search using available tools, fetch and extract content
   - Ingest results via `wiki-writer` agent (mode: ingest)
   - Answer from the newly created pages with `[[slug]]` citations
   - Note: "Researched fresh and saved to wiki."
5. Offer to save analysis as a wiki page if the answer is substantial

### Quick depth
- Read `.wiki/index.md` only
- Scan for matching slugs/titles by text match
- Return: list of relevant pages with one-line descriptions
- No page content read — fastest possible response

### Standard depth (default)
- Read `.wiki/index.md`
- Identify 2-4 relevant pages by title/tag match
- Use `bin/search-fulltext.py` for ranked results
- Read the relevant pages
- Synthesize a cited answer with `[[slug]]` references
- Offer to save analysis as a wiki page if the answer is substantial

### Deep depth
- Everything in standard, plus:
- Search `.wiki/raw/` for source materials matching the query
- Cross-reference raw sources with compiled pages
- Use all available tools iteratively for multi-channel research if needed
- Most thorough — uses the most context
