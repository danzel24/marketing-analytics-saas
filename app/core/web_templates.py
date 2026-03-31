"""Single Jinja2 environment + helpers for HTML pages (production-safe paths)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse

from app.core.web_paths import TEMPLATES_DIR

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def template_response(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
) -> HTMLResponse:
    """
    Render HTML via Starlette Jinja2Templates using explicit kwargs (stable across Starlette versions).
    """
    ctx: dict[str, Any] = dict(context) if context else {}
    return templates.TemplateResponse(
        request=request,
        name=name,
        context=ctx,
        status_code=status_code,
    )


def template_response_safe(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
) -> HTMLResponse | PlainTextResponse:
    """
    Same as template_response, but never raises: logs full traceback and returns plain text 500.
    Use in exception handlers so a broken error template cannot mask the root error.
    """
    try:
        return template_response(
            request=request,
            name=name,
            context=context,
            status_code=status_code,
        )
    except Exception:
        logger.exception(
            "template_render_failed template=%s http_path=%s",
            name,
            request.url.path,
        )
        return PlainTextResponse(
            "Internal Server Error",
            status_code=500,
            media_type="text/plain; charset=utf-8",
        )
