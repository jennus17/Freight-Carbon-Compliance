"""
Structured logging — JSON format suitable for ingest into ELK / Loki / CloudWatch.

In dev (``log_format='console'``) the formatter falls back to a human-readable
single-line format. In all environments, ``extra={...}`` fields passed to a
logger call are flattened into the top-level log document, so:

    log.info("calculation", extra={"transport_type": "truck", "co2e_kg": 12.3})

becomes

    {"timestamp": "...", "level": "INFO", "message": "calculation",
     "transport_type": "truck", "co2e_kg": 12.3}
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


# Standard LogRecord attributes that should NOT be promoted to top-level
# fields when serialising the log entry.
_RESERVED_LOGRECORD_ATTRS = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
})


class JSONFormatter(logging.Formatter):
    """One JSON object per log line, ELK-friendly."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_ATTRS:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


class ConsoleFormatter(logging.Formatter):
    """Human-readable single-line format for local development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )


def setup_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Idempotent logger setup — call once at app startup."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter() if fmt == "json" else ConsoleFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Quiet down uvicorn's own access logger — our middleware does access logging.
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False
