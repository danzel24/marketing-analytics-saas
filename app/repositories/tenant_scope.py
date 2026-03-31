"""Shared tenant boundary validation for repositories."""

from __future__ import annotations

from app.core.domain_errors import InvalidClientIdError


def require_positive_client_id(client_id: int) -> int:
    """
    Normalize and validate tenant id. Call at the start of every repository method
    that accepts a client_id (never trust callers).
    """
    try:
        cid = int(client_id)
    except (TypeError, ValueError) as exc:
        raise InvalidClientIdError() from exc
    if cid < 1:
        raise InvalidClientIdError()
    return cid
