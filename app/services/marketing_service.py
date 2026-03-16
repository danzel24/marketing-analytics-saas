from __future__ import annotations

from app.models.campaign import Campaign
from app.schemas.campaign import CampaignOut, MetricsOut


class MarketingService:
    @staticmethod
    def _roas(revenue: float, spend: float) -> float:
        return round((revenue / spend) if spend else 0.0, 4)

    def campaigns_overview(self, campaigns: list[Campaign]) -> list[CampaignOut]:
        result: list[CampaignOut] = []
        for c in campaigns:
            profit = c.revenue - c.spend
            result.append(
                CampaignOut(
                    campaign=c.name,
                    spend=round(c.spend, 2),
                    revenue=round(c.revenue, 2),
                    profit=round(profit, 2),
                    roas=self._roas(c.revenue, c.spend),
                )
            )
        return result

    def aggregated_metrics(self, campaigns: list[Campaign]) -> MetricsOut:
        total_spend = sum(c.spend for c in campaigns)
        total_revenue = sum(c.revenue for c in campaigns)
        total_profit = total_revenue - total_spend

        per_campaign_roas = [self._roas(c.revenue, c.spend) for c in campaigns]
        average_roas = round((sum(per_campaign_roas) / len(per_campaign_roas)) if campaigns else 0.0, 4)

        return MetricsOut(
            total_spend=round(total_spend, 2),
            total_revenue=round(total_revenue, 2),
            total_profit=round(total_profit, 2),
            average_roas=average_roas,
            campaigns_count=len(campaigns),
        )

