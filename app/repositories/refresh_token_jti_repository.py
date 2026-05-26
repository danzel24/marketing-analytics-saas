from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, delete, select

from app.models.db_models import RefreshTokenJti


class RefreshTokenJtiRepository:
    """Persistent storage for consumed refresh token ``jti`` values (replay protection)."""

    def delete_expired_before(self, session: Session, *, before: datetime) -> int:
        """Remove rows whose JWT expiry is before ``before`` (typically UTC now)."""
        stmt = delete(RefreshTokenJti).where(RefreshTokenJti.expires_at < before)
        result = session.exec(stmt)
        session.commit()
        return int(result.rowcount or 0)

    def delete_expired(self, session: Session) -> int:
        """Delete all JTI rows whose JWT expiry is in the past. Returns count deleted."""
        return self.delete_expired_before(session, before=datetime.now(timezone.utc))

    def try_consume_refresh_jti(
        self,
        session: Session,
        *,
        jti: str,
        user_id: int,
        client_id: int,
        expires_at: datetime,
    ) -> bool:
        """
        Record ``jti`` as consumed. Returns True if this call stored a new row.
        Returns False if ``jti`` was already recorded (replay / concurrent refresh).

        A DB-level UNIQUE on ``jti`` is required for concurrent safety; we also check
        existence first so replay fails even if a legacy DB missed the unique index.
        """
        existing = session.exec(select(RefreshTokenJti).where(RefreshTokenJti.jti == jti)).first()
        if existing is not None:
            return False

        row = RefreshTokenJti(
            jti=jti,
            user_id=user_id,
            client_id=client_id,
            expires_at=expires_at,
        )
        session.add(row)
        try:
            session.commit()
            return True
        except IntegrityError:
            session.rollback()
            return False
