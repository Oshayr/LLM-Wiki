"""
Manages a persistent Claude CLI subprocess bridge for wiki chat sidebar.
Maintains conversation history and streams responses via WebSocket.
"""

import asyncio
import json
import logging
import tempfile
from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

# Maximum conversation history to maintain (older messages truncated)
MAX_HISTORY = 20

# Threshold for summarizing conversation history
HISTORY_SUMMARIZE_THRESHOLD = 10


class ChatManager:
    """Manages Claude CLI subprocess with persistent conversation history."""

    def __init__(self, wiki_store=None):
        """Initialize chat manager with empty history.

        Args:
            wiki_store: Optional WikiStore instance for providing page context
        """
        self.history: list[dict[str, str]] = []
        self.process: asyncio.subprocess.Process | None = None
        self.current_context: dict[str, str] = {}
        self.wiki_store = wiki_store
        self._lock = asyncio.Lock()
        self.messages_sent: int = 0
        self.estimated_tokens: int = 0
        self._cached_page_list: str = ""
        self._cached_page_count: int = 0
        self._refresh_page_cache()

    def _refresh_page_cache(self) -> None:
        """Rebuild the cached page list string. Call when pages change, not per-message.

        Uses a compact format: title ([[slug]]) for each page.
        Summaries are available in the DB but excluded to keep context lean.
        """
        if not self.wiki_store:
            return
        try:
            pages = self.wiki_store.get_all_pages()
            if pages:
                self._cached_page_list = ", ".join(
                    f"{p.get('title', p['slug'])} ([[{p['slug']}]])" for p in pages[:40]
                )
                self._cached_page_count = len(pages)
            else:
                self._cached_page_list = ""
                self._cached_page_count = 0
        except Exception as e:
            logger.debug(f"Error refreshing page cache: {e}")

    def _cap_history(self) -> None:
        """Truncate history to MAX_HISTORY most recent messages."""
        if len(self.history) > MAX_HISTORY:
            self.history = self.history[-MAX_HISTORY:]

    def _summarize_history(self) -> None:
        """
        Summarize the first 8 messages when history exceeds HISTORY_SUMMARIZE_THRESHOLD.
        Keeps only the summary + last 2 messages to prevent quadratic token growth.
        """
        if len(self.history) <= HISTORY_SUMMARIZE_THRESHOLD:
            return

        # Extract topics and key points from first 8 messages
        first_messages = self.history[:8]
        topics = []
        key_points = []

        for msg in first_messages:
            content = msg["content"]
            # Extract first 100 chars as topic indicators
            snippet = content[:100].replace("\n", " ").strip()
            if snippet:
                topics.append(snippet)
            # Extract sentences with key markers
            if any(
                marker in content.lower()
                for marker in ["important", "key", "note", "found", "identified"]
            ):
                key_points.append(content[:150])

        # Create summary message
        topic_str = ", ".join(topics[:2]) if topics else "previous discussion"
        points_str = ". ".join(key_points[:2]) if key_points else "context established"
        summary_content = (
            f"Previous conversation covered: {topic_str}. Key points: {points_str}."
        )

        # Keep summary + last 2 messages
        summary_message = {"role": "assistant", "content": summary_content}
        self.history = [summary_message] + self.history[-2:]

    def get_stats(self) -> dict:
        """
        Get conversation statistics.

        Returns:
            dict with 'messages_sent' and 'estimated_tokens' keys
        """
        return {
            "messages_sent": self.messages_sent,
            "estimated_tokens": self.estimated_tokens,
        }

    def _build_prompt(self) -> str:
        """Build the prompt to send to Claude with full conversation history."""
        lines = [
            "You are a wiki assistant for the LLM Wiki — a knowledge base about "
            "AI, research, and related topics. Answer questions concisely using "
            "your knowledge. Reference wiki page slugs as [[slug]] when relevant.",
            "",
        ]

        # Inject cached page list — auto-invalidates when page count changes
        if self.wiki_store:
            try:
                current_count = len(self.wiki_store.get_all_pages())
                if current_count != self._cached_page_count:
                    self._refresh_page_cache()
            except Exception as e:
                logger.debug(f"Error getting page count: {e}")
        if self._cached_page_list:
            lines.append(f"Wiki pages available: {self._cached_page_list}")
            lines.append("")

        # Add per-page context if available
        if self.current_context:
            page_title = self.current_context.get("page_title", "")
            page_slug = self.current_context.get("page_slug", "")
            lines.append(
                f"The user is currently viewing: {page_title} ([[{page_slug}]])"
            )
            lines.append("")

        # Add conversation history
        for msg in self.history:
            role = msg["role"].upper()
            content = msg["content"]
            lines.append(f"{role}: {content}")
            lines.append("")

        return "\n".join(lines)

    async def start(self) -> None:
        """Mark the chat manager as ready. No persistent subprocess needed —
        send_message() uses one-shot `claude -p` calls."""
        self._started = True
        logger.info("ChatManager ready (one-shot mode)")

    async def send_message(self, text: str) -> str:
        """
        Send a message and get Claude's response.
        Uses single-shot claude -p calls with conversation history maintained server-side.

        Args:
            text: User message to send to Claude

        Returns:
            Claude's response as a string
        """
        async with self._lock:
            # Add user message to history
            self.history.append({"role": "user", "content": text})
            self._cap_history()

            # Summarize history if needed
            if len(self.history) > HISTORY_SUMMARIZE_THRESHOLD:
                self._summarize_history()

            # Build full prompt with context and history
            prompt = self._build_prompt()

            try:
                # Run claude -p with prompt via stdin.
                # --allowedTools restricted to prevent web searches
                # (chat should answer from knowledge, not research).
                # --model haiku for fast responses.
                # cwd=tempdir avoids project .claude/ hooks that inject
                # ~40K tokens of SessionStart context and often crash the subprocess.
                safe_cwd = tempfile.gettempdir()
                proc = await asyncio.create_subprocess_exec(
                    "claude",
                    "-p",
                    "--model",
                    "haiku",
                    "--allowedTools",
                    "",
                    "--max-budget-usd",
                    "0.10",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=safe_cwd,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(input=prompt.encode("utf-8")), timeout=90.0
                    )
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
                    logger.error("Claude subprocess timed out after 90 seconds")
                    return "That took too long — try a simpler question."

                if proc.returncode != 0:
                    error_msg = stderr.decode(errors="replace").strip()
                    logger.error(f"Claude subprocess error: {error_msg}")
                    # Don't add broken response to history; return error instead
                    # Remove the user message we added since it didn't produce a valid response
                    if self.history and self.history[-1]["role"] == "user":
                        self.history.pop()
                    return "I encountered an error processing that. Could you try rephrasing?"
                else:
                    response = stdout.decode(errors="replace").strip()

                # Add assistant response to history
                self.history.append({"role": "assistant", "content": response})
                self._cap_history()

                # Update statistics
                self.messages_sent += 1
                input_tokens = len(prompt) // 4
                output_tokens = len(response) // 4
                self.estimated_tokens += input_tokens + output_tokens

                return response

            except Exception as e:
                logger.error(f"Error communicating with Claude: {e}", exc_info=True)
                # Remove user message from history since it failed
                if self.history and self.history[-1]["role"] == "user":
                    self.history.pop()
                raise

    async def get_response_stream(self) -> AsyncGenerator[str, None]:
        """
        Async generator that yields response chunks as they arrive.
        In the single-shot model, this yields the complete response at once.
        Preserved for API compatibility with streaming expectations.
        """
        if self.history and self.history[-1]["role"] == "assistant":
            yield self.history[-1]["content"]

    async def inject_context(self, page_title: str, page_slug: str) -> None:
        """
        Inject context about the current wiki page.
        This context is prepended to prompts sent to Claude.

        Args:
            page_title: Human-readable page title
            page_slug: URL-safe page identifier
        """
        async with self._lock:
            self.current_context = {
                "page_title": page_title,
                "page_slug": page_slug,
            }
            logger.debug(f"Context injected: {page_title} ({page_slug})")

    async def stop(self) -> None:
        """Mark chat manager as stopped."""
        self._started = False
        logger.info("ChatManager stopped")

    @property
    def is_alive(self) -> bool:
        """Check if the chat manager is ready to accept messages."""
        return getattr(self, "_started", False)


async def chat_websocket_handler(websocket, chat_manager: ChatManager) -> None:
    """
    WebSocket handler for wiki chat sidebar.
    Bridges browser messages to Claude subprocess and streams responses back.

    Args:
        websocket: FastAPI WebSocket connection
        chat_manager: ChatManager instance to use
    """
    try:
        await websocket.accept()

        # Ensure ChatManager is started
        if not chat_manager.is_alive:
            await chat_manager.start()

        logger.info("WebSocket client connected")

        async for message in websocket.iter_text():
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON received: {message}")
                await websocket.send_json(
                    {
                        "type": "error",
                        "content": "Invalid message format",
                    }
                )
                continue

            message_type = data.get("type")

            if message_type == "message":
                # Handle user message
                content = data.get("content", "").strip()
                if not content:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "content": "Empty message",
                        }
                    )
                    continue

                try:
                    # Check if subprocess is still alive; respawn if needed
                    if not chat_manager.is_alive:
                        await chat_manager.start()

                    # Send message and get response
                    response = await chat_manager.send_message(content)

                    # Stream response back via WebSocket
                    await websocket.send_json(
                        {
                            "type": "response",
                            "content": response,
                            "done": True,
                        }
                    )

                except Exception as e:
                    import traceback

                    logger.error(
                        f"Error processing message: {type(e).__name__}: {e}\n{traceback.format_exc()}",
                        exc_info=True
                    )
                    try:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "content": f"Error: {type(e).__name__}: {str(e) or 'unknown'}",
                            }
                        )
                    except Exception as e:
                        logger.debug(f"Error sending error response to websocket: {e}")  # WebSocket already closed

            elif message_type == "context":
                # Handle context injection
                page_title = data.get("title", "")
                page_slug = data.get("page", "")
                await chat_manager.inject_context(page_title, page_slug)
                await websocket.send_json(
                    {
                        "type": "context_updated",
                        "page": page_slug,
                        "title": page_title,
                    }
                )

            else:
                logger.warning(f"Unknown message type: {message_type}")
                await websocket.send_json(
                    {
                        "type": "error",
                        "content": f"Unknown message type: {message_type}",
                    }
                )

    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        logger.info("WebSocket client disconnected; subprocess remains alive")
