"""Build API error JSON bodies (shared shape for handler + docs)."""

from __future__ import annotations

from datetime import datetime, timezone


def build_error_payload(
    *,
    code: str,
    message: str,
    request_id: str,
    trace_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, dict[str, str]]:
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    tid = trace_id if trace_id is not None else request_id
    err: dict[str, str] = {
        "code": code,
        "message": message,
        "request_id": request_id,
        "trace_id": tid,
        "timestamp": ts,
    }
    return {"error": err}
