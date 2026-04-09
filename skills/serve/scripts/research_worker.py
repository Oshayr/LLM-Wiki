"""
Background research worker that processes tasks from ResearchQueue.

Spawns 'claude -p' subprocesses to research wiki topics, monitors progress,
and updates the queue and wiki store as tasks complete.
"""

import json
import logging
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """
    Estimate token count from text.

    Uses a simple heuristic: approximately 1 token per 4 characters.

    Args:
        text: Text to estimate tokens for

    Returns:
        Approximate token count
    """
    return len(text) // 4


class ResearchWorkerPool:
    """
    Thread pool that processes research tasks via 'claude -p' subprocesses.

    Each worker thread:
    1. Dequeues a task from ResearchQueue
    2. Builds a claude command based on task_type and parameters
    3. Spawns subprocess with stdout/stderr capture
    4. Monitors progress by parsing subprocess output
    5. Updates queue and wiki store on completion or failure
    """

    def __init__(
        self,
        queue: "ResearchQueue",
        wiki_store: "WikiStore",
        wiki_dir: str,
        num_workers: int = 2,
    ):
        """
        Initialize the worker pool.

        Args:
            queue: ResearchQueue instance to pull tasks from
            wiki_store: WikiStore instance to refresh pages on completion
            wiki_dir: Path to .wiki directory (for claude to write pages into)
            num_workers: Number of concurrent worker threads (default 2)
        """
        self.queue = queue
        self.wiki_store = wiki_store
        self.wiki_dir = Path(wiki_dir)
        self.num_workers = num_workers

        self._running = False
        self._stop_event = threading.Event()
        self._worker_threads = []
        self._active_subprocesses = {}  # task_id -> Popen instance
        self._process_lock = threading.Lock()

        # Pre-computed prompt fragments (avoids rebuilding ~400 tokens per task)
        self._depth_instructions = {
            "stub": "Write a brief 2-3 sentence summary. Use only 1 web search. Keep it under 100 words.",
            "summary": "Write a 2-3 paragraph summary. Use 2-3 web searches. Cover key points.",
            "full": (
                "Research thoroughly using a complexity-adaptive search strategy:\n\n"
                "## Search Strategy\n"
                "1. **Classify complexity**: Is this a simple factual topic (1-2 searches) or broad (3-5)?\n"
                "2. **Generate 2-3 diverse query variants** — don't repeat similar searches\n"
                "3. **After each result, evaluate quality** — if 3+ authoritative sources agree, STOP and write\n"
                "4. **Maximum 5 searches** — quality over quantity\n\n"
                "## Quality Gate\n"
                "Before writing, verify: at least 2 independent sources, key facts with dates/numbers.\n"
                "If not, do ONE more targeted search. Then write regardless."
            ),
        }
        self._image_instructions = (
            "\n## Inline Links & Images\n\n"
            "- **Web links**: Include inline hyperlinks to authoritative sources. "
            "Use `[text](url)` so readers can follow references.\n"
            "- **Images**: Embed relevant images as `![alt](url)` — diagrams, photos, logos. "
            "Sources: Wikimedia Commons, official sites. Place at least 1 near top.\n"
            "- List each source in frontmatter `sources:` array."
        )

    def start(self) -> None:
        """Start all worker threads."""
        if self._running:
            logger.warning("Worker pool already running")
            return

        self._running = True
        self._stop_event.clear()

        for i in range(self.num_workers):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"ResearchWorker-{i}",
                daemon=False,
            )
            thread.start()
            self._worker_threads.append(thread)

        logger.info(f"Started {self.num_workers} research worker threads")

    def stop(self) -> None:
        """Signal workers to stop and wait for threads to finish."""
        if not self._running:
            logger.warning("Worker pool not running")
            return

        logger.info("Stopping research worker pool...")
        self._stop_event.set()

        # Terminate any running subprocesses
        with self._process_lock:
            for task_id, proc in list(self._active_subprocesses.items()):
                try:
                    logger.debug(
                        f"Terminating subprocess for task {task_id} (PID {proc.pid})"
                    )
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        logger.warning(f"Force-killing subprocess for task {task_id}")
                        proc.kill()
                        proc.wait()
                except Exception as e:
                    logger.error(
                        f"Error terminating subprocess for task {task_id}: {e}", exc_info=True
                    )

            self._active_subprocesses.clear()

        # Wait for all worker threads
        for thread in self._worker_threads:
            thread.join(timeout=10)
            if thread.is_alive():
                logger.warning(f"Worker thread {thread.name} did not stop cleanly")

        self._worker_threads.clear()
        self._running = False
        logger.info("Research worker pool stopped")

    @property
    def is_running(self) -> bool:
        """Return whether the worker pool is running."""
        return self._running

    def kill_task(self, task_id: int) -> bool:
        """
        Kill the subprocess for a specific task (used when cancelling an active task).

        Args:
            task_id: Task ID whose subprocess should be killed

        Returns:
            True if a subprocess was found and killed, False otherwise
        """
        with self._process_lock:
            proc = self._active_subprocesses.get(task_id)
            if proc is None:
                return False

            try:
                logger.info(
                    f"Killing subprocess for cancelled task {task_id} (PID {proc.pid})"
                )
                proc.kill()
                proc.wait(timeout=5)
            except Exception as e:
                logger.error(f"Error killing subprocess for task {task_id}: {e}", exc_info=True)

            self._active_subprocesses.pop(task_id, None)
            return True

    def _worker_loop(self) -> None:
        """Main loop for a single worker thread."""
        thread_name = threading.current_thread().name
        logger.info(f"{thread_name} started")

        while not self._stop_event.is_set():
            # Try to dequeue a task
            task = self.queue.dequeue()

            if task is None:
                # Queue is empty, sleep briefly and retry
                time.sleep(2)
                continue

            task_id = task["id"]
            task_type = task["task_type"]

            try:
                logger.info(
                    f"{thread_name} processing task {task_id} ({task_type}): {task['slug']}"
                )

                # Build and run the claude command
                self._process_task(task)

                # Mark complete
                self.queue.complete(task_id)
                logger.info(f"{thread_name} completed task {task_id}")

                # Refresh the page in wiki store
                self.wiki_store.refresh_page(task["slug"])

                # Stub-first auto-upgrade: if a summary task just completed for
                # page_create, enqueue a full-depth follow-up at low priority.
                task_depth = task.get("depth", "full")
                if task_type == "page_create" and task_depth == "summary":
                    self.queue.enqueue(
                        slug=task["slug"],
                        query=task.get("query", task["slug"]),
                        task_type="page_create",
                        priority="low",
                        depth="full",
                    )
                    logger.info(f"Auto-enqueued full-depth upgrade for {task['slug']}")

            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                logger.error(
                    f"{thread_name} failed task {task_id}: {error_msg}",
                    exc_info=True,
                )
                self.queue.fail(task_id, error_msg)

        logger.info(f"{thread_name} stopping")

    def _process_task(self, task: dict[str, Any]) -> None:
        """
        Process a single research task by spawning a claude subprocess.

        Args:
            task: Task dict from queue

        Raises:
            Exception on failure (will be caught and recorded by queue.fail)
        """
        task_id = task["id"]
        task_type = task["task_type"]
        slug = task["slug"]
        query = task.get("query")
        section = task.get("section")
        depth = task.get("depth", "full")

        # Build the prompt based on task type
        if task_type == "page_create":
            if not query:
                raise ValueError("page_create task requires 'query'")
            prompt = self._build_page_create_prompt(query, slug, depth)

        elif task_type == "section_expand":
            if not section:
                raise ValueError("section_expand task requires 'section'")
            prompt = self._build_section_expand_prompt(slug, section, depth)

        elif task_type == "search_fill":
            if not query:
                raise ValueError("search_fill task requires 'query'")
            prompt = self._build_search_fill_prompt(query, slug, depth)

        else:
            raise ValueError(f"Unknown task_type: {task_type}")

        # Spawn the subprocess
        self._run_claude_subprocess(task_id, prompt, task_type, depth)

    def _build_page_create_prompt(
        self, query: str, slug: str, depth: str = "full"
    ) -> str:
        """
        Build prompt for page_create task.

        Args:
            query: The topic to research
            slug: The page slug
            depth: Research depth ('stub', 'summary', or 'full')
        """
        today = datetime.utcnow().strftime("%Y-%m-%d")
        title = self._slugify_to_title(slug)

        pages_dir = self.wiki_dir / "pages"
        index_path = self.wiki_dir / "index.md"
        page_path = pages_dir / f"{slug}.md"

        depth_instruction = self._depth_instructions.get(
            depth, self._depth_instructions["full"]
        )

        return f"""You are a wiki research agent. All file paths are absolute.

Research the topic '{query}':
{depth_instruction}

IMPORTANT: Be efficient. Search → evaluate → write. Stop searching as soon as you have enough material. Write immediately — do not over-research.

1. Use WebSearch with diverse query variants (not repetitive searches)
2. Synthesize findings into a wiki page
3. Create the page at {page_path} with this frontmatter:
   ---
   title: {title}
   type: concept
   confidence: medium
   sources:
     - url: <source_url>
       title: <source_title>
   related: [[related-slug-1]], [[related-slug-2]]
   created: {today}
   updated: {today}
   ---
4. Include [[wiki-links]] to related concepts throughout the text
5. Update {index_path} to include this page
6. Structure with ## sections for Overview, Key Concepts, Details, See Also
{self._image_instructions if depth == "full" else ""}

Be factual and comprehensive. Cite sources."""

    def _build_section_expand_prompt(
        self, slug: str, section: str, depth: str = "full"
    ) -> str:
        """
        Build prompt for section_expand task.

        Args:
            slug: The page slug
            section: The section heading to expand
            depth: Research depth ('stub', 'summary', or 'full')
        """
        _expand = {
            "stub": "Expand to 1.5x with 1 search.",
            "summary": "Expand to 2-3x with 2-3 searches.",
            "full": "Expand to 3-5x with thorough research.",
        }
        depth_instruction = _expand.get(depth, _expand["full"])
        page_path = self.wiki_dir / "pages" / f"{slug}.md"

        return f"""You are a wiki research agent. All file paths are absolute.

Read the wiki page at {page_path}.
Find the section '## {section}' (or ### {section}).
Research that specific subtopic in greater depth:
1. Use WebSearch for detailed, authoritative information
2. {depth_instruction}
3. Add subsections if appropriate
4. Add [[wiki-links]] for new concepts discovered
5. Include inline hyperlinks: `[descriptive text](https://url)` to sources you reference
6. Add relevant images: `![alt text](https://image-url)` — diagrams, photos, or illustrations related to the section topic
7. Preserve the rest of the page unchanged

Write the updated page back to the same file."""

    def _build_search_fill_prompt(
        self, query: str, slug: str, depth: str = "full"
    ) -> str:
        """
        Build prompt for search_fill task.

        Args:
            query: The search query
            slug: The page slug
            depth: Research depth ('stub', 'summary', or 'full')
        """
        depth_instruction = self._depth_instructions.get(
            depth, self._depth_instructions["full"]
        )
        pages_dir = self.wiki_dir / "pages"
        index_path = self.wiki_dir / "index.md"
        page_path = pages_dir / f"{slug}.md"

        return f"""You are a wiki research agent. All file paths are absolute.

The user searched for '{query}' but no wiki page exists.
Research this topic and create a wiki page:
{depth_instruction}

IMPORTANT: Be efficient. Search → read key results → write the page. Do not do more than 5 web searches total. If you have enough information, stop searching and start writing immediately.

1. Generate a good slug from the query
2. Research with WebSearch (3-5 searches max)
3. Create {page_path} with proper frontmatter (include sources with URLs)
4. Update {index_path}
5. Include [[wiki-links]] to related concepts
6. Include inline hyperlinks: `[descriptive text](https://url)` to authoritative sources throughout the text
7. Include relevant images: `![alt text](https://image-url)` — at least 1 near the top, more in sections as relevant. Use direct image URLs from Wikimedia Commons, official sites, or other reliable sources."""

    def _slugify_to_title(self, slug: str) -> str:
        """Convert slug to Title Case."""
        # Replace hyphens and underscores with spaces, then title case
        words = slug.replace("-", " ").replace("_", " ").split()
        return " ".join(word.capitalize() for word in words)

    def _run_claude_subprocess(
        self,
        task_id: int,
        prompt: str,
        task_type: str = "page_create",
        depth: str = "full",
    ) -> None:
        """
        Spawn a 'claude -p' subprocess and monitor progress in real time.

        Merges stderr into stdout (one pipe) so we can read line-by-line
        for progress without the classic two-pipe deadlock. A reader thread
        drains output and updates progress, while the main thread waits
        for process exit with a timeout.

        Args:
            task_id: Task ID for progress tracking
            prompt: Prompt to send to claude
            task_type: Type of task (for model selection)
            depth: Research depth (for timeout and model selection)

        Raises:
            Exception on subprocess failure or timeout
        """
        # Select model explicitly — NEVER leave it to CLI default (which inherits
        # the user's current session model, potentially opus at $75/MTok output).
        # - haiku for stubs, summaries, and section expansion (read+extend, not deep synthesis)
        # - sonnet for full page_create and search_fill (broad research + synthesis)
        if depth in ("stub", "summary"):
            model = "haiku"
        elif task_type == "section_expand":
            model = "haiku"  # Section expand is targeted read+write, not broad research
        else:
            model = "sonnet"

        # Build claude command — prompt goes via stdin, not as argument.
        # --output-format stream-json streams real-time JSON events so we
        # can track progress (tool calls, results) as they happen.
        # --max-budget-usd prevents runaway spending on broad topics.
        allowed_tools = "WebSearch,WebFetch,Read,Write,Edit,Bash"
        budget = "2.00" if depth == "full" else "0.50"
        cmd = [
            "claude",
            "-p",
            "--verbose",
            "--output-format",
            "stream-json",
            "--max-budget-usd",
            budget,
            "--allowedTools",
            allowed_tools,
            "--model",
            model,
        ]

        # Generous timeouts — web research with multiple searches takes time
        timeout = 600 if depth == "full" else 180

        logger.info(
            f"Task {task_id}: spawning claude subprocess (model={model or 'default'}, timeout={timeout}s)"
        )

        # Collected output for post-mortem on failure
        output_lines = []

        try:
            # Merge stderr into stdout so there's only ONE pipe to read.
            # This eliminates the deadlock where stdout blocks because
            # stderr's buffer is full (or vice versa).
            # cwd=tempdir avoids picking up project .claude/ hooks that would
            # inject SessionStart context (~40K tokens) and often crash the subprocess.
            safe_cwd = tempfile.gettempdir()
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=safe_cwd,
            )

            # Write prompt to stdin and close it so claude starts processing
            proc.stdin.write(prompt)
            proc.stdin.close()

            with self._process_lock:
                self._active_subprocesses[task_id] = proc

            # Reader thread: drains stdout line-by-line for progress detection.
            # With --output-format stream-json, each line is a JSON event like:
            #   {"type":"assistant","message":{"content":[{"type":"tool_use","name":"WebSearch",...}]}}
            #   {"type":"result","result":"...","cost_usd":0.05}
            detected_stages = set()
            last_tool = [None]  # mutable for closure

            def reader():
                try:
                    for line in proc.stdout:
                        output_lines.append(line)
                        stripped = line.strip()
                        if not stripped:
                            continue

                        # Try to parse as JSON stream event
                        try:
                            evt = json.loads(stripped)
                        except (json.JSONDecodeError, ValueError):
                            continue

                        stage = None
                        evt_type = evt.get("type", "")

                        # Detect tool use from assistant messages
                        if evt_type == "assistant":
                            msg = evt.get("message", {})
                            for block in msg.get("content", []):
                                if block.get("type") == "tool_use":
                                    tool_name = block.get("name", "")
                                    last_tool[0] = tool_name
                                    if tool_name in ("WebSearch", "WebFetch"):
                                        stage = "searching"
                                    elif tool_name == "Read":
                                        stage = "analyzing"
                                    elif tool_name in ("Write", "Edit"):
                                        stage = "writing"
                                    elif tool_name == "Bash":
                                        stage = "indexing"

                                    if stage and stage not in detected_stages:
                                        detected_stages.add(stage)
                                        logger.info(
                                            f"Task {task_id}: stage → {stage} (tool: {tool_name})"
                                        )
                                        try:
                                            self.queue.update_progress(task_id, stage)
                                        except Exception as e:
                                            logger.debug(f"Error updating progress for task {task_id}: {e}")

                        # Detect completion
                        elif evt_type == "result":
                            cost = evt.get("cost_usd")
                            if cost:
                                logger.info(f"Task {task_id}: cost ${cost:.4f}")

                except Exception as e:
                    logger.debug(f"Error reading subprocess output: {e}")  # Process may have been killed

            reader_thread = threading.Thread(
                target=reader, name=f"OutputReader-{task_id}", daemon=True
            )
            reader_thread.start()

            # Wait for process exit with timeout
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning(
                    f"Task {task_id}: subprocess timeout ({timeout}s), killing..."
                )
                proc.kill()
                proc.wait()
                raise RuntimeError(
                    f"Claude subprocess timed out after {timeout} seconds"
                )
            finally:
                # Let reader thread finish draining
                reader_thread.join(timeout=5)

            # Check return code
            if proc.returncode != 0:
                error_tail = (
                    "".join(output_lines[-20:]) if output_lines else "(no output)"
                )
                raise RuntimeError(
                    f"Claude subprocess failed with code {proc.returncode}: {error_tail[:500]}"
                )

            all_output = "".join(output_lines)
            estimated_tokens = _estimate_tokens(all_output)
            logger.info(
                f"Task {task_id}: completed ({estimated_tokens} est. tokens, stages: {detected_stages or 'none detected'})"
            )

        finally:
            with self._process_lock:
                self._active_subprocesses.pop(task_id, None)

    def _monitor_subprocess_progress(
        self, task_id: int, proc: subprocess.Popen
    ) -> None:
        """
        Monitor subprocess output for progress indicators.

        Parses stdout for explicit progress markers: [PROGRESS:stage]
        Falls back to keyword detection if markers are not found.

        Supported stages: searching, analyzing, writing, indexing

        Args:
            task_id: Task ID
            proc: Popen subprocess instance
        """
        # Pattern for explicit progress markers
        progress_pattern = re.compile(r"\[PROGRESS:(\w+)\]")

        detected_stages = set()

        # Keywords for fallback detection
        search_keywords = ["search", "websearch", "finding sources"]
        analyze_keywords = ["reading", "analyzing", "source", "synthesiz"]
        write_keywords = ["writing", "creating", "page", "markdown"]
        index_keywords = ["index", "updating", "update"]

        while proc.poll() is None:
            try:
                # Read a line from stdout with timeout
                # (non-blocking approach using select would be better, but this is simpler)
                if proc.stdout:
                    line = proc.stdout.readline()
                    if not line:
                        time.sleep(0.5)
                        continue

                    # Try to match explicit progress marker first
                    match = progress_pattern.search(line)
                    stage = None

                    if match:
                        stage = match.group(1)
                    else:
                        # Fallback to keyword detection
                        line_lower = line.lower()
                        if any(kw in line_lower for kw in search_keywords):
                            stage = "searching"
                        elif any(kw in line_lower for kw in analyze_keywords):
                            stage = "analyzing"
                        elif any(kw in line_lower for kw in write_keywords):
                            stage = "writing"
                        elif any(kw in line_lower for kw in index_keywords):
                            stage = "indexing"

                    # Update queue if we detected a new stage
                    if stage and stage not in detected_stages:
                        detected_stages.add(stage)
                        logger.debug(f"Task {task_id}: detected stage '{stage}'")
                        self.queue.update_progress(task_id, stage)

            except Exception as e:
                logger.debug(f"Task {task_id}: error reading subprocess output: {e}", exc_info=True)
                time.sleep(0.5)


def main():
    """Quick test/demo of the worker pool."""
    # This would require imports of ResearchQueue and WikiStore
    # Left as a stub for now
    logger.info("research_worker module loaded")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    main()
