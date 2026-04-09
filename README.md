<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT">
  <img src="https://img.shields.io/badge/version-1.0.0-green.svg" alt="Version">
  <img src="https://img.shields.io/badge/platform-Claude%20Code-blueviolet.svg" alt="Platform">
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome">
</p>

# llm-wiki

LLM-powered personal wiki for [Claude Code](https://claude.ai/claude-code) — an autonomous knowledge base with full-text search, multi-channel research, spaced repetition, knowledge graph visualization, and a Wikipedia-style web UI.

LLM-powered personal wiki that grows as you work. Research is automatically saved, questions are answered from existing knowledge first, and everything is interlinked. Built on [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): raw sources are immutable, the LLM maintains the wiki layer, and a schema governs behavior.

---

## Why llm-wiki?

Most knowledge tools require you to manually organize information. llm-wiki is different:

- **Zero friction** — knowledge is captured automatically as you work
- **Wiki-first answers** — Claude checks your wiki before searching the web
- **Research-on-miss** — if the wiki doesn't have the answer, it researches and saves it
- **Tool-agnostic** — works with whatever search/research tools you have (WebSearch, Perplexity MCP, Exa, etc.)
- **Self-maintaining** — lints broken links, merges duplicates, flags stale content
- **Compounding returns** — the more you use it, the smarter it gets

---

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
- **Wikipedia-style** browsable website with 4 themes (light, dark, terminal, wikipedia)
- **Interactive knowledge graph** — Cytoscape.js with clustering, layouts, neighborhood highlighting
- **Canvas view** — spatial whiteboard for arranging and connecting pages
- **Split-pane editor** — markdown + live preview with AI assist toolbar
- **Live research** — click any red link to auto-research the topic
- **Spaced repetition** — FSRS-based review scheduling for active recall
- **Gap analysis dashboard** — find missing knowledge and structural holes
- **Chat sidebar** — RAG-augmented Q&A grounded in your wiki

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

### Install

```bash
# Copy into your Claude Code plugins directory
cp -r llm-wiki .claude/plugins/

# Install dependencies
# Install dependencies
pip install -r .claude/plugins/llm-wiki/requirements.txt
```

The `.wiki/` data directory is created automatically on first use.

### First Use

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

```
llm-wiki/
  .claude-plugin/       Plugin metadata (plugin.json, marketplace.json)
  agents/               10 autonomous agents
  bin/                  22 CLI utilities (search, embed, backlinks, gaps, cache, ...)
  mcp/                  MCP server for wiki operations
  rules/                Workflow and integration rules
  skills/               5 user-facing skills
    serve/
      scripts/          FastAPI server, WikiStore, RAG, chat, research workers
      static/           JavaScript + CSS (4 themes)
      templates/        16 Jinja2 templates
```

---

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

### Page Frontmatter

```yaml
---
title: Machine Learning Basics
type: concept                    # concept, entity, source, idea, status, rules, memory, reference
confidence: medium               # high (3+ sources), medium (2+), low (1 source)
sources: [ml-textbook, andrew-ng-course]
related: [deep-learning, neural-networks]
tags: [ml, ai, fundamentals]
freshness_tier: academic         # optional: live, breaking, current, fast, moderate, standard, academic, evergreen, permanent
ttl: 365d                        # optional: custom TTL override
created: 2025-01-15
updated: 2025-03-20
---
```

### Page Types

| Type | Purpose |
|------|---------|
| concept | Standard knowledge article |
| entity | Person, organization, product, tool |
| source | Summary of a source document |
| idea | Single idea with evaluation |
| brainstorming | Freeform ideas with themes |
| status | Dashboard with metrics and action items |
| rules | Numbered policies with exceptions |
| config | Key-value settings |
| memory | Persistent facts and relationships |
| reference | Pointers to external resources |

---

## Agents

| Agent | Model | Role |
|-------|-------|------|
| wiki-writer | sonnet | Create and update wiki pages autonomously |
| wiki-reader | haiku | Search wiki, synthesize answers, research fallback |
| wiki-auditor | haiku | Lint links, fix frontmatter, detect duplicates |
| backlink-manager | haiku | Maintain reverse-link index and related fields |
| search-orchestrator | sonnet | Multi-channel parallel search coordination |
| search-channel | haiku | Execute search on a single channel |
| research-loop | sonnet | Iterative research with git-based rollback |
| research-processor | haiku | Deduplicate and condense research findings |
| fact-checker | sonnet | Verify claims against external sources |
| citation-explorer | sonnet | Academic citation graph snowballing |

---

## MCP Server

The plugin includes an MCP server (`mcp/wiki-mcp-server.py`) exposing wiki operations as tools:

| Tool | Description |
|------|-------------|
| `wiki_search` | Hybrid semantic + keyword search |
| `wiki_read` | Read a page by slug |
| `wiki_write` | Create or update a page |
| `wiki_list` | List pages, filter by type |
| `wiki_backlinks` | Get backlinks and unlinked mentions |
| `wiki_stats` | Page count, types, confidence distribution |
| `wiki_query` | Dataview-style frontmatter queries |
| `wiki_gaps` | Content gap analysis |
| `wiki_daily` | Create or get today's daily note |

Resources: `wiki://index`, `wiki://pages/{slug}`

---

## Compatibility

- **Obsidian** — open `.wiki/` as a vault for graph visualization and editing
- **Any MCP tools** — research fallback uses whatever search/fetch MCPs are available
- **Git** — auto-commit with attribution, rollback support
- **PDF/Word/text** — ingest any readable file format

---

## How It Works

1. **You work normally** — Claude saves relevant knowledge to the wiki automatically
2. **Wiki grows** — research, ideas, decisions, and patterns accumulate as interlinked pages
3. **Wiki serves you** — Claude checks the wiki first when you ask questions, citing sources
4. **Wiki maintains itself** — periodic lint, dedup, confidence upgrades, stale detection
5. **Knowledge compounds** — the more you use it, the richer and more useful it becomes

---

## Credits

- [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — the foundational idea
- [FSRS](https://github.com/open-spaced-repetition/fsrs4anki) — spaced repetition scheduling algorithm
- [Cytoscape.js](https://js.cytoscape.org/) — knowledge graph visualization
- [Semantic Scholar API](https://api.semanticscholar.org/) — academic paper search
- [Reciprocal Rank Fusion](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf) — hybrid search ranking

## License

MIT
