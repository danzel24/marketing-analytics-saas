from __future__ import annotations

import logging
import os
from typing import Any

from sqlmodel import Session, select

from app.core.domain_errors import ForbiddenError, InvalidOperationError
from app.core.error_codes import ErrorCode
from app.models.db_models import Client, User
from app.repositories.campaign_metric_repository import CampaignMetricRepository
from app.repositories.tenant_scope import require_positive_client_id

logger = logging.getLogger(__name__)

CLEAR_CONFIRMATION = "CLEAR"


class AdminService:
    """Admin-only operations; keeps HTTP routes free of business rules."""

    def list_registered_users_overview(self, session: Session) -> list[dict[str, Any]]:
        """All users with workspace name and timestamps (admin HTML only)."""
        stmt = (
            select(User, Client)
            .join(Client, User.client_id == Client.id)  # type: ignore[arg-type]
            .order_by(User.created_at.desc())  # type: ignore[union-attr]
        )
        rows: list[dict[str, Any]] = []
        for user, client in session.exec(stmt):
            rows.append(
                {
                    "email": user.email,
                    "client_name": client.name,
                    "registered_at": user.created_at,
                    "last_login_at": user.last_login_at,
                    "role": user.role,
                }
            )
        return rows

    def clear_tenant_campaign_metrics(
        self,
        session: Session,
        *,
        client_id: int,
        confirmation: str | None,
    ) -> int:
        cid = require_positive_client_id(client_id)

        env = os.getenv("APP_ENV", "").lower()
        if env in {"prod", "production"}:
            raise ForbiddenError(
                "clear-data disabled in production",
                code=ErrorCode.CLEAR_DATA_DISABLED,
            )

        if confirmation != CLEAR_CONFIRMATION:
            raise InvalidOperationError(
                "Pro smazání dat je nutné poslat { confirm: 'CLEAR' }",
                code=ErrorCode.INVALID_CONFIRMATION,
            )

        repo = CampaignMetricRepository(session)
        deleted = repo.delete_metrics_by_client(cid)
        logger.warning(
            "admin clear-data executed client_id=%s deleted_rows=%s",
            cid,
            deleted,
        )
        return deleted
