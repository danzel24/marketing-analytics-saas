"""CSV spend/cost column mapping and parsing."""

from unittest.mock import MagicMock

import pytest

from app.services.csv_service import CSVService


@pytest.fixture
def csv_service() -> CSVService:
    return CSVService(MagicMock(), MagicMock())


def test_spend_column_prefers_spend_then_cost(csv_service: CSVService) -> None:
    hm = {"date": "date", "campaign": "campaign", "revenue": "revenue", "cost": "cost", "spend": "spend"}
    assert csv_service._spend_column_original(hm) == "spend"

    hm2 = {"date": "date", "campaign": "campaign", "revenue": "revenue", "cost": "Cost"}
    assert csv_service._spend_column_original(hm2) == "Cost"


def test_spend_column_ad_spend_header(csv_service: CSVService) -> None:
    hm = {"date": "d", "campaign": "c", "revenue": "r", "ad spend": "Ad_Spend"}
    assert csv_service._spend_column_original(hm) == "Ad_Spend"


def test_parse_row_custom_name_maps_cost_to_spend(csv_service: CSVService) -> None:
    csv_service._resolve_campaign_by_name = MagicMock(return_value=99)  # type: ignore[method-assign]
    header_map = {
        "date": "date",
        "campaign": "campaign",
        "revenue": "revenue",
        "cost": "cost",
    }
    row = {
        "date": "2025-06-01",
        "campaign": "fb",
        "revenue": "1000",
        "cost": "500",
    }
    parsed, err = csv_service._parse_row(
        row=row,
        fmt="custom_name",
        header_map=header_map,
        client_id=1,
        row_index=2,
    )
    assert err is None
    assert parsed is not None
    assert parsed["revenue"] == 1000.0
    assert parsed["spend"] == 500.0
    assert parsed["campaign_id"] == 99
    # ROAS = revenue / spend
    assert parsed["revenue"] / parsed["spend"] == 2.0


def test_parse_row_custom_id_maps_cost(csv_service: CSVService) -> None:
    csv_service._resolve_campaign_id = MagicMock(return_value=(42, None))  # type: ignore[method-assign]
    header_map = {
        "date": "date",
        "campaign id": "campaign id",
        "revenue": "revenue",
        "cost": "cost",
    }
    row = {"date": "2025-06-01", "campaign id": "42", "revenue": "1000", "cost": "500"}
    parsed, err = csv_service._parse_row(
        row=row,
        fmt="custom_id",
        header_map=header_map,
        client_id=1,
        row_index=3,
    )
    assert err is None
    assert parsed is not None
    assert parsed["spend"] == 500.0
    assert parsed["revenue"] / parsed["spend"] == 2.0
