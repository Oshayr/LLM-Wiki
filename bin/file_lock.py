"""file_lock.py — Cross-platform advisory file locking.

Wraps fcntl (Unix) and msvcrt (Windows) behind a uniform `flock` context
manager. Used by wiki_repo to serialize concurrent reads/writes against the
local wiki clone across processes.

Usage:
    with flock(path, exclusive=True):
        ...  # holds an exclusive lock for the duration of the block
"""

from __future__ import annotations

import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

_process_lock = threading.Lock()


if sys.platform == "win32":
    import msvcrt

    @contextmanager
    def flock(path: Path, exclusive: bool = True):
        """Cross-platform file lock — Windows backend (msvcrt)."""
        path.touch(exist_ok=True)
        # msvcrt has no shared/exclusive distinction — treat all locks as exclusive.
        with _process_lock:
            fd = os.open(str(path), os.O_RDWR | os.O_BINARY)
            try:
                # Lock 1 byte at offset 0 — advisory range lock.
                while True:
                    try:
                        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                        break
                    except OSError:
                        # LK_LOCK retries 10x at 1s intervals; on final failure,
                        # fall back to no-op (lock is best-effort advisory).
                        break
                yield
            finally:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
                os.close(fd)
else:
    import fcntl

    @contextmanager
    def flock(path: Path, exclusive: bool = True):
        """Cross-platform file lock — POSIX backend (fcntl)."""
        path.touch(exist_ok=True)
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        with _process_lock:
            fd = os.open(str(path), os.O_RDWR)
            try:
                fcntl.flock(fd, mode)
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
