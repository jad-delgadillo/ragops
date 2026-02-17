"""Structured JSON logging with request correlation and CloudWatch metric helpers."""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any


class JSONFormatter(logging.Formatter):
    """Emit structured JSON log lines for CloudWatch / local dev."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Attach extras (request_id, latency, etc.)
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)  # type: ignore[attr-defined]
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with JSON formatter."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Remove existing handlers to avoid duplicates in Lambda
    for h in root.handlers[:]:
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)


# ---------------------------------------------------------------------------
# Request correlation
# ---------------------------------------------------------------------------

_request_id: str = ""


def set_request_id(rid: str | None = None) -> str:
    """Set or generate a request correlation ID."""
    global _request_id
    _request_id = rid or str(uuid.uuid4())
    return _request_id


def get_request_id() -> str:
    return _request_id


# ---------------------------------------------------------------------------
# Metric helpers (CloudWatch EMF-style)
# ---------------------------------------------------------------------------


def emit_metric(namespace: str, metric_name: str, value: float, unit: str = "None") -> None:
    """Emit a structured metric log line (CloudWatch Embedded Metric Format)."""
    logger = logging.getLogger("metrics")
    metric_log = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": namespace,
                    "Dimensions": [["Environment"]],
                    "Metrics": [{"Name": metric_name, "Unit": unit}],
                }
            ],
        },
        "Environment": "local",
        metric_name: value,
        "request_id": get_request_id(),
    }
    logger.info(json.dumps(metric_log, default=str))


@contextmanager
def timed_metric(namespace: str, metric_name: str) -> Generator[None, None, None]:
    """Context manager that emits a timing metric in milliseconds."""
    start = time.perf_counter()
    yield
    elapsed_ms = (time.perf_counter() - start) * 1000
    emit_metric(namespace, metric_name, elapsed_ms, unit="Milliseconds")
