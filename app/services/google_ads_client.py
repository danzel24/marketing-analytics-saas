from __future__ import annotations

from typing import Any

from app.models.db_models import Integration


class GoogleAdsClient:
    """Mock Google Ads API client (no real HTTP calls)."""

    def fetch_campaign_data(self, integration: Integration) -> list[dict[str, Any]]:
        _ = integration  # reserved for future real API use
        return [
            {
                "date": "2026-03-01",
                "campaign": "google_ads",
                "cost": 1200,
                "revenue": 2500,
            }
        ]
