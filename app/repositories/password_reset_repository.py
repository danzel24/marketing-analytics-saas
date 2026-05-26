from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.models.db_models import PasswordResetToken


class PasswordResetRepository:
    def create_token(
        self,
        session: Session,
        *,
        user_id: int,
        token: str,
        expires_at: datetime,
    ) -> PasswordResetToken:
        row = PasswordResetToken(user_id=user_id, token=token, expires_at=expires_at)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    def get_valid_token(
        self,
        session: Session,
        *,
        token: str,
    ) -> Optional[PasswordResetToken]:
        """Return token row only if it exists, has not been used, and has not expired."""
        now = datetime.now(tz=timezone.utc)
        row = session.exec(
            select(PasswordResetToken).where(PasswordResetToken.token == token)
        ).first()
        if row is None:
            return None
        if row.used:
            return None
        # expires_at may be naive (SQLite) — compare defensively
        exp = row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now > exp:
            return None
        return row

    def mark_used(self, session: Session, *, token_row: PasswordResetToken) -> None:
        """Stage token_row.used = True. Caller is responsible for session.commit()."""
        token_row.used = True
        session.add(token_row)
