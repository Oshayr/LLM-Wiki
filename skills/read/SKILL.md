---
name: read
description: "Search and query the wiki — get cited answers from existing knowledge. Three depth levels. Use when: 'check wiki', 'what do we know about', 'look up', 'find in wiki', 'search wiki', 'search for', 'find information about', 'do we have notes on', 'wiki context', 'existing knowledge'."
---

# Read

Ask the wiki a question and get a cited answer from existing knowledge.

Find `.wiki/` by walking up from working directory. If not found, say "No wiki found. Use `/write` to create one."

## Arguments

- **`/read <question>`** — standard query (default depth)
- **`/read quick <question>`** — index scan only (fastest, no page reads)
- **`/read deep <question>`** — search articles + raw sources (most thorough)

## Process

Launch the `wiki-reader` agent with the question and depth level.

### Quick depth
- Read `.wiki/index.md` only
- Scan for matching slugs/titles by text match
- Return: list of relevant pages with one-line descriptions
- No page content read — fastest possible response

### Standard depth (default)
- Read `.wiki/index.md`
- Identify 2-4 relevant pages by title/tag match
- For >200 pages: use `bin/search-fulltext.py` for ranked results
- Read the relevant pages
- Synthesize a cited answer with `[[slug]]` references
- Offer to save analysis as a wiki page if the answer is substantial

### Deep depth
- Everything in standard, plus:
- Search `.wiki/raw/` for source materials matching the query
- Cross-reference raw sources with compiled pages
- Note any gaps between raw sources and compiled knowledge
- Most thorough — uses the most context
