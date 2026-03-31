"""Request correlation id: logging, error responses, downstream tracing."""

from __future__ import annotations

import contextvars
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
TRACE_ID_HEADER = "X-Trace-ID"
STATE_KEY = "request_id"
STATE_KEY_TRACE = "trace_id"

# Propagates to logging filters / any code during the request (async-safe).
request_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
trace_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)

# Safe inbound ids: UUID or short alphanumeric (load balancers / gateways)
_REQUEST_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")


def get_request_id(request: Request) -> str | None:
    return getattr(request.state, STATE_KEY, None)


def get_trace_id(request: Request) -> str | None:
    return getattr(request.state, STATE_KEY_TRACE, None)


def _normalize_incoming_request_id(raw: str | None) -> str | None:
    if not raw:
        return None
    candidate = raw.strip()
    if not candidate or len(candidate) > 128:
        return None
    if _REQUEST_ID_PATTERN.match(candidate):
        return candidate
    return None


def bind_worker_correlation_context() -> tuple[Any, Any]:
    """
    Start of thread pool / background worker: clear inherited context (async copy safety).
    Always pair with :func:`reset_worker_correlation_context` in ``finally``.
    """
    return (request_id_context.set(None), trace_id_context.set(None))


def reset_worker_correlation_context(tokens: tuple[Any, Any]) -> None:
    trace_id_context.reset(tokens[1])
    request_id_context.reset(tokens[0])


async def correlation_id_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    incoming = _normalize_incoming_request_id(request.headers.get(REQUEST_ID_HEADER))
    request_id = incoming or str(uuid.uuid4())
    trace_incoming = _normalize_incoming_request_id(request.headers.get(TRACE_ID_HEADER))
    trace_id = trace_incoming or request_id

    setattr(request.state, STATE_KEY, request_id)
    setattr(request.state, STATE_KEY_TRACE, trace_id)

    token_rid = request_id_context.set(request_id)
    token_tid = trace_id_context.set(trace_id)
    try:
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[TRACE_ID_HEADER] = trace_id
        return response
    finally:
        trace_id_context.reset(token_tid)
        request_id_context.reset(token_rid)
