from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlmodel import Session

# NOTE: We keep existing CSV-based API methods for now (routes depend on them).
from app.models.campaign import Campaign
from app.repositories.campaign_metric_repository import CampaignMetricRepository
from app.repositories.campaign_repository_sql import CampaignRepository as SqlCampaignRepository
from app.schemas.campaign import CampaignOut, MetricsOut


class MarketingService:
    def __init__(self, session: Session | None = None) -> None:
        self._session = session
        self._campaign_repo = SqlCampaignRepository(session) if session else None
        self._metric_repo = CampaignMetricRepository(session) if session else None

    @staticmethod
    def _safe_div(n: float, d: float) -> float:
        return n / d if d else 0.0

    @staticmethod
    def _roas(revenue: float, spend: float) -> float:
        return round((revenue / spend) if spend else 0.0, 4)

    @classmethod
    def kpis(
        cls,
        *,
        spend: float,
        revenue: float,
        clicks: int,
        conversions: int,
    ) -> dict[str, float]:
        profit = revenue - spend
        roas = cls._safe_div(revenue, spend)
        cpa = cls._safe_div(spend, float(conversions))
        cpc = cls._safe_div(spend, float(clicks))
        conversion_rate = cls._safe_div(float(conversions), float(clicks))

        return {
            "spend": float(spend),
            "revenue": float(revenue),
            "profit": float(profit),
            "roas": float(roas),
            "cpa": float(cpa),
            "cpc": float(cpc),
            "conversion_rate": float(conversion_rate),
        }

    def aggregated_kpis(self, rows: list[dict[str, float | int]]) -> dict[str, float]:
        total_spend = float(sum(float(r.get("spend", 0.0)) for r in rows))
        total_revenue = float(sum(float(r.get("revenue", 0.0)) for r in rows))
        total_clicks = int(sum(int(r.get("clicks", 0)) for r in rows))
        total_conversions = int(sum(int(r.get("conversions", 0)) for r in rows))
        return self.kpis(
            spend=total_spend,
            revenue=total_revenue,
            clicks=total_clicks,
            conversions=total_conversions,
        )

    # -------- DB-backed helpers (used later by routes/services integration) --------
    def _db_requirements(self) -> None:
        if not self._session or not self._campaign_repo or not self._metric_repo:
            raise RuntimeError("MarketingService requires a Session for DB operations.")

    def _db_campaign_ids_for_client(self, *, client_id: int) -> set[int]:
        self._db_requirements()
        campaigns = self._campaign_repo.list(offset=0, limit=100_000)  # type: ignore[union-attr]
        return {c.id for c in campaigns if c.id is not None and c.client_id == client_id}

    def _db_metrics_for_client(self, *, client_id: int, days: int | None = None):
        self._db_requirements()
        campaign_ids = self._db_campaign_ids_for_client(client_id=client_id)
        metrics = self._metric_repo.list(offset=0, limit=500_000)  # type: ignore[union-attr]

        if days is None:
            return [m for m in metrics if m.campaign_id in campaign_ids]

        start = date.today() - timedelta(days=max(int(days), 1) - 1)
        return [m for m in metrics if m.campaign_id in campaign_ids and getattr(m, "metric_date") >= start]

    def campaign_performance(self, *, client_id: int) -> list[dict[str, float | int | str]]:
        """
        Returns campaign-level performance aggregated over all CampaignMetric rows.
        Requires MarketingService(session=...).
        """
        self._db_requirements()

        campaigns = [c for c in self._campaign_repo.list(offset=0, limit=100_000) if c.client_id == client_id]  # type: ignore[union-attr]
        campaigns_by_id = {c.id: c for c in campaigns if c.id is not None}
        metrics = self._db_metrics_for_client(client_id=client_id, days=None)

        agg: dict[int, dict[str, float | int]] = defaultdict(lambda: {"spend": 0.0, "revenue": 0.0, "clicks": 0, "conversions": 0})
        for m in metrics:
            camp = campaigns_by_id.get(m.campaign_id)
            if not camp or camp.client_id != client_id:
                continue
            a = agg[m.campaign_id]
            a["spend"] = float(a["spend"]) + float(m.spend)
            a["revenue"] = float(a["revenue"]) + float(m.revenue)
            a["clicks"] = int(a["clicks"]) + int(m.clicks)
            a["conversions"] = int(a["conversions"]) + int(m.conversions)

        out: list[dict[str, float | int | str]] = []
        for campaign_id, totals in agg.items():
            camp = campaigns_by_id[campaign_id]
            k = self.kpis(
                spend=float(totals["spend"]),
                revenue=float(totals["revenue"]),
                clicks=int(totals["clicks"]),
                conversions=int(totals["conversions"]),
            )
            out.append(
                {
                    "campaign": camp.name,
                    "spend": round(k["spend"], 2),
                    "revenue": round(k["revenue"], 2),
                    "roas": round(k["roas"], 4),
                    "profit": round(k["profit"], 2),
                    "cpa": round(k["cpa"], 4),
                }
            )
        out.sort(key=lambda x: float(x["revenue"]), reverse=True)
        return out

    def dashboard_overview_db(self, *, client_id: int, days: int | None = None) -> dict[str, float]:
        """
        DB-only: aggregated KPIs for a client (optionally over last N days).
        Returns: total_spend, total_revenue, total_profit, average_roas
        """
        metrics = self._db_metrics_for_client(client_id=client_id, days=days)
        total_spend = float(sum(float(m.spend) for m in metrics))
        total_revenue = float(sum(float(m.revenue) for m in metrics))
        total_profit = total_revenue - total_spend
        average_roas = float(self._safe_div(total_revenue, total_spend))
        return {
            "total_spend": round(total_spend, 2),
            "total_revenue": round(total_revenue, 2),
            "total_profit": round(total_profit, 2),
            "average_roas": round(average_roas, 4),
        }

    def revenue_trend_db(self, *, client_id: int, days: int = 30) -> dict[str, list]:
        metrics = self._db_metrics_for_client(client_id=client_id, days=days)
        by_day: dict[date, float] = defaultdict(float)
        for m in metrics:
            by_day[getattr(m, "metric_date")] += float(m.revenue)
        labels = [(date.today() - timedelta(days=i)) for i in range(max(int(days), 1) - 1, -1, -1)]
        return {"labels": [d.isoformat() for d in labels], "revenue": [round(by_day.get(d, 0.0), 2) for d in labels]}

    def spend_trend_db(self, *, client_id: int, days: int = 30) -> dict[str, list]:
        metrics = self._db_metrics_for_client(client_id=client_id, days=days)
        by_day: dict[date, float] = defaultdict(float)
        for m in metrics:
            by_day[getattr(m, "metric_date")] += float(m.spend)
        labels = [(date.today() - timedelta(days=i)) for i in range(max(int(days), 1) - 1, -1, -1)]
        return {"labels": [d.isoformat() for d in labels], "spend": [round(by_day.get(d, 0.0), 2) for d in labels]}

    def roas_trend_db(self, *, client_id: int, days: int = 30) -> dict[str, list]:
        metrics = self._db_metrics_for_client(client_id=client_id, days=days)
        rev_by_day: dict[date, float] = defaultdict(float)
        spend_by_day: dict[date, float] = defaultdict(float)
        for m in metrics:
            d = getattr(m, "metric_date")
            rev_by_day[d] += float(m.revenue)
            spend_by_day[d] += float(m.spend)
        labels = [(date.today() - timedelta(days=i)) for i in range(max(int(days), 1) - 1, -1, -1)]
        values = [round(self._safe_div(rev_by_day.get(d, 0.0), spend_by_day.get(d, 0.0)), 4) for d in labels]
        return {"labels": [d.isoformat() for d in labels], "roas": values}

    def top_campaigns_db(self, *, client_id: int, days: int = 30, top_n: int = 5) -> list[dict[str, float | int | str]]:
        """
        DB-only: Top campaigns by revenue (default). Aggregates metrics over last N days.
        Returns items compatible with the requested campaign performance shape.
        """
        self._db_requirements()

        campaigns = [c for c in self._campaign_repo.list(offset=0, limit=100_000) if c.client_id == client_id]  # type: ignore[union-attr]
        campaigns_by_id = {c.id: c for c in campaigns if c.id is not None}
        metrics = self._db_metrics_for_client(client_id=client_id, days=days)

        agg: dict[int, dict[str, float | int]] = defaultdict(lambda: {"spend": 0.0, "revenue": 0.0, "clicks": 0, "conversions": 0})
        for m in metrics:
            if m.campaign_id not in campaigns_by_id:
                continue
            a = agg[m.campaign_id]
            a["spend"] = float(a["spend"]) + float(m.spend)
            a["revenue"] = float(a["revenue"]) + float(m.revenue)
            a["clicks"] = int(a["clicks"]) + int(m.clicks)
            a["conversions"] = int(a["conversions"]) + int(m.conversions)

        rows: list[dict[str, float | int | str]] = []
        for campaign_id, totals in agg.items():
            camp = campaigns_by_id[campaign_id]
            k = self.kpis(
                spend=float(totals["spend"]),
                revenue=float(totals["revenue"]),
                clicks=int(totals["clicks"]),
                conversions=int(totals["conversions"]),
            )
            rows.append(
                {
                    "campaign": camp.name,
                    "spend": round(k["spend"], 2),
                    "revenue": round(k["revenue"], 2),
                    "roas": round(k["roas"], 4),
                    "profit": round(k["profit"], 2),
                    "cpa": round(k["cpa"], 4),
                }
            )

        rows.sort(key=lambda x: float(x["revenue"]), reverse=True)
        return rows[: max(int(top_n), 0)]

    def dashboard_full_db(self, *, client_id: int, days: int = 30, top_n: int = 5) -> dict[str, object]:
        """
        DB-only: One payload powering the whole dashboard.
        """
        overview = self.dashboard_overview_db(client_id=client_id, days=days)
        revenue_trend = self.revenue_trend_db(client_id=client_id, days=days)
        spend_trend = self.spend_trend_db(client_id=client_id, days=days)
        top_campaigns = self.top_campaigns_db(client_id=client_id, days=days, top_n=top_n)
        return {
            "overview": overview,
            "revenue_trend": revenue_trend,
            "spend_trend": spend_trend,
            "top_campaigns": top_campaigns,
        }

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

