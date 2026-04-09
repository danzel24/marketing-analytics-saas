"""Registration must not attach a new user to an existing tenant by reusing Client.name."""

from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.domain_errors import ClientNameAlreadyExistsError, EmailAlreadyRegisteredError
from app.models.db_models import Client, User
from app.services.auth_service import AuthService


def test_register_rejects_duplicate_client_name() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Client(name="Acme Corp"))
        session.commit()

        svc = AuthService()
        with pytest.raises(ClientNameAlreadyExistsError):
            svc.register(
                session,
                email="new@example.com",
                password="password12",
                client_name="Acme Corp",
            )


def test_register_maps_client_integrity_error_to_duplicate_name() -> None:
    """If the pre-insert check races, DB unique on Client.name still yields a domain error."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Client(name="Race Corp"))
        session.commit()

        svc = AuthService()
        with patch.object(
            svc.repo,
            "client_name_exists_unscoped_internal",
            return_value=False,
        ):
            with pytest.raises(ClientNameAlreadyExistsError):
                svc.register(
                    session,
                    email="new@example.com",
                    password="password12",
                    client_name="Race Corp",
                )


def test_register_creates_new_tenant_when_name_unique() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Client(name="Other Tenant"))
        session.commit()

        svc = AuthService()
        user = svc.register(
            session,
            email="u@example.com",
            password="password12",
            client_name="Fresh Workspace",
        )
        assert user.client_id is not None
        clients = session.exec(select(Client)).all()
        assert len(clients) == 2
        assert {c.name for c in clients} == {"Other Tenant", "Fresh Workspace"}


def test_register_still_rejects_duplicate_email() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        c = Client(name="T1")
        session.add(c)
        session.commit()
        session.refresh(c)
        session.add(User(email="dup@example.com", password_hash="x", client_id=c.id))
        session.commit()

        svc = AuthService()
        with pytest.raises(EmailAlreadyRegisteredError):
            svc.register(
                session,
                email="dup@example.com",
                password="password12",
                client_name="T2 Name",
            )
