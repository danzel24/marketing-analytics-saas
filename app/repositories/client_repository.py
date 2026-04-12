from __future__ import annotations

from sqlmodel import Session, select

from app.core.internal_call import require_internal_call
from app.models.db_models import Client
from app.repositories.tenant_scope import require_positive_client_id


class ClientRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_unscoped_internal(
        self,
        client: Client,
        *,
        _internal_call: bool = False,
    ) -> Client:
        """INTERNAL USE ONLY – NOT SAFE FOR MULTI-TENANT ACCESS. Bootstrap / registration only."""
        require_internal_call(_internal_call=_internal_call)
        self.session.add(client)
        self.session.commit()
        self.session.refresh(client)
        return client

    def get_by_id_for_client(self, client_id: int) -> Client | None:
        """
        Load the tenant row by primary key. ``client_id`` is ``Client.id`` (tenant id).
        """
        cid = require_positive_client_id(client_id)
        return self.session.get(Client, cid)

    def list_unscoped_internal(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        _internal_call: bool = False,
    ) -> list[Client]:
        """INTERNAL USE ONLY – NOT SAFE FOR MULTI-TENANT ACCESS. System jobs only."""
        require_internal_call(_internal_call=_internal_call)
        stmt = select(Client).offset(offset).limit(limit)
        return list(self.session.exec(stmt))

    def delete_for_client(self, client_id: int) -> bool:
        """Delete the tenant row identified by ``client_id`` (primary key)."""
        cid = require_positive_client_id(client_id)
        obj = self.session.get(Client, cid)
        if not obj:
            return False
        self.session.delete(obj)
        self.session.commit()
        return True

    def update_margin_for_client(self, client_id: int, margin: float) -> Client | None:
        """Persist gross margin as a decimal in (0, 1), e.g. 0.4 for 40 %."""
        cid = require_positive_client_id(client_id)
        obj = self.session.get(Client, cid)
        if obj is None:
            return None
        obj.margin = float(margin)
        self.session.add(obj)
        self.session.commit()
        self.session.refresh(obj)
        return obj
