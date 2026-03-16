from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from app.models.db_models import Campaign
from app.utils.csv_loader import read_ads_rows


@lru_cache(maxsize=64)
def _load_campaigns(csv_path_str: str, mtime_ns: int) -> tuple[Campaign, ...]:
    """
    Cache invalidates when the CSV file mtime changes.
    """
    csv_path = Path(csv_path_str)
    spend_by_campaign: dict[str, float] = defaultdict(float)
    revenue_by_campaign: dict[str, float] = defaultdict(float)

    for row in read_ads_rows(csv_path):
        name = (row.get("campaign") or "").strip()
        if not name:
            continue
        spend_by_campaign[name] += float(row.get("spend") or 0)
        revenue_by_campaign[name] += float(row.get("revenue") or 0)

    campaigns = tuple(
        Campaign(name=name, spend=spend_by_campaign[name], revenue=revenue_by_campaign[name])
        for name in sorted(set(spend_by_campaign) | set(revenue_by_campaign))
    )
    return campaigns


class CampaignRepository:
    def __init__(self, csv_path: Path) -> None:
        self._csv_path = csv_path

    def list_campaigns(self) -> list[Campaign]:
        mtime_ns = self._csv_path.stat().st_mtime_ns
        return list(_load_campaigns(str(self._csv_path), mtime_ns))

