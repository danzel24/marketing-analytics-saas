from __future__ import annotations

import logging
import os
from collections.abc import Generator
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.engine.url import make_url
from sqlmodel import Session, create_engine

logger = logging.getLogger(__name__)


def _normalize_database_url(url: str) -> str:
    """
    Render/Heroku-style ``postgres://`` is not always accepted; SQLAlchemy expects ``postgresql://``.
    Does not alter query params or credentials.
    """
    u = url.strip()
    if u.startswith("postgres://"):
        return "postgresql://" + u[len("postgres://") :]
    return u


def _resolve_database_url() -> str:
    """
    Prefer ``DATABASE_URL`` (PostgreSQL on Render, explicit SQLite path, etc.).
    Fallback: project-root ``marketing.db`` (local dev).
    """
    explicit = os.getenv("DATABASE_URL", "").strip()
    if explicit:
        return _normalize_database_url(explicit)
    db_path = (Path(__file__).resolve().parents[1] / "marketing.db").resolve()
    return f"sqlite:///{db_path.as_posix()}"


DATABASE_URL = _resolve_database_url()


def _is_sqlite_url(url: str) -> bool:
    return make_url(url).drivername == "sqlite"


def _engine_kwargs(url: str) -> dict:
    if _is_sqlite_url(url):
        return {"connect_args": {"check_same_thread": False}}
    # PostgreSQL and other servers: avoid stale connections after idle timeouts.
    return {"pool_pre_ping": True}


engine = create_engine(DATABASE_URL, **_engine_kwargs(DATABASE_URL))


def log_database_startup(target: logging.Logger | None = None) -> None:
    """
    Log which database backend is active. Never logs passwords or connection secrets.
    """
    log = target or logger
    u = make_url(DATABASE_URL)
    driver = u.drivername or "unknown"
    if driver == "sqlite":
        log.info(
            "database_config kind=sqlite sqlalchemy_backend=%s database_path=%s",
            driver,
            u.database or "",
        )
        return
    kind = "postgresql" if "postgres" in driver else "other_server"
    log.info(
        "database_config kind=%s sqlalchemy_backend=%s host=%s port=%s database=%s",
        kind,
        driver,
        u.host or "",
        u.port or "",
        u.database or "",
    )


def run_alembic_upgrade() -> None:
    """Apply Alembic migrations to head (SQLite / PostgreSQL-ready URL)."""
    root = Path(__file__).resolve().parents[1]
    ini = root / "alembic.ini"
    cfg = AlembicConfig(str(ini))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(cfg, "head")


def create_db_and_tables() -> None:
    """
    Production path: Alembic migrations + legacy SQLite column alignment for old files.

    Runtime ``CREATE INDEX`` / one-off ALTER hacks were replaced by idempotent Alembic baseline
    where possible; remaining PRAGMA checks cover pre-migration SQLite DBs missing columns.
    """
    run_alembic_upgrade()
    if _is_sqlite_url(DATABASE_URL):
        _ensure_user_token_version_column()
        _ensure_client_margin_column()


def _ensure_user_token_version_column() -> None:
    """Legacy SQLite: add columns if DB predates Alembic baseline."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.exec_driver_sql('PRAGMA table_info("user")').fetchall()]
        if "token_version" not in cols:
            conn.exec_driver_sql('ALTER TABLE "user" ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1')
        if "role" not in cols:
            conn.exec_driver_sql('ALTER TABLE "user" ADD COLUMN role TEXT NOT NULL DEFAULT "user"')


def _ensure_client_margin_column() -> None:
    """Legacy SQLite: add columns if DB predates Alembic baseline."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.exec_driver_sql('PRAGMA table_info("client")').fetchall()]
        if "margin" not in cols:
            conn.exec_driver_sql('ALTER TABLE "client" ADD COLUMN margin REAL DEFAULT 0.4')
        conn.exec_driver_sql('UPDATE "client" SET margin = 0.4 WHERE margin IS NULL')


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
