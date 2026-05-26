from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlmodel import Session

from app.core.auth_cookies import clear_refresh_cookie, set_refresh_cookie
from app.core.deps import get_current_user
from app.core.domain_errors import UnauthorizedError, ValidationError
from app.core.security import (
    REFRESH_TOKEN_EXPIRES_SECONDS,
    REFRESH_TOKEN_SHORT_EXPIRES_SECONDS,
    decode_refresh_token,
    hash_password,
)
from app.database import get_session
from app.models.db_models import User, utcnow
from app.repositories.client_repository import ClientRepository
from app.repositories.password_reset_repository import PasswordResetRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import ForgotPasswordIn, LoginIn, RegisterIn, ResetPasswordIn, TokenOut
from app.services.auth_service import AuthService
from app.services.email_service import send_password_reset_email
from app.services.marketing_service import MarketingService

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)


@router.post("/api/v1/auth/register", response_model=TokenOut)
def register(payload: RegisterIn, response: Response, session: Session = Depends(get_session)) -> TokenOut:
    svc = AuthService()
    user = svc.register(session, email=str(payload.email), password=payload.password, client_name=payload.client_name)
    tokens = svc.issue_tokens_for_user(
        user,
        refresh_expires_in_seconds=REFRESH_TOKEN_SHORT_EXPIRES_SECONDS,
        remember_me=False,
    )
    set_refresh_cookie(response, tokens["refresh_token"], REFRESH_TOKEN_SHORT_EXPIRES_SECONDS)
    return TokenOut(access_token=tokens["access_token"])


@router.post("/api/v1/auth/login", response_model=TokenOut)
def login(payload: LoginIn, response: Response, session: Session = Depends(get_session)) -> TokenOut:
    svc = AuthService()
    user = svc.authenticate(session, email=str(payload.email), password=payload.password)
    svc.record_successful_password_login(session, user)
    refresh_ttl = REFRESH_TOKEN_EXPIRES_SECONDS if payload.remember_me else REFRESH_TOKEN_SHORT_EXPIRES_SECONDS
    tokens = svc.issue_tokens_for_user(
        user,
        refresh_expires_in_seconds=refresh_ttl,
        remember_me=payload.remember_me,
    )
    set_refresh_cookie(response, tokens["refresh_token"], refresh_ttl)
    return TokenOut(access_token=tokens["access_token"])


@router.post("/api/v1/auth/refresh", response_model=TokenOut)
def refresh_token_endpoint(
    response: Response,
    session: Session = Depends(get_session),
    refresh_token: str | None = Cookie(default=None),
) -> TokenOut:
    if not refresh_token:
        logger.warning("refresh failed: missing refresh token cookie")
        raise UnauthorizedError("Refresh token missing")

    svc = AuthService()
    tokens, refresh_ttl = svc.rotate_refresh_session(session, refresh_token=refresh_token)
    logger.info("refresh success")
    set_refresh_cookie(response, tokens["refresh_token"], refresh_ttl)
    return TokenOut(access_token=tokens["access_token"])


@router.post("/api/v1/auth/logout")
def logout(
    response: Response,
    session: Session = Depends(get_session),
    refresh_token: str | None = Cookie(default=None),
) -> dict[str, str]:
    if refresh_token:
        payload = decode_refresh_token(refresh_token)
        if payload:
            try:
                user_id = int(payload.get("sub"))
                client_id = int(payload.get("client_id"))
                token_version = int(payload.get("token_version", 0))
                if AuthService().invalidate_refresh_session_if_claims_valid(
                    session,
                    user_id=user_id,
                    jwt_client_id=client_id,
                    jwt_token_version=token_version,
                ):
                    logger.info("logout: invalidated tokens for user_id=%s", user_id)
            except (TypeError, ValueError):
                logger.warning("logout: refresh payload malformed")
    clear_refresh_cookie(response)
    return {"status": "ok"}


@router.get("/api/v1/auth/me")
def get_me(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    repo = ClientRepository(session)
    client = repo.get_by_id_for_client(current_user.client_id)
    raw_margin = getattr(client, "margin", None) if client else None
    m = MarketingService._validated_margin(raw_margin)
    return {
        "id": current_user.id,
        "email": current_user.email,
        "is_admin": str(getattr(current_user, "role", "user")) == "admin",
        "margin_percent": int(round(m * 100)),
    }


@router.post("/api/v1/auth/forgot-password")
def forgot_password(
    body: ForgotPasswordIn,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Request a password reset link.

    Always returns 200 regardless of whether the email exists (prevents enumeration).
    """
    _SUCCESS = {
        "status": "ok",
        "message": "Pokud email existuje, přijde vám zpráva s odkazem pro obnovení hesla.",
    }
    user_repo = UserRepository()
    user = user_repo.get_by_email_unscoped_internal(session, str(body.email), _internal_call=True)
    if user is None or user.id is None:
        return _SUCCESS

    reset_repo = PasswordResetRepository()
    # Invalidate any pending (unused, unexpired) tokens before issuing a new one.
    # Prevents token proliferation if the user clicks "Forgot password" multiple times.
    reset_repo.delete_pending_for_user(session, user_id=user.id)

    token = secrets.token_hex(32)  # 64-char hex
    expires_at = utcnow() + timedelta(hours=1)
    reset_repo.create_token(
        session, user_id=user.id, token=token, expires_at=expires_at
    )

    base = str(request.base_url).rstrip("/")
    reset_link = f"{base}/reset-password?token={token}"
    send_password_reset_email(to_email=str(body.email), reset_link=reset_link)
    logger.info("forgot_password token_issued user_id=%s", user.id)
    return _SUCCESS


@router.post("/api/v1/auth/reset-password")
def reset_password(
    body: ResetPasswordIn,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Consume a password reset token and set a new password."""
    reset_repo = PasswordResetRepository()
    user_repo = UserRepository()

    token_row = reset_repo.get_valid_token(session, token=body.token)
    if token_row is None:
        raise ValidationError("Token je neplatný nebo vypršel. Požádejte o nový odkaz.")

    user = user_repo.get_by_id_unscoped_internal(session, token_row.user_id, _internal_call=True)
    if user is None:
        raise ValidationError("Token je neplatný nebo vypršel. Požádejte o nový odkaz.")

    user.password_hash = hash_password(body.new_password)
    # Bump token_version to invalidate all existing JWT sessions
    user.token_version = int(getattr(user, "token_version", 1) or 1) + 1
    session.add(user)
    reset_repo.mark_used(session, token_row=token_row)
    # Single commit — password change + token invalidation are atomic.
    # If this fails, neither the password nor the token state changes.
    session.commit()
    logger.info("reset_password success user_id=%s", user.id)
    return {"status": "ok", "message": "Heslo bylo úspěšně změněno."}
