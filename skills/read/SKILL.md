---
name: wiki-read
description: "Search the wiki and get cited answers — with automatic research fallback using whatever tools are available. Three depth levels. Use when: 'check wiki', 'what do we know about', 'look up', 'find in wiki', 'search wiki', 'search for', 'find information about', 'do we have notes on', 'wiki context', 'existing knowledge', 'research', 'look into', 'find out about', 'investigate', 'what is', 'how does X work', 'deep dive', 'learn about', 'explore topic'."
---

# Wiki Read

Ask the wiki a question. Get a cited answer from existing knowledge — or research it fresh using whatever tools are available.

Resolve `.wiki/` from plugin install scope (user-level → `~/.wiki/`, project-level → project root). If not found, say "No wiki found. Use `/wiki-write` to create one."

## Arguments

- **`/wiki-read <question>`** — standard query with research fallback (default)
- **`/wiki-read quick <question>`** — index scan only (fastest, no page reads, no research)
- **`/wiki-read deep <question>`** — full search + raw sources + multi-round research (most thorough)

## Process

Launch the `wiki-reader` agent with the question and depth level.

### Quick depth
- Read `.wiki/index.md` only
- Scan for matching slugs/titles by text match
- Return: list of relevant pages with one-line descriptions
- No page content read, no research fallback — fastest possible response
- If nothing found: suggest running `/wiki-read <question>` (standard) for research

### Standard depth (default)
1. Read `.wiki/index.md`
2. Identify 2-4 relevant pages by title/tag match
3. Use `bin/search-fulltext.py` for ranked results
4. Read the relevant pages
5. Synthesize a cited answer with `[[slug]]` references

**Research fallback**: If <2 relevant pages found or the answer is insufficient:
1. Inform user: "Wiki doesn't cover this yet. Researching now..."
2. Use whatever search/fetch tools are available (WebSearch, WebFetch, MCP tools, etc.)
3. Ingest results via `wiki-writer` agent (mode: ingest) — autonomous, no confirmation
4. Re-read the newly ingested pages
5. Present the answer noting: "Researched fresh and saved to the wiki."

### Deep depth
Everything in standard, plus:
- Search `.wiki/raw/` for source materials matching the query
- Cross-reference raw sources with compiled pages
- If gaps exist between raw and compiled knowledge: trigger research to fill them
- Use all available tools iteratively — multiple search rounds if needed
- Launch `search-orchestrator` agent for multi-channel parallel search when the topic is complex
- Most thorough — uses the most context

## Tool Discovery

This skill works with **whatever tools the user has**. No hardcoded channels or services.

Available tools are discovered at runtime:
- `WebSearch` / `WebFetch` — Claude Code built-in web search and fetch
- Any MCP search tools (Perplexity, Exa, Tavily, etc.)
- `bin/search-academic.py` — Semantic Scholar, arXiv, OpenAlex, CrossRef (if available)
- `bin/search-code.py` — GitHub, npm, PyPI, Stack Overflow (if available)
- `bin/fetch.py` — content extraction chain

The skill uses whatever is available — if the user has Perplexity MCP, it gets used. If they only have WebSearch, that works too.
