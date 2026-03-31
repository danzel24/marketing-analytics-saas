"""Refresh JTI replay: repository + unique constraint behavior."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.db_models import Client, User
from app.repositories.refresh_token_jti_repository import RefreshTokenJtiRepository


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        c = Client(name="replay_client_test")
        s.add(c)
        s.commit()
        s.refresh(c)
        u = User(email="replay@test.local", password_hash="x", client_id=c.id, token_version=1)
        s.add(u)
        s.commit()
        s.refresh(u)
        yield s


def test_try_consume_second_call_with_same_jti_is_false(session: Session) -> None:
    user = session.exec(select(User)).first()
    client = session.exec(select(Client)).first()
    assert user is not None and client is not None and user.id is not None

    repo = RefreshTokenJtiRepository()
    exp = datetime.now(tz=timezone.utc)
    assert repo.try_consume_refresh_jti(
        session,
        jti="same-jti-replay-test",
        user_id=user.id,
        client_id=client.id,
        expires_at=exp,
    )
    assert not repo.try_consume_refresh_jti(
        session,
        jti="same-jti-replay-test",
        user_id=user.id,
        client_id=client.id,
        expires_at=exp,
    )
