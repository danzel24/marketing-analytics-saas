from __future__ import annotations

from datetime import date

from sqlmodel import Session, delete, select

from app.core.domain_errors import InvalidOperationError, NotFoundError
from app.core.error_codes import ErrorCode
from app.core.internal_call import require_internal_call
from app.models.db_models import Campaign, CampaignMetric
from app.repositories.tenant_scope import require_positive_client_id


class CampaignMetricRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_for_client(self, client_id: int, metric: CampaignMetric) -> CampaignMetric:
        """Insert a row only if ``metric.campaign_id`` belongs to ``client_id``."""
        cid = require_positive_client_id(client_id)
        owner = self.session.exec(
            select(Campaign.id).where(Campaign.id == metric.campaign_id).where(Campaign.client_id == cid)
        ).first()
        if owner is None:
            raise NotFoundError("Campaign not found for tenant")
        self.session.add(metric)
        self.session.commit()
        self.session.refresh(metric)
        return metric

    def bulk_create_for_client(self, client_id: int, metrics: list[CampaignMetric]) -> int:
        """Bulk insert after verifying every campaign_id belongs to ``client_id``."""
        cid = require_positive_client_id(client_id)
        if not metrics:
            return 0
        ids = {int(m.campaign_id) for m in metrics}
        stmt = select(Campaign.id).where(Campaign.client_id == cid).where(Campaign.id.in_(ids))  # type: ignore[union-attr]
        allowed = {row for row in self.session.exec(stmt)}
        if not ids.issubset(allowed):
            raise NotFoundError("Campaign not found for tenant")
        self.session.add_all(metrics)
        self.session.commit()
        return len(metrics)

    def get_by_id_unscoped_internal(
        self,
        metric_id: int,
        *,
        _internal_call: bool = False,
    ) -> CampaignMetric | None:
        """INTERNAL USE ONLY – NOT SAFE FOR MULTI-TENANT ACCESS."""
        require_internal_call(_internal_call=_internal_call)
        return self.session.get(CampaignMetric, metric_id)

    def get_by_id_for_client(self, metric_id: int, client_id: int) -> CampaignMetric | None:
        cid = require_positive_client_id(client_id)
        stmt = (
            select(CampaignMetric)
            .join(Campaign, Campaign.id == CampaignMetric.campaign_id)
            .where(CampaignMetric.id == metric_id)
            .where(Campaign.client_id == cid)
        )
        return self.session.exec(stmt).first()

    def list_for_client(
        self,
        client_id: int,
        *,
        offset: int = 0,
        limit: int = 500_000,
    ) -> list[CampaignMetric]:
        cid = require_positive_client_id(client_id)
        stmt = (
            select(CampaignMetric)
            .join(Campaign, Campaign.id == CampaignMetric.campaign_id)
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
    ) -> list[CampaignMetric]:
        """INTERNAL USE ONLY – NOT SAFE FOR MULTI-TENANT ACCESS."""
        require_internal_call(_internal_call=_internal_call)
        stmt = select(CampaignMetric).offset(offset).limit(limit)
        return list(self.session.exec(stmt))

    def list_metrics_for_campaign_ids_for_client(
        self,
        client_id: int,
        campaign_ids: set[int],
        *,
        date_from: date | None = None,
    ) -> list[CampaignMetric]:
        """
        Metrics for given campaigns with JOIN + ``client_id`` (DB-level tenant scope).
        ``campaign_ids`` must be non-empty; empty set returns [].
        """
        cid = require_positive_client_id(client_id)
        if not campaign_ids:
            return []
        stmt = (
            select(CampaignMetric)
            .join(Campaign, Campaign.id == CampaignMetric.campaign_id)
            .where(Campaign.client_id == cid)
            .where(CampaignMetric.campaign_id.in_(campaign_ids))  # type: ignore[union-attr]
        )
        if date_from is not None:
            stmt = stmt.where(CampaignMetric.metric_date >= date_from)
        return list(self.session.exec(stmt))

    def get_by_campaign_and_date_for_client(
        self,
        client_id: int,
        campaign_id: int,
        metric_date: date,
    ) -> CampaignMetric | None:
        cid = require_positive_client_id(client_id)
        stmt = (
            select(CampaignMetric)
            .join(Campaign, Campaign.id == CampaignMetric.campaign_id)
            .where(Campaign.client_id == cid)
            .where(CampaignMetric.campaign_id == campaign_id)
            .where(CampaignMetric.metric_date == metric_date)
        )
        return self.session.exec(stmt).first()

    def save_for_client(self, client_id: int, metric: CampaignMetric) -> CampaignMetric:
        """Persist updates only for existing metrics that belong to ``client_id`` (use create_for_client for inserts)."""
        cid = require_positive_client_id(client_id)
        if metric.id is None:
            raise InvalidOperationError("Use create_for_client for new metrics", code=ErrorCode.INVALID_METRIC_SAVE)
        if self.get_by_id_for_client(int(metric.id), cid) is None:
            raise NotFoundError("Metric not found for tenant")
        self.session.add(metric)
        self.session.commit()
        self.session.refresh(metric)
        return metric

    def save_many_for_client(self, client_id: int, metrics: list[CampaignMetric]) -> int:
        if not metrics:
            return 0
        cid = require_positive_client_id(client_id)
        for m in metrics:
            if m.id is None:
                raise InvalidOperationError("Batch save requires persisted metrics", code=ErrorCode.INVALID_METRIC_SAVE)
            if self.get_by_id_for_client(int(m.id), cid) is None:
                raise NotFoundError("Metric not found for tenant")
        self.session.add_all(metrics)
        self.session.commit()
        return len(metrics)

    def get_metrics_since_for_client(self, client_id: int, date_from: date) -> list[CampaignMetric]:
        """All metrics from ``date_from`` onward for campaigns owned by ``client_id``."""
        cid = require_positive_client_id(client_id)
        stmt = (
            select(CampaignMetric)
            .join(Campaign, Campaign.id == CampaignMetric.campaign_id)
            .where(Campaign.client_id == cid)
            .where(CampaignMetric.metric_date >= date_from)
        )
        return list(self.session.exec(stmt))

    def list_metrics_in_date_range_for_client(
        self,
        client_id: int,
        date_from: date,
        date_to: date,
    ) -> list[CampaignMetric]:
        """Closed interval [``date_from``, ``date_to``] for tenant campaigns (dashboard comparisons)."""
        cid = require_positive_client_id(client_id)
        stmt = (
            select(CampaignMetric)
            .join(Campaign, Campaign.id == CampaignMetric.campaign_id)
            .where(Campaign.client_id == cid)
            .where(CampaignMetric.metric_date >= date_from)
            .where(CampaignMetric.metric_date <= date_to)
        )
        return list(self.session.exec(stmt))

    def delete_for_client(self, metric_id: int, client_id: int) -> bool:
        obj = self.get_by_id_for_client(metric_id, client_id)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.commit()
        return True

    def delete_all_metrics_unscoped_internal(self, *, _internal_call: bool = False) -> int:
        """INTERNAL USE ONLY – NOT SAFE FOR MULTI-TENANT ACCESS (all tenants)."""
        require_internal_call(_internal_call=_internal_call)
        stmt = delete(CampaignMetric)
        result = self.session.exec(stmt)
        self.session.commit()
        return int(result.rowcount or 0)

    def delete_metrics_by_client(self, client_id: int) -> int:
        cid = require_positive_client_id(client_id)
        campaign_ids_subquery = select(Campaign.id).where(Campaign.client_id == cid)
        stmt = delete(CampaignMetric).where(CampaignMetric.campaign_id.in_(campaign_ids_subquery))  # type: ignore[union-attr]
        result = self.session.exec(stmt)
        self.session.commit()
        return int(result.rowcount or 0)
