"""
SQLite-backed task queue for wiki research tasks.

Used by the local wiki web server to manage asynchronous research tasks
for dynamically generated wiki pages.
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

MAX_RETRIES = 1  # Failed tasks get re-enqueued once at low priority


class ResearchQueue:
    """Thread-safe SQLite-backed task queue for wiki research tasks."""

    def __init__(self, db_path: str):
        """
        Initialize the research queue with a SQLite database.

        Args:
            db_path: Path to the SQLite database file (typically state/wiki/cache/serve-queue.db)
        """
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Create a DB connection with Row factory for name-based column access."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the research_tasks table if it doesn't exist."""
        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS research_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    query TEXT,
                    section TEXT,
                    status TEXT DEFAULT 'queued',
                    priority TEXT DEFAULT 'medium',
                    depth TEXT DEFAULT 'full',
                    retry_count INTEGER DEFAULT 0,
                    progress TEXT DEFAULT '{}',
                    worker_pid INTEGER,
                    created_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT
                )
            """)

            # Add columns to existing databases that predate this schema
            for col_sql in [
                "ALTER TABLE research_tasks ADD COLUMN depth TEXT DEFAULT 'full'",
                "ALTER TABLE research_tasks ADD COLUMN retry_count INTEGER DEFAULT 0",
            ]:
                try:
                    cursor.execute(col_sql)
                    conn.commit()
                except Exception as e:
                    logger.debug(f"Column migration: {e}")  # Column already exists

            # Create index for efficient lookups by slug and status
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_slug_status
                ON research_tasks(slug, status)
            """)

            conn.commit()
            conn.close()

    def _now_iso(self) -> str:
        """Return current timestamp in ISO 8601 format."""
        return datetime.utcnow().isoformat() + "Z"

    def recover_stale(self) -> int:
        """
        Reset 'researching' tasks back to 'queued'.

        Called at server startup to recover tasks that were interrupted
        when the previous server instance was killed mid-research.

        Returns:
            Number of tasks recovered
        """
        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE research_tasks
                SET status = 'queued', started_at = NULL, worker_pid = NULL
                WHERE status = 'researching'
                """)
            count = cursor.rowcount
            conn.commit()
            conn.close()

            return count

    def enqueue(
        self,
        slug: str,
        task_type: str,
        query: str | None = None,
        section: str | None = None,
        priority: str = "medium",
        depth: str = "full",
    ) -> int:
        """
        Enqueue a research task, deduplicating if an active task exists.

        If a task with the same slug already exists in 'queued' or 'researching'
        status, returns its ID instead of creating a duplicate.

        Args:
            slug: Page slug (e.g., 'python_programming')
            task_type: Type of task ('page_create', 'section_expand', 'search_fill')
            query: Original search/click text
            section: Section heading for section_expand tasks
            priority: Task priority ('high', 'medium', 'low'). Defaults to 'medium'

        Returns:
            Task ID (int)
        """
        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            # Check for existing active task
            cursor.execute(
                """
                SELECT id FROM research_tasks
                WHERE slug = ? AND status IN ('queued', 'researching')
                LIMIT 1
                """,
                (slug,),
            )
            existing = cursor.fetchone()

            if existing:
                conn.close()
                return existing[0]

            # Create new task
            created_at = self._now_iso()
            cursor.execute(
                """
                INSERT INTO research_tasks
                (slug, task_type, query, section, status, priority, depth, progress, created_at)
                VALUES (?, ?, ?, ?, 'queued', ?, ?, '{}', ?)
                """,
                (slug, task_type, query, section, priority, depth, created_at),
            )
            task_id = cursor.lastrowid
            conn.commit()
            conn.close()

            return task_id

    def dequeue(self) -> dict[str, Any] | None:
        """
        Pick the highest-priority queued task, transition it to 'researching'.

        Picks highest priority first (high > medium > low), then oldest within
        the same priority level.

        Returns:
            Task dict or None if queue is empty
        """
        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            # Get highest priority queued task
            # Priority order: high (0) > medium (1) > low (2)
            cursor.execute("""
                SELECT * FROM research_tasks
                WHERE status = 'queued'
                ORDER BY
                    CASE priority
                        WHEN 'high' THEN 0
                        WHEN 'medium' THEN 1
                        WHEN 'low' THEN 2
                        ELSE 1
                    END,
                    created_at ASC
                LIMIT 1
                """)
            row = cursor.fetchone()

            if not row:
                conn.close()
                return None

            task_id = row[0]

            # Transition to researching
            started_at = self._now_iso()
            cursor.execute(
                """
                UPDATE research_tasks
                SET status = 'researching', started_at = ?
                WHERE id = ?
                """,
                (started_at, task_id),
            )
            conn.commit()

            # Fetch the updated row
            cursor.execute("SELECT * FROM research_tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            conn.close()

            return self._row_to_dict(row)

    def update_progress(self, task_id: int, stage: str, detail: str = "") -> None:
        """
        Update task progress with a stage name and optional detail.

        Args:
            task_id: Task ID
            stage: Current stage (e.g., 'searching', 'parsing', 'writing')
            detail: Optional detail message
        """
        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            progress = {"stage": stage}
            if detail:
                progress["detail"] = detail

            cursor.execute(
                """
                UPDATE research_tasks
                SET progress = ?
                WHERE id = ?
                """,
                (json.dumps(progress), task_id),
            )
            conn.commit()
            conn.close()

    def complete(self, task_id: int) -> None:
        """
        Mark a task as done.

        Args:
            task_id: Task ID
        """
        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            completed_at = self._now_iso()
            cursor.execute(
                """
                UPDATE research_tasks
                SET status = 'done', completed_at = ?
                WHERE id = ?
                """,
                (completed_at, task_id),
            )
            conn.commit()
            conn.close()

    def fail(self, task_id: int, error: str) -> None:
        """
        Mark a task as failed. If retry_count < MAX_RETRIES, auto-enqueue
        a retry at low priority instead of permanent failure.

        Args:
            task_id: Task ID
            error: Error message
        """
        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            # Check current retry count
            cursor.execute(
                "SELECT slug, task_type, query, section, depth, retry_count FROM research_tasks WHERE id = ?",
                (task_id,),
            )
            row = cursor.fetchone()

            completed_at = self._now_iso()

            if row and (row[5] or 0) < MAX_RETRIES:
                slug, task_type, query, section, depth, retry_count = row
                # Mark original as failed with retry note
                cursor.execute(
                    """
                    UPDATE research_tasks
                    SET status = 'failed', completed_at = ?, error = ?
                    WHERE id = ?
                    """,
                    (completed_at, f"[retry scheduled] {error}", task_id),
                )
                # Enqueue retry at low priority with incremented retry_count
                cursor.execute(
                    """
                    INSERT INTO research_tasks
                    (slug, task_type, query, section, status, priority, depth, retry_count, progress, created_at)
                    VALUES (?, ?, ?, ?, 'queued', 'low', ?, ?, '{}', ?)
                    """,
                    (
                        slug,
                        task_type,
                        query,
                        section,
                        depth,
                        (retry_count or 0) + 1,
                        completed_at,
                    ),
                )
            else:
                # Permanent failure — no more retries
                cursor.execute(
                    """
                    UPDATE research_tasks
                    SET status = 'failed', completed_at = ?, error = ?
                    WHERE id = ?
                    """,
                    (completed_at, error, task_id),
                )

            conn.commit()
            conn.close()

    def get_status(self, slug: str) -> dict[str, Any] | None:
        """
        Get the most recent task for a slug.

        Used for SSE streaming status updates.

        Args:
            slug: Page slug

        Returns:
            Task dict or None if no task exists
        """
        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM research_tasks
                WHERE slug = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (slug,),
            )
            row = cursor.fetchone()
            conn.close()

            if not row:
                return None

            return self._row_to_dict(row)

    def get_active_tasks(self, limit: int = 0) -> list[dict[str, Any]]:
        """
        Get all queued or researching tasks.

        Returns:
            List of task dicts
        """
        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            sql = """
                SELECT * FROM research_tasks
                WHERE status IN ('queued', 'researching')
                ORDER BY created_at ASC
                """
            if limit > 0:
                sql += f" LIMIT {int(limit)}"
            cursor.execute(sql)
            rows = cursor.fetchall()
            conn.close()

            return [self._row_to_dict(row) for row in rows]

    def get_queue_stats(self) -> dict[str, int]:
        """
        Get counts of tasks by status.

        Returns:
            Dict with keys: queued, researching, done, failed
        """
        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            stats = {"queued": 0, "researching": 0, "done": 0, "failed": 0}

            for status in stats.keys():
                cursor.execute(
                    "SELECT COUNT(*) FROM research_tasks WHERE status = ?",
                    (status,),
                )
                count = cursor.fetchone()[0]
                stats[status] = count

            conn.close()
            return stats

    def reset_stale(self, timeout_seconds: int = 300) -> int:
        """
        Reset 'researching' tasks older than timeout back to 'queued'.

        Useful for recovering from worker crashes.

        Args:
            timeout_seconds: Reset tasks that started more than this long ago

        Returns:
            Number of tasks reset
        """
        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            # Calculate cutoff timestamp
            now = datetime.utcnow()
            cutoff = (now.timestamp() - timeout_seconds) * 1000

            cursor.execute(
                """
                SELECT id FROM research_tasks
                WHERE status = 'researching'
                AND started_at IS NOT NULL
                AND datetime(started_at) < datetime('now', '-' || ? || ' seconds')
                """,
                (timeout_seconds,),
            )
            stale_ids = [row[0] for row in cursor.fetchall()]

            if stale_ids:
                placeholders = ",".join("?" * len(stale_ids))
                cursor.execute(
                    f"""
                    UPDATE research_tasks
                    SET status = 'queued', started_at = NULL, progress = '{{}}'
                    WHERE id IN ({placeholders})
                    """,
                    stale_ids,
                )
                conn.commit()

            conn.close()
            return len(stale_ids)

    def cancel(self, task_id: int) -> str | None:
        """
        Cancel a queued or researching task.

        Args:
            task_id: Task ID to cancel

        Returns:
            Previous status ('queued' or 'researching') if cancelled, None if not found/already done
        """
        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            cursor.execute("SELECT status FROM research_tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()

            if not row or row[0] not in ("queued", "researching"):
                conn.close()
                return None

            prev_status = row[0]
            cursor.execute(
                """
                UPDATE research_tasks
                SET status = 'cancelled', completed_at = ?, error = 'Cancelled by user'
                WHERE id = ?
                """,
                (self._now_iso(), task_id),
            )
            conn.commit()
            conn.close()

            return prev_status

    def reorder(self, task_id: int, direction: str) -> bool:
        """
        Move a queued task up or down in priority.

        'up' promotes: low→medium→high
        'down' demotes: high→medium→low

        Args:
            task_id: Task ID to reorder
            direction: 'up' or 'down'

        Returns:
            True if reordered, False if task not found or already at limit
        """
        priority_order = ["low", "medium", "high"]

        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT priority, status FROM research_tasks WHERE id = ?",
                (task_id,),
            )
            row = cursor.fetchone()

            if not row or row[1] != "queued":
                conn.close()
                return False

            current = row[0] or "medium"
            idx = priority_order.index(current) if current in priority_order else 1

            if direction == "up" and idx < len(priority_order) - 1:
                new_priority = priority_order[idx + 1]
            elif direction == "down" and idx > 0:
                new_priority = priority_order[idx - 1]
            else:
                conn.close()
                return False

            cursor.execute(
                "UPDATE research_tasks SET priority = ? WHERE id = ?",
                (new_priority, task_id),
            )
            conn.commit()
            conn.close()

            return True

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Get recently completed or failed tasks, most recent first.

        Useful for the research dashboard to show recent activity.

        Args:
            limit: Maximum number of tasks to return (default 50)

        Returns:
            List of task dicts sorted by completion time (newest first)
        """
        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM research_tasks
                WHERE status IN ('done', 'failed')
                ORDER BY completed_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            conn.close()

            return [self._row_to_dict(row) for row in rows]

    def get_priority_stats(self) -> dict[str, int]:
        """
        Get counts of active tasks by priority level.

        Returns:
            Dict with keys: high, medium, low (counts of queued/researching tasks)
        """
        with self._lock:
            conn = self._connect()
            cursor = conn.cursor()

            stats = {"high": 0, "medium": 0, "low": 0}

            for priority in stats.keys():
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM research_tasks
                    WHERE status IN ('queued', 'researching') AND priority = ?
                    """,
                    (priority,),
                )
                count = cursor.fetchone()[0]
                stats[priority] = count

            conn.close()
            return stats

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        """Convert a database row to a task dict.
        Works with sqlite3.Row (name-based) or plain tuple (positional fallback)."""
        if isinstance(row, sqlite3.Row):
            task = dict(row)
        else:
            # Positional fallback for legacy code paths — order matches CREATE TABLE
            columns = [
                "id",
                "slug",
                "task_type",
                "query",
                "section",
                "status",
                "priority",
                "depth",
                "retry_count",
                "progress",
                "worker_pid",
                "created_at",
                "started_at",
                "completed_at",
                "error",
            ]
            task = dict(zip(columns, row))

        # Parse progress JSON
        progress = task.get("progress")
        if progress and isinstance(progress, str):
            try:
                task["progress"] = json.loads(progress)
            except (json.JSONDecodeError, TypeError):
                task["progress"] = {}
        elif not progress:
            task["progress"] = {}

        return task
