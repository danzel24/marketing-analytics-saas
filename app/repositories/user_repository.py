from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from app.core.internal_call import require_internal_call
from app.models.db_models import Client, User
from app.repositories.tenant_scope import require_positive_client_id


class UserRepository:
    def get_by_id_unscoped_internal(
        self,
        session: Session,
        user_id: int,
        *,
        _internal_call: bool = False,
    ) -> Optional[User]:
        """INTERNAL USE ONLY – NOT SAFE FOR MULTI-TENANT ACCESS. Auth must verify JWT client_id."""
        require_internal_call(_internal_call=_internal_call)
        return session.exec(select(User).where(User.id == user_id)).first()

    def get_by_email_unscoped_internal(
        self,
        session: Session,
        email: str,
        *,
        _internal_call: bool = False,
    ) -> Optional[User]:
        """INTERNAL USE ONLY – NOT SAFE FOR MULTI-TENANT ACCESS. Login is global by email."""
        require_internal_call(_internal_call=_internal_call)
        return session.exec(select(User).where(User.email == email)).first()

    def create_user(self, session: Session, *, email: str, password_hash: str, client_id: int) -> User:
        cid = require_positive_client_id(client_id)
        user = User(email=email, password_hash=password_hash, client_id=cid)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    def get_or_create_client_unscoped_internal(
        self,
        session: Session,
        *,
        name: str,
        _internal_call: bool = False,
    ) -> Client:
        """INTERNAL USE ONLY – NOT SAFE FOR MULTI-TENANT ACCESS. Registration bootstrap."""
        require_internal_call(_internal_call=_internal_call)
        client = session.exec(select(Client).where(Client.name == name)).first()
        if client:
            return client
        client = Client(name=name)
        session.add(client)
        session.commit()
        session.refresh(client)
        return client

    def increment_token_version(self, session: Session, user: User) -> User:
        user.token_version = int(getattr(user, "token_version", 1) or 1) + 1
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
