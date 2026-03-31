"""Clear CSV-imported campaigns/metrics for current tenant only (platform=imported)."""

from datetime import date

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.domain_errors import InvalidOperationError
from app.models.db_models import Campaign, CampaignMetric, Client
from app.repositories.campaign_metric_repository import CampaignMetricRepository
from app.repositories.campaign_repository_sql import CampaignRepository
from app.services.csv_service import CLEAR_IMPORTED_CONFIRMATION, CSVService


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def test_clear_imported_requires_exact_confirmation(engine) -> None:
    with Session(engine) as session:
        client = Client(name="t", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)
        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)
        svc = CSVService(cr, mr)
        with pytest.raises(InvalidOperationError):
            svc.clear_imported_data_for_client(client.id, "wrong")


def test_clear_imported_removes_only_imported_platform(engine) -> None:
    with Session(engine) as session:
        client = Client(name="c1", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)

        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)

        imp = cr.create_for_client(
            client.id,
            Campaign(name="CSV A", platform="imported", client_id=client.id),
        )
        goog = cr.create_for_client(
            client.id,
            Campaign(name="Google Ads", platform="google", client_id=client.id),
        )

        mr.bulk_create_for_client(
            client.id,
            [
                CampaignMetric(
                    campaign_id=imp.id,
                    metric_date=date(2025, 1, 1),
                    revenue=100.0,
                    spend=50.0,
                ),
                CampaignMetric(
                    campaign_id=goog.id,
                    metric_date=date(2025, 1, 1),
                    revenue=200.0,
                    spend=80.0,
                ),
            ],
        )

        svc = CSVService(cr, mr)
        out = svc.clear_imported_data_for_client(client.id, CLEAR_IMPORTED_CONFIRMATION)
        assert out["metrics_deleted"] == 1
        assert out["campaigns_deleted"] == 1

        camps = list(session.exec(select(Campaign).where(Campaign.client_id == client.id)))
        assert len(camps) == 1
        assert camps[0].platform == "google"

        metrics = list(session.exec(select(CampaignMetric)))
        assert len(metrics) == 1
        assert metrics[0].campaign_id == goog.id


def test_clear_imported_rolls_back_if_second_step_fails(engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """Metrics delete + campaign delete must be one transaction (no partial commit)."""
    with Session(engine) as session:
        client = Client(name="c3", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)
        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)
        imp = cr.create_for_client(
            client.id,
            Campaign(name="X", platform="imported", client_id=client.id),
        )
        mr.bulk_create_for_client(
            client.id,
            [CampaignMetric(campaign_id=imp.id, metric_date=date(2025, 2, 1), revenue=10.0, spend=5.0)],
        )
        svc = CSVService(cr, mr)

        def boom(*_a, **_k):
            raise RuntimeError("simulated DB failure")

        monkeypatch.setattr(cr, "delete_imported_campaigns_for_client", boom)

        with pytest.raises(RuntimeError, match="simulated"):
            svc.clear_imported_data_for_client(client.id, CLEAR_IMPORTED_CONFIRMATION)

    with Session(engine) as s2:
        assert len(list(s2.exec(select(CampaignMetric)))) == 1
        assert len(list(s2.exec(select(Campaign).where(Campaign.platform == "imported")))) == 1


def test_clear_imported_idempotent_empty(engine) -> None:
    with Session(engine) as session:
        client = Client(name="c2", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)
        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)
        svc = CSVService(cr, mr)
        out = svc.clear_imported_data_for_client(client.id, CLEAR_IMPORTED_CONFIRMATION)
        assert out["metrics_deleted"] == 0
        assert out["campaigns_deleted"] == 0
