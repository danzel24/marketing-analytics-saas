"""
Production-oriented logging: JSON lines, request_id + trace_id on every record, access + slow-request logs.

Enable JSON output when JSON_LOGS=1/true or APP_ENV is prod/production (override with JSON_LOGS=0).
Slow request threshold: SLOW_REQUEST_MS (default 1000).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from app.core.request_id import get_request_id, get_trace_id, request_id_context, trace_id_context

ACCESS_LOGGER = logging.getLogger("app.access")

# Access / APM: warn when request handling exceeds this many milliseconds (override via env).
_SLOW_REQUEST_MS = float(os.environ.get("SLOW_REQUEST_MS", "1000"))

# Baseline keys on LogRecord; any other attribute is treated as structured ``extra``.
_BASELINE = logging.LogRecord(
    name="_",
    level=logging.INFO,
    pathname=__file__,
    lineno=1,
    msg="m",
    args=(),
    exc_info=None,
)
STANDARD_LOG_RECORD_KEYS = frozenset(_BASELINE.__dict__.keys()) | frozenset({"message", "asctime"})

_CONFIGURED = False


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


class RequestIdLoggingFilter(logging.Filter):
    """Attach ``request_id`` and ``trace_id`` (context wins; else existing extra; else ``none``)."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx_rid = request_id_context.get()
        if ctx_rid is not None:
            record.request_id = ctx_rid
        elif not hasattr(record, "request_id"):
            record.request_id = "none"

        ctx_tid = trace_id_context.get()
        if ctx_tid is not None:
            record.trace_id = ctx_tid
        elif not hasattr(record, "trace_id"):
            record.trace_id = "none"
        return True


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line: level, logger, message, request_id, trace_id, timestamp, extras, exception."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "timestamp": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "none"),
            "trace_id": getattr(record, "trace_id", "none"),
        }
        for key, value in record.__dict__.items():
            if key in STANDARD_LOG_RECORD_KEYS or key.startswith("_"):
                continue
            if key in ("request_id", "trace_id"):
                continue
            payload[key] = _json_safe(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info).rstrip()
        return json.dumps(payload, default=str, ensure_ascii=False)


def _use_json_logs() -> bool:
    raw = os.environ.get("JSON_LOGS", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    env = os.environ.get("APP_ENV", "").strip().lower()
    return env in ("prod", "production")


def _handlers_for_structured_logging() -> list[logging.Handler]:
    """Collect handlers that should receive the request-id filter (root + common uvicorn loggers)."""
    seen: set[int] = set()
    out: list[logging.Handler] = []
    names = ("", "uvicorn", "uvicorn.error", "uvicorn.access")
    for name in names:
        lg = logging.getLogger(name)
        for handler in lg.handlers:
            hid = id(handler)
            if hid not in seen:
                seen.add(hid)
                out.append(handler)
    return out


def _handler_has_request_id_filter(handler: logging.Handler) -> bool:
    return any(isinstance(f, RequestIdLoggingFilter) for f in handler.filters)


def configure_structured_logging() -> None:
    """
    Idempotent: add RequestIdLoggingFilter to root + uvicorn handlers; optionally set JsonLogFormatter on root only.
    Safe to call from FastAPI startup (after uvicorn attached handlers).
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    req_filter = RequestIdLoggingFilter()
    for handler in _handlers_for_structured_logging():
        if not _handler_has_request_id_filter(handler):
            handler.addFilter(req_filter)

    if _use_json_logs():
        json_fmt = JsonLogFormatter()
        root = logging.getLogger()
        for handler in root.handlers:
            if not isinstance(handler.formatter, JsonLogFormatter):
                handler.setFormatter(json_fmt)

    level_name = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    if level_name in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        logging.getLogger().setLevel(getattr(logging, level_name))


async def access_log_middleware(request: Request, call_next) -> Response:
    """Log method, path, status, duration_ms, request_id, trace_id; duration always recorded (incl. errors)."""
    start = time.perf_counter()
    response: Response | None = None
    try:
        response = await call_next(request)
        return response
    except BaseException:
        raise
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 3)
        status_code = int(response.status_code) if response is not None else 500
        rid = get_request_id(request) or request_id_context.get() or "none"
        tid = get_trace_id(request) or trace_id_context.get() or rid
        base_extra: dict[str, Any] = {
            "http_method": request.method,
            "http_path": request.url.path,
            "http_status": status_code,
            "duration_ms": duration_ms,
            "request_id": rid,
            "trace_id": tid,
        }
        ACCESS_LOGGER.info("http_access", extra=base_extra)
        if duration_ms > _SLOW_REQUEST_MS:
            ACCESS_LOGGER.warning(
                "slow_request",
                extra={
                    **base_extra,
                    "slow_request_threshold_ms": _SLOW_REQUEST_MS,
                },
            )
