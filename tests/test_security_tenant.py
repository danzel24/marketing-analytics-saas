"""Tenant path segment validation and JWT secret configuration."""

import os

import pytest

from app.core.config import get_jwt_secret_bytes, normalize_tenant_path_segment
from app.core.domain_errors import InvalidClientIdError


def test_normalize_tenant_accepts_slug_and_digits() -> None:
    assert normalize_tenant_path_segment("acme-corp") == "acme-corp"
    assert normalize_tenant_path_segment("42") == "42"


@pytest.mark.parametrize(
    "bad",
    [
        "../x",
        "..",
        "a/b",
        "a\\b",
        "UPPER",
        "under_score",
        "dot.dot",
        "",
        " " * 3,
    ],
)
def test_normalize_tenant_rejects_unsafe_segments(bad: str) -> None:
    with pytest.raises(InvalidClientIdError):
        normalize_tenant_path_segment(bad)


def test_jwt_secret_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        get_jwt_secret_bytes()


def test_jwt_secret_too_short_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(RuntimeError, match="32"):
        get_jwt_secret_bytes()


def test_jwt_secret_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    assert len(get_jwt_secret_bytes()) == 32


def test_jwt_access_roundtrip_hs256(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.core.security import create_access_token, decode_access_token

    token = create_access_token({"sub": "42", "client_id": 7, "token_version": 3})
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert int(payload["client_id"]) == 7
    assert int(payload["token_version"]) == 3
    assert payload.get("token_type") == "access"


def test_jwt_refresh_requires_jti(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    import time

    import jwt

    from app.core.config import get_jwt_secret_str
    from app.core.security import JWT_ALGORITHM, decode_refresh_token

    now = int(time.time())
    bad = jwt.encode(
        {
            "sub": "1",
            "client_id": 1,
            "token_version": 1,
            "token_type": "refresh",
            "iat": now,
            "exp": now + 3600,
        },
        get_jwt_secret_str(),
        algorithm=JWT_ALGORITHM,
    )
    assert decode_refresh_token(bad) is None
