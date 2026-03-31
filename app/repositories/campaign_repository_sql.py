from __future__ import annotations

from sqlmodel import Session, select

from app.core.domain_errors import EntityTenantMismatchError
from app.core.internal_call import require_internal_call
from app.models.db_models import Campaign
from app.repositories.tenant_scope import require_positive_client_id


class CampaignRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_for_client(self, client_id: int, campaign: Campaign) -> Campaign:
        """``campaign.client_id`` must equal ``client_id`` (fail-fast)."""
        cid = require_positive_client_id(client_id)
        if int(campaign.client_id) != cid:
            raise EntityTenantMismatchError()
        self.session.add(campaign)
        self.session.commit()
        self.session.refresh(campaign)
        return campaign

    def get_by_id_unscoped_internal(
        self,
        campaign_id: int,
        *,
        _internal_call: bool = False,
    ) -> Campaign | None:
        """INTERNAL USE ONLY – NOT SAFE FOR MULTI-TENANT ACCESS."""
        require_internal_call(_internal_call=_internal_call)
        return self.session.get(Campaign, campaign_id)

    def get_by_id_for_client(self, campaign_id: int, client_id: int) -> Campaign | None:
        cid = require_positive_client_id(client_id)
        stmt = select(Campaign).where(Campaign.id == campaign_id).where(Campaign.client_id == cid)
        return self.session.exec(stmt).first()

    def get_by_name(self, client_id: int, name: str) -> Campaign | None:
        cid = require_positive_client_id(client_id)
        stmt = select(Campaign).where(Campaign.client_id == cid).where(Campaign.name == name)
        return self.session.exec(stmt).first()

    def list_for_client(self, client_id: int, *, offset: int = 0, limit: int = 100_000) -> list[Campaign]:
        cid = require_positive_client_id(client_id)
        stmt = (
            select(Campaign)
            .where(Campaign.client_id == cid)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.exec(stmt))

    def list_unscoped_internal(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        _internal_call: bool = False,
    ) -> list[Campaign]:
        """INTERNAL USE ONLY – NOT SAFE FOR MULTI-TENANT ACCESS."""
        require_internal_call(_internal_call=_internal_call)
        stmt = select(Campaign).offset(offset).limit(limit)
        return list(self.session.exec(stmt))

    def delete_for_client(self, campaign_id: int, client_id: int) -> bool:
        obj = self.get_by_id_for_client(campaign_id, client_id)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.commit()
        return True
