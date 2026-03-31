from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlmodel import Session

from app.models.db_models import Campaign
from app.repositories.campaign_metric_repository import CampaignMetricRepository
from app.repositories.campaign_repository_sql import CampaignRepository
from app.repositories.client_repository import ClientRepository
from app.repositories.integration_repository import IntegrationRepository
from app.core.internal_call import require_internal_call
from app.repositories.tenant_scope import require_positive_client_id
from app.services.csv_service import CSVService
from app.services.google_ads_client import GoogleAdsClient

logger = logging.getLogger(__name__)

GOOGLE_ADS_PLATFORM = "google_ads"


class IntegrationService:
    def __init__(
        self,
        session: Session,
        *,
        ads_client: GoogleAdsClient | None = None,
    ) -> None:
        self._session = session
        self._integration_repo = IntegrationRepository(session)
        self._campaign_repo = CampaignRepository(session)
        self._metric_repo = CampaignMetricRepository(session)
        self._client_repo = ClientRepository(session)
        self._csv_service = CSVService(self._campaign_repo, self._metric_repo)
        self._ads_client = ads_client or GoogleAdsClient()

    def sync_google_ads(self, client_id: int) -> dict[str, Any]:
        cid = require_positive_client_id(client_id)

        integration = self._integration_repo.get_active(cid, GOOGLE_ADS_PLATFORM)
        if integration is None:
            return {"status": "skipped", "reason": "no_active_integration", "imported": 0, "updated": 0}

        if integration.client_id != cid:
            logger.warning("integration ownership mismatch: client_id=%s integration.client_id=%s", cid, integration.client_id)
            return {"status": "error", "reason": "ownership_mismatch", "imported": 0, "updated": 0}

        raw_rows = self._ads_client.fetch_campaign_data(integration)
        normalized_rows: list[dict[str, object]] = []
        errors: list[dict[str, object]] = []

        for index, raw in enumerate(raw_rows, start=1):
            row = self._normalize_google_ads_row(raw, client_id=cid)
            if row is None:
                errors.append({"row": index, "reason": "invalid_google_ads_row", "data": raw})
                continue
            normalized_rows.append(row)

        imported, updated = self._csv_service._upsert_normalized_rows(  # noqa: SLF001
            normalized_rows,
            client_id=cid,
            errors=errors,
        )

        return {
            "status": "ok",
            "imported": imported,
            "updated": updated,
            "errors": errors,
        }

    def sync_all_clients_unscoped_internal(self, *, _internal_call: bool = False) -> dict[str, Any]:
        """
        INTERNAL USE ONLY – NOT SAFE FOR MULTI-TENANT ACCESS.
        Iterates all tenants (e.g. background worker). Each sync uses per-tenant ``sync_google_ads``.
        """
        require_internal_call(_internal_call=_internal_call)
        total_imported = 0
        total_updated = 0
        clients_touched = 0

        clients = self._client_repo.list_unscoped_internal(
            offset=0, limit=100_000, _internal_call=True
        )
        for client in clients:
            cid = client.id
            if cid is None:
                continue
            if self._integration_repo.get_active(cid, GOOGLE_ADS_PLATFORM) is None:
                continue
            result = self.sync_google_ads(cid)
            if result.get("status") == "ok":
                clients_touched += 1
                total_imported += int(result.get("imported") or 0)
                total_updated += int(result.get("updated") or 0)

        return {
            "clients_synced": clients_touched,
            "imported": total_imported,
            "updated": total_updated,
        }

    def _normalize_google_ads_row(self, raw: dict[str, Any], *, client_id: int) -> dict[str, object] | None:
        metric_date = CSVService._parse_date(str(raw.get("date") or ""))  # noqa: SLF001
        if metric_date is None or not isinstance(metric_date, date):
            return None

        revenue = self._coerce_amount(raw.get("revenue"))
        spend = self._coerce_amount(raw.get("cost"))
        if revenue is None or spend is None:
            return None

        campaign_name = str(raw.get("campaign") or "").strip() or "google_ads"
        campaign = self._get_or_create_google_campaign(client_id, campaign_name)

        verified = self._campaign_repo.get_by_id_for_client(campaign.id, client_id)
        if verified is None:
            return None

        return {
            "date": metric_date,
            "campaign_id": verified.id,
            "revenue": revenue,
            "spend": spend,
        }

    def _get_or_create_google_campaign(self, client_id: int, name: str) -> Campaign:
        existing = self._campaign_repo.get_by_name(client_id, name)
        if existing:
            return existing
        return self._campaign_repo.create_for_client(
            client_id,
            Campaign(
                name=name,
                platform=GOOGLE_ADS_PLATFORM,
                client_id=client_id,
            ),
        )

    @staticmethod
    def _coerce_amount(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        parsed = CSVService.parse_currency(str(value))
        return parsed
