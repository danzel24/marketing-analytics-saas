"""Shared HttpOnly refresh cookie helpers (routes + middleware)."""

from __future__ import annotations

from starlette.responses import Response

from app.core.config import get_startup_settings


def set_refresh_cookie(response: Response, refresh_token: str, max_age: int) -> None:
    s = get_startup_settings()
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        max_age=max_age,
        httponly=True,
        secure=s.cookie_secure,
        samesite=s.cookie_samesite,
        path="/",
    )


def clear_refresh_cookie(response: Response) -> None:
    s = get_startup_settings()
    response.delete_cookie(
        key="refresh_token",
        path="/",
        secure=s.cookie_secure,
        samesite=s.cookie_samesite,
    )
