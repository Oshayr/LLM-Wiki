#!/usr/bin/env python3
"""
FastAPI web server for wiki-serve skill.

Integrates WikiStore, ResearchQueue, ResearchWorkerPool, ChatManager, and WikiRenderer
into a unified web application for collaborative wiki research.
"""

import sys
from pathlib import Path

# Add sibling modules to path
sys.path.insert(0, str(Path(__file__).parent))

import argparse
import asyncio
import json
import logging
import random
import re
import signal
import socket
import subprocess
import webbrowser
from datetime import datetime

import uvicorn
from chat_manager import ChatManager, chat_websocket_handler
from fastapi import Depends, FastAPI, Query, WebSocket
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_renderer import WikiRenderer
from research_queue import ResearchQueue
from research_worker import ResearchWorkerPool
from starlette.requests import Request
from wiki_store import WikiStore

logger = logging.getLogger(__name__)


# State is managed via app.state (FastAPI dependency injection pattern)
# Components are attached to app.state in main() and accessed via Depends() in routes
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _validate_slug(slug: str) -> str | None:
    """Validate and sanitise a slug, returning None if invalid."""
    if not slug or not _SLUG_RE.fullmatch(slug) or ".." in slug:
        return None
    return slug


# Dependency injection helpers — accessed via Depends() in route handlers
def get_wiki_store(request: Request) -> WikiStore:
    """Get WikiStore from app state."""
    return request.app.state.wiki_store


def get_research_queue(request: Request) -> ResearchQueue:
    """Get ResearchQueue from app state."""
    return request.app.state.research_queue


def get_wiki_renderer(request: Request) -> WikiRenderer:
    """Get WikiRenderer from app state."""
    return request.app.state.wiki_renderer


def get_templates(request: Request) -> Jinja2Templates:
    """Get Jinja2Templates from app state."""
    return request.app.state.templates


def get_chat_manager(request: Request) -> ChatManager | None:
    """Get ChatManager from app state (may be None if disabled)."""
    return request.app.state.chat_manager


def get_worker_pool(request: Request) -> ResearchWorkerPool | None:
    """Get ResearchWorkerPool from app state."""
    return request.app.state.worker_pool


def get_wiki_dir(request: Request) -> Path:
    """Get wiki directory from app state."""
    return request.app.state.wiki_dir


def _find_similar_page(slug: str, store) -> str | None:
    """Check if an existing wiki page already covers this topic.

    Two-stage approach:
    1. FTS5 search — fast, free. If the slug words match an existing page title, redirect.
    2. Agent check — for ambiguous cases, a quick haiku call decides semantic similarity.

    Returns matching slug or None.
    """
    # Convert slug to search query
    query = slug.replace("-", " ").replace("_", " ").strip()
    if not query:
        return None

    # Stage 1: FTS5 search — check if the topic words match an existing page
    results = store.search(query, limit=3)
    if not results:
        return None

    # If the top result's slug is very close (prefix/contained), redirect directly
    top = results[0]
    top_slug = top.get("slug", "")
    if top_slug == slug:
        return None  # Exact match means page exists (handled elsewhere)

    # Check obvious overlap: one slug contains the other or shares >60% tokens
    slug_tokens = set(query.lower().split())
    top_tokens = set(top_slug.replace("-", " ").lower().split())
    if slug_tokens and top_tokens:
        intersection = slug_tokens & top_tokens
        union = slug_tokens | top_tokens
        jaccard = len(intersection) / len(union) if union else 0
        if jaccard >= 0.6:
            return top_slug

    # Stage 2: Agent similarity check — ask haiku if the topic is already covered
    # Only if FTS5 returned a plausible match (search hit exists)
    if results:
        import asyncio
        import tempfile as _tf

        candidates = ", ".join(
            f"'{r.get('title', r['slug'])}' ({r['slug']})" for r in results[:3]
        )
        prompt = (
            f"Is the topic '{query}' already covered by one of these wiki pages?\n"
            f"Candidates: {candidates}\n\n"
            f"If yes, respond with ONLY the slug of the matching page (e.g., climate-change).\n"
            f"If no page covers this topic, respond with ONLY the word: NONE"
        )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context — use subprocess directly
                import subprocess as _sp

                safe_cwd = _tf.gettempdir()
                result = _sp.run(
                    [
                        "claude",
                        "-p",
                        "--model",
                        "haiku",
                        "--allowedTools",
                        "",
                        "--max-budget-usd",
                        "0.02",
                    ],
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    cwd=safe_cwd,
                )
                answer = result.stdout.strip().lower().replace("'", "").replace('"', "")
                if answer and answer != "none" and not answer.startswith("none"):
                    # Verify the answer is actually an existing slug
                    for r in results:
                        if r["slug"] == answer or answer in r["slug"]:
                            return r["slug"]
        except Exception as e:
            logger.debug(f"Agent similarity check error: {e}")  # Timeout or error — skip agent check, proceed to research

    return None


def find_free_port(start_port: int, max_attempts: int = 10) -> int:
    """Find a free port starting from start_port, trying up to max_attempts ports."""
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(
        f"Could not find free port in range {start_port}-{start_port + max_attempts - 1}"
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="LLM Wiki", description="Collaborative wiki research and knowledge base"
    )

    # Mount static files
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # GET /
    @app.get("/")
    async def home(
        request: Request,
        wiki_store: WikiStore = Depends(get_wiki_store),
        research_queue: ResearchQueue = Depends(get_research_queue),
        templates: Jinja2Templates = Depends(get_templates),
        chat_manager: ChatManager | None = Depends(get_chat_manager),
    ):
        """Home page with wiki stats and recent pages."""
        stats = wiki_store.get_stats()
        recent = wiki_store.get_recent_pages(limit=10)
        active_tasks = research_queue.get_active_tasks(limit=5)

        return templates.TemplateResponse(
            request,
            "home.html",
            context={
                "stats": stats,
                "recent_pages": recent,
                "active_tasks": active_tasks,
                "chat_enabled": chat_manager is not None,
            },
        )

    # GET /wiki/{slug}
    @app.get("/wiki/{slug}")
    async def wiki_page(
        request: Request,
        slug: str,
        wiki_store: WikiStore = Depends(get_wiki_store),
        research_queue: ResearchQueue = Depends(get_research_queue),
        wiki_renderer: WikiRenderer = Depends(get_wiki_renderer),
        templates: Jinja2Templates = Depends(get_templates),
        chat_manager: ChatManager | None = Depends(get_chat_manager),
    ):
        """Render or research a wiki page."""
        page = wiki_store.get_page(slug)

        if page:
            # Always render through WikiRenderer to get wiki-link transformation
            # and red-link detection (the stored content_html from WikiStore uses
            # plain MarkdownIt without [[slug]] → <a> conversion).
            existing_slugs = {p["slug"] for p in wiki_store.get_all_pages()}
            content_md = page.get("content_md", "")
            # Strip frontmatter before rendering (WikiRenderer expects body only)
            if content_md.startswith("---"):
                end = content_md.find("---", 3)
                if end != -1:
                    content_md = content_md[end + 3 :].strip()
            # Page resolver for transclusion support
            def _resolve_page_section(target_slug, section):
                return wiki_store.get_page_section(target_slug, section)

            html = wiki_renderer.render(
                content_md, slug=slug, existing_slugs=existing_slugs,
                page_resolver=_resolve_page_section,
                wiki_dir=str(wiki_store.wiki_dir),
            )
            return templates.TemplateResponse(
                request,
                "page.html",
                context={
                    "slug": slug,
                    "page": page,
                    "content_html": html,
                    "chat_enabled": chat_manager is not None,
                },
            )
        else:
            # Wiki-as-cache: check if a similar page already exists (fuzzy match).
            # This prevents near-duplicate research (e.g. "python-async" vs "python-asyncio").
            similar = _find_similar_page(slug, wiki_store)
            if similar:
                from starlette.responses import RedirectResponse

                return RedirectResponse(url=f"/wiki/{similar}", status_code=302)

            # Check if already researching
            task = research_queue.get_status(slug)

            if task and task.get("status") in ("queued", "researching"):
                # Active task in progress — show status
                return templates.TemplateResponse(
                    request,
                    "researching.html",
                    context={
                        "slug": slug,
                        "task_id": task.get("id", ""),
                        "status": task.get("status", "unknown"),
                        "progress": (
                            task.get("progress")
                            if isinstance(task.get("progress"), dict)
                            else {}
                        ),
                        "chat_enabled": chat_manager is not None,
                    },
                )
            else:
                # No active task (none exists, or previous one failed/done).
                # Enqueue a new research task.
                # Use "summary" depth for browser-triggered research:
                # haiku writes a quick summary (~30s, $0.50) so the user sees
                # content fast; the worker then auto-enqueues a full upgrade.
                task_id = research_queue.enqueue(
                    slug=slug, query=slug, task_type="page_create", depth="summary"
                )

                return templates.TemplateResponse(
                    request,
                    "researching.html",
                    context={
                        "slug": slug,
                        "task_id": task_id,
                        "status": "queued",
                        "progress": {},
                        "chat_enabled": chat_manager is not None,
                    },
                )

    # GET /search
    @app.get("/search")
    async def search(
        request: Request,
        q: str = Query("", alias="q"),
        wiki_store: WikiStore = Depends(get_wiki_store),
        templates: Jinja2Templates = Depends(get_templates),
        chat_manager: ChatManager | None = Depends(get_chat_manager),
    ):
        """Search for pages and topics."""
        results = []

        if q:
            results = wiki_store.search(q)

        return templates.TemplateResponse(
            request,
            "search.html",
            context={
                "query": q,
                "results": results,
                "total_results": len(results),
                "chat_enabled": chat_manager is not None,
            },
        )

    # POST /api/research
    @app.post("/api/research")
    async def api_research(
        request: Request,
        research_queue: ResearchQueue = Depends(get_research_queue),
    ):
        """Queue a research task."""
        try:
            data = await request.json()
        except Exception as e:
            logger.error(f"Invalid JSON in /api/research/queue: {e}", exc_info=True)
            return JSONResponse(
                {"error": "Invalid or empty JSON body"}, status_code=400
            )
        slug = data.get("slug")
        query = data.get("query", slug)
        task_type = data.get("task_type", "page_create")
        priority = data.get("priority", "medium")
        depth = data.get("depth", "full")

        if not _validate_slug(slug):
            return JSONResponse({"error": "invalid or missing slug"}, status_code=400)

        task_id = research_queue.enqueue(
            slug=slug, query=query, task_type=task_type, priority=priority, depth=depth
        )
        task = research_queue.get_status(slug)

        return {
            "task_id": task_id,
            "slug": slug,
            "status": task.get("status", "pending"),
        }

    # POST /api/expand
    @app.post("/api/expand")
    async def api_expand(
        request: Request,
        research_queue: ResearchQueue = Depends(get_research_queue),
    ):
        """Queue a section expansion task."""
        data = await request.json()
        slug = data.get("slug")
        section = data.get("section")

        if not _validate_slug(slug) or not section:
            return JSONResponse({"error": "valid slug and section required"}, status_code=400)

        task_id = research_queue.enqueue(
            slug=slug, query=f"{slug} - {section}", task_type="section_expand"
        )
        task = research_queue.get_status(slug)

        return {
            "task_id": task_id,
            "slug": slug,
            "section": section,
            "status": task.get("status", "pending"),
        }

    # POST /api/research/{task_id}/cancel
    @app.post("/api/research/{task_id}/cancel")
    async def api_cancel_task(
        task_id: int,
        research_queue: ResearchQueue = Depends(get_research_queue),
        worker_pool: ResearchWorkerPool | None = Depends(get_worker_pool),
    ):
        """Cancel a queued or researching task."""
        prev_status = research_queue.cancel(task_id)
        if prev_status is None:
            return JSONResponse(
                {"error": "Task not found or already completed"}, status_code=404
            )

        # If it was actively researching, kill the subprocess
        if prev_status == "researching" and worker_pool:
            worker_pool.kill_task(task_id)

        return {"status": "cancelled", "task_id": task_id, "was": prev_status}

    # POST /api/research/{task_id}/reorder
    @app.post("/api/research/{task_id}/reorder")
    async def api_reorder_task(
        request: Request,
        task_id: int,
        research_queue: ResearchQueue = Depends(get_research_queue),
    ):
        """Move a queued task up or down in priority."""
        data = await request.json()
        direction = data.get("direction", "up")

        if direction not in ("up", "down"):
            return JSONResponse(
                {"error": "direction must be 'up' or 'down'"}, status_code=400
            )

        success = research_queue.reorder(task_id, direction)
        if not success:
            return JSONResponse(
                {"error": "Task not found, not queued, or already at limit"},
                status_code=404,
            )

        return {"status": "reordered", "task_id": task_id, "direction": direction}

    # DELETE /api/wiki/{slug}
    @app.delete("/api/wiki/{slug}")
    async def api_delete_page(
        slug: str,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        """Delete a wiki page."""
        if not _validate_slug(slug):
            return JSONResponse({"error": "invalid slug"}, status_code=400)
        deleted = wiki_store.delete_page(slug)
        if deleted:
            return {"status": "deleted", "slug": slug}
        return {"status": "not_found", "slug": slug}

    # GET /api/research/active
    @app.get("/api/research/active")
    async def api_research_active(
        research_queue: ResearchQueue = Depends(get_research_queue),
    ):
        """Get active and queued research tasks for the sidebar."""
        tasks = research_queue.get_active_tasks(limit=20)
        result = []
        for t in tasks:
            progress = t.get("progress") if isinstance(t.get("progress"), dict) else {}
            item = {
                "id": t.get("id"),
                "slug": t.get("slug"),
                "status": t.get("status"),
                "task_type": t.get("task_type"),
                "priority": t.get("priority", "medium"),
                "progress": progress,
            }
            # Add elapsed time for researching tasks
            if t.get("started_at") and t.get("status") == "researching":
                try:
                    started = datetime.fromisoformat(
                        t["started_at"].replace("Z", "+00:00")
                    )
                    elapsed = int(
                        (datetime.now(started.tzinfo) - started).total_seconds()
                    )
                    item["elapsed"] = elapsed
                except (ValueError, TypeError):
                    pass
            result.append(item)
        return result

    # GET /api/status/{slug}
    @app.get("/api/status/{slug}")
    async def api_status(
        slug: str,
        research_queue: ResearchQueue = Depends(get_research_queue),
    ):
        """SSE endpoint for research progress updates."""

        async def sse_generator():
            while True:
                task = research_queue.get_status(slug)

                if task is None:
                    yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                    break

                data = {
                    "status": task["status"],
                    "progress": (
                        task.get("progress")
                        if isinstance(task.get("progress"), dict)
                        else {}
                    ),
                    "task_type": task.get("task_type"),
                }

                if task.get("started_at"):
                    try:
                        started = datetime.fromisoformat(
                            task["started_at"].replace("Z", "+00:00")
                        )
                        elapsed = (
                            datetime.now(started.tzinfo) - started
                        ).total_seconds()
                        data["elapsed_seconds"] = int(elapsed)
                    except (ValueError, TypeError):
                        pass

                yield f"data: {json.dumps(data)}\n\n"

                if task["status"] in ("done", "failed"):
                    break

                await asyncio.sleep(2)

        return StreamingResponse(sse_generator(), media_type="text/event-stream")

    # GET /api/suggestions
    @app.get("/api/suggestions")
    async def api_suggestions(
        q: str = Query("", alias="q"),
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        """Search autocomplete suggestions."""
        if not q or len(q) < 2:
            return []

        results = wiki_store.search(q, limit=10)
        suggestions = [
            {"slug": r.get("slug"), "title": r.get("title"), "type": r.get("type")}
            for r in results
        ]

        return suggestions

    # WS /ws/chat
    @app.websocket("/ws/chat")
    async def websocket_chat(websocket: WebSocket):
        """WebSocket chat endpoint."""
        chat_manager: ChatManager | None = websocket.app.state.chat_manager
        if chat_manager is None:
            await websocket.close(code=1008, reason="Chat disabled")
            return

        await chat_websocket_handler(websocket, chat_manager)

    # GET /research - Research Dashboard
    @app.get("/research", response_class=HTMLResponse)
    async def research_dashboard(
        request: Request,
        research_queue: ResearchQueue = Depends(get_research_queue),
        templates: Jinja2Templates = Depends(get_templates),
        chat_manager: ChatManager | None = Depends(get_chat_manager),
        wiki_dir: Path = Depends(get_wiki_dir),
    ):
        """Research pipeline dashboard."""
        active_tasks = research_queue.get_active_tasks()
        history = research_queue.get_history(limit=30)
        queue_stats = research_queue.get_queue_stats()
        priority_stats = research_queue.get_priority_stats()

        # Read autoresearch scoreboard if it exists
        scoreboard_path = wiki_dir / "../autoresearch/scoreboard.md"
        scoreboard = ""
        if scoreboard_path.exists():
            scoreboard = scoreboard_path.read_text()

        # Chat stats if available
        chat_stats = chat_manager.get_stats() if chat_manager else {}

        return templates.TemplateResponse(
            request,
            "research_dashboard.html",
            context={
                "active_tasks": active_tasks,
                "history": history,
                "queue_stats": queue_stats,
                "priority_stats": priority_stats,
                "scoreboard": scoreboard,
                "chat_stats": chat_stats,
                "chat_enabled": chat_manager is not None,
            },
        )

    # GET /graph - Knowledge Graph
    @app.get("/graph", response_class=HTMLResponse)
    async def knowledge_graph(
        request: Request,
        wiki_store: WikiStore = Depends(get_wiki_store),
        templates: Jinja2Templates = Depends(get_templates),
        chat_manager: ChatManager | None = Depends(get_chat_manager),
    ):
        """Interactive knowledge graph visualization."""
        pages = wiki_store.get_all_pages()

        # Build graph data: nodes and edges
        nodes = []
        edges = []
        existing_slugs = {p["slug"] for p in pages}

        for page in pages:
            nodes.append(
                {
                    "id": page["slug"],
                    "title": page.get("title", page["slug"]),
                    "type": page.get("type", "unknown"),
                    "confidence": page.get("confidence", "unknown"),
                    "superseded": bool(page.get("superseded_by")),
                }
            )

        # Get links from wiki_store's links table (with relationship type)
        with wiki_store.lock:
            cursor = wiki_store.db.cursor()
            cursor.execute("SELECT from_slug, to_slug, relationship FROM links")
            for row in cursor.fetchall():
                if row[0] in existing_slugs and row[1] in existing_slugs:
                    edges.append(
                        {
                            "source": row[0],
                            "target": row[1],
                            "relationship": row[2] or "reference",
                        }
                    )

        return templates.TemplateResponse(
            request,
            "graph.html",
            context={
                "nodes_json": json.dumps(nodes),
                "edges_json": json.dumps(edges),
                "chat_enabled": chat_manager is not None,
            },
        )

    # GET /wiki/{slug}/history - Page History
    @app.get("/wiki/{slug}/history", response_class=HTMLResponse)
    async def page_history(
        request: Request,
        slug: str,
        wiki_store: WikiStore = Depends(get_wiki_store),
        templates: Jinja2Templates = Depends(get_templates),
        chat_manager: ChatManager | None = Depends(get_chat_manager),
    ):
        """Git-backed page history."""
        page = wiki_store.get_page(slug)
        if not page:
            return templates.TemplateResponse(
                request,
                "error.html",
                context={
                    "message": f"Page '{slug}' not found",
                    "chat_enabled": chat_manager is not None,
                },
                status_code=404,
            )

        # Get git history for this page
        page_path = wiki_store.pages_dir / f"{slug}.md"
        history = []
        try:
            result = subprocess.run(
                [
                    "git",
                    "log",
                    "--pretty=format:%H|%ai|%s",
                    "-20",
                    "--",
                    str(page_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(wiki_store.pages_dir),
            )
            for line in result.stdout.strip().split("\n"):
                if "|" in line:
                    parts = line.split("|", 2)
                    history.append(
                        {"hash": parts[0][:8], "date": parts[1], "message": parts[2]}
                    )
        except Exception as e:
            logger.debug(f"Error parsing git history: {e}")

        return templates.TemplateResponse(
            request,
            "history.html",
            context={
                "page": page,
                "history": history,
                "chat_enabled": chat_manager is not None,
            },
        )

    # GET /api/wiki/{slug}/diff/{commit_hash} - View diff for a commit
    @app.get("/api/wiki/{slug}/diff/{commit_hash}")
    async def api_page_diff(
        slug: str,
        commit_hash: str,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        """Return git diff for a specific commit on a page."""
        if not _validate_slug(slug):
            return JSONResponse({"error": "invalid slug"}, status_code=400)
        if not re.fullmatch(r"[0-9a-f]{7,40}", commit_hash):
            return JSONResponse({"error": "invalid commit hash"}, status_code=400)
        page_path = wiki_store.pages_dir / f"{slug}.md"
        try:
            result = subprocess.run(
                [
                    "git",
                    "diff",
                    f"{commit_hash}~1..{commit_hash}",
                    "--",
                    str(page_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(wiki_store.pages_dir),
            )
            diff_text = result.stdout.strip()
            if not diff_text:
                # First commit — show full content
                result = subprocess.run(
                    ["git", "show", f"{commit_hash}:{page_path.name}"],
                    capture_output=True,
                    text=True,
                    cwd=str(wiki_store.pages_dir),
                )
                diff_text = f"+++ {page_path.name}\n" + "\n".join(
                    f"+{line}" for line in result.stdout.split("\n")
                )
            return JSONResponse({"diff": diff_text, "commit": commit_hash})
        except Exception as e:
            logger.error(f"Error getting wiki diff: {e}", exc_info=True)
            return JSONResponse({"error": str(e)}, status_code=500)

    # GET /wiki/{slug}/edit - Edit page
    @app.get("/wiki/{slug}/edit", response_class=HTMLResponse)
    async def edit_page(
        request: Request,
        slug: str,
        wiki_store: WikiStore = Depends(get_wiki_store),
        templates: Jinja2Templates = Depends(get_templates),
        chat_manager: ChatManager | None = Depends(get_chat_manager),
    ):
        """Markdown editor for a wiki page."""
        page = wiki_store.get_page(slug)
        if not page:
            return RedirectResponse(url=f"/create?slug={slug}")

        content_md = page.get("content_md", "")
        return templates.TemplateResponse(
            request,
            "edit.html",
            context={
                "slug": slug,
                "page": page,
                "content_md": content_md,
                "chat_enabled": chat_manager is not None,
            },
        )

    # POST /api/wiki/{slug}/save - Save edited page
    @app.post("/api/wiki/{slug}/save")
    async def api_save_page(
        request: Request,
        slug: str,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        """Save edited markdown content for a page."""
        if not _validate_slug(slug):
            return JSONResponse({"error": "invalid slug"}, status_code=400)
        try:
            data = await request.json()
        except Exception as e:
            logger.error(f"Invalid JSON in /api/wiki/{slug}/save: {e}", exc_info=True)
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        content_md = data.get("content", "")
        if not content_md.strip():
            return JSONResponse({"error": "Content cannot be empty"}, status_code=400)

        # Write directly to the page file
        page_path = wiki_store.pages_dir / f"{slug}.md"
        page_path.write_text(content_md, encoding="utf-8")

        # Refresh in wiki store
        wiki_store.refresh_page(slug)

        return {"status": "saved", "slug": slug}

    # GET /create - Create new page form
    @app.get("/create", response_class=HTMLResponse)
    async def create_page_form(
        request: Request,
        slug: str = Query("", alias="slug"),
        templates: Jinja2Templates = Depends(get_templates),
        chat_manager: ChatManager | None = Depends(get_chat_manager),
    ):
        """Form to create a new wiki page."""
        return templates.TemplateResponse(
            request,
            "create.html",
            context={
                "slug": slug,
                "chat_enabled": chat_manager is not None,
            },
        )

    # POST /api/wiki/create - Create a new page
    @app.post("/api/wiki/create")
    async def api_create_page(
        request: Request,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        """Create a new wiki page from form data."""
        try:
            data = await request.json()
        except Exception as e:
            logger.error(f"Invalid JSON in /api/wiki/create: {e}", exc_info=True)
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        slug = data.get("slug", "").strip()
        content_md = data.get("content", "").strip()

        if not _validate_slug(slug):
            return JSONResponse({"error": "Invalid or missing slug"}, status_code=400)
        if not content_md:
            return JSONResponse({"error": "Content is required"}, status_code=400)

        # Check if page already exists
        existing = wiki_store.get_page(slug)
        if existing:
            return JSONResponse({"error": "Page already exists"}, status_code=409)

        # Write the page file
        page_path = wiki_store.pages_dir / f"{slug}.md"
        page_path.write_text(content_md, encoding="utf-8")

        # Refresh in wiki store
        wiki_store.refresh_page(slug)

        return {"status": "created", "slug": slug}

    # POST /api/wiki/import - Import files (txt, images, PDF)
    @app.post("/api/wiki/import")
    async def api_import_file(
        request: Request,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        """Import a file as a wiki page or attachment."""
        import re as re_mod

        form = await request.form()
        file = form.get("file")
        target_slug = form.get("slug", "")

        if not file or not hasattr(file, "read"):
            return JSONResponse({"error": "No file uploaded"}, status_code=400)

        filename = file.filename or "unknown"
        content_bytes = await file.read()
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        # Generate slug from filename if not provided
        if not target_slug:
            base = filename.rsplit(".", 1)[0] if "." in filename else filename
            target_slug = re_mod.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")

        if not _validate_slug(target_slug):
            return JSONResponse({"error": "Invalid slug"}, status_code=400)

        if ext in ("txt", "md", "markdown"):
            # Text/markdown → create as wiki page
            text = content_bytes.decode("utf-8", errors="replace")
            if not text.startswith("---"):
                # Add minimal frontmatter
                today = datetime.now().strftime("%Y-%m-%d")
                title = target_slug.replace("-", " ").title()
                text = f"---\ntitle: {title}\ntype: concept\nconfidence: medium\ncreated: {today}\nupdated: {today}\n---\n\n{text}"

            page_path = wiki_store.pages_dir / f"{target_slug}.md"
            page_path.write_text(text, encoding="utf-8")
            wiki_store.refresh_page(target_slug)
            return {"status": "imported", "slug": target_slug, "type": "page"}

        elif ext in ("jpg", "jpeg", "png", "gif", "svg", "webp"):
            # Image → save to static/uploads/ and return URL
            uploads_dir = Path(__file__).parent.parent / "static" / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re_mod.sub(r"[^a-z0-9._-]", "", filename.lower())
            if ".." in safe_name or not safe_name:
                return JSONResponse({"error": "Invalid filename"}, status_code=400)
            dest = uploads_dir / safe_name
            dest.write_bytes(content_bytes)
            return {
                "status": "imported",
                "slug": target_slug,
                "type": "image",
                "url": f"/static/uploads/{safe_name}",
            }

        elif ext == "pdf":
            # PDF → extract text if possible, create page
            try:
                # Try basic text extraction
                text = content_bytes.decode("utf-8", errors="replace")
                # If mostly binary garbage, just note the PDF
                printable = sum(
                    1 for c in text[:1000] if c.isprintable() or c in "\n\r\t"
                )
                if printable / max(len(text[:1000]), 1) < 0.5:
                    text = f"*Imported from PDF: {filename}*\n\nBinary PDF content — use a PDF viewer for full content."
            except Exception as e:
                logger.error(f"Error extracting text from PDF {filename}: {e}", exc_info=True)
                text = f"*Imported from PDF: {filename}*\n\nCould not extract text."

            today = datetime.now().strftime("%Y-%m-%d")
            title = target_slug.replace("-", " ").title()
            md = f'---\ntitle: {title}\ntype: concept\nconfidence: low\nsources:\n  - title: "{filename}"\ncreated: {today}\nupdated: {today}\n---\n\n{text}'

            page_path = wiki_store.pages_dir / f"{target_slug}.md"
            page_path.write_text(md, encoding="utf-8")
            wiki_store.refresh_page(target_slug)
            return {"status": "imported", "slug": target_slug, "type": "pdf"}

        else:
            return JSONResponse(
                {"error": f"Unsupported file type: .{ext}"}, status_code=400
            )

    # POST /api/annotations - Add annotation
    @app.post("/api/annotations")
    async def add_annotation(
        request: Request,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        """Add an annotation to a page."""
        data = await request.json()
        aid = wiki_store.add_annotation(
            slug=data["slug"],
            annotation_type=data.get("type", "comment"),
            content=data["content"],
            start=data.get("start"),
            end=data.get("end"),
        )
        return JSONResponse({"id": aid, "status": "created"})

    # GET /api/annotations/{slug} - Get annotations
    @app.get("/api/annotations/{slug}")
    async def get_annotations(
        slug: str,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        """Get all annotations for a page."""
        annotations = wiki_store.get_annotations(slug)
        return JSONResponse(annotations)

    # POST /api/annotations/{annotation_id}/resolve - Resolve annotation
    @app.post("/api/annotations/{annotation_id}/resolve")
    async def resolve_annotation(
        annotation_id: int,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        """Mark an annotation as resolved."""
        wiki_store.resolve_annotation(annotation_id)
        return JSONResponse({"status": "resolved"})

    # GET /api/suggestions/research/{slug} - Research suggestions
    @app.get("/api/suggestions/research/{slug}")
    async def research_suggestions(
        slug: str,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        """Suggest related topics to research based on current page."""
        page = wiki_store.get_page(slug)
        suggestions = []

        if page:
            # 1. Missing pages linked from this page (redlinks)
            missing = wiki_store.get_missing_pages()
            # Filter to ones linked from this slug
            with wiki_store.lock:
                cursor = wiki_store.db.cursor()
                cursor.execute("SELECT to_slug FROM links WHERE from_slug = ?", (slug,))
                linked = {row[0] for row in cursor.fetchall()}

            for m in missing:
                if m["slug"] in linked:
                    suggestions.append(
                        {
                            "slug": m["slug"],
                            "reason": f"Linked from this page but no article exists ({m.get('reference_count', 0)} references)",
                            "priority": "high",
                        }
                    )

            # 2. Low-confidence related pages
            related = (
                page.get("related", []) if isinstance(page.get("related"), list) else []
            )
            for r_slug in related[:5]:
                r_page = wiki_store.get_page(r_slug)
                if r_page and r_page.get("confidence") == "low":
                    suggestions.append(
                        {
                            "slug": r_slug,
                            "reason": f"Related page '{r_page.get('title', r_slug)}' has low confidence",
                            "priority": "medium",
                        }
                    )

        return JSONResponse(suggestions[:10])

    # ======================================================================
    # NEW ROUTES — Wave 1-3 Features
    # ======================================================================

    # GET /daily — Today's daily note
    @app.get("/daily")
    async def daily_note(
        request: Request,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        """Redirect to today's daily note, creating it if needed."""
        import subprocess

        bin_dir = Path(__file__).parent.parent.parent.parent / "bin"
        pages_dir = wiki_store.pages_dir
        result = subprocess.run(
            [sys.executable, str(bin_dir / "daily.py"), "today", str(pages_dir)],
            capture_output=True, text=True, timeout=10,
        )
        try:
            data = json.loads(result.stdout)
            slug = data.get("slug", f"daily-{datetime.now().strftime('%Y-%m-%d')}")
        except Exception as e:
            logger.error(f"Error parsing daily note JSON: {e}", exc_info=True)
            slug = f"daily-{datetime.now().strftime('%Y-%m-%d')}"

        # Refresh in case it was just created
        wiki_store.refresh_page(slug)
        return RedirectResponse(url=f"/wiki/{slug}")

    # GET /review — Spaced repetition review
    @app.get("/review", response_class=HTMLResponse)
    async def review_page(
        request: Request,
        templates: Jinja2Templates = Depends(get_templates),
        chat_manager: ChatManager | None = Depends(get_chat_manager),
    ):
        """Spaced repetition review interface."""
        import subprocess

        bin_dir = Path(__file__).parent.parent.parent.parent / "bin"

        # Get due cards
        result = subprocess.run(
            [sys.executable, str(bin_dir / "flashcards.py"), "due", "--limit", "20"],
            capture_output=True, text=True, timeout=10,
        )
        try:
            cards = json.loads(result.stdout)
        except Exception as e:
            logger.error(f"Error parsing flashcards JSON: {e}", exc_info=True)
            cards = []

        # Get stats
        result = subprocess.run(
            [sys.executable, str(bin_dir / "flashcards.py"), "stats"],
            capture_output=True, text=True, timeout=10,
        )
        try:
            stats = json.loads(result.stdout)
        except Exception as e:
            logger.error(f"Error parsing flashcard stats JSON: {e}", exc_info=True)
            stats = {}

        return templates.TemplateResponse(
            request, "review.html",
            context={"cards": cards, "stats": stats, "chat_enabled": chat_manager is not None},
        )

    # GET /api/review/next — Next due flashcard
    @app.get("/api/review/next")
    async def api_review_next():
        import subprocess
        bin_dir = Path(__file__).parent.parent.parent.parent / "bin"
        result = subprocess.run(
            [sys.executable, str(bin_dir / "flashcards.py"), "due", "--limit", "1"],
            capture_output=True, text=True, timeout=10,
        )
        try:
            cards = json.loads(result.stdout)
            return JSONResponse(cards[0] if cards else {"done": True})
        except Exception as e:
            logger.error(f"Error parsing flashcard JSON: {e}", exc_info=True)
            return JSONResponse({"done": True})

    # POST /api/review/grade — Grade a flashcard
    @app.post("/api/review/grade")
    async def api_review_grade(request: Request):
        import subprocess
        data = await request.json()
        card_id = data.get("card_id")
        rating = data.get("rating")
        if not card_id or not rating:
            return JSONResponse({"error": "card_id and rating required"}, status_code=400)
        bin_dir = Path(__file__).parent.parent.parent.parent / "bin"
        result = subprocess.run(
            [sys.executable, str(bin_dir / "flashcards.py"), "review", str(card_id), str(rating)],
            capture_output=True, text=True, timeout=10,
        )
        try:
            return JSONResponse(json.loads(result.stdout))
        except Exception as e:
            logger.error(f"Error grading flashcard: {e}", exc_info=True)
            return JSONResponse({"error": result.stderr[:200]}, status_code=500)

    # GET /api/wiki/{slug}/backlinks — Enhanced backlinks with unlinked mentions
    @app.get("/api/wiki/{slug}/backlinks")
    async def api_backlinks(
        slug: str,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        backlinks = wiki_store.get_backlinks(slug)
        # Also get unlinked mentions
        import subprocess
        bin_dir = Path(__file__).parent.parent.parent.parent / "bin"
        result = subprocess.run(
            [sys.executable, str(bin_dir / "mentions.py"), "page", str(wiki_store.pages_dir), slug],
            capture_output=True, text=True, timeout=15,
        )
        try:
            mentions = json.loads(result.stdout)
        except Exception as e:
            logger.error(f"Error parsing mentions JSON: {e}", exc_info=True)
            mentions = []
        return JSONResponse({"backlinks": backlinks, "mentions": mentions})

    # POST /api/wiki/{slug}/link-mention — Convert unlinked mention to wiki link
    @app.post("/api/wiki/{slug}/link-mention")
    async def api_link_mention(
        slug: str,
        request: Request,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        data = await request.json()
        source_slug = data.get("source_slug")
        line_number = data.get("line_number")
        if not source_slug or not line_number:
            return JSONResponse({"error": "source_slug and line_number required"}, status_code=400)
        import subprocess
        bin_dir = Path(__file__).parent.parent.parent.parent / "bin"
        result = subprocess.run(
            [sys.executable, str(bin_dir / "mentions.py"), "link",
             str(wiki_store.pages_dir), source_slug, slug, str(line_number)],
            capture_output=True, text=True, timeout=10,
        )
        wiki_store.refresh_page(source_slug)
        return JSONResponse({"status": "linked" if result.returncode == 0 else "failed"})

    # GET /api/wiki/{slug}/suggested-links — Suggested links via backlinks analysis
    @app.get("/api/wiki/{slug}/suggested-links")
    async def api_suggested_links(
        slug: str,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        import subprocess
        bin_dir = Path(__file__).parent.parent.parent.parent / "bin"
        result = subprocess.run(
            [sys.executable, str(bin_dir / "backlinks.py"), "query",
             str(wiki_store.pages_dir), slug],
            capture_output=True, text=True, timeout=30,
        )
        try:
            return JSONResponse(json.loads(result.stdout))
        except Exception as e:
            logger.error(f"Error parsing backlinks JSON: {e}", exc_info=True)
            return JSONResponse([])

    # GET /api/wiki/{slug}/provenance — Provenance chain
    @app.get("/api/wiki/{slug}/provenance")
    async def api_provenance(
        slug: str,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        import subprocess
        bin_dir = Path(__file__).parent.parent.parent.parent / "bin"
        cache_dir = str(wiki_store.wiki_dir / "cache")
        result = subprocess.run(
            [sys.executable, str(bin_dir / "provenance.py"), "trace", slug, "--cache-dir", cache_dir],
            capture_output=True, text=True, timeout=10,
        )
        try:
            return JSONResponse(json.loads(result.stdout))
        except Exception as e:
            logger.error(f"Error parsing provenance JSON: {e}", exc_info=True)
            return JSONResponse([])

    # GET /gaps — Gap analysis dashboard
    @app.get("/gaps", response_class=HTMLResponse)
    async def gaps_dashboard(
        request: Request,
        wiki_store: WikiStore = Depends(get_wiki_store),
        templates: Jinja2Templates = Depends(get_templates),
        chat_manager: ChatManager | None = Depends(get_chat_manager),
    ):
        import subprocess
        bin_dir = Path(__file__).parent.parent.parent.parent / "bin"
        result = subprocess.run(
            [sys.executable, str(bin_dir / "gaps.py"), "analyze", str(wiki_store.pages_dir)],
            capture_output=True, text=True, timeout=30,
        )
        try:
            gaps = json.loads(result.stdout)
        except Exception as e:
            logger.error(f"Error parsing gaps analysis JSON: {e}", exc_info=True)
            gaps = {"summary": {}, "structural_gaps": [], "depth_gaps": [], "freshness_gaps": [], "missing_pages": []}

        return templates.TemplateResponse(
            request, "gaps.html",
            context={"gaps": gaps, "chat_enabled": chat_manager is not None},
        )

    # POST /api/query — Execute frontmatter query
    @app.post("/api/query")
    async def api_query(
        request: Request,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        data = await request.json()
        query_str = data.get("query", "")
        if not query_str:
            return JSONResponse({"error": "query required"}, status_code=400)
        import subprocess
        bin_dir = Path(__file__).parent.parent.parent.parent / "bin"
        result = subprocess.run(
            [sys.executable, str(bin_dir / "query.py"), "exec", str(wiki_store.pages_dir), query_str],
            capture_output=True, text=True, timeout=10,
        )
        try:
            return JSONResponse(json.loads(result.stdout))
        except Exception as e:
            logger.error(f"Error parsing query results JSON: {e}", exc_info=True)
            return JSONResponse({"error": result.stderr[:200]}, status_code=500)

    # POST /api/wiki/{slug}/undo — Undo last commit for a page
    @app.post("/api/wiki/{slug}/undo")
    async def api_undo_page(
        slug: str,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        import subprocess
        bin_dir = Path(__file__).parent.parent.parent.parent / "bin"
        result = subprocess.run(
            [sys.executable, str(bin_dir / "wiki_git.py"), "undo", str(wiki_store.wiki_dir), slug],
            capture_output=True, text=True, timeout=15,
        )
        wiki_store.refresh_page(slug)
        try:
            return JSONResponse(json.loads(result.stdout))
        except Exception as e:
            logger.error(f"Error undoing page {slug}: {e}", exc_info=True)
            return JSONResponse({"error": result.stderr[:200]}, status_code=500)

    # GET /canvas — Canvas/whiteboard view
    @app.get("/canvas", response_class=HTMLResponse)
    async def canvas_view(
        request: Request,
        wiki_store: WikiStore = Depends(get_wiki_store),
        templates: Jinja2Templates = Depends(get_templates),
        chat_manager: ChatManager | None = Depends(get_chat_manager),
    ):
        """Interactive canvas/whiteboard with wiki page cards."""
        pages = wiki_store.get_all_pages()
        existing_slugs = {p["slug"] for p in pages}

        # Build nodes from pages
        nodes = []
        for page in pages:
            nodes.append({
                "id": page["slug"],
                "title": page.get("title", page["slug"]),
                "type": page.get("type", "unknown"),
                "confidence": page.get("confidence", "unknown"),
            })

        # Build edges from links
        edges = []
        with wiki_store.lock:
            cursor = wiki_store.db.cursor()
            cursor.execute("SELECT from_slug, to_slug, relationship FROM links")
            for row in cursor.fetchall():
                if row[0] in existing_slugs and row[1] in existing_slugs:
                    edges.append({"source": row[0], "target": row[1], "type": row[2] or "reference"})

        # Load canvas layout if saved
        canvas_path = wiki_store.wiki_dir / "canvas" / "default.canvas.json"
        canvas_data = {}
        if canvas_path.exists():
            try:
                canvas_data = json.loads(canvas_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error(f"Error loading canvas data: {e}", exc_info=True)

        return templates.TemplateResponse(
            request, "canvas.html",
            context={
                "nodes_json": json.dumps(nodes),
                "edges_json": json.dumps(edges),
                "canvas_data_json": json.dumps(canvas_data),
                "chat_enabled": chat_manager is not None,
            },
        )

    # POST /api/canvas/save — Save canvas layout
    @app.post("/api/canvas/save")
    async def api_canvas_save(
        request: Request,
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        data = await request.json()
        canvas_dir = wiki_store.wiki_dir / "canvas"
        canvas_dir.mkdir(parents=True, exist_ok=True)
        canvas_path = canvas_dir / "default.canvas.json"
        canvas_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return JSONResponse({"status": "saved"})

    # GET /random - Random page redirect
    @app.get("/random")
    async def random_page(
        wiki_store: WikiStore = Depends(get_wiki_store),
    ):
        """Redirect to a random wiki page."""
        pages = wiki_store.get_all_pages()
        if not pages:
            return RedirectResponse(url="/")
        page = random.choice(pages)
        return RedirectResponse(url=f"/wiki/{page['slug']}")

    # GET /recent - Recent changes
    @app.get("/recent", response_class=HTMLResponse)
    async def recent_changes(
        request: Request,
        wiki_store: WikiStore = Depends(get_wiki_store),
        templates: Jinja2Templates = Depends(get_templates),
        chat_manager: ChatManager | None = Depends(get_chat_manager),
    ):
        """Recent changes page."""
        recent = wiki_store.get_recent_pages(limit=50)
        return templates.TemplateResponse(
            request,
            "recent.html",
            context={
                "recent_pages": recent,
                "chat_enabled": chat_manager is not None,
            },
        )

    # GET /stats - Wiki statistics
    @app.get("/stats", response_class=HTMLResponse)
    async def stats_page(
        request: Request,
        wiki_store: WikiStore = Depends(get_wiki_store),
        research_queue: ResearchQueue = Depends(get_research_queue),
        templates: Jinja2Templates = Depends(get_templates),
        chat_manager: ChatManager | None = Depends(get_chat_manager),
    ):
        """Detailed wiki statistics."""
        stats = wiki_store.get_stats()
        missing = wiki_store.get_missing_pages()
        queue_stats = research_queue.get_queue_stats()
        return templates.TemplateResponse(
            request,
            "stats.html",
            context={
                "stats": stats,
                "missing_pages": missing,
                "queue_stats": queue_stats,
                "chat_enabled": chat_manager is not None,
            },
        )

    # POST /api/chat - HTTP fallback for chat
    @app.post("/api/chat")
    async def api_chat(
        request: Request,
        chat_manager: ChatManager | None = Depends(get_chat_manager),
    ):
        """HTTP fallback for chat messages."""
        if chat_manager is None:
            return JSONResponse({"error": "Chat disabled"}, status_code=503)
        data = await request.json()
        message = data.get("message", "").strip()
        if not message:
            return JSONResponse({"error": "Empty message"}, status_code=400)
        try:
            response = await chat_manager.send_message(message)
            return JSONResponse({"response": response})
        except Exception as e:
            logger.error(f"Error sending chat message: {e}", exc_info=True)
            return JSONResponse({"error": str(e)}, status_code=500)

    # GET /api/chat/history - Chat history
    @app.get("/api/chat/history")
    async def api_chat_history(
        chat_manager: ChatManager | None = Depends(get_chat_manager),
    ):
        """Return chat history."""
        if chat_manager is None:
            return JSONResponse({"messages": []})
        messages = [
            {"role": m["role"], "content": m["content"]} for m in chat_manager.history
        ]
        return JSONResponse({"messages": messages})

    # POST /api/preview - Render markdown to HTML for live preview
    @app.post("/api/preview")
    async def api_preview(
        request: Request,
        wiki_renderer: WikiRenderer = Depends(get_wiki_renderer),
    ):
        """Render markdown content to HTML for the editor preview pane."""
        data = await request.json()
        content = data.get("content", "")
        # Strip frontmatter for preview rendering
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                content = parts[2].strip()
        html = wiki_renderer.render(content)
        return JSONResponse({"html": html})

    # POST /api/editor/assist - AI-assisted editing via claude subprocess
    @app.post("/api/editor/assist")
    async def api_editor_assist(request: Request):
        """Use Claude haiku to modify wiki content based on user instruction.
        Spawns a one-shot claude -p subprocess with safe CWD (no project hooks)."""
        import tempfile as _tempfile

        data = await request.json()
        content = data.get("content", "")
        instruction = data.get("instruction", "")
        slug = data.get("slug", "unknown")

        if not instruction:
            return JSONResponse({"error": "instruction required"}, status_code=400)

        prompt = (
            "You are a wiki editor assistant. "
            "The user is editing the page '" + slug + "'.\n"
            "Current content:\n```markdown\n" + content + "\n```\n\n"
            "Instruction: " + instruction + "\n\n"
            "Return ONLY the modified markdown content (including frontmatter if present). "
            "Do not add explanations or code fences around the output."
        )

        try:
            # Safe CWD avoids picking up project .claude/ hooks
            safe_cwd = _tempfile.gettempdir()
            cmd = [
                "claude",
                "-p",
                "--model",
                "haiku",
                "--allowedTools",
                "",
                "--max-budget-usd",
                "0.10",
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=safe_cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")), timeout=60.0
            )

            if proc.returncode != 0:
                error_msg = stderr.decode(errors="replace").strip()[:200]
                return JSONResponse(
                    {"error": "AI subprocess failed: " + error_msg}, status_code=500
                )

            result = stdout.decode(errors="replace").strip()
            tokens_est = (len(prompt) + len(result)) // 4
            return JSONResponse({"result": result, "tokens_est": tokens_est})

        except TimeoutError:
            logger.error("AI request timed out", exc_info=True)
            return JSONResponse({"error": "AI request timed out"}, status_code=504)
        except Exception as e:
            logger.error(f"Error in AI chat endpoint: {e}", exc_info=True)
            return JSONResponse({"error": str(e)}, status_code=500)

    # GET /api/export/{format} - Export entire wiki
    @app.get("/api/export/{fmt}")
    async def api_export(
        fmt: str,
        wiki_store: WikiStore = Depends(get_wiki_store),
        wiki_renderer: WikiRenderer = Depends(get_wiki_renderer),
    ):
        """Export the entire wiki as a single HTML file or markdown bundle.
        Supported formats: html, md"""
        pages = wiki_store.get_all_pages()

        if fmt == "html":
            # Build a single HTML document with all pages
            parts = [
                "<!DOCTYPE html><html><head><meta charset='utf-8'>",
                "<title>LLM Wiki Export</title>",
                "<style>body{font-family:sans-serif;max-width:800px;margin:0 auto;padding:20px;}"
                "h1{border-bottom:2px solid #333;padding-bottom:8px;}"
                ".page-break{page-break-before:always;border-top:2px solid #ccc;margin-top:40px;padding-top:20px;}"
                "a{color:#2563eb;}code{background:#f4f4f4;padding:2px 4px;border-radius:3px;}"
                "pre{background:#f4f4f4;padding:12px;border-radius:6px;overflow-x:auto;}"
                "table{border-collapse:collapse;width:100%;}th,td{border:1px solid #ddd;padding:8px;}"
                "</style></head><body>",
                "<h1>LLM Wiki Export</h1>",
                f"<p>Exported {len(pages)} pages</p><hr>",
            ]
            for page in sorted(pages, key=lambda p: p.get("title", p["slug"])):
                content_md = page.get("content_md", "")
                if content_md.startswith("---"):
                    end = content_md.find("---", 3)
                    if end != -1:
                        content_md = content_md[end + 3 :].strip()
                html = wiki_renderer.render(content_md)
                parts.append(f'<div class="page-break" id="{page["slug"]}">')
                parts.append(f'<h1>{page.get("title", page["slug"])}</h1>')
                parts.append(html)
                parts.append("</div>")
            parts.append("</body></html>")

            from starlette.responses import Response

            return Response(
                content="\n".join(parts),
                media_type="text/html",
                headers={
                    "Content-Disposition": "attachment; filename=llm-wiki-export.html"
                },
            )

        elif fmt == "md":
            # Bundle all markdown files into a single document
            parts = [f"# LLM Wiki Export\n\nExported {len(pages)} pages\n\n---\n"]
            for page in sorted(pages, key=lambda p: p.get("title", p["slug"])):
                content_md = page.get("content_md", "")
                parts.append(f"\n\n---\n\n# {page.get('title', page['slug'])}\n\n")
                parts.append(content_md)
            from starlette.responses import Response

            return Response(
                content="\n".join(parts),
                media_type="text/markdown",
                headers={
                    "Content-Disposition": "attachment; filename=llm-wiki-export.md"
                },
            )

        return JSONResponse(
            {"error": "Unsupported format. Use 'html' or 'md'"}, status_code=400
        )

    return app


async def shutdown_handler(app: FastAPI | None = None):
    """Gracefully shut down all services."""
    print("\nShutting down...")

    if app:
        worker_pool: ResearchWorkerPool | None = getattr(app.state, "worker_pool", None)
        chat_manager: ChatManager | None = getattr(app.state, "chat_manager", None)

        if worker_pool:
            worker_pool.stop()

        if chat_manager:
            await chat_manager.stop()

    print("Shutdown complete")


def main():
    """Parse arguments and start the server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="LLM Wiki FastAPI Server")
    parser.add_argument(
        "--wiki-dir", required=True, help="Path to state/wiki directory"
    )
    parser.add_argument(
        "--port", type=int, default=8420, help="Server port (default 8420)"
    )
    parser.add_argument(
        "--workers", type=int, default=2, help="Number of research workers (default 2)"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Don't auto-open browser"
    )
    parser.add_argument("--no-chat", action="store_true", help="Disable chat sidebar")

    args = parser.parse_args()

    wiki_dir = Path(args.wiki_dir)
    wiki_dir.mkdir(parents=True, exist_ok=True)

    print("Initializing wiki-serve...")
    print(f"  Wiki directory: {wiki_dir}")
    print(f"  Workers: {args.workers}")
    print(f"  Chat enabled: {not args.no_chat}")

    # Initialize WikiStore
    wiki_store = WikiStore(wiki_dir)
    print(f"  WikiStore initialized ({wiki_store.get_stats()['total_pages']} pages)")

    # Initialize ResearchQueue
    queue_db = Path(wiki_dir) / "cache" / "serve-queue.db"
    queue_db.parent.mkdir(parents=True, exist_ok=True)
    research_queue = ResearchQueue(queue_db)
    recovered = research_queue.recover_stale()
    if recovered:
        print(f"  ResearchQueue initialized (recovered {recovered} stale tasks)")
    else:
        print("  ResearchQueue initialized")

    # Seed missing pages
    missing = wiki_store.get_missing_pages()
    for page_slug in missing:
        research_queue.enqueue(
            slug=page_slug, query=page_slug, task_type="page_create", priority="low"
        )
    if missing:
        print(f"  Seeded {len(missing)} missing pages to research queue")

    # Initialize ResearchWorkerPool
    worker_pool = ResearchWorkerPool(
        research_queue, wiki_store, wiki_dir=str(wiki_dir), num_workers=args.workers
    )
    worker_pool.start()
    print(f"  Research workers started ({args.workers} workers)")

    # Initialize ChatManager (if enabled)
    chat_manager = None
    if not args.no_chat:
        chat_manager = ChatManager(wiki_store=wiki_store)
        print("  ChatManager initialized")

    # Initialize WikiRenderer
    wiki_renderer = WikiRenderer()
    print("  WikiRenderer initialized")

    # Setup templates
    templates_dir = Path(__file__).parent.parent / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    templates = Jinja2Templates(directory=str(templates_dir))

    def humanize_datetime(value):
        """Convert ISO datetime string to human-readable format."""
        if not value:
            return ""
        try:
            if isinstance(value, str):
                for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                    try:
                        dt = datetime.fromisoformat(value)
                        break
                    except ValueError:
                        continue
                else:
                    return value
            else:
                dt = value
            now = datetime.now()
            diff = now - dt
            if diff.days == 0:
                hours = diff.seconds // 3600
                if hours == 0:
                    minutes = diff.seconds // 60
                    return f"{minutes}m ago" if minutes > 0 else "just now"
                return f"{hours}h ago"
            elif diff.days == 1:
                return "yesterday"
            elif diff.days < 7:
                return f"{diff.days}d ago"
            elif diff.days < 30:
                return f"{diff.days // 7}w ago"
            else:
                return dt.strftime("%b %d, %Y")
        except Exception as e:
            logger.debug(f"Error humanizing datetime: {e}")
            return str(value)[:10] if value else ""

    templates.env.filters["humanize"] = humanize_datetime

    # Smoke test
    try:
        WikiStore.smoke_test()
        logger.info("Smoke test passed")
    except Exception as e:
        logger.error(f"Smoke test failed: {e}", exc_info=True)
        sys.exit(1)

    # Create and configure app
    app = create_app()

    # Store components in app.state (FastAPI dependency injection pattern)
    app.state.wiki_store = wiki_store
    app.state.research_queue = research_queue
    app.state.worker_pool = worker_pool
    app.state.chat_manager = chat_manager
    app.state.wiki_renderer = wiki_renderer
    app.state.templates = templates
    app.state.wiki_dir = wiki_dir

    # Find available port
    port = find_free_port(args.port)
    if port != args.port:
        print(f"  Port {args.port} taken, using {port}")

    # Setup signal handlers for graceful shutdown
    loop = asyncio.new_event_loop()

    def signal_handler(signum, frame):
        loop.call_soon_threadsafe(loop.create_task, shutdown_handler(app))

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Open browser if not disabled
    if not args.no_browser:
        url = f"http://localhost:{port}"
        print(f"\nOpening browser at {url}...")
        webbrowser.open(url)

    # Start server
    print(f"\nStarting server on http://localhost:{port}")
    print("Press Ctrl+C to stop\n")

    try:
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            log_level="info",
        )
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(shutdown_handler(app))


if __name__ == "__main__":
    main()
