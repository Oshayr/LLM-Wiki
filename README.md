# llm-wiki

LLM-powered personal wiki for [Claude Code](https://claude.ai/claude-code) — an autonomous knowledge base with full-text search, multi-channel research, spaced repetition, knowledge graph visualization, and a Wikipedia-style web UI.

Inspired by [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): raw sources are immutable, the LLM maintains the wiki layer, and a schema governs behavior. Knowledge compounds over time.

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

**Web UI**
- Wikipedia-style browsable website with 4 themes (light, dark, terminal, wikipedia)
- Interactive knowledge graph (Cytoscape.js) with multiple layouts, clustering, and neighborhood highlighting
- Canvas/whiteboard view for spatial page arrangement
- Split-pane markdown editor with live preview and AI assist
- Live research — click any red link to auto-research the topic
- Spaced repetition review interface (FSRS-based scheduling)
- Content gap analysis dashboard
- WebSocket chat sidebar with RAG-augmented Q&A

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

## Install

```bash
# Copy into your Claude Code plugins directory
cp -r llm-wiki .claude/plugins/

# Install dependencies (web server + MCP server)
pip install -r .claude/plugins/llm-wiki/requirements.txt
```

The `.wiki/` data directory is created automatically on first use.

### Verify Installation

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

Each page has frontmatter: `title`, `type`, `confidence` (high/medium/low), `sources`, `tags`, `created`, `updated`.

Compatible with Obsidian — open `.wiki/` as a vault for graph visualization and editing.

## How It Works

1. **You work normally** — Claude saves relevant knowledge to the wiki automatically
2. **Wiki grows** — research, ideas, decisions, and patterns accumulate as interlinked pages
3. **Wiki serves you** — Claude checks the wiki first when you ask questions, citing sources
4. **Wiki maintains itself** — periodic lint, dedup, confidence upgrades, stale detection

## MCP Server

The plugin includes an MCP server (`mcp/wiki-mcp-server.py`) exposing wiki operations as tools:

`wiki_search`, `wiki_read`, `wiki_write`, `wiki_list`, `wiki_backlinks`, `wiki_stats`, `wiki_query`, `wiki_gaps`, `wiki_daily`

## License

MIT
