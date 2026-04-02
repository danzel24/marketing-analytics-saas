"""Dashboard time series: gaps as null, not zero."""

from datetime import date, timedelta
from types import SimpleNamespace

from app.services.marketing_service import MarketingService


def test_calendar_window_series_inserts_null_without_metrics() -> None:
    """Window ends at the newest day that exists in ``present_days``, not at server today."""
    today = date.today()
    last_data = today - timedelta(days=2)
    first = last_data - timedelta(days=5)
    present = {first, last_data}
    sparse = [
        {"date": first, "value": 100.0},
        {"date": last_data, "value": 50.0},
    ]
    filled = MarketingService._calendar_window_series(sparse, days=7, present_days=present)
    assert len(filled) == 7
    assert filled[-1]["date"] == last_data
    assert filled[-1]["value"] == 50.0
    # Middle days without rows: gap, not 0
    assert any(r["value"] is None for r in filled)


def test_calendar_window_series_ends_today_when_data_includes_today() -> None:
    today = date.today()
    start = today - timedelta(days=6)
    present = {start, start + timedelta(days=1), today}
    sparse = [
        {"date": start, "value": 10.0},
        {"date": today, "value": 99.0},
    ]
    filled = MarketingService._calendar_window_series(sparse, days=7, present_days=present)
    assert filled[-1]["date"] == today
    assert filled[-1]["value"] == 99.0


def test_finite_series_values_skips_nulls() -> None:
    assert MarketingService._finite_series_values([1, None, 3]) == [1.0, 3.0]


def test_incomplete_trailing_day_flagged_when_volume_low_vs_baseline() -> None:
    today = date.today()
    d1 = today - timedelta(days=3)
    d2 = today - timedelta(days=2)
    d3 = today - timedelta(days=1)
    metrics = [
        SimpleNamespace(metric_date=d1, revenue=100.0, spend=50.0),
        SimpleNamespace(metric_date=d2, revenue=100.0, spend=50.0),
        SimpleNamespace(metric_date=d3, revenue=100.0, spend=50.0),
        SimpleNamespace(metric_date=today, revenue=10.0, spend=5.0),
    ]
    start = today - timedelta(days=6)
    excl = MarketingService._detect_incomplete_trailing_calendar_day(
        metrics, window_start=start, window_end=today
    )
    assert excl == today


def test_incomplete_trailing_day_not_flagged_when_stable() -> None:
    today = date.today()
    metrics = [
        SimpleNamespace(metric_date=today - timedelta(days=3), revenue=100.0, spend=50.0),
        SimpleNamespace(metric_date=today - timedelta(days=2), revenue=100.0, spend=50.0),
        SimpleNamespace(metric_date=today - timedelta(days=1), revenue=100.0, spend=50.0),
        SimpleNamespace(metric_date=today, revenue=95.0, spend=48.0),
    ]
    start = today - timedelta(days=6)
    excl = MarketingService._detect_incomplete_trailing_calendar_day(
        metrics, window_start=start, window_end=today
    )
    assert excl is None
