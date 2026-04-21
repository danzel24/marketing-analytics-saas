"""
In-process rate limiting for sensitive auth and upload endpoints (single-worker friendly).

On multi-worker deployments each process has its own counters — use a shared store later if needed.
"""

from __future__ import annotations

import os
import threading
import time
from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.error_response import build_error_payload
from app.core.request_id import REQUEST_ID_HEADER, TRACE_ID_HEADER, get_request_id, get_trace_id

_AUTH_PATHS = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/refresh",
    }
)
_WINDOW_SEC = int(os.getenv("AUTH_RATE_LIMIT_WINDOW_SEC", "60"))
_MAX_PER_WINDOW = int(os.getenv("AUTH_RATE_LIMIT_MAX", "30"))

_UPLOAD_PREFIX = "/api/v1/upload/"
_UPLOAD_WINDOW_SEC = int(os.getenv("UPLOAD_RATE_LIMIT_WINDOW_SEC", str(_WINDOW_SEC)))
_UPLOAD_MAX_PER_WINDOW = int(os.getenv("UPLOAD_RATE_LIMIT_MAX", str(_MAX_PER_WINDOW)))

_buckets: dict[tuple[str, str], list[float]] = {}
_lock = threading.Lock()


def _parse_bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _client_ip(request: Request) -> str:
    if _parse_bool_env("TRUST_PROXY_HEADERS", False):
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _rate_limit_json_response(request: Request) -> JSONResponse:
    request_id = get_request_id(request) or "none"
    trace_id = get_trace_id(request) or request_id
    payload = build_error_payload(
        code="rate_limited",
        message="Too many requests. Please try again later.",
        request_id=request_id,
        trace_id=trace_id,
    )
    response = JSONResponse(status_code=429, content=payload)
    response.headers[REQUEST_ID_HEADER] = request_id
    response.headers[TRACE_ID_HEADER] = trace_id
    return response


def auth_rate_limit_response_or_none(request: Request) -> JSONResponse | None:
    if request.method != "POST":
        return None
    path = request.url.path
    if path not in _AUTH_PATHS:
        return None

    ip = _client_ip(request)
    key = (ip, path)
    now = time.monotonic()
    with _lock:
        lst = [t for t in _buckets.get(key, []) if t > now - _WINDOW_SEC]
        if len(lst) >= _MAX_PER_WINDOW:
            pass
        else:
            lst.append(now)
            _buckets[key] = lst
            return None

    return _rate_limit_json_response(request)


def upload_rate_limit_response_or_none(request: Request) -> JSONResponse | None:
    """One shared counter per client IP for all POST ``/api/v1/upload/*`` routes."""
    if request.method != "POST":
        return None
    path = request.url.path
    if not path.startswith(_UPLOAD_PREFIX):
        return None

    ip = _client_ip(request)
    key = (ip, "__upload__")
    now = time.monotonic()
    with _lock:
        lst = [t for t in _buckets.get(key, []) if t > now - _UPLOAD_WINDOW_SEC]
        if len(lst) >= _UPLOAD_MAX_PER_WINDOW:
            pass
        else:
            lst.append(now)
            _buckets[key] = lst
            return None

    return _rate_limit_json_response(request)
