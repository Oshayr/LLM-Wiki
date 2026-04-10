"""
Shared logging configuration for LLM-Wiki.

Usage in any bin/ script:

    from wiki_logging import get_logger
    logger = get_logger(__name__)

    logger.info("Built backlink index", extra={"pages": 42})
    logger.error("Failed to fetch URL", extra={"url": url, "status": 503})

Environment variables:
    WIKI_LOG_LEVEL   — DEBUG, INFO, WARNING, ERROR (default: INFO)
    WIKI_LOG_FORMAT  — "json" or "text" (default: text)
    WIKI_LOG_FILE    — optional file path for log output
"""

import logging
import json
import os
import sys
from datetime import datetime, timezone


class StructuredFormatter(logging.Formatter):
    """JSON structured log formatter for machine-readable output."""

    def format(self, record):
        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }
        # Merge extra fields (skip standard LogRecord attributes)
        standard = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())
        for k, v in record.__dict__.items():
            if k not in standard and k not in entry:
                try:
                    json.dumps(v)
                    entry[k] = v
                except (TypeError, ValueError):
                    entry[k] = str(v)
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable formatter with optional color and extra fields."""

    COLORS = {
        "DEBUG": "\033[36m",     # cyan
        "INFO": "\033[32m",      # green
        "WARNING": "\033[33m",   # yellow
        "ERROR": "\033[31m",     # red
        "CRITICAL": "\033[1;31m",# bold red
    }
    RESET = "\033[0m"

    def __init__(self, use_color=True):
        super().__init__()
        self.use_color = use_color and hasattr(sys.stderr, "isatty") and sys.stderr.isatty()

    def format(self, record):
        level = record.levelname
        if self.use_color:
            prefix = f"{self.COLORS.get(level, '')}{level:>7}{self.RESET}"
        else:
            prefix = f"{level:>7}"

        ts = datetime.now().strftime("%H:%M:%S")
        msg = f"{ts} {prefix} [{record.name}] {record.getMessage()}"

        # Append extra fields
        standard = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())
        extras = {k: v for k, v in record.__dict__.items()
                  if k not in standard and k not in ("message", "msg")}
        if extras:
            pairs = " ".join(f"{k}={v}" for k, v in extras.items())
            msg += f"  ({pairs})"

        if record.exc_info and record.exc_info[0] is not None:
            msg += f"\n  {record.exc_info[0].__name__}: {record.exc_info[1]}"
        return msg


_configured = False


def configure_logging():
    """Configure root logging based on environment variables. Called once."""
    global _configured
    if _configured:
        return
    _configured = True

    level_name = os.environ.get("WIKI_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = os.environ.get("WIKI_LOG_FORMAT", "text").lower()
    log_file = os.environ.get("WIKI_LOG_FILE")

    root = logging.getLogger()
    root.setLevel(level)

    # Stderr handler
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    if fmt == "json":
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(TextFormatter())
    root.addHandler(handler)

    # Optional file handler (always JSON for parseability)
    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setLevel(level)
        fh.setFormatter(StructuredFormatter())
        root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger, configuring the root on first call."""
    configure_logging()
    return logging.getLogger(name)
