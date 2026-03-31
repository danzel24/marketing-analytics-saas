"""Campaign name resolution for custom_name CSV import (multi-tenant)."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.db_models import Campaign
from app.services.csv_service import CSVService, DEFAULT_IMPORT_CAMPAIGN_NAME


@pytest.fixture
def campaign_repo() -> MagicMock:
    return MagicMock()


@pytest.fixture
def csv_service(campaign_repo: MagicMock) -> CSVService:
    return CSVService(campaign_repo, MagicMock())


def test_resolve_empty_name_uses_default_campaign(csv_service: CSVService, campaign_repo: MagicMock) -> None:
    default = Campaign(id=7, name=DEFAULT_IMPORT_CAMPAIGN_NAME, platform="imported", client_id=1)
    csv_service.get_or_create_default_campaign = MagicMock(return_value=default)  # type: ignore[method-assign]

    assert csv_service._resolve_campaign_by_name("", 1) == 7
    csv_service.get_or_create_default_campaign.assert_called_once_with(1)
    campaign_repo.get_by_name.assert_not_called()


def test_resolve_existing_name_returns_id(csv_service: CSVService, campaign_repo: MagicMock) -> None:
    existing = Campaign(id=42, name="Summer Sale", platform="google", client_id=1)
    campaign_repo.get_by_name.return_value = existing

    assert csv_service._resolve_campaign_by_name("Summer Sale", 1) == 42
    campaign_repo.get_by_name.assert_called_once_with(1, "Summer Sale")
    campaign_repo.create_for_client.assert_not_called()


def test_resolve_new_name_creates_import_campaign(csv_service: CSVService, campaign_repo: MagicMock) -> None:
    campaign_repo.get_by_name.return_value = None
    created = Campaign(id=99, name="New Promo", platform="imported", client_id=1)
    campaign_repo.create_for_client.return_value = created

    assert csv_service._resolve_campaign_by_name("New Promo", 1) == 99
    campaign_repo.create_for_client.assert_called_once()
    args, kwargs = campaign_repo.create_for_client.call_args
    assert args[0] == 1
    c = args[1]
    assert isinstance(c, Campaign)
    assert c.name == "New Promo"
    assert c.platform == "imported"
    assert c.client_id == 1


def test_resolve_integrity_error_fetches_existing(csv_service: CSVService, campaign_repo: MagicMock) -> None:
    campaign_repo.get_by_name.side_effect = [
        None,
        Campaign(id=3, name="Race", platform="imported", client_id=1),
    ]
    campaign_repo.create_for_client.side_effect = IntegrityError("stmt", "params", Exception("orig"))
    campaign_repo.session = MagicMock()

    assert csv_service._resolve_campaign_by_name("Race", 1) == 3
    campaign_repo.session.rollback.assert_called_once()


def test_resolve_integrity_no_row_returns_none(csv_service: CSVService, campaign_repo: MagicMock) -> None:
    campaign_repo.get_by_name.return_value = None
    campaign_repo.create_for_client.side_effect = IntegrityError("stmt", "params", Exception("orig"))
    campaign_repo.session = MagicMock()

    assert csv_service._resolve_campaign_by_name("X", 1) is None
