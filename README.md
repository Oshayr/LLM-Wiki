# llm-wiki

LLM-powered personal wiki for [Claude Code](https://claude.ai/claude-code) — an autonomous knowledge base with full-text search, multi-channel research, spaced repetition, knowledge graph visualization, and a Wikipedia-style web UI.

**An autonomous knowledge base that grows as you work.** LLM Wiki is a [Claude Code](https://claude.ai/claude-code) plugin that captures research, ideas, and decisions into an interlinked wiki with semantic search, automatic research, and a Wikipedia-style web UI. Knowledge compounds over time — the more you use it, the smarter it gets.

Inspired by [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): raw sources are immutable, the LLM maintains the wiki layer, and a schema governs behavior.

## Features

**Knowledge Management**
- Automatic knowledge capture — saves research, ideas, decisions, and findings to the wiki
- Smart retrieval — checks the wiki before web search, grounds answers in existing knowledge
- TF-IDF full-text search with title/paragraph boosts and snippet extraction
- Block references and transclusion — `[[page#heading]]` links and `![[page#section]]` embeds
- Backlinks panel with unlinked mention detection
- Custom page types via `.wiki/templates/` — users can define their own page structures
- Frontmatter query language (Dataview-like) — query your wiki like a database

**Research Engine**
- Web search via Claude's built-in tools
- Autonomous research loops — iterative hypothesis-driven research with checkpoint-based rollback
- Research provenance tracking (W3C PROV-inspired) — every fact traces back to its source
- Fact-checking pipeline — extract claims, verify against external sources, track verification status
- Source credibility scoring with tiered ranking

### Web UI
- **Wikipedia-style browsable website** with 4 themes (light, dark, terminal, wikipedia)
- **Interactive knowledge graph** ([Cytoscape.js](https://js.cytoscape.org/)) with multiple layouts, clustering, and neighborhood highlighting
- **Canvas/whiteboard view** for spatial page arrangement
- **Split-pane markdown editor** with live preview and AI assist
- **Live research** — click any red link to auto-research the topic
- **Spaced repetition** review interface ([FSRS](https://github.com/open-spaced-repetition/fsrs4anki)-based scheduling)
- **Content gap analysis** dashboard
- **WebSocket chat** sidebar with RAG-augmented Q&A

  **Server Launch:** The web server runs only when explicitly invoked via `/wiki-serve` skill or manually via CLI:
  ```bash
  python .claude/plugins/llm-wiki/skills/serve/scripts/server.py --wiki-dir .wiki/ --port 8420
  ```

**Maintenance**
- Self-maintaining — lints broken links, merges duplicates, upgrades confidence, flags stale content
- Fact-checking pipeline integration via `/wiki-maintain fact-check`
- Daily notes and journal workflows
- Smart caching with adaptive TTL and stale-while-revalidate
- Circuit breakers for external API resilience
- Structured logging (JSON or text) via `wiki_logging.py` with custom exception hierarchy
- Activity logging with attribution and history tracking

## Quick Start

```bash
# Copy into your Claude Code plugins directory
cp -r llm-wiki .claude/plugins/

# Install dependencies
pip install -r .claude/plugins/llm-wiki/requirements.txt
```

The `.wiki/` data directory is created automatically on first use.

## Skills Reference

After installing, restart Claude Code. The plugin provides 6 slash commands (`/wiki-write`, `/wiki-read`, `/wiki-research`, `/wiki-serve`, `/wiki-maintain`, `/wiki-view`) and 9 agents that activate automatically based on context.

## Skills

| Command | Purpose |
|---------|---------|
| `/wiki-write <source>` | Add content from URL, file, or text |
| `/wiki-read <question>` | Search wiki, get cited answers |
| `/wiki-research <topic>` | Multi-channel web research with auto-ingestion |
| `/wiki-serve` | Start Wikipedia-style website on localhost:8420 |
| `/wiki-maintain` | Lint, deduplicate, upgrade confidence, gap analysis |
| `/wiki-view` | Dashboard, knowledge graph, stats, export |

## Architecture

```
llm-wiki/
  .claude-plugin/       Plugin metadata (plugin.json, marketplace.json)
  agents/               9 autonomous agents (writer, reader, auditor, search, research, fact-checker)
  bin/                  18 CLI utilities (search, backlinks, mentions, daily, rag, query, ...)
  mcp/                  MCP server for wiki operations (search, read, write, query, gaps)
  rules/                Workflow rules (when to read/write, quality standards)
  skills/               6 user-facing skills (write, read, research, serve, maintain, view)
    serve/
      scripts/          FastAPI server, WikiStore, RAG handler, chat manager
      static/           JavaScript (wiki, chat, editor) + CSS (4 themes)
      templates/        16 Jinja2 templates (page, graph, canvas, review, gaps, ...)
```

## Data Model

Wiki data lives in `.wiki/` in the current working directory. Location can be overridden by the user.

```
.wiki/
  pages/          Markdown files with YAML frontmatter (source of truth)
  templates/      Custom page type templates (user-defined structures)
  index.md        Auto-generated page catalog
  log.md          Append-only activity log
  overview.md     Current understanding synthesis
  cache/          SQLite databases (search, backlinks, flashcards, provenance)
  raw/            Immutable source materials (web, papers, code, transcripts)
```

### Frontmatter Schema

```yaml
---
title: "Page Title"
type: concept|entity|source|analysis|idea|status|rules|config|skill|memory
confidence: high|medium|low
sources: [source-slug-1, source-slug-2]
related: [related-slug-1, related-slug-2]
tags: [tag1, tag2]
freshness_tier: standard  # optional override
created: 2025-01-15
updated: 2025-01-15
---
```

### Freshness Tiers

| Tier | TTL | Examples |
|------|-----|----------|
| `live` | 15 min | stock prices, live scores, server status |
| `breaking` | 1-6 hours | breaking news, incident updates |
| `current` | 1-3 days | news articles, current events |
| `fast` | 1-4 weeks | AI/LLM/MCP, API changes, benchmarks |
| `moderate` | 1-3 months | software versions, frameworks |
| `standard` | 6 months | general knowledge, how-to guides (default) |
| `academic` | 1 year | research papers, studies |
| `evergreen` | 5 years | history, biographies, theorems |
| `permanent` | never | personal notes, ideas, memories |

## Web UI

Start with `/wiki-serve` — opens at `localhost:8420`:

- **Home** — recent pages, quick stats, search
- **Page view** — rendered markdown with backlinks sidebar, annotations
- **Editor** — split-pane markdown + live preview with AI assist toolbar
- **Knowledge graph** — interactive Cytoscape.js visualization with layout options
- **Canvas** — spatial whiteboard for arranging pages
- **Search** — full-text search with snippets
- **Stats** — page count, type/confidence distributions
- **Gaps** — content gap analysis dashboard
- **Review** — spaced repetition flashcard interface
- **Research dashboard** — background research task queue

## Agents

| Agent | Model | Purpose |
|-------|-------|---------|
| `wiki-writer` | Sonnet | Create/update pages — autonomous ingest and update |
| `wiki-reader` | Haiku | Search wiki, synthesize cited answers, research on miss |
| `wiki-auditor` | Haiku | Lint, dedup, fix broken links, upgrade confidence |
| `backlink-manager` | Haiku | Maintain reverse index, update related fields, detect unlinked mentions |
| `search-orchestrator` | Sonnet | Classify complexity, fan out to channels, rank results |
| `search-channel` | Haiku | Execute searches per channel (web, academic, code, docs) |
| `research-loop` | Sonnet | Iterative research with git-based rollback (max 3 iterations) |
| `research-processor` | Haiku | Condense and deduplicate parallel research results |
| `fact-checker` | Sonnet | Verify claims against external sources |
| `citation-explorer` | Sonnet | Academic citation graph snowballing |

## MCP Tools

The plugin includes an MCP server exposing wiki operations:

| Tool | Description |
|------|-------------|
| `wiki_search` | Hybrid semantic + keyword search |
| `wiki_read` | Read a page by slug |
| `wiki_write` | Create or update a page |
| `wiki_list` | List pages, optionally filtered by type |
| `wiki_backlinks` | Get backlinks + unlinked mentions |
| `wiki_stats` | Page count, type/confidence distributions |
| `wiki_query` | Dataview-style frontmatter queries |
| `wiki_gaps` | Content gap analysis |
| `wiki_daily` | Create/get today's daily note |
| `wiki_wikipedia_search` | Search Wikipedia via MediaWiki Action API |

## Compatibility

- **Obsidian** — open `.wiki/` as a vault for graph visualization and editing
- **Any MCP tools** — the wiki discovers available tools at runtime (Perplexity, Context7, etc.)
- **Git** — wiki changes are tracked, with auto-commit and rollback support

## Credits

- [Andrej Karpathy's LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — the original pattern
- [FSRS](https://github.com/open-spaced-repetition/fsrs4anki) — spaced repetition scheduling algorithm
- [Cytoscape.js](https://js.cytoscape.org/) — knowledge graph visualization
- [FastMCP](https://github.com/jlowin/fastmcp) — MCP server framework
- [FastAPI](https://fastapi.tiangolo.com/) — web server framework
- [markdown-it](https://github.com/markdown-it/markdown-it) — markdown rendering

## License

MIT
