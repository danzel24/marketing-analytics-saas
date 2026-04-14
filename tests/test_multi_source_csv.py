"""Multi-source CSV pilot: parsers, storage platforms, channel overview aggregation."""

from __future__ import annotations

import datetime as dt
from datetime import date, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.csv_upload_platforms import (
    PLATFORM_CSV_GOOGLE_ADS,
    PLATFORM_CSV_META_ADS,
    PLATFORM_CSV_SHOP_ORDERS,
)
from app.models.db_models import Campaign, CampaignMetric, Client
from app.repositories.campaign_metric_repository import CampaignMetricRepository
from app.repositories.campaign_repository_sql import CampaignRepository
from app.services.marketing_service import MarketingService
from app.services.multi_source_csv_service import MultiSourceCSVService, _dates_from_czech_period_text


def test_dates_from_czech_period_named_months() -> None:
    _, end = _dates_from_czech_period_text("1. března 2026 - 31. března 2026")
    assert end == date(2026, 3, 31)
    _, end2 = _dates_from_czech_period_text("Období: 1. března 2026 – 31. března 2026")
    assert end2 == date(2026, 3, 31)


def test_channel_overview_window_hints_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.multi_source_csv_service as msvc

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> dt.date:
            return dt.date(2026, 6, 15)

    monkeypatch.setattr(msvc, "date", FixedDate)
    old = MultiSourceCSVService._channel_overview_window_hints(dt.date(2026, 1, 1), dt.date(2026, 1, 31))
    assert old["import_outside_default_channel_overview_window"] is True
    assert old["suggested_channel_overview_days"] == 166
    inside = MultiSourceCSVService._channel_overview_window_hints(dt.date(2026, 6, 1), dt.date(2026, 6, 10))
    assert inside["import_outside_default_channel_overview_window"] is False
    assert inside["suggested_channel_overview_days"] is None


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def test_orders_simple_import_aggregates_by_day(engine) -> None:
    csv_content = "date,total\n2026-01-10,100\n2026-01-10,50\n2026-01-11,20\n"
    with Session(engine) as session:
        client = Client(name="c_ms", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)
        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)
        svc = MultiSourceCSVService(cr, mr)
        out = svc.import_orders_csv_bytes(csv_content.encode("utf-8"), client.id)
        assert out["imported_metrics"] == 2
        assert out["validation_status"] == "ok"

        camps = list(session.exec(select(Campaign).where(Campaign.client_id == client.id)))
        assert len(camps) == 1
        assert camps[0].platform == PLATFORM_CSV_SHOP_ORDERS

        metrics = list(session.exec(select(CampaignMetric)))
        assert len(metrics) == 2
        by_date = {m.metric_date: (m.revenue, m.conversions) for m in metrics}
        assert by_date[date(2026, 1, 10)] == (150.0, 2)
        assert by_date[date(2026, 1, 11)] == (20.0, 1)


def test_meta_spend_import(engine) -> None:
    csv_content = "Day,Amount spent (CZK)\n2026-02-01,10.5\n2026-02-01,2.5\n2026-02-02,1\n"
    with Session(engine) as session:
        client = Client(name="c_meta", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)
        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)
        svc = MultiSourceCSVService(cr, mr)
        out = svc.import_meta_csv_bytes(csv_content.encode("utf-8"), client.id)
        assert out["imported_metrics"] == 2
        camps = list(session.exec(select(Campaign).where(Campaign.platform == PLATFORM_CSV_META_ADS)))
        assert len(camps) == 1
        metrics = list(session.exec(select(CampaignMetric)))
        by_date = {m.metric_date: m.spend for m in metrics}
        assert by_date[date(2026, 2, 1)] == 13.0
        assert by_date[date(2026, 2, 2)] == 1.0
        assert all(float(m.revenue) == 0.0 for m in metrics)


def test_google_spend_import(engine) -> None:
    csv_content = "Day,Cost\n2026-03-01,100\n"
    with Session(engine) as session:
        client = Client(name="c_g", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)
        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)
        svc = MultiSourceCSVService(cr, mr)
        out = svc.import_google_csv_bytes(csv_content.encode("utf-8"), client.id)
        assert out["imported_metrics"] == 1
        camps = list(session.exec(select(Campaign).where(Campaign.platform == PLATFORM_CSV_GOOGLE_ADS)))
        assert len(camps) == 1


def test_channel_overview_db_respects_window(engine) -> None:
    today = date.today()
    d_in = today - timedelta(days=5)
    d_old = today - timedelta(days=100)
    with Session(engine) as session:
        client = Client(name="c_co", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)
        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)
        shop = cr.create_for_client(
            client.id,
            Campaign(name="Shop", platform=PLATFORM_CSV_SHOP_ORDERS, client_id=client.id),
        )
        meta = cr.create_for_client(
            client.id,
            Campaign(name="Meta", platform=PLATFORM_CSV_META_ADS, client_id=client.id),
        )
        mr.bulk_create_for_client(
            client.id,
            [
                CampaignMetric(
                    campaign_id=shop.id,
                    metric_date=d_in,
                    revenue=200.0,
                    spend=0.0,
                    conversions=2,
                ),
                CampaignMetric(
                    campaign_id=shop.id,
                    metric_date=d_old,
                    revenue=999.0,
                    spend=0.0,
                    conversions=9,
                ),
                CampaignMetric(
                    campaign_id=meta.id,
                    metric_date=d_in,
                    revenue=0.0,
                    spend=40.0,
                    conversions=0,
                ),
            ],
        )

        msvc = MarketingService(session=session)
        payload = msvc.channel_overview_db(client_id=client.id, days=30)
        assert payload["e_shop"]["total_revenue_czk"] == 200.0
        assert payload["e_shop"]["order_or_row_count"] == 2
        assert payload["ad_channels"]["meta_ads"]["spend_czk"] == 40.0


def test_client_orders_semicolon_excludes_cancelled(engine) -> None:
    csv_content = (
        "code;date;statusName;currencyCode;totalPriceWithVat\n"
        "1;01.04.2026;Completed;CZK;100,00\n"
        "2;01.04.2026;Cancelled;CZK;999\n"
        "3;02.04.2026;Vyřízeno;CZK;50\n"
    )
    with Session(engine) as session:
        client = Client(name="c_ord", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)
        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)
        svc = MultiSourceCSVService(cr, mr)
        out = svc.import_orders_csv_bytes(csv_content.encode("utf-8"), client.id)
        assert out["detected_file_type"] == "client_orders_v1"
        assert out.get("excluded_cancelled_orders") == 1
        metrics = list(session.exec(select(CampaignMetric)))
        assert len(metrics) == 2
        by_d = {m.metric_date: (m.revenue, m.conversions) for m in metrics}
        assert by_d[date(2026, 4, 1)] == (100.0, 1)
        assert by_d[date(2026, 4, 2)] == (50.0, 1)


def test_meta_cz_monthly_iso_only_on_total_row_detail_dates_empty(engine) -> None:
    """Souhrnný řádek nese ISO období; kampaně mají výdaj ale prázdné datumové sloupce."""
    csv_content = (
        "Název kampaně;Vydaná částka (CZK);Začátek reportování;Konce reportů\n"
        ";0;2026-03-01;2026-03-31\n"
        "Camp A;150,00;;\n"
        "Camp B;200,00;;\n"
    )
    with Session(engine) as session:
        client = Client(name="c_mtot", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)
        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)
        svc = MultiSourceCSVService(cr, mr)
        out = svc.import_meta_csv_bytes(csv_content.encode("utf-8"), client.id)
        assert out["imported_metrics"] == 1
        m = session.exec(select(CampaignMetric)).first()
        assert m.metric_date == date(2026, 3, 31)
        assert abs(float(m.spend) - 350.0) < 0.01


def test_meta_cz_monthly_iso_dates_on_total_row_utf8_bom(engine) -> None:
    """Real Meta UI: UTF-8 BOM, ISO in Začátek/Konce, souhrnný řádek první, kampaně bez opakovaných dat."""
    csv_content = (
        "\ufeff"
        "Název kampaně;Dosah;Vydaná částka (CZK);Začátek reportování;Konce reportů\n"
        ";0;0;2026-03-01;2026-03-31\n"
        "Camp A;0;100,50;2026-03-01;2026-03-31\n"
        "Camp B;0;200;2026-03-01;2026-03-31\n"
    )
    with Session(engine) as session:
        client = Client(name="c_miso", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)
        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)
        svc = MultiSourceCSVService(cr, mr)
        out = svc.import_meta_csv_bytes(csv_content.encode("utf-8"), client.id)
        assert out["detected_file_type"] == "meta_cz_monthly_campaign"
        assert out["imported_metrics"] == 1
        m = session.exec(select(CampaignMetric)).first()
        assert m is not None
        assert m.metric_date == date(2026, 3, 31)
        assert abs(float(m.spend) - 300.5) < 0.01


def test_meta_cz_monthly_skips_empty_campaign_total_row(engine) -> None:
    csv_content = (
        "Název kampaně;Dosah;Vydaná částka (CZK);Začátek reportování;Konce reportů\n"
        ";0;500,00;1.4.2026;30.4.2026\n"
        "Camp A;0;100;1.4.2026;30.4.2026\n"
        "Camp B;0;200;1.4.2026;30.4.2026\n"
    )
    with Session(engine) as session:
        client = Client(name="c_mcz", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)
        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)
        svc = MultiSourceCSVService(cr, mr)
        out = svc.import_meta_csv_bytes(csv_content.encode("utf-8"), client.id)
        assert out["detected_file_type"] == "meta_cz_monthly_campaign"
        assert out["imported_metrics"] == 1
        m = session.exec(select(CampaignMetric)).first()
        assert m is not None
        assert m.metric_date == date(2026, 4, 30)
        assert abs(float(m.spend) - 300.0) < 0.01


def test_google_cz_ui_named_month_period_line(engine) -> None:
    """Real Google UI: title, Czech month names in period (not d.m.y), then header row."""
    csv_content = (
        "Výkon kampaní\n"
        "1. března 2026 - 31. března 2026\n"
        "Kampaň;Stav kampaně;Typ kampaně;Prokliky;Zobr.;Cena;Konverze;Konverzní poměr\n"
        ";0;0;10;10;50,00;0;0%\n"
        "Brand;Povoleno;Vyhledávání;1;1;25,5;1;1%\n"
        "Generic;Povoleno;Výkonnost;2;2;75;2;1%\n"
    )
    with Session(engine) as session:
        client = Client(name="c_gnm", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)
        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)
        svc = MultiSourceCSVService(cr, mr)
        out = svc.import_google_csv_bytes(csv_content.encode("utf-8"), client.id)
        assert out["detected_file_type"] == "google_cz_campaign_period"
        assert out["imported_metrics"] == 1
        m = session.exec(select(CampaignMetric)).first()
        assert m is not None
        assert m.metric_date == date(2026, 3, 31)
        assert abs(float(m.spend) - 100.5) < 0.01


def test_google_cz_ui_preamble_and_campaign_rows(engine) -> None:
    csv_content = (
        "Výkon kampaní\n"
        "Období: 1. 4. 2026 – 30. 4. 2026\n"
        "Kampaň;Prokliky;Zobr.;Cena;Konverze;Konverzní poměr\n"
        ";10;10;50;0;0\n"
        "Brand;1;1;25;1;1\n"
        "Generic;2;2;75;2;1\n"
    )
    with Session(engine) as session:
        client = Client(name="c_gcz", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)
        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)
        svc = MultiSourceCSVService(cr, mr)
        out = svc.import_google_csv_bytes(csv_content.encode("utf-8"), client.id)
        assert out["detected_file_type"] == "google_cz_campaign_period"
        assert out["imported_metrics"] == 1
        m = session.exec(select(CampaignMetric)).first()
        assert m is not None
        assert m.metric_date == date(2026, 4, 30)
        assert abs(float(m.spend) - 100.0) < 0.01


def test_clear_imported_removes_multi_source_platforms_keeps_google_ads(engine) -> None:
    from app.services.csv_service import CLEAR_IMPORTED_CONFIRMATION, CSVService

    with Session(engine) as session:
        client = Client(name="c_clr", margin=0.4)
        session.add(client)
        session.commit()
        session.refresh(client)
        cr = CampaignRepository(session)
        mr = CampaignMetricRepository(session)
        imp = cr.create_for_client(
            client.id,
            Campaign(name="I", platform="imported", client_id=client.id),
        )
        mcsv = cr.create_for_client(
            client.id,
            Campaign(name="M", platform=PLATFORM_CSV_META_ADS, client_id=client.id),
        )
        api = cr.create_for_client(
            client.id,
            Campaign(name="API", platform="google_ads", client_id=client.id),
        )
        mr.bulk_create_for_client(
            client.id,
            [
                CampaignMetric(campaign_id=imp.id, metric_date=date(2026, 1, 1), revenue=1, spend=1),
                CampaignMetric(campaign_id=mcsv.id, metric_date=date(2026, 1, 1), revenue=0, spend=2),
                CampaignMetric(campaign_id=api.id, metric_date=date(2026, 1, 1), revenue=0, spend=3),
            ],
        )
        svc = CSVService(cr, mr)
        out = svc.clear_imported_data_for_client(client.id, CLEAR_IMPORTED_CONFIRMATION)
        assert out["metrics_deleted"] == 2
        assert out["campaigns_deleted"] == 2
        camps = list(session.exec(select(Campaign).where(Campaign.client_id == client.id)))
        assert len(camps) == 1
        assert camps[0].platform == "google_ads"
