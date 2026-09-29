"""Structured, redacted application logging.

The application never logs request bodies or dialogue text.  This module adds
defence in depth for values that could still be included accidentally by a
future log statement.
"""

from __future__ import annotations

import json
import logging
import os
import re
import traceback
from datetime import UTC, datetime
from typing import Any


_SENSITIVE_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "DATABASE_URL")
_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_-]?key|password|secret|token)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(https?://[^:/\s]+:)[^@/\s]+(@)"),
)


def _known_secrets() -> tuple[str, ...]:
    values: set[str] = set()
    for name, value in os.environ.items():
        if value and len(value) >= 6 and any(marker in name.upper() for marker in _SENSITIVE_ENV_MARKERS):
            values.add(value)
    return tuple(sorted(values, key=len, reverse=True))


def redact(value: Any) -> Any:
    """Recursively redact secrets while keeping log fields machine-readable."""

    if isinstance(value, dict):
        return {str(key): redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value

    result = value
    for secret in _known_secrets():
        result = result.replace(secret, "[REDACTED]")
    for pattern in _PATTERNS:
        result = pattern.sub(r"\1[REDACTED]\2" if pattern.groups >= 2 else r"\1[REDACTED]", result)
    return result


class StructuredRedactingFormatter(logging.Formatter):
    """Render one compact JSON object per log entry."""

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", None) or record.getMessage()
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": event,
        }
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload.update(context)
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
            payload["traceback"] = "".join(traceback.format_exception(*record.exc_info))[-6000:]
        return json.dumps(redact(payload), ensure_ascii=False, separators=(",", ":"), default=str)


def configure_logging() -> logging.Logger:
    """Configure the project logger once without dumping global configuration."""

    base = logging.getLogger("negotiation_arena")
    base.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    if not any(getattr(handler, "_arena_handler", False) for handler in base.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredRedactingFormatter())
        handler._arena_handler = True  # type: ignore[attr-defined]
        base.addHandler(handler)
    base.propagate = False
    return base


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    exc_info: bool = False,
    **context: Any,
) -> None:
    """Write a structured event with redaction applied by the formatter."""

    logger.log(
        level,
        event,
        extra={"event": event, "context": context},
        exc_info=exc_info,
    )


__all__ = ["configure_logging", "log_event", "redact"]
