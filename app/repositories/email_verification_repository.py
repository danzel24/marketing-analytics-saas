from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import or_
from sqlmodel import Session, delete, select

from app.models.db_models import EmailVerificationToken


class EmailVerificationRepository:
    def create_token(
        self,
        session: Session,
        *,
        user_id: int,
        token: str,
        expires_at: datetime,
    ) -> EmailVerificationToken:
        row = EmailVerificationToken(user_id=user_id, token=token, expires_at=expires_at)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    def get_valid_token(
        self,
        session: Session,
        *,
        token: str,
    ) -> Optional[EmailVerificationToken]:
        """Return token row only if it exists, has not been used, and has not expired."""
        now = datetime.now(tz=timezone.utc)
        row = session.exec(
            select(EmailVerificationToken).where(EmailVerificationToken.token == token)
        ).first()
        if row is None:
            return None
        if row.used:
            return None
        exp = row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now > exp:
            return None
        return row

    def mark_used(self, session: Session, *, token_row: EmailVerificationToken) -> None:
        """Stage token_row.used = True. Caller is responsible for session.commit()."""
        token_row.used = True
        session.add(token_row)

    def delete_pending_for_user(self, session: Session, *, user_id: int) -> int:
        """Delete all unused (pending) tokens for a user before issuing a new one."""
        stmt = delete(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user_id,
            EmailVerificationToken.used == False,  # noqa: E712
        )
        result = session.exec(stmt)
        session.commit()
        return int(result.rowcount or 0)

    def delete_expired(self, session: Session) -> int:
        """Delete tokens that are expired or already used. Returns count deleted."""
        now = datetime.now(tz=timezone.utc)
        stmt = delete(EmailVerificationToken).where(
            or_(
                EmailVerificationToken.expires_at < now,
                EmailVerificationToken.used == True,  # noqa: E712
            )
        )
        result = session.exec(stmt)
        session.commit()
        return int(result.rowcount or 0)
