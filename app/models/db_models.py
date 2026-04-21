from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class Client(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    margin: Optional[float] = Field(default=0.4)
    created_at: datetime = Field(default_factory=utcnow, index=True)


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    client_id: int = Field(foreign_key="client.id", index=True)
    token_version: int = Field(default=1, index=True)
    role: str = Field(default="user", index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    # last_login_at: updated on successful POST /api/v1/auth/login only (not register/refresh).
    last_login_at: Optional[datetime] = Field(default=None, index=True)


class Campaign(SQLModel, table=True):
    """Rows are scoped by (client_id, platform, name) in application logic; not only by name."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    platform: str = Field(index=True)
    client_id: int = Field(foreign_key="client.id", index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)


class CampaignMetric(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id", index=True)
    metric_date: date = Field(index=True)
    spend: float = 0.0
    revenue: float = 0.0
    clicks: int = 0
    conversions: int = 0


class Integration(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", index=True)
    platform: str = Field(index=True)
    access_token: str
    refresh_token: Optional[str] = None
    account_id: str
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)


class RefreshTokenJti(SQLModel, table=True):
    """One row per consumed refresh token ``jti`` (rotation / replay detection)."""

    __tablename__ = "refresh_token_jti"

    id: Optional[int] = Field(default=None, primary_key=True)
    jti: str = Field(index=True, unique=True, max_length=128)
    user_id: int = Field(foreign_key="user.id", index=True)
    client_id: int = Field(foreign_key="client.id", index=True)
    expires_at: datetime = Field(index=True)
    used_at: datetime = Field(default_factory=utcnow, index=True)

