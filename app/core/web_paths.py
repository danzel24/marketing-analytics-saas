"""Resolved paths to packaged web assets (templates, static). CWD-independent (Render-safe)."""

from __future__ import annotations

import logging
from pathlib import Path

# app/core/web_paths.py -> parents[1] == app package directory
_APP_DIR = Path(__file__).resolve().parents[1]

APP_DIR: Path = _APP_DIR
TEMPLATES_DIR: Path = _APP_DIR / "templates"
STATIC_DIR: Path = _APP_DIR / "static"

REQUIRED_TEMPLATE_FILES: tuple[str, ...] = (
    "login.html",
    "register.html",
    "dashboard.html",
    "upload.html",
    "forgot_password.html",
    "reset_password.html",
    "error_404.html",
    "error_500.html",
    "error_http.html",
)


def log_web_paths(logger: logging.Logger | None = None) -> None:
    """Log resolved dirs and whether each expected template file exists (Linux case-sensitive)."""
    lg = logger or logging.getLogger(__name__)
    lg.info(
        "web_paths app_dir=%s templates_dir=%s static_dir=%s",
        APP_DIR,
        TEMPLATES_DIR,
        STATIC_DIR,
    )
    lg.info(
        "web_paths exists dir_templates=%s dir_static=%s",
        TEMPLATES_DIR.is_dir(),
        STATIC_DIR.is_dir(),
    )
    for name in REQUIRED_TEMPLATE_FILES:
        p = TEMPLATES_DIR / name
        ok = p.is_file()
        lg.info("web_paths template name=%s path=%s exists=%s", name, p, ok)
        if not ok:
            lg.error("web_paths MISSING template file (case-sensitive on Linux): %s", p)
