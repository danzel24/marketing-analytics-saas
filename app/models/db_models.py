from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Column, Text
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
    # email_verified: False for new registrations until the link in the welcome email is clicked.
    # Migration sets existing rows to True so pre-existing users are not affected.
    email_verified: bool = Field(default=False, index=True)


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


class Lead(SQLModel, table=True):
    """Internal admin outreach / validation (Lead OS); not scoped to SaaS tenants."""

    __tablename__ = "lead"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_name: str = Field(index=True, max_length=512)
    website: Optional[str] = Field(default=None, max_length=512)
    contact_name: Optional[str] = Field(default=None, max_length=255)
    contact_email: Optional[str] = Field(default=None, index=True, max_length=255)
    contact_linkedin: Optional[str] = Field(default=None, max_length=512)
    role: Optional[str] = Field(default=None, max_length=255)
    source: Optional[str] = Field(default=None, max_length=255)
    status: str = Field(default="new", index=True, max_length=64)
    signal_strength: str = Field(default="weak", index=True, max_length=32)
    decision_level: Optional[str] = Field(default=None, max_length=64)
    source_of_truth: Optional[str] = Field(default=None, max_length=64)
    last_contacted_at: Optional[datetime] = Field(default=None, index=True)
    next_follow_up_at: Optional[date] = Field(default=None, index=True)
    next_action: Optional[str] = Field(default=None, max_length=512)
    notes: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow, index=True)


class LeadInteraction(SQLModel, table=True):
    __tablename__ = "leadinteraction"

    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int = Field(foreign_key="lead.id", index=True)
    channel: str = Field(default="email", max_length=32)
    direction: str = Field(default="outbound", max_length=32)
    message_summary: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class EmailVerificationToken(SQLModel, table=True):
    """Single-use email verification tokens; expire after 24 hours."""

    __tablename__ = "emailverificationtoken"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    # 64-char hex string (secrets.token_hex(32))
    token: str = Field(index=True, unique=True, max_length=128)
    expires_at: datetime = Field(index=True)
    used: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)


class PasswordResetToken(SQLModel, table=True):
    """Single-use password reset tokens; expire after 1 hour."""

    __tablename__ = "passwordresettoken"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    # 64-char hex string (secrets.token_hex(32))
    token: str = Field(index=True, unique=True, max_length=128)
    expires_at: datetime = Field(index=True)
    used: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
