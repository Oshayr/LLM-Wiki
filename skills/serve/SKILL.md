---
name: wiki-serve
description: "Start the wiki web server — browsable Wikipedia-style UI with live research, split-pane editor, AI assist, and themes. Manual trigger only: /wiki-serve, 'start wiki server', 'browse the wiki'."
---

# Serve

Launch a local web server that presents the wiki as a browsable, Wikipedia-style website with live background research, integrated chat, and a split-pane editor with AI assist.

Resolve `.wiki/` from plugin install scope (user-level → `~/.wiki/`, project-level → project root). Auto-create if missing.

## Arguments

- **`/wiki-serve`** — start the server (default port 8420)
- **`/wiki-serve stop`** — stop the running server

## Startup

1. Install dependencies if needed:
   ```bash
   uv add fastapi uvicorn markdown-it-py mdit-py-plugins jinja2 watchdog websockets
   ```
2. Run the server:
   ```bash
   uv run python ${CLAUDE_PLUGIN_ROOT}/skills/serve/scripts/server.py \
     --wiki-dir <.wiki/ path> \
     --port 8420
   ```
3. The script handles: page indexing, research workers, file watching, serving.
4. Open browser automatically.

## Features

- **Page rendering** — markdown → HTML with wiki-link transformation, red-link detection
- **Live research** — click any red link to trigger background research (stub-first: summary in 30s, full upgrade async)
- **Search** — full-text search with autocomplete
- **Split-pane editor** — markdown + live preview, markdown toolbar, AI assist bar
- **Page type templates** — concept, brainstorming, idea, memory, status, rules, config, skill
- **Chat** — wiki-aware AI assistant in bottom-right panel
- **Research queue** — manage, cancel, reorder research tasks
- **Knowledge graph** — interactive page relationship visualization
- **Three themes** — light, dark, terminal
- **Export** — HTML and markdown download

## Stop

Kill the server process on port 8420. Either:
- `/wiki-serve stop`
- The server auto-stops when the session ends (daemon process)
