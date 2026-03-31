from __future__ import annotations

import time
from typing import Any, Literal
from uuid import uuid4

import jwt
from passlib.context import CryptContext

from app.core.config import get_jwt_secret_str

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRES_SECONDS = 60 * 15  # 15 minutes
REFRESH_TOKEN_EXPIRES_SECONDS = 60 * 60 * 24 * 30  # 30 days
REFRESH_TOKEN_SHORT_EXPIRES_SECONDS = 60 * 60 * 24  # 1 day

_DECODE_OPTIONS = {
    "require": ["exp", "iat", "sub"],
    "verify_signature": True,
    "verify_exp": True,
}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def _encode_token(
    data: dict[str, Any],
    *,
    token_type: Literal["access", "refresh"],
    expires_in_seconds: int,
) -> str:
    now = int(time.time())
    payload = {**data, "iat": now, "exp": now + expires_in_seconds, "token_type": token_type}
    return jwt.encode(payload, get_jwt_secret_str(), algorithm=JWT_ALGORITHM)


def create_access_token(data: dict[str, Any], expires_in_seconds: int = ACCESS_TOKEN_EXPIRES_SECONDS) -> str:
    return _encode_token(data, token_type="access", expires_in_seconds=expires_in_seconds)


def create_refresh_token(data: dict[str, Any], expires_in_seconds: int = REFRESH_TOKEN_EXPIRES_SECONDS) -> str:
    payload = dict(data)
    payload.setdefault("jti", str(uuid4()))
    return _encode_token(payload, token_type="refresh", expires_in_seconds=expires_in_seconds)


def _decode_token_verify(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(
            token,
            get_jwt_secret_str(),
            algorithms=[JWT_ALGORITHM],
            options=_DECODE_OPTIONS,
        )
    except jwt.PyJWTError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _validate_access_claims(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("token_type") != "access":
        return None
    if "client_id" not in payload or "token_version" not in payload:
        return None
    try:
        int(payload["sub"])
        int(payload["client_id"])
        int(payload["token_version"])
    except (TypeError, ValueError):
        return None
    return payload


def _validate_refresh_claims(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("token_type") != "refresh":
        return None
    if "client_id" not in payload or "token_version" not in payload:
        return None
    jti = str(payload.get("jti") or "").strip()
    if not jti:
        return None
    try:
        int(payload["sub"])
        int(payload["client_id"])
        int(payload["token_version"])
    except (TypeError, ValueError):
        return None
    return payload


def decode_access_token(token: str) -> dict[str, Any] | None:
    payload = _decode_token_verify(token)
    if not payload:
        return None
    return _validate_access_claims(payload)


def decode_refresh_token(token: str) -> dict[str, Any] | None:
    payload = _decode_token_verify(token)
    if not payload:
        return None
    return _validate_refresh_claims(payload)
