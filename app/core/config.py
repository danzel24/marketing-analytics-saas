from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from app.core.domain_errors import InvalidClientIdError

logger = logging.getLogger(__name__)

_TENANT_SEGMENT_RE = re.compile(r"^[a-z0-9-]{1,128}$")


def get_jwt_secret_str() -> str:
    """
    Return JWT signing secret from ``JWT_SECRET``.

    Fails fast when unset or too short — never use a default secret in production.
    """
    raw = os.getenv("JWT_SECRET", "").strip()
    if not raw:
        raise RuntimeError(
            "JWT_SECRET is not set. Set a strong secret in the environment before starting the application."
        )
    if len(raw) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters.")
    return raw


def get_jwt_secret_bytes() -> bytes:
    return get_jwt_secret_str().encode("utf-8")


def normalize_tenant_path_segment(tenant_id: str) -> str:
    """
    Strict tenant directory segment: only ``a-z``, ``0-9``, ``-``; no path separators or ``..``.
    """
    s = tenant_id.strip()
    if not _TENANT_SEGMENT_RE.fullmatch(s):
        raise InvalidClientIdError("Invalid tenant identifier")
    return s


def _parse_bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _parse_samesite() -> Literal["lax", "strict", "none"]:
    v = os.getenv("COOKIE_SAMESITE", "lax").strip().lower()
    if v in ("lax", "strict", "none"):
        return v  # type: ignore[return-value]
    return "lax"


@dataclass(frozen=True)
class Settings:
    data_csv_path: Path
    tenants_data_dir: Path
    """When True, ``/api/v1/dashboard/full?calc_debug=1`` may include a ``calc_debug`` block."""
    dashboard_calc_debug: bool


def _parse_feedback_settings() -> tuple[str | None, str, bool]:
    """
    Optional feedback CTA: ``FEEDBACK_URL`` (https form, etc.) or ``FEEDBACK_EMAIL`` (mailto).
    If both are set, URL wins. Label from ``FEEDBACK_LINK_TEXT`` (default Czech).
    """
    label_raw = (os.getenv("FEEDBACK_LINK_TEXT") or "").strip()
    label = label_raw or "Poslat zpětnou vazbu"

    raw_url = os.getenv("FEEDBACK_URL", "").strip()
    raw_email = os.getenv("FEEDBACK_EMAIL", "").strip()

    if raw_url:
        low = raw_url.lower()
        if low.startswith("javascript:") or low.startswith("data:"):
            return None, label, False
        new_tab = low.startswith("http://") or low.startswith("https://")
        return raw_url, label, new_tab

    if raw_email and "@" in raw_email:
        subj = quote("Zpětná vazba — Marketingový přehled", safe="")
        return f"mailto:{raw_email}?subject={subj}", label, False

    return None, label, False


@dataclass(frozen=True)
class StartupSettings:
    """Validated once at process startup (web or worker)."""

    app_env: str
    is_production: bool
    cookie_secure: bool
    cookie_samesite: Literal["lax", "strict", "none"]
    enable_background_sync: bool
    enable_google_ads_user_api: bool
    enable_legacy_v1_csv_campaigns: bool
    data_csv_path: Path
    tenants_data_dir: Path
    feedback_href: str | None
    feedback_label: str
    feedback_open_new_tab: bool


def get_settings() -> Settings:
    """
    Minimal config layer ready for SaaS extension (envs, per-tenant config, etc.).
    """
    base_dir = Path(__file__).resolve().parents[2]  # .../python-projekty
    default_csv = base_dir / "data" / "ads_report.csv"
    tenants_dir = base_dir / "data" / "tenants"
    csv_path = Path(os.getenv("ADS_REPORT_CSV_PATH", str(default_csv))).resolve()
    dbg = _parse_bool_env("DASHBOARD_CALC_DEBUG", False)
    return Settings(
        data_csv_path=csv_path,
        tenants_data_dir=tenants_dir.resolve(),
        dashboard_calc_debug=dbg,
    )


@lru_cache(maxsize=1)
def get_startup_settings() -> StartupSettings:
    """
    Load environment-derived operational settings (cookie flags, background jobs).

    Call :func:`validate_startup_config` before relying on this in production.
    """
    app_env = os.getenv("APP_ENV", "development").strip().lower() or "development"
    is_production = app_env in {"prod", "production"}

    cookie_secure = _parse_bool_env("COOKIE_SECURE", is_production)
    samesite = _parse_samesite()
    if samesite == "none" and not cookie_secure:
        raise RuntimeError(
            "COOKIE_SAMESITE=none requires COOKIE_SECURE=true (SameSite=None cookies must be Secure)."
        )

    enable_background_sync = _parse_bool_env("ENABLE_BACKGROUND_SYNC", False)
    enable_google_ads_user_api = _parse_bool_env("ENABLE_GOOGLE_ADS_USER_API", False)
    enable_legacy_v1_csv_campaigns = _parse_bool_env("ENABLE_LEGACY_V1_CSV_CAMPAIGNS", False)

    st = get_settings()
    data_csv = st.data_csv_path
    tenants = st.tenants_data_dir
    fb_href, fb_label, fb_new_tab = _parse_feedback_settings()

    return StartupSettings(
        app_env=app_env,
        is_production=is_production,
        cookie_secure=cookie_secure,
        cookie_samesite=samesite,
        enable_background_sync=enable_background_sync,
        enable_google_ads_user_api=enable_google_ads_user_api,
        enable_legacy_v1_csv_campaigns=enable_legacy_v1_csv_campaigns,
        data_csv_path=data_csv,
        tenants_data_dir=tenants,
        feedback_href=fb_href,
        feedback_label=fb_label,
        feedback_open_new_tab=fb_new_tab,
    )


def validate_startup_config() -> None:
    """
    Fail fast on missing/unsafe configuration. Safe to call from app startup and workers.

    Does not log secret values.
    """
    get_jwt_secret_str()
    get_startup_settings.cache_clear()
    s = get_startup_settings()

    if s.is_production and not s.cookie_secure:
        raise RuntimeError(
            "COOKIE_SECURE must be true when APP_ENV is production (HTTPS-only refresh cookies)."
        )

    db_url = os.getenv("DATABASE_URL", "").strip().lower()
    if s.is_production and (not db_url or "sqlite" in db_url):
        logger.warning(
            "production_sqlite: using SQLite (unset DATABASE_URL or sqlite:// URL). "
            "Mount persistent disk for the DB file or use PostgreSQL (DATABASE_URL)."
        )

    if s.is_production and s.enable_background_sync:
        logger.warning(
            "ENABLE_BACKGROUND_SYNC is true in a production web process: hourly Google Ads sync runs "
            "inside the web worker. Prefer a dedicated worker process unless this is intentional."
        )

    if not s.tenants_data_dir.exists():
        s.tenants_data_dir.mkdir(parents=True, exist_ok=True)

    parent = s.data_csv_path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)


def csv_path_for_tenant(settings: Settings, tenant_id: str | None) -> Path:
    """
    Tenant routing strategy (simple, file-based):
    - default: settings.data_csv_path
    - tenant: data/tenants/<tenant_id>/ads_report.csv

    ``tenant_id`` must pass :func:`normalize_tenant_path_segment`; resolved path must stay under
    ``tenants_data_dir`` (defeats path traversal / symlink escape).
    """
    base_tenants = settings.tenants_data_dir.resolve()
    if not tenant_id:
        return settings.data_csv_path
    safe = normalize_tenant_path_segment(tenant_id)
    candidate = (base_tenants / safe / "ads_report.csv").resolve()
    try:
        candidate.relative_to(base_tenants)
    except ValueError:
        raise InvalidClientIdError("Invalid tenant path") from None
    return candidate
