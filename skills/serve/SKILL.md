---
name: wiki-serve
description: "Start the wiki web server — browsable Wikipedia-style UI with live research, split-pane editor, AI assist, and themes. Manual trigger only: /wiki-serve, 'start wiki server', 'browse the wiki'."
---

# Serve

Launch a local web server that presents the wiki as a browsable, Wikipedia-style website with live background research, integrated chat, and a split-pane editor with AI assist.

Uses `.wiki/` in the current working directory. Location can be overridden by the user. If not found, auto-create it.

## Arguments

- **`/wiki-serve`** — start the server (default port 8420)
- **`/wiki-serve stop`** — stop the running server

## Startup

The FastAPI web server **only runs when explicitly requested**. There are two ways to start it:

### Skill-Based Launch

1. Run the `/wiki-serve` skill from Claude Code (recommended):
   ```bash
   /wiki-serve
   ```
2. The server automatically:
   - Installs dependencies if needed
   - Handles page indexing, research workers, and file watching
   - Opens your browser to localhost:8420

### Manual Launch

To start the server manually from the command line without using the skill:

1. Install dependencies once (if not already installed):
   ```bash
   uv add fastapi uvicorn markdown-it-py mdit-py-plugins jinja2 watchdog websockets
   ```
2. Run the server script:
   ```bash
   python path/to/skills/serve/scripts/server.py --wiki-dir .wiki/ --port 8420
   ```
   
   Or with `uv`:
   ```bash
   uv run python path/to/skills/serve/scripts/server.py --wiki-dir .wiki/ --port 8420
   ```

Replace `path/to` with the full path to your LLM-Wiki installation (typically `.claude/plugins/llm-wiki`).

## Features

- **Page rendering** — markdown → HTML with wiki-link transformation, red-link detection
- **Live research** — click any red link to trigger background research (stub-first: summary in 30s, full upgrade async)
- **Search** — full-text search with autocomplete
- **Split-pane editor** — markdown + live preview, markdown toolbar, AI assist bar
- **Page type templates** — concept, brainstorming, idea, memory, status, rules, config, skill, plus custom templates from `.wiki/templates/`
- **Chat** — wiki-aware AI assistant in bottom-right panel
- **Research queue** — manage, cancel, reorder research tasks
- **Knowledge graph** — interactive page relationship visualization
- **Three themes** — light, dark, terminal
- **Export** — HTML and markdown download

## Stop

Kill the server process on port 8420. Either:
- `/wiki-serve stop`
- The server auto-stops when the session ends (daemon process)
