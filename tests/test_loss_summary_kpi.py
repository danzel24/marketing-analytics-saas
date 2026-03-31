"""Portfolio loss KPI aligns with campaign table economics (contribution profit)."""

from app.services.marketing_service import MarketingService


def test_loss_kpi_counts_at_risk_negative_contribution() -> None:
    row = {
        "source": "paid",
        "status": "at_risk",
        "contribution_profit": -1832.0,
        "campaign": "Google Shopping",
    }
    assert MarketingService._campaign_row_counts_toward_loss_kpi(row) is True


def test_loss_kpi_counts_loss_status() -> None:
    row = {
        "source": "paid",
        "status": "loss",
        "contribution_profit": -500.0,
    }
    assert MarketingService._campaign_row_counts_toward_loss_kpi(row) is True


def test_loss_kpi_skips_at_risk_positive_contribution() -> None:
    row = {
        "source": "paid",
        "status": "at_risk",
        "contribution_profit": 120.0,
    }
    assert MarketingService._campaign_row_counts_toward_loss_kpi(row) is False


def test_loss_kpi_skips_organic_and_insufficient() -> None:
    assert (
        MarketingService._campaign_row_counts_toward_loss_kpi(
            {"source": "organic", "status": "loss", "contribution_profit": -10.0}
        )
        is False
    )
    assert (
        MarketingService._campaign_row_counts_toward_loss_kpi(
            {"source": "paid", "status": "insufficient_data", "contribution_profit": -10.0}
        )
        is False
    )
