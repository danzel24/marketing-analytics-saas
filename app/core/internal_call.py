"""System boundary: prevents accidental use of cross-tenant / unscoped repository APIs."""

from __future__ import annotations

from app.core.domain_errors import InternalMisuseError


def require_internal_call(*, _internal_call: object) -> None:
    """
    Unscoped repository methods MUST be called with ``_internal_call=True`` (identity check).
    Omitting the flag or passing any other value raises immediately.
    """
    if _internal_call is not True:
        raise InternalMisuseError(
            "Blocked call to internal-only API: pass _internal_call=True only from vetted system "
            "code paths (never from tenant-facing handlers)."
        )
