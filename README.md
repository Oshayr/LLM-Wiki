# llm-wiki

LLM-powered personal wiki for [Claude Code](https://claude.ai/claude-code) — an autonomous knowledge base with semantic search, multi-channel research, spaced repetition, knowledge graph visualization, and a Wikipedia-style web UI.

Inspired by [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): raw sources are immutable, the LLM maintains the wiki layer, and a schema governs behavior. Knowledge compounds over time.

## Features

**Knowledge Management**
- Automatic knowledge capture — saves research, ideas, decisions, and findings to the wiki
- Smart retrieval — checks the wiki before web search, grounds answers in existing knowledge
- Hybrid search — combines BM25 keyword matching with semantic vector similarity (Reciprocal Rank Fusion)
- Block references and transclusion — `[[page#heading]]` links and `![[page#section]]` embeds
- Backlinks panel with unlinked mention detection
- Frontmatter query language (Dataview-like) — query your wiki like a database

**Research Engine**
- Multi-channel parallel search — web, academic (Semantic Scholar, OpenAlex, CrossRef, arXiv), code (GitHub, npm, PyPI), docs (Context7)
- Citation snowballing — forward/backward citation graph building from seed papers
- Autonomous research loops — iterative hypothesis-driven research with git-based rollback
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

**Maintenance**
- Self-maintaining — lints broken links, merges duplicates, upgrades confidence, flags stale content
- Progressive summarization and note maturity tracking (seed/growing/mature/evergreen)
- Daily notes and journal workflows
- Smart caching with adaptive TTL and stale-while-revalidate
- Circuit breakers for external API resilience
- Git integration with auto-commit, attribution, and undo

## Install

```bash
# Clone into your Claude Code plugins directory
git clone https://github.com/Oshayr/llm-wiki .claude/plugins/llm-wiki

# Install dependencies (web server + MCP server)
pip install -r .claude/plugins/llm-wiki/requirements.txt
```

No further setup required. The `.wiki/` data directory is created automatically on first use.

### Optional: Semantic Search

For hybrid semantic + keyword search, install the embedding dependencies:

```bash
pip install onnxruntime tokenizers numpy sqlite-vec
```

The embedding model (~23MB ONNX) downloads automatically on first use. No PyTorch required.

### Verify Installation

After installing, restart Claude Code. The plugin provides 6 slash commands (`/write`, `/read`, `/research`, `/serve`, `/maintain`, `/view`) and 9 agents that activate automatically based on context.

## Skills

| Command | Purpose |
|---------|---------|
| `/write <source>` | Add content from URL, file, or text |
| `/read <question>` | Search wiki, get cited answers |
| `/research <topic>` | Multi-channel web research with auto-ingestion |
| `/serve` | Start Wikipedia-style website on localhost:8420 |
| `/maintain` | Lint, deduplicate, upgrade confidence, gap analysis |
| `/view` | Dashboard, knowledge graph, stats, export |

## Architecture

```
llm-wiki/
  .claude-plugin/       Plugin metadata (plugin.json, marketplace.json)
  agents/               9 autonomous agents (writer, reader, auditor, search, research, fact-checker)
  bin/                  22 CLI utilities (embed, search, backlinks, mentions, daily, rag, query, ...)
  mcp/                  MCP server for wiki operations (search, read, write, query, gaps)
  rules/                Workflow rules (when to read/write, quality standards)
  skills/               6 user-facing skills (write, read, research, serve, maintain, view)
    serve/
      scripts/          FastAPI server, WikiStore, RAG handler, chat manager
      static/           JavaScript (wiki, chat, editor) + CSS (4 themes)
      templates/        16 Jinja2 templates (page, graph, canvas, review, gaps, ...)
```

## Data Model

Wiki data lives in `.wiki/` at your project root (not inside the plugin):

```
.wiki/
  pages/          Markdown files with YAML frontmatter (source of truth)
  index.md        Auto-generated page catalog
  log.md          Append-only activity log
  overview.md     Current understanding synthesis
  cache/          SQLite databases (search, vectors, backlinks, flashcards, provenance)
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
