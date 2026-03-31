from __future__ import annotations

import logging
import os
from collections.abc import Generator
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlmodel import Session, create_engine

logger = logging.getLogger(__name__)


def _resolve_database_url() -> str:
    """
    Prefer ``DATABASE_URL`` (PostgreSQL, absolute SQLite path on a volume, etc.).
    Fallback: project-root ``marketing.db`` (local dev).
    """
    explicit = os.getenv("DATABASE_URL", "").strip()
    if explicit:
        return explicit
    db_path = (Path(__file__).resolve().parents[1] / "marketing.db").resolve()
    return f"sqlite:///{db_path.as_posix()}"


DATABASE_URL = _resolve_database_url()


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    # PostgreSQL and other servers: avoid stale connections after idle timeouts.
    return {"pool_pre_ping": True}


engine = create_engine(DATABASE_URL, **_engine_kwargs(DATABASE_URL))


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
