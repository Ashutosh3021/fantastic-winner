"""Structured JSON logging with a request-scoped correlation id (§22.1).

No user text and no user code ever reach the logs. Problems log a *size* and a
*hash*; that is enough to correlate two requests without copying a learner's
answer into a log aggregator.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str] = ContextVar("request_id", default="-")

def set_request_id(value: str) -> None:
    _request_id.set(value)

def get_request_id() -> str:
    return _request_id.get()

def text_fingerprint(text: str | None) -> str:
    """A short, stable id for a piece of user text - never the text itself."""
    if not text:
        return "-"
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
        }
        for field in ("user_id_hash", "route", "latency_ms", "status", "cache", "task_id", "event"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)

def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # uvicorn installs its own noisy access logger; route it through ours.
    for name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).handlers = [handler]
        logging.getLogger(name).propagate = False

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

def hash_user_id(user_id: str | None) -> str:
    """Logs identify a user by hash, never by raw id (§22.1)."""
    if not user_id:
        return "-"
    return hashlib.sha256(f"cm:{user_id}".encode()).hexdigest()[:12]