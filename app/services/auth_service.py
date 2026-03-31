from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session

from app.core.security import (
    REFRESH_TOKEN_EXPIRES_SECONDS,
    REFRESH_TOKEN_SHORT_EXPIRES_SECONDS,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.models.db_models import User
from app.repositories.refresh_token_jti_repository import RefreshTokenJtiRepository
from app.repositories.tenant_scope import require_positive_client_id
from app.repositories.user_repository import UserRepository

from app.core.domain_errors import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    UnauthorizedError,
)

logger = logging.getLogger(__name__)

# Client-facing refresh failures: single message to avoid leaking replay vs expiry vs malformed.
REFRESH_TOKEN_INVALID_MESSAGE = "Invalid or expired refresh token"


@dataclass(frozen=True)
class SilentRefreshResult:
    """Outcome of cookie-based silent refresh (middleware)."""

    success: bool = False
    access_token: str | None = None
    refresh_token: str | None = None
    refresh_max_age: int | None = None
    clear_refresh_cookie: bool = False


class AuthService:
    """Centralizes user ↔ JWT tenant claims validation (routes must not duplicate ownership checks)."""

    def __init__(
        self,
        repo: UserRepository | None = None,
        refresh_jti_repo: RefreshTokenJtiRepository | None = None,
    ) -> None:
        self.repo = repo or UserRepository()
        self._refresh_jti_repo = refresh_jti_repo or RefreshTokenJtiRepository()

    def load_user_matching_jwt_claims(
        self,
        session: Session,
        *,
        user_id: int,
        jwt_client_id: int,
        jwt_token_version: int,
    ) -> User:
        """
        Resolve DB user and enforce ``user.client_id == jwt_client_id`` and token version.
        Raises :class:`UnauthorizedError` on any mismatch (same response shape as invalid token).
        """
        user = self.repo.get_by_id_unscoped_internal(session, user_id, _internal_call=True)
        if user is None:
            raise UnauthorizedError("Invalid token")
        if int(user.client_id) != int(jwt_client_id):
            raise UnauthorizedError("Invalid token")
        if int(getattr(user, "token_version", 1) or 1) != int(jwt_token_version):
            raise UnauthorizedError("Invalid token")
        return user

    def invalidate_refresh_session_if_claims_valid(
        self,
        session: Session,
        *,
        user_id: int,
        jwt_client_id: int,
        jwt_token_version: int,
    ) -> bool:
        """Logout: bump token version only when refresh claims match the stored user."""
        try:
            user = self.load_user_matching_jwt_claims(
                session,
                user_id=user_id,
                jwt_client_id=jwt_client_id,
                jwt_token_version=jwt_token_version,
            )
        except UnauthorizedError:
            return False
        self.repo.increment_token_version(session, user)
        return True

    def register(self, session: Session, *, email: str, password: str, client_name: str) -> User:
        if self.repo.get_by_email_unscoped_internal(session, email, _internal_call=True):
            raise EmailAlreadyRegisteredError()
        client = self.repo.get_or_create_client_unscoped_internal(
            session, name=client_name, _internal_call=True
        )
        user = self.repo.create_user(
            session,
            email=email,
            password_hash=hash_password(password),
            client_id=client.id,  # type: ignore[arg-type]
        )
        return user

    def authenticate(self, session: Session, *, email: str, password: str) -> User:
        user = self.repo.get_by_email_unscoped_internal(session, email, _internal_call=True)
        if not user or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()
        if user.id is None:
            raise InvalidCredentialsError()
        return user

    def issue_tokens(
        self,
        *,
        user_id: int,
        client_id: int,
        token_version: int,
        refresh_expires_in_seconds: int,
        remember_me: bool = False,
    ) -> dict[str, str]:
        require_positive_client_id(client_id)
        payload = {"sub": str(user_id), "client_id": client_id, "token_version": token_version}
        return {
            "access_token": create_access_token(payload),
            "refresh_token": create_refresh_token(
                {**payload, "remember_me": remember_me},
                expires_in_seconds=refresh_expires_in_seconds,
            ),
        }

    def issue_tokens_for_user(
        self,
        user: User,
        *,
        refresh_expires_in_seconds: int,
        remember_me: bool = False,
    ) -> dict[str, str]:
        """Single entry point for issuing access + refresh pair from a loaded ``User`` row."""
        if user.id is None:
            raise InvalidCredentialsError()
        return self.issue_tokens(
            user_id=user.id,
            client_id=int(user.client_id),
            token_version=int(getattr(user, "token_version", 1) or 1),
            refresh_expires_in_seconds=refresh_expires_in_seconds,
            remember_me=remember_me,
        )

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
        Persist ``jti`` as consumed after a successful refresh rotation.

        Returns False if ``jti`` was already consumed (replay).
        """
        require_positive_client_id(client_id)
        return self._refresh_jti_repo.try_consume_refresh_jti(
            session,
            jti=jti,
            user_id=user_id,
            client_id=client_id,
            expires_at=expires_at,
        )

    def _maybe_cleanup_expired_jti(self, session: Session) -> None:
        """Opportunistic TTL cleanup to bound table growth (no background worker)."""
        if random.random() >= 0.05:
            return
        cutoff = datetime.now(tz=timezone.utc)
        try:
            deleted = self._refresh_jti_repo.delete_expired_before(session, before=cutoff)
            if deleted:
                logger.debug("refresh_jti_cleanup deleted=%s", deleted)
        except Exception:
            logger.exception("refresh_jti_cleanup_failed")

    def _refresh_rotation_core(self, session: Session, *, refresh_token: str) -> tuple[dict[str, str], int]:
        """
        Single gatekeeper for refresh: decode → user → DB replay consume → issue new pair.

        Returns ``(tokens, refresh_cookie_max_age_seconds)``.
        Raises :class:`UnauthorizedError` with a generic client message on any failure.
        """
        payload = decode_refresh_token(refresh_token)
        if not payload:
            raise UnauthorizedError(REFRESH_TOKEN_INVALID_MESSAGE)

        try:
            user_id = int(payload.get("sub"))
            client_id = int(payload.get("client_id"))
            token_version = int(payload.get("token_version", 0))
            exp = int(payload.get("exp", 0))
        except (TypeError, ValueError):
            raise UnauthorizedError(REFRESH_TOKEN_INVALID_MESSAGE) from None

        jti = str(payload.get("jti") or "")
        if not jti:
            raise UnauthorizedError(REFRESH_TOKEN_INVALID_MESSAGE)

        try:
            user = self.load_user_matching_jwt_claims(
                session,
                user_id=user_id,
                jwt_client_id=client_id,
                jwt_token_version=token_version,
            )
        except UnauthorizedError as exc:
            raise UnauthorizedError(REFRESH_TOKEN_INVALID_MESSAGE) from exc

        exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
        if not self.try_consume_refresh_jti(
            session,
            jti=jti,
            user_id=user_id,
            client_id=client_id,
            expires_at=exp_dt,
        ):
            logger.warning("refresh replay blocked jti_prefix=%s", jti[:8])
            raise UnauthorizedError(REFRESH_TOKEN_INVALID_MESSAGE)

        remember_me = bool(payload.get("remember_me", False))
        refresh_ttl = REFRESH_TOKEN_EXPIRES_SECONDS if remember_me else REFRESH_TOKEN_SHORT_EXPIRES_SECONDS
        tokens = self.issue_tokens_for_user(
            user,
            refresh_expires_in_seconds=refresh_ttl,
            remember_me=remember_me,
        )
        self._maybe_cleanup_expired_jti(session)
        return tokens, refresh_ttl

    def rotate_refresh_session(self, session: Session, *, refresh_token: str) -> tuple[dict[str, str], int]:
        """HTTP `/auth/refresh`: same rotation semantics as silent middleware."""
        return self._refresh_rotation_core(session, refresh_token=refresh_token)

    def try_silent_refresh(self, session: Session, *, refresh_token: str) -> SilentRefreshResult:
        """
        Middleware: attempt rotation using the same core as `/auth/refresh`.

        On failure, instruct caller to clear the refresh cookie (invalid / expired / replay).
        """
        try:
            tokens, ttl = self._refresh_rotation_core(session, refresh_token=refresh_token)
            return SilentRefreshResult(
                success=True,
                access_token=tokens["access_token"],
                refresh_token=tokens["refresh_token"],
                refresh_max_age=ttl,
            )
        except UnauthorizedError:
            return SilentRefreshResult(clear_refresh_cookie=True)
