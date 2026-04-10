# Wiki Serve — Local Browsable Wiki with Live Research

**A skill that starts a local web server presenting the LLM Wiki as a browsable, Wikipedia-style website with real-time background research, dynamic page creation, and an integrated chat sidebar.**

*Architecture Plan — April 7, 2026 · Last updated: April 10, 2026*

---

## 1. What This Is

A single command (`/wiki-serve`) that launches a local web server (default `http://localhost:8420`) turning the existing CScratch wiki (`.wiki/pages/`) into a live, browsable website. The server isn't just a static renderer — it orchestrates background research agents so the wiki grows as the user explores it.

**The user experience:** You open the wiki in your browser. You see existing pages rendered beautifully in Wikipedia style. You click a link to a page that doesn't exist yet — instead of a 404, you see a "Researching..." page with a live progress bar. In the background, a `claude -p` subprocess is running `/wiki-write` to research that topic. When it finishes (usually 15-60 seconds), the page auto-refreshes with the new content. You can also search for anything from the search bar, click "Expand" buttons on sections to trigger deeper research, and chat with Claude in a persistent sidebar that stays visible across page changes.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        BROWSER (localhost:8420)                  │
│  ┌───────────────────────────────────────┐ ┌─────────────────┐  │
│  │         Wikipedia-Style Page          │ │   Chat Sidebar  │  │
│  │  ┌─────────────────────────────────┐  │ │                 │  │
│  │  │  Search Bar                     │  │ │  [Claude CLI]   │  │
│  │  ├─────────────────────────────────┤  │ │                 │  │
│  │  │  Page Content (Markdown→HTML)   │  │ │  User: ...      │  │
│  │  │                                 │  │ │  Claude: ...    │  │
│  │  │  [[Internal Links]] → clickable │  │ │                 │  │
│  │  │  [🔍 Expand] buttons on headers │  │ │  [input box]    │  │
│  │  │                                 │  │ │                 │  │
│  │  └─────────────────────────────────┘  │ └─────────────────┘  │
│  └───────────────────────────────────────┘                      │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTP + WebSocket + SSE
┌────────────────────────▼────────────────────────────────────────┐
│                    WIKI SERVER (FastAPI + Uvicorn)               │
│                                                                  │
│  Routes:                                                         │
│    GET  /                     → Home/portal page                │
│    GET  /wiki/{slug}          → Render page (or researching)    │
│    GET  /search?q=...         → Search results                  │
│    POST /api/expand           → Queue deep research on section  │
│    GET  /api/status/{slug}    → Research progress (SSE stream)  │
│    GET  /api/suggestions?q=.. → Search autocomplete             │
│    WS   /ws/chat              → Chat subprocess bridge          │
│                                                                  │
│  Internals:                                                      │
│    WikiStore     → reads/indexes .wiki/pages/*.md     │
│    ResearchQueue → SQLite queue of pending research tasks       │
│    ChatManager   → Claude CLI subprocess lifecycle              │
└────────────────────────┬────────────────────────────────────────┘
                         │ spawns subprocesses
┌────────────────────────▼────────────────────────────────────────┐
│                    RESEARCH WORKERS (Background Threads)         │
│                                                                  │
│  Each worker:                                                    │
│    1. Picks a task from ResearchQueue                            │
│    2. Spawns: claude -p "research <topic> and /wiki-write it"   │
│    3. Streams progress → SSE to browser                         │
│    4. On completion: WikiStore re-indexes, notifies frontend    │
│                                                                  │
│  Task types:                                                     │
│    • page_create  — research a new topic from scratch           │
│    • section_expand — deepen a specific section of a page       │
│    • search_fill  — research a search query with no results     │
│                                                                  │
│  Concurrency: 2 workers (configurable), queued FIFO             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Design

### 3.1 WikiStore — The Data Layer

Reads the existing wiki on disk. No separate database for page content — the markdown files in `.wiki/pages/` ARE the source of truth (matching the existing wiki architecture).

**Responsibilities:**
- Parse frontmatter + markdown for all pages on startup
- Build an in-memory index: slug → {title, type, confidence, summary, links_to, linked_from}
- Watch filesystem for changes (new/modified .md files) and update index
- Provide search: TF-IDF full-text search + title matching
- Convert `[[slug]]` wiki links to `<a href="/wiki/slug">` HTML links
- Detect missing pages (linked-to but don't exist) for research queue seeding

**Index storage:** SQLite with FTS5 for search. Rebuilt on startup from .md files. This is a read cache, not a source of truth.

```python
# Simplified schema
pages(slug TEXT PK, title TEXT, type TEXT, confidence TEXT,
      content_md TEXT, content_html TEXT, summary TEXT,
      updated_at TEXT, status TEXT DEFAULT 'ready')

links(from_slug TEXT, to_slug TEXT, UNIQUE(from_slug, to_slug))

-- FTS5 virtual table for search
pages_fts(slug, title, content_md)
```

### 3.2 ResearchQueue — The Task Queue

SQLite-backed queue (same db as WikiStore) for research tasks.

```python
research_tasks(
    id INTEGER PK AUTOINCREMENT,
    slug TEXT,              # target page slug
    task_type TEXT,         # page_create | section_expand | search_fill
    query TEXT,             # the original search/click that triggered this
    section TEXT,           # for section_expand: which heading to deepen
    status TEXT,            # queued | researching | done | failed
    progress TEXT,          # JSON: {"stage": "searching", "detail": "..."}
    worker_pid INTEGER,     # PID of the claude subprocess
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    error TEXT              # error message if failed
)
```

**Deduplication:** Before enqueuing, check if the same slug already has an active task (queued/researching). If so, return the existing task ID — don't double-research.

### 3.3 Research Workers — The Background Agents

A thread pool (default 2 workers) that processes the research queue.

**For `page_create` tasks:**
```bash
claude -p "You are a wiki research agent. Research the topic '<topic>' thoroughly.
Use web search, find authoritative sources. Then create a wiki page at
.wiki/pages/<slug>.md following the wiki page format with frontmatter
(type, title, confidence, sources, related). Include [[wiki-links]] to related
concepts. Update .wiki/index.md. Be comprehensive but concise." \
--allowedTools "WebSearch,WebFetch,Read,Write,Edit" \
--max-tokens 8000
```

Actually — better to delegate to the existing wiki skills. The research worker should invoke the existing agents:

```bash
# Option A: Use search-orchestrator → /wiki-write pipeline
claude -p "Research '<topic>' comprehensively using web search, then run
//wiki-write with the findings. Create the page at <slug>.md." \
--allowedTools "WebSearch,WebFetch,Read,Write,Edit,Bash"

# Option B: Use autoresearch for deeper topics
claude -p "Run an autoresearch loop on '<topic>'. Max 2 iterations." \
--allowedTools "WebSearch,WebFetch,Read,Write,Edit,Bash"
```

**For `section_expand` tasks:**
```bash
claude -p "Read the wiki page at .wiki/pages/<slug>.md.
Find the section '<heading>'. Research that specific subtopic in much
greater depth. Expand the section with detailed findings, preserving
the page structure. Add new [[wiki-links]] for concepts discovered." \
--allowedTools "WebSearch,WebFetch,Read,Write,Edit"
```

**Progress reporting:** The worker writes progress updates to the SQLite `research_tasks.progress` column as JSON. The SSE endpoint polls this every 2 seconds to stream updates to the browser.

Progress stages: `queued` → `starting` → `searching` → `analyzing` → `writing` → `indexing` → `done`

### 3.4 ChatManager — The Sidebar Chat

Manages a persistent `claude` CLI subprocess for the chat sidebar.

**Lifecycle:**
1. On first WebSocket connection to `/ws/chat`, spawn `claude` with `--verbose` in a PTY
2. Bridge stdin/stdout/stderr through the WebSocket
3. Keep the process alive across page navigations (the WebSocket reconnects; the process persists)
4. On server shutdown, gracefully terminate the subprocess

**Implementation:** Use `asyncio.subprocess` with a PTY for proper terminal emulation. Parse ANSI codes to detect Claude's output boundaries (prompt markers). Convert to clean text/markdown for the browser.

**Context bridge (optional enhancement):** When the user navigates to a wiki page, automatically inject context into the chat: "The user is now viewing the wiki page: <title>. Slug: <slug>." This way the chat is contextually aware of what the user is reading.

### 3.5 Frontend — The Wikipedia-Style UI

A single-page-ish application with traditional page navigation (not an SPA — pages reload, but the chat sidebar persists via an iframe or WebSocket reconnect).

**Layout:**
```
┌──────────────────────────────────────────────────────────┐
│  🔍 [Search bar.........................] [Search]       │
│  Wiki Serve · Home · Random · Recent · Stats             │
├──────────────────────────────────┬───────────────────────┤
│                                  │  💬 Chat              │
│  Page Title                      │  ──────────────       │
│  ═══════════                     │  You: what is this?   │
│                                  │  Claude: This page    │
│  From Wikipedia-style layout     │  covers...            │
│                                  │                       │
│  ## Section One                  │                       │
│  Content with [[links]] and      │                       │
│  citations.        [🔍 Expand]   │                       │
│                                  │                       │
│  ## Section Two                  │                       │
│  More content.     [🔍 Expand]   │                       │
│                                  │  ──────────────       │
│  ─── Page Info ───               │  [Type a message...]  │
│  Type: concept | Confidence: high│  [Send]               │
│  Sources: 3 | Links: 12         │                       │
├──────────────────────────────────┴───────────────────────┤
│  Categories: AI · Machine Learning · Neural Networks      │
└──────────────────────────────────────────────────────────┘
```

**Key frontend behaviors:**

1. **Wiki links:** All `[[slug]]` references become `<a href="/wiki/slug">`. If the target page exists, normal link. If not, styled with a red/dashed underline (Wikipedia "redlink" style) — clicking triggers research.

2. **Search bar:** Autocomplete from existing pages (debounced, hits `/api/suggestions`). On submit, goes to `/search?q=...`. If no results, offers "Research this topic?" button which queues it.

3. **Researching page:** When navigating to a slug that's being researched:
   ```
   🔬 Researching: Quantum Computing
   ═══════════════════════════════════

   [████████░░░░░░░░░░░░] 40% — Analyzing sources...

   Stage: Searching for authoritative sources
   Started: 12 seconds ago
   Estimated: ~30 seconds remaining

   This page is being researched right now. It will appear
   automatically when ready.

   [Cancel Research]
   ```
   Uses SSE (`/api/status/{slug}`) for live progress. Auto-redirects to the actual page when status becomes `done`.

4. **Expand buttons:** Each `## Section` heading gets a `[🔍 Expand]` button. Clicking sends `POST /api/expand` with slug + section heading. Shows inline "Expanding..." indicator. When done, the section content updates (via polling or SSE).

5. **Chat sidebar:**
   - Resizable (drag the divider)
   - Collapsible (toggle button)
   - Persists across page navigation (WebSocket reconnects to same subprocess)
   - Shows Claude's responses with markdown rendering
   - Input box at bottom with send button + Enter key

**Rendering pipeline:**
```
.md file → parse frontmatter → markdown-it → HTML
  → transform [[links]] to <a> tags
  → inject [Expand] buttons on h2/h3 headers
  → inject into Jinja2 template
  → serve
```

---

## 4. Key Flows

### Flow 1: User navigates to an existing page
```
Browser: GET /wiki/transformer-architecture
Server:  WikiStore.get("transformer-architecture") → found, status=ready
Server:  Render markdown → HTML, inject into template
Browser: Displays page with all links, expand buttons, sidebar chat
```

### Flow 2: User clicks a "redlink" (missing page)
```
Browser: GET /wiki/attention-mechanisms  (page doesn't exist)
Server:  WikiStore.get("attention-mechanisms") → not found
Server:  ResearchQueue.enqueue("attention-mechanisms", "page_create")
Server:  Render "Researching..." page with SSE connection
Browser: Shows progress bar, auto-polls /api/status/attention-mechanisms
Worker:  Picks up task, spawns claude -p "research attention mechanisms..."
Worker:  Updates progress: searching → analyzing → writing → done
Server:  SSE pushes progress to browser
Worker:  Done — new .md file created, WikiStore re-indexes
Browser: SSE receives "done" → auto-redirects to /wiki/attention-mechanisms
Browser: Full page renders with content
```

### Flow 3: User searches for unknown topic
```
Browser: GET /search?q=quantum%20error%20correction
Server:  WikiStore.search("quantum error correction") → 0 results
Server:  Render search results page with "No results. Research this topic?" button
Browser: User clicks "Research this topic?"
Browser: POST /api/research {query: "quantum error correction"}
Server:  Generates slug: "quantum-error-correction"
Server:  ResearchQueue.enqueue("quantum-error-correction", "search_fill", query=...)
Server:  Redirect to /wiki/quantum-error-correction (shows researching page)
```

### Flow 4: User expands a section
```
Browser: User clicks [🔍 Expand] on "## Training Methods" in /wiki/transformers
Browser: POST /api/expand {slug: "transformers", section: "Training Methods"}
Server:  ResearchQueue.enqueue("transformers", "section_expand", section=...)
Browser: Shows inline spinner on that section
Worker:  Reads page, researches that section deeply, updates the .md file
Server:  WikiStore detects file change, re-indexes
Browser: Polls /api/status → done → refreshes page content (or just that section)
```

### Flow 5: Chat interaction
```
Browser: WebSocket connect to /ws/chat
Server:  ChatManager.get_or_create_session() → spawns claude subprocess
Browser: User types "explain the attention mechanism in simple terms"
Server:  Pipes message to claude subprocess stdin
Claude:  Responds via stdout
Server:  Streams response tokens via WebSocket to browser
Browser: Renders response in chat sidebar with markdown formatting
```

---

## 5. File Structure

```
wiki-serve/
├── SKILL.md                        # Skill definition and instructions
├── scripts/
│   ├── __init__.py                 # Package marker
│   ├── server.py                   # FastAPI app — routes, SSE, WebSocket
│   ├── wiki_store.py               # WikiStore — file reading, indexing, search
│   ├── research_queue.py           # ResearchQueue — SQLite task queue
│   ├── research_worker.py          # Background worker thread pool
│   ├── chat_manager.py             # Claude CLI subprocess + WebSocket bridge
│   ├── markdown_renderer.py        # Markdown → HTML with wiki link transforms
│   ├── rag_handler.py              # RAG context augmentation for chat
│   └── requirements.txt            # fastapi, uvicorn, markdown-it-py, etc.
├── templates/
│   ├── base.html                   # Wikipedia-style base layout + chat sidebar
│   ├── home.html                   # Portal / main page
│   ├── page.html                   # Wiki page template
│   ├── search.html                 # Search results
│   ├── edit.html                   # Split-pane markdown editor with live preview
│   ├── create.html                 # New page creation
│   ├── graph.html                  # Interactive Cytoscape.js knowledge graph
│   ├── canvas.html                 # Spatial whiteboard for page arrangement
│   ├── stats.html                  # Wiki statistics dashboard
│   ├── gaps.html                   # Content gap analysis dashboard
│   ├── history.html                # Git-backed page history with diffs
│   ├── recent.html                 # Recently modified pages
│   ├── review.html                 # FSRS spaced repetition flashcard interface
│   ├── research_dashboard.html     # Background research task queue
│   ├── researching.html            # Research-in-progress page
│   └── error.html                  # Error page
├── static/
│   ├── style.css                   # Wikipedia-inspired stylesheet (4 themes)
│   ├── wiki.js                     # Page logic (expand, search, SSE, navigation)
│   ├── chat.js                     # Chat sidebar WebSocket logic
│   └── editor.js                   # Split-pane editor logic
└── references/
    └── architecture.md             # This document
```

---

## 6. Technology Choices

| Component | Choice | Why |
|-----------|--------|-----|
| Web framework | **FastAPI** | Async, WebSocket support, SSE support, lightweight |
| ASGI server | **Uvicorn** | Standard for FastAPI, good performance |
| Markdown → HTML | **markdown-it-py** | Fast, extensible, plugin ecosystem |
| Template engine | **Jinja2** | Built into FastAPI, familiar, powerful |
| Search | **SQLite FTS5** | Zero infrastructure, fast full-text, already used for wiki cache |
| Task queue | **SQLite** (same db) | No Redis/Celery needed, everything in one file |
| Chat subprocess | **asyncio.subprocess** | Native Python, no PTY library needed |
| File watching | **watchdog** | Cross-platform file system events |
| CSS framework | **None** (custom Wikipedia CSS) | Wikipedia's style is distinctive, lightweight, well-understood |

**Python dependencies:**
```
fastapi>=0.111
uvicorn[standard]>=0.30
markdown-it-py>=3.0
mdit-py-plugins>=0.4
jinja2>=3.1
watchdog>=4.0
aiosqlite>=0.20
websockets>=12.0
```

---

## 7. Startup Sequence

When the skill is invoked (`/wiki-serve`):

1. **Check prerequisites:** `.wiki/SCHEMA.md` exists (wiki initialized). If not, auto-create `.wiki/` directory structure.
2. **Dependencies:** Already installed by the plugin's `SessionStart` hook (runs automatically on session start)
3. **Initialize WikiStore:** Scan `.wiki/pages/*.md`, build SQLite index
4. **Seed research queue:** Find all `[[slug]]` links pointing to non-existent pages → enqueue as low-priority `page_create` tasks
5. **Start research workers:** 2 background threads begin processing queue
6. **Start web server:** Uvicorn on `localhost:8420`
7. **Open browser:** `webbrowser.open("http://localhost:8420")`
8. **Print to terminal:** "Wiki Serve running at http://localhost:8420 — Ctrl+C to stop"

The server runs in the foreground. The skill keeps the process alive until Ctrl+C.

---

## 8. Integration with Existing Wiki System

This skill is a **read-heavy, write-through** layer on top of the existing wiki:

- **Reads from:** `.wiki/pages/*.md`, `.wiki/index.md`, `.wiki/log.md`
- **Writes via:** Spawned `claude -p` subprocesses that use the existing /wiki-write and wiki-update agents — NOT direct writes. This ensures all wiki conventions (frontmatter format, index updates, log entries) are maintained.
- **Search index:** Ephemeral SQLite db in `/tmp/wiki-serve-cache.db` — rebuilt on startup, not committed

The existing CLI workflow (`/wiki-write`, `/wiki-read`, `/wiki-view`, etc.) continues to work alongside the web UI. Changes made via CLI are picked up by the file watcher and reflected in the browser.

---

## 9. Edge Cases and Resilience

**Concurrent research for same topic:** Deduplicated at enqueue time. Second request gets the same task ID and status stream.

**Research failure:** Worker catches errors, sets task status to `failed` with error message. Browser shows "Research failed: <reason>. [Retry]" button.

**Server crash during research:** On restart, check for `researching` tasks with no running PID → reset to `queued` for retry.

**Large wiki (>500 pages):** FTS5 handles search efficiently. Page list on home uses pagination. Index navigation uses the existing `index.md` hierarchy.

**Chat subprocess dies:** WebSocket detects disconnect, respawns the `claude` process on next message.

**Port conflict:** If 8420 is taken, try 8421, 8422, etc. Print the actual port.

---

## 10. Enhancement Status

**Now implemented:**
- **Split-pane editor** (`edit.html` + `editor.js`) — markdown editing with live preview and AI assist toolbar
- **Knowledge graph** (`graph.html`) — interactive Cytoscape.js visualization with multiple layouts
- **Canvas view** (`canvas.html`) — spatial whiteboard for page arrangement
- **Page history** (`history.html`) — git-backed history viewer with diffs
- **Export** (`/wiki-view export`) — HTML, markdown, and JSON knowledge graph export
- **4 themes** (light, dark, terminal, wikipedia) — CSS variable-based theming with localStorage persistence
- **Research dashboard** (`research_dashboard.html`) — task queue visualization and management
- **Spaced repetition** (`review.html`) — FSRS-based flashcard review interface
- **Stats dashboard** (`stats.html`) — page count, type/confidence distributions
- **Content gap analysis** (`gaps.html`) — structural, depth, and freshness gap detection

**Remaining future ideas:**
- **Multi-user:** Authentication + concurrent editing
- **PDF export:** One-click export to PDF
