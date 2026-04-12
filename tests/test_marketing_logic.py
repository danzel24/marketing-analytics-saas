"""Core financial and status logic for marketing metrics."""

from datetime import date, datetime

from app.services.marketing_service import (
    MIN_SPEND_CZK_FOR_HARD_STOP,
    MarketingService,
)
from app.services.csv_service import CSVService


def test_campaign_status_is_consistent_with_contribution_profit() -> None:
    svc = MarketingService()
    margin = 0.3

    profitable = svc.calculate_campaign_metrics(revenue=1200.0, cost=300.0, margin=margin)
    # BE = 1/0.3 ≈ 3.33; at_risk band [0.9×BE, 1.1×BE] → e.g. ROAS 3.0
    at_risk = svc.calculate_campaign_metrics(revenue=900.0, cost=300.0, margin=margin)
    loss = svc.calculate_campaign_metrics(revenue=400.0, cost=300.0, margin=margin)

    campaigns = [profitable, at_risk, loss]

    statuses = {str(c["status"]) for c in campaigns}
    assert "profitable" in statuses
    assert "at_risk" in statuses
    assert "loss" in statuses

    for campaign in campaigns:
        status = str(campaign["status"])
        contribution_profit = float(campaign["contribution_profit"])

        if status == "loss":
            assert contribution_profit < 0
        if status == "profitable":
            assert contribution_profit >= 0


def test_roas_and_break_even_formulas() -> None:
    m = MarketingService.calculate_campaign_metrics(revenue=1000.0, cost=250.0, margin=0.4)
    assert m["roas"] == 4.0
    assert m["break_even_roas"] == 2.5
    assert m["marketing_profit"] == 1000.0 * 0.4 - 250.0


def test_break_even_campaign_near_boundary() -> None:
    """At exactly ROAS = BE, contribution is zero — buffer band marks at_risk."""
    margin = 0.4
    be = 1.0 / margin
    cost = 200.0
    revenue = cost * be
    m = MarketingService.calculate_campaign_metrics(revenue=revenue, cost=cost, margin=margin)
    assert m["status"] == "at_risk"
    assert abs(float(m["contribution_profit"])) < 1e-6


def test_zero_spend_positive_revenue_is_no_ad_spend() -> None:
    m = MarketingService.calculate_campaign_metrics(revenue=500.0, cost=0.0, margin=0.4)
    assert m["status"] == "no_ad_spend"
    assert m["roas"] == 0.0
    assert float(m["marketing_profit"]) > 0
    assert "reklamní náklady" in str(m["status_reason"])


def test_zero_spend_recommendation_avoids_roas_break_even_copy() -> None:
    m = MarketingService.calculate_campaign_metrics(revenue=500.0, cost=0.0, margin=0.4)
    rec = MarketingService.generate_campaign_recommendation(m, "Orphan", window_days=30)
    combined = str(rec.get("rec_reason", "")) + str(rec.get("message", ""))
    assert "bod zvratu" not in combined.lower()
    assert "0.00" not in str(rec.get("rec_reason", ""))


def test_zero_spend_zero_revenue_is_insufficient_data() -> None:
    m = MarketingService.calculate_campaign_metrics(revenue=0.0, cost=0.0, margin=0.4)
    assert m["status"] == "insufficient_data"


def test_negative_inputs_clamped_to_zero() -> None:
    m = MarketingService.calculate_campaign_metrics(revenue=-100.0, cost=50.0, margin=0.4)
    assert float(m["revenue"]) == 0.0
    m2 = MarketingService.calculate_campaign_metrics(revenue=100.0, cost=-10.0, margin=0.4)
    assert float(m2["cost"]) == 0.0


def test_margin_percent_style_normalized() -> None:
    m = MarketingService.calculate_campaign_metrics(revenue=1000.0, cost=400.0, margin=40.0)
    assert float(m["margin_used"]) == 0.4
    assert m["break_even_roas"] == 2.5


def test_safe_div_zero_denominator() -> None:
    assert MarketingService._safe_div(100.0, 0.0) == 0.0


def test_portfolio_roas_status_matches_bands() -> None:
    be = 2.5
    # loss < 2.25 ; at_risk [2.25, 2.75] ; profitable > 2.75
    assert MarketingService.portfolio_roas_status(3.0, 100.0, be) == "profitable"
    assert MarketingService.portfolio_roas_status(2.5, 100.0, be) == "at_risk"
    assert MarketingService.portfolio_roas_status(2.0, 100.0, be) == "loss"
    assert MarketingService.portfolio_roas_status(5.0, 0.0, be) == "insufficient_data"


def test_recommendation_insufficient_data_is_not_stop() -> None:
    m = MarketingService.calculate_campaign_metrics(0.0, 0.0, 0.4)
    rec = MarketingService.generate_campaign_recommendation(m, "Test")
    assert rec["severity"] == "info"
    assert "Vypni" not in str(rec["message"])
    assert "❌" not in str(rec.get("action_label", ""))


def test_recommendation_scale_requires_min_spend_unless_big_profit() -> None:
    margin = 0.4
    be = 2.5
    # ROAS well above BE but spend below threshold and modest profit
    revenue = 1000.0
    cost = min(MIN_SPEND_CZK_FOR_HARD_STOP, 200.0)
    assert cost < MIN_SPEND_CZK_FOR_HARD_STOP
    m = MarketingService.calculate_campaign_metrics(revenue=revenue, cost=cost, margin=margin)
    assert float(m["roas"]) >= be * 1.25
    rec = MarketingService.generate_campaign_recommendation(m, "Small", window_days=30)
    assert rec["type"] != "scale"


def test_normalize_metric_day_accepts_date_datetime_and_iso_string() -> None:
    assert MarketingService._normalize_metric_day(date(2024, 6, 1)) == date(2024, 6, 1)
    assert MarketingService._normalize_metric_day(datetime(2024, 6, 1, 14, 30)) == date(2024, 6, 1)
    assert MarketingService._normalize_metric_day("2024-06-15") == date(2024, 6, 15)
    assert MarketingService._normalize_metric_day("2024-06-15T12:00:00Z") == date(2024, 6, 15)
    assert MarketingService._normalize_metric_day(None) is None
    assert MarketingService._normalize_metric_day("") is None


def test_csv_parse_currency_strips_kc() -> None:
    assert CSVService.parse_currency("1 234,50 Kč") == 1234.5
    assert CSVService.parse_currency("100€") == 100.0


def test_loss_recommendation_soft_day_phrase_when_all_days_loss() -> None:
    margin = 0.4
    m = MarketingService.calculate_campaign_metrics(revenue=100.0, cost=500.0, margin=margin)
    assert m["status"] == "loss"
    rec = MarketingService.generate_campaign_recommendation(
        m,
        "fb",
        window_days=30,
        day_stats={"days_total": 28, "days_in_loss": 28, "days_below_be_roas": 28},
    )
    combined = str(rec.get("rec_reason", "")) + str(rec.get("message", ""))
    assert "28/28" in combined and "minusu" in combined
