from __future__ import annotations

from sqlmodel import Session, select

from app.core.domain_errors import EntityTenantMismatchError, InvalidOperationError, NotFoundError
from app.core.error_codes import ErrorCode
from app.models.db_models import Integration
from app.repositories.tenant_scope import require_positive_client_id


class IntegrationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_active(self, client_id: int, platform: str) -> Integration | None:
        cid = require_positive_client_id(client_id)
        stmt = (
            select(Integration)
            .where(Integration.client_id == cid)
            .where(Integration.platform == platform)
            .where(Integration.is_active.is_(True))
        )
        return self.session.exec(stmt).first()

    def create_for_client(self, client_id: int, integration: Integration) -> Integration:
        """``integration.client_id`` must equal ``client_id`` (fail-fast)."""
        cid = require_positive_client_id(client_id)
        if int(integration.client_id) != cid:
            raise EntityTenantMismatchError()
        self.session.add(integration)
        self.session.commit()
        self.session.refresh(integration)
        return integration

    def update(self, integration: Integration) -> Integration:
        """
        Persist changes. Loads row by (id, client_id) to enforce tenant scope.
        """
        if integration.id is None:
            raise InvalidOperationError("integration.id is required for update", code=ErrorCode.INVALID_INTEGRATION_UPDATE)
        cid = require_positive_client_id(integration.client_id)
        existing = self.session.exec(
            select(Integration).where(
                Integration.id == integration.id,
                Integration.client_id == cid,
            )
        ).first()
        if existing is None:
            raise NotFoundError("Integration not found for tenant")

        existing.access_token = integration.access_token
        existing.refresh_token = integration.refresh_token
        existing.account_id = integration.account_id
        existing.is_active = integration.is_active
        existing.platform = integration.platform

        self.session.add(existing)
        self.session.commit()
        self.session.refresh(existing)
        return existing

    def list_by_client(self, client_id: int) -> list[Integration]:
        cid = require_positive_client_id(client_id)
        stmt = select(Integration).where(Integration.client_id == cid)
        return list(self.session.exec(stmt))
