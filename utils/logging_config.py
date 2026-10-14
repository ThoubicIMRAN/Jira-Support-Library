"""JSON logging with correlation IDs.

Produces single-line JSON records on stdout, suitable for ingestion by
log aggregators (Datadog, CloudWatch, Loki, etc.).

Public API:
    configure_logging(level=INFO) -> None
    new_correlation_id() -> str                 # generate without setting
    set_correlation_id(value=None) -> str       # generate + set context
    correlation_id                              # ContextVar for direct use
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "configure_logging",
    "new_correlation_id",
    "set_correlation_id",
    "correlation_id",
    "JsonFormatter",
]


correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


# Loggers that emit their own handlers and would otherwise bypass JSON.
_THIRD_PARTY_LOGGERS = ("streamlit", "sqlalchemy.engine", "urllib3")


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record on a single line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "location": f"{record.module}:{record.lineno}",
            "correlation_id": correlation_id.get(),
            "message": record.getMessage(),
        }

        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            payload["exception"] = {
                "type": getattr(exc_type, "__name__", None),
                "message": str(exc_value) if exc_value else None,
                "traceback": self.formatException(record.exc_info),
            }

        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: int | str = logging.INFO) -> None:
    """Install the JSON formatter on the root logger (idempotent).

    Runs once per process: subsequent calls only update the level.
    """
    root = logging.getLogger()

    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)

        # Force third-party loggers to bubble up through our formatter.
        for name in _THIRD_PARTY_LOGGERS:
            logger = logging.getLogger(name)
            logger.handlers.clear()
            logger.propagate = True

    root.setLevel(level)


def new_correlation_id() -> str:
    """Return a fresh correlation id without touching the current context."""
    return uuid.uuid4().hex


def set_correlation_id(value: str | None = None) -> str:
    """Set the current context's correlation id (generating one if needed).

    Returns the value that was set.
    """
    value = value or new_correlation_id()
    correlation_id.set(value)
    return value