from __future__ import annotations

import logging
from typing import Any
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session

logger = logging.getLogger(__name__)

# Table „Důvod“ column for zero-spend rows (explicit copy for API + UI fallback).
NO_AD_SPEND_TABLE_REASON = "ROAS se nepočítá, protože v datech nejsou reklamní náklady."

# NOTE: We keep existing CSV-based API methods for now (routes depend on them).
from app.core.domain_errors import InternalMisuseError, NotFoundError
from app.models.campaign import Campaign
from app.repositories.campaign_metric_repository import CampaignMetricRepository
from app.repositories.client_repository import ClientRepository
from app.repositories.campaign_repository_sql import CampaignRepository as SqlCampaignRepository
from app.repositories.tenant_scope import require_positive_client_id
from app.schemas.campaign import CampaignOut, MetricsOut

DEFAULT_MARGIN = 0.4

# Minimum paid spend (CZK) before we use the strongest "turn off" wording.
MIN_SPEND_CZK_FOR_HARD_STOP = 500.0
# Minimum distinct active days in window before day-based proof is trusted for hard stop.
MIN_ACTIVE_DAYS_FOR_HARD_STOP = 5

# Anti-flip buffer: ROAS must clear break-even by these factors to leave the "at_risk" band.
ROAS_LOSS_FACTOR = 0.9
ROAS_PROFITABLE_FACTOR = 1.1


class MarketingService:
    def __init__(self, session: Session | None = None, client_margin: float = DEFAULT_MARGIN) -> None:
        self._session = session
        self._client_margin = client_margin if 0 < client_margin < 1 else DEFAULT_MARGIN
        self._campaign_repo = SqlCampaignRepository(session) if session else None
        self._metric_repo = CampaignMetricRepository(session) if session else None
        self._client_repo = ClientRepository(session) if session else None

    @staticmethod
    def _safe_div(n: float, d: float) -> float:
        return n / d if d else 0.0

    @staticmethod
    def portfolio_roas_status(average_roas: float, paid_spend: float, break_even_roas: float) -> str:
        """Classify portfolio ROAS using the same buffer as per-campaign status (requires paid spend)."""
        if paid_spend <= 0:
            return "insufficient_data"
        if break_even_roas <= 0:
            return "at_risk"
        if average_roas > break_even_roas * ROAS_PROFITABLE_FACTOR:
            return "profitable"
        if average_roas < break_even_roas * ROAS_LOSS_FACTOR:
            return "loss"
        return "at_risk"

    @staticmethod
    def _non_negative_money(x: float) -> float:
        """Imported amounts should not be negative; clamp to avoid misleading ROAS/profit."""
        v = float(x)
        return v if v >= 0.0 else 0.0

    @staticmethod
    def _pct_change_vs_prior(current: float, prior: float, *, min_prior_abs: float) -> float | None:
        """(current − prior) / |prior| × 100; None if prior is too small to avoid noisy / misleading %."""
        p = float(prior)
        if abs(p) < float(min_prior_abs):
            return None
        return round((float(current) - p) / abs(p) * 100.0, 1)

    @staticmethod
    def _validated_margin(margin: float | int | None) -> float:
        m = float(margin or 0.0)
        if 0 < m < 1:
            return m
        # Common misconfiguration: store 40 meaning 40 %
        if 1 < m <= 100:
            return m / 100.0
        return DEFAULT_MARGIN

    @staticmethod
    def _margin_explanation() -> str:
        return "Zisk = tržby × marže − náklady na reklamu"

    @staticmethod
    def _parse_trend_date(raw: object) -> date | None:
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return raw.date()
        if isinstance(raw, date):
            return raw
        s = str(raw).strip()
        if not s:
            return None
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

    @classmethod
    def _normalize_metric_day(cls, value: object) -> date | None:
        """
        Coerce ORM/DB ``metric_date`` to ``date`` for day-level aggregations and trends.

        KPI sums iterate all rows regardless of type; trend helpers used ``isinstance(..., date)``
        only. If a driver returns ISO strings, ``present_days`` stayed empty and charts were all-null
        while totals and the campaign table still looked correct.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return cls._parse_trend_date(value)
        return None

    @classmethod
    def _calendar_window_series(
        cls,
        sparse: list[dict[str, object]],
        days: int,
        *,
        present_days: set[date],
    ) -> list[dict[str, object]]:
        """
        Last ``days`` calendar days in chronological order.

        The window ends at ``min(today, max(present_days))`` when ``present_days`` is non-empty,
        so charts do not extend past the newest day that exists in the dataset (uploaded CSV).

        Days with **no** metric rows in the window use ``value: None`` (chart gap — never fake zero).
        Days with at least one row use the aggregated float (zero is a real zero).
        """
        n = max(int(days), 1)
        end = date.today()
        if present_days:
            end = min(end, max(present_days))
        start = end - timedelta(days=n - 1)
        by_day: dict[date, float] = defaultdict(float)
        for item in sparse:
            d = cls._parse_trend_date(item.get("date"))
            if d is None:
                continue
            try:
                by_day[d] += float(item.get("value", 0) or 0)
            except (TypeError, ValueError):
                continue
        out: list[dict[str, object]] = []
        for i in range(n):
            d = start + timedelta(days=i)
            if d not in present_days:
                out.append({"date": d, "value": None})
            else:
                out.append({"date": d, "value": round(float(by_day.get(d, 0.0)), 2)})
        return out

    @classmethod
    def _metric_dates_in_window(cls, metrics: list[object]) -> set[date]:
        dates: set[date] = set()
        for m in metrics:
            md = cls._normalize_metric_day(getattr(m, "metric_date", None))
            if md is not None:
                dates.add(md)
        return dates

    @staticmethod
    def _roas(revenue: float, spend: float) -> float:
        return round((revenue / spend) if spend else 0.0, 4)

    def get_break_even_roas(self) -> float:
        return round((1 / self._client_margin) if self._client_margin > 0 else 0.0, 4)

    @staticmethod
    def _is_organic_campaign(campaign_name: str | None) -> bool:
        return str(campaign_name or "").strip().lower() == "shopify"

    @staticmethod
    def calculate_campaign_metrics(
        revenue: float,
        cost: float,
        margin: float = DEFAULT_MARGIN,
    ) -> dict[str, float | str | dict[str, float]]:
        revenue_f = MarketingService._non_negative_money(revenue)
        cost_f = MarketingService._non_negative_money(cost)
        margin_f = MarketingService._validated_margin(margin)
        # This is NOT real profit (does not include COGS, VAT, logistics).
        # "Marketingový přínos" is contribution-level proxy:
        # contribution_profit = revenue * margin - ad_spend
        marketing_profit = revenue_f * margin_f - cost_f
        contribution_profit = revenue_f * margin_f - cost_f
        roas = MarketingService._safe_div(revenue_f, cost_f)
        break_even_roas = MarketingService._safe_div(1.0, margin_f)

        if revenue_f <= 0.0 and cost_f <= 0.0:
            status = "insufficient_data"
        elif cost_f <= 0.0 and revenue_f > 0.0:
            # ROAS is undefined at zero spend; do not classify like a paid ROAS band.
            status = "no_ad_spend"
        elif cost_f <= 0.0:
            status = "profitable" if contribution_profit >= 0 else "loss"
        else:
            loss_line = break_even_roas * ROAS_LOSS_FACTOR
            win_line = break_even_roas * ROAS_PROFITABLE_FACTOR
            if roas > win_line:
                status = "profitable"
            elif roas < loss_line:
                status = "loss"
            else:
                status = "at_risk"

        metrics: dict[str, float | str | dict[str, float]] = {
            "revenue": revenue_f,
            "cost": cost_f,
            "marketing_profit": marketing_profit,
            "contribution_profit": contribution_profit,
            "profit": marketing_profit,  # backward compatibility
            "roas": round(roas, 2),
            "break_even_roas": round(break_even_roas, 2),
            "margin_used": round(margin_f, 4),
            "status": status,
        }
        explanation = MarketingService.explain_campaign_status(metrics)
        metrics["status_reason"] = explanation["reason"]
        metrics["status_details"] = explanation["details"]
        if __debug__:
            MarketingService._assert_status_matches_economics(metrics)
        return metrics

    @staticmethod
    def _assert_status_matches_economics(metrics: dict[str, float | str | dict[str, float]]) -> None:
        """Dev-only consistency check between status, ROAS, break-even and contribution profit."""
        status = str(metrics.get("status", ""))
        cost = float(metrics.get("cost", 0) or 0)
        rev = float(metrics.get("revenue", 0) or 0)
        contrib = float(metrics.get("contribution_profit", 0) or 0)
        margin_f = float(metrics.get("margin_used", 0) or 0)
        roas_raw = MarketingService._safe_div(rev, cost)
        be_raw = MarketingService._safe_div(1.0, margin_f) if margin_f > 0 else 0.0
        if status == "insufficient_data":
            assert rev <= 0 and cost <= 0
            return
        if status == "no_ad_spend":
            assert rev > 0 and cost <= 0
            return
        if cost <= 0:
            return
        assert be_raw > 0
        loss_line = be_raw * ROAS_LOSS_FACTOR
        win_line = be_raw * ROAS_PROFITABLE_FACTOR
        if status == "profitable":
            assert roas_raw > win_line - 1e-9
            assert contrib >= -1e-3
        elif status == "at_risk":
            assert loss_line - 1e-9 <= roas_raw <= win_line + 1e-9
        elif status == "loss":
            assert roas_raw < loss_line + 1e-9
            assert contrib < -1e-3

    @staticmethod
    def explain_campaign_status(metrics: dict[str, float | str | dict[str, float]]) -> dict[str, str | dict[str, float]]:
        roas = float(metrics.get("roas", 0) or 0)
        break_even = float(metrics.get("break_even_roas", 0) or 0)
        profit = float(metrics.get("profit", 0) or 0)
        status = str(metrics.get("status", ""))

        if status == "insufficient_data":
            return {
                "reason": "Žádná aktivita v období",
                "details": {"revenue": float(metrics.get("revenue", 0) or 0), "cost": float(metrics.get("cost", 0) or 0)},
            }

        if status == "no_ad_spend":
            return {
                "reason": NO_AD_SPEND_TABLE_REASON,
                "details": {
                    "revenue": float(metrics.get("revenue", 0) or 0),
                    "cost": 0.0,
                    "profit": profit,
                },
            }

        if status == "loss":
            return {
                "reason": "Kampaň nevydělává",
                "details": {
                    "profit": profit,
                    "roas": roas,
                    "break_even_roas": break_even,
                },
            }

        if status == "at_risk":
            return {
                "reason": "Kampaň je mírně pod bodem zvratu (v pásmu tolerance)",
                "details": {
                    "roas": roas,
                    "break_even_roas": break_even,
                    "profit": profit,
                },
            }

        return {
            "reason": "Kampaň vydělává",
            "details": {
                "roas": roas,
                "break_even_roas": break_even,
                "profit": profit,
            },
        }

    @staticmethod
    def campaign_decision_from_row(row: dict[str, object]) -> dict[str, str]:
        """Table ACTION column: aligns with ROAS vs break-even status."""
        if str(row.get("source", "paid")) == "organic":
            return {"code": "organic", "label": "—"}
        status = str(row.get("status", ""))
        if status == "insufficient_data":
            return {"code": "needs_data", "label": "⚪ Nedostatek dat — zatím nedoporučujeme akci"}
        if status == "no_ad_spend":
            return {"code": "no_ad_spend", "label": "ℹ️ Bez nákladů na reklamu"}
        if status == "loss":
            return {"code": "stop", "label": "❌ Vypnout"}
        if status == "at_risk":
            return {"code": "adjust", "label": "⚠️ Upravit"}
        return {"code": "scale", "label": "✅ Škálovat"}

    @staticmethod
    def _attach_decision_fields(row: dict[str, object]) -> None:
        d = MarketingService.campaign_decision_from_row(row)
        row["decision_action"] = d["code"]
        row["decision_label"] = d["label"]
        if __debug__:
            MarketingService._assert_decision_matches_status(row)

    @staticmethod
    def _assert_decision_matches_status(row: dict[str, object]) -> None:
        """Dev guard: status and decision_action must never contradict (trust hardening)."""
        st = str(row.get("status", ""))
        act = str(row.get("decision_action", ""))
        src = str(row.get("source", "paid"))
        if src == "organic":
            assert act == "organic", (st, act, row.get("campaign"))
            return
        if st == "insufficient_data":
            assert act == "needs_data", (st, act, row.get("campaign"))
            return
        if st == "no_ad_spend":
            assert act == "no_ad_spend", (st, act, row.get("campaign"))
            return
        if st == "loss":
            assert act == "stop", (st, act, row.get("campaign"))
        elif st == "at_risk":
            assert act == "adjust", (st, act, row.get("campaign"))
        elif st == "profitable":
            assert act == "scale", (st, act, row.get("campaign"))

    @staticmethod
    def evaluation_snapshot_from_row(row: dict[str, object]) -> dict[str, object]:
        """Read-only view of campaign evaluation for insights/UI — no recalculation."""
        return {
            "campaign": row.get("campaign"),
            "roas": row.get("roas"),
            "profit": row.get("profit"),
            "break_even_roas": row.get("break_even_roas"),
            "status": row.get("status"),
            "decision_label": row.get("decision_label"),
            "decision_action": row.get("decision_action"),
        }

    @staticmethod
    def dedupe_daily_against_primary(
        primary: dict[str, object] | None,
        daily: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        """Drop list items identical to the primary card (same campaign + same text)."""
        if not primary or not daily:
            return daily
        pc = str(primary.get("campaign") or "").strip().lower()
        pt = str(primary.get("text") or "").strip()
        if not pc or not pt:
            return daily
        return [
            d
            for d in daily
            if not (
                str(d.get("campaign") or "").strip().lower() == pc
                and str(d.get("text") or "").strip() == pt
            )
        ]

    @staticmethod
    def _paid_rows_for_signals(rows: list[dict[str, object]]) -> list[dict[str, object]]:
        """Paid campaigns with enough data to drive recommendations (excludes organic + empty window)."""
        return [
            r
            for r in rows
            if str(r.get("source", "paid")) != "organic"
            and str(r.get("status", "")) not in ("insufficient_data", "no_ad_spend")
        ]

    def _campaign_day_stats_map(
        self,
        client_id: int,
        days: int,
        *,
        metrics: list[object] | None = None,
    ) -> dict[int, dict[str, int]]:
        """Per-campaign: days with spend/revenue in window, days with negative contribution profit, days ROAS < BE."""
        self._db_requirements()
        cid = require_positive_client_id(client_id)
        margin = self._margin_for_client(cid)
        break_even = (1 / margin) if margin > 0 else 0.0
        if metrics is None:
            metrics, _ = self._metrics_for_client_window(client_id=cid, days=days)
        day_totals: dict[tuple[int, date], list[float]] = defaultdict(lambda: [0.0, 0.0])
        for m in metrics:
            md = MarketingService._normalize_metric_day(getattr(m, "metric_date", None))
            if md is None:
                continue
            key = (int(m.campaign_id), md)
            day_totals[key][0] += float(m.revenue)
            day_totals[key][1] += float(m.spend)

        per_campaign: dict[int, list[tuple[bool, bool]]] = defaultdict(list)
        for (camp_id, _d), (rev, spend) in day_totals.items():
            if rev <= 0 and spend <= 0:
                continue
            prof = rev * margin - spend
            roas_d = (rev / spend) if spend > 0 else 0.0
            loss_day = prof < 0
            has_spend = spend > 0
            below_be = has_spend and break_even > 0 and roas_d < break_even
            above_be = has_spend and break_even > 0 and roas_d >= break_even
            per_campaign[camp_id].append((loss_day, below_be, above_be, has_spend))

        out: dict[int, dict[str, int]] = {}
        for camp_id, flags in per_campaign.items():
            dt = len(flags)
            dil = sum(1 for loss_day, _, _, _ in flags if loss_day)
            dbe = sum(1 for _, bb, _, _ in flags if bb)
            dab = sum(1 for (_, _, ab, _) in flags if ab)
            dws = sum(1 for (_, _, _, hs) in flags if hs)
            out[camp_id] = {
                "days_total": dt,
                "days_in_loss": dil,
                "days_below_be_roas": dbe,
                "days_above_break_even_roas": dab,
                "days_with_spend": dws,
            }
        return out

    @staticmethod
    def _log_recommendation_consistency(
        campaign_name: str,
        metrics: dict[str, float | str | dict[str, float]],
        rec: dict[str, str | int],
    ) -> None:
        """Catch impossible combinations of ROAS, status, and recommendation type (trust)."""
        roas = float(metrics.get("roas", 0) or 0)
        be = float(metrics.get("break_even_roas", 0) or 0)
        st = str(metrics.get("status", ""))
        rtype = str(rec.get("type", ""))
        if be <= 0:
            return
        if roas > be and st == "loss":
            logger.warning(
                "Recommendation consistency: %r has ROAS %.4f > break-even %.4f but status=loss.",
                campaign_name,
                roas,
                be,
            )
        if roas > be and rtype == "critical":
            logger.warning(
                "Recommendation consistency: %r has ROAS %.4f > break-even %.4f but type=critical.",
                campaign_name,
                roas,
                be,
            )

    @staticmethod
    def generate_campaign_recommendation(
        metrics: dict[str, float | str | dict[str, float]],
        campaign_name: str,
        *,
        window_days: int = 30,
        day_stats: dict[str, int] | None = None,
    ) -> dict[str, str | int]:
        roas = float(metrics.get("roas", 0) or 0)
        break_even = float(metrics.get("break_even_roas", 0) or 0)
        profit = float(metrics.get("marketing_profit", metrics.get("profit", 0)) or 0)
        cost = float(metrics.get("cost", 0) or 0)
        status = str(metrics.get("status", ""))
        name = (campaign_name or "").strip() or "Kampaň"
        roas_vs = f"{roas:.2f}× vs {break_even:.2f}×" if break_even > 0 else f"{roas:.2f}×"

        gap_ratio = 0.0
        if break_even > 0:
            gap_ratio = max(0.0, min(1.0, (break_even - roas) / break_even))
        reduction_pct = int(round(gap_ratio * 100))
        wd = max(int(window_days), 1)

        dt = int(day_stats.get("days_total", 0)) if day_stats else 0
        dil = int(day_stats.get("days_in_loss", 0)) if day_stats else 0
        dbe = int(day_stats.get("days_below_be_roas", 0)) if day_stats else 0
        dab = int(day_stats.get("days_above_break_even_roas", 0)) if day_stats else 0
        dws = int(day_stats.get("days_with_spend", 0)) if day_stats else 0

        # Same window as day_stats: impossible for every paid day to be below BE if window ROAS > BE,
        # unless some days have revenue without spend (mixing / attribution). Log for support/debug.
        if (
            day_stats
            and break_even > 0
            and cost > 0
            and roas > break_even
            and dws > 0
            and dab == 0
        ):
            logger.warning(
                "Trust check: campaign %r has window ROAS %.4f > break-even %.4f but zero paid days "
                "with daily ROAS >= BE (days_with_spend=%s, days_total=%s).",
                name,
                roas,
                break_even,
                dws,
                dt,
            )

        if status == "insufficient_data":
            return {
                "type": "hold",
                "severity": "info",
                "rec_status": "⚪ Bez dat",
                "rec_action": "Počkat na import",
                "rec_reason": "V období chybí tržby nebo náklady.",
                "message": "Počkejte na kompletní data.",
                "action_label": "Bez akce",
                "budget_cut_pct": 0,
                "impact_text": "Doplňte data v importu.",
                "reason_short": "Žádná aktivita",
                "action_steps": "",
                "days_in_loss": 0,
                "days_total": 0,
                "days_above_break_even_roas": 0,
                "days_with_spend": 0,
                "roas_vs_break_even": "",
            }

        if status == "no_ad_spend":
            return {
                "type": "hold",
                "severity": "info",
                "rec_status": "ℹ️ Bez nákladů na reklamu",
                "rec_action": "Ověřte přiřazení nákladů",
                "rec_reason": "Nulové náklady na reklamu — ROAS se nepočítá. Výsledek interpretujte opatrně.",
                "message": "Tržby bez přiřazených reklamních nákladů — ROAS nevyhodnocujeme.",
                "action_label": "Ověřit data",
                "budget_cut_pct": 0,
                "impact_text": "Zkontrolujte, zda náklady patří do importu nebo jiné kampaně.",
                "reason_short": "Bez nákladů na reklamu — ROAS n/a",
                "action_steps": "",
                "days_in_loss": dil,
                "days_total": dt,
                "days_above_break_even_roas": dab,
                "days_with_spend": dws,
                "roas_vs_break_even": "",
            }

        if status == "loss":
            cut = max(reduction_pct, 30 if roas < 1 else 20)
            thin_evidence = (
                0 < cost < MIN_SPEND_CZK_FOR_HARD_STOP
                and 0 < dt < MIN_ACTIVE_DAYS_FOR_HARD_STOP
            )
            if thin_evidence:
                sev = "warning"
                rec_status = "⚠️ Ztráta"
                rec_action = "Zkontrolovat nebo vypnout"
            else:
                sev = "critical"
                rec_status = "❌ Ztráta"
                rec_action = "Vypnout kampaň"
            if dt > 0 and dil > 0:
                rec_reason = f"ROAS {roas:.2f}× < bod zvratu {break_even:.2f}× · {dil}/{dt} dní v minusu"
            else:
                rec_reason = f"ROAS {roas:.2f}× < bod zvratu {break_even:.2f}×"
            msg = rec_action + "."
            return {
                "type": "critical" if sev == "critical" else "warning",
                "severity": sev,
                "rec_status": rec_status,
                "rec_action": rec_action,
                "rec_reason": rec_reason,
                "message": msg,
                "action_label": "⚠️ Ověřit" if thin_evidence else "❌ Vypnout",
                "budget_cut_pct": cut,
                "impact_text": "Omezit výdaje na této kampani." if thin_evidence else "Zastavit výdaje šetří budget.",
                "reason_short": rec_reason,
                "action_steps": "",
                "days_in_loss": dil,
                "days_total": dt,
                "days_above_break_even_roas": dab,
                "days_with_spend": dws,
                "roas_vs_break_even": roas_vs,
            }

        if status == "at_risk":
            cut = max(reduction_pct, 15)
            rec_status = "⚠️ Mírně pod bodem zvratu"
            rec_action = "Snižte budget"
            if dt > 0 and dbe > 0:
                rec_reason = f"ROAS {roas:.2f}× u bodu zvratu {break_even:.2f}× · {dbe}/{dt} dní pod BE"
            else:
                rec_reason = f"ROAS {roas:.2f}× u bodu zvratu {break_even:.2f}×"
            msg = "Snižte budget — jste těsně u bodu zvratu."
            return {
                "type": "warning",
                "severity": "warning",
                "rec_status": rec_status,
                "rec_action": rec_action,
                "rec_reason": rec_reason,
                "message": msg,
                "action_label": "⚠️ Upravit",
                "budget_cut_pct": cut,
                "impact_text": "Zkraťte rozpočet.",
                "reason_short": rec_reason,
                "action_steps": "",
                "days_in_loss": dil,
                "days_total": dt,
                "days_above_break_even_roas": dab,
                "days_with_spend": dws,
                "roas_vs_break_even": roas_vs,
            }

        if str(status) == "profitable" and (
            profit > 5000
            or (
                break_even > 0
                and roas >= break_even * 1.25
                and cost >= MIN_SPEND_CZK_FOR_HARD_STOP
            )
        ):
            zisk = ""
            if dt > 0 and dil == 0:
                zisk = f"{dt}/{dt} dní ziskových"
            elif dt > 0:
                zisk = f"{dt - dil}/{dt} dní ziskových"
            rec_status = "✅ Škálovat"
            rec_action = "Navýšit rozpočet postupně"
            if zisk:
                rec_reason = f"ROAS {roas:.2f}× > bod zvratu {break_even:.2f}× · {zisk}"
            else:
                rec_reason = f"ROAS {roas:.2f}× > bod zvratu {break_even:.2f}×"
            msg = "Navýšit rozpočet — ROAS nad bodem zvratu."
            return {
                "type": "scale",
                "severity": "positive",
                "rec_status": rec_status,
                "rec_action": rec_action,
                "rec_reason": rec_reason,
                "message": msg,
                "action_label": "✅ Škálovat",
                "impact_text": "Kampaň má prostor pro škálování.",
                "reason_short": rec_reason,
                "action_steps": "Zvyšte rozpočet o 10–20 % a sledujte ROAS",
                "days_in_loss": dil,
                "days_total": dt,
                "days_above_break_even_roas": dab,
                "days_with_spend": dws,
                "roas_vs_break_even": roas_vs,
            }

        if __debug__ and str(status) == "loss":
            raise AssertionError("generate_campaign_recommendation: loss status must not reach default branch")
        rec_status = "✅ V plusu"
        rec_action = "Držet a hlídat"
        rec_reason = f"ROAS {roas:.2f}× > bod zvratu {break_even:.2f}×" if break_even > 0 else f"ROAS {roas_vs}"
        msg = "Držte výkon a hlídejte náklady."
        ok_steps = ""
        if break_even > 0 and roas > break_even:
            ok_steps = "Zvyšte rozpočet o 10–20 % a sledujte ROAS"
        return {
            "type": "ok",
            "severity": "info",
            "rec_status": rec_status,
            "rec_action": rec_action,
            "rec_reason": rec_reason,
            "message": msg,
            "action_label": "✅ Sledovat",
            "impact_text": "Držte současný rozpočet.",
            "reason_short": rec_reason,
            "action_steps": ok_steps,
            "days_in_loss": dil,
            "days_total": dt,
            "days_above_break_even_roas": dab,
            "days_with_spend": dws,
            "roas_vs_break_even": roas_vs,
        }

    @staticmethod
    def determine_primary_action(campaigns: list[dict[str, object]]) -> dict[str, str] | None:
        if not campaigns:
            return None

        campaigns = [
            c
            for c in campaigns
            if str(c.get("status", "")) != "insufficient_data"
            and str(c.get("status", "")) != "no_ad_spend"
            and str(c.get("source", "paid")) != "organic"
        ]
        if not campaigns:
            return None

        # 1) LOSS -> campaign with the biggest absolute loss
        loss_campaigns = [c for c in campaigns if str(c.get("status", "")) == "loss"]
        if loss_campaigns:
            worst = min(loss_campaigns, key=lambda x: float(x.get("profit", 0) or 0))
            name = str(worst.get("name") or worst.get("campaign") or "Kampaň")
            return {
                "type": "critical",
                "campaign": name,
                "message": f"Vypnout «{name}» — největší ztráta v tabulce.",
            }

        # 2) AT RISK -> the lowest ROAS among at-risk campaigns
        at_risk_campaigns = [c for c in campaigns if str(c.get("status", "")) == "at_risk"]
        if at_risk_campaigns:
            worst = min(at_risk_campaigns, key=lambda x: float(x.get("roas", 0) or 0))
            name = str(worst.get("name") or worst.get("campaign") or "Kampaň")
            rec = worst.get("recommendation") if isinstance(worst.get("recommendation"), dict) else {}
            pct = int(rec.get("budget_cut_pct", 15)) if rec else 15
            return {
                "type": "warning",
                "campaign": name,
                "message": f"Upravit «{name}» — snížit budget (~{pct} %).",
            }

        # 3) PROFITABLE -> the highest profit for scaling opportunity
        profitable_campaigns = [c for c in campaigns if str(c.get("status", "")) == "profitable"]
        if profitable_campaigns:
            best = max(profitable_campaigns, key=lambda x: float(x.get("profit", 0) or 0))
            name = str(best.get("name") or best.get("campaign") or "Kampaň")
            roas_b = float(best.get("roas", 0) or 0)
            return {
                "type": "scale",
                "campaign": name,
                "message": f"Škálovat «{name}» — silný ROAS ({roas_b:.2f}×).",
            }

        return None

    def build_primary_recommendation(self, client_id: int, days: int) -> dict[str, object] | None:
        """
        Single highest-priority item: worst loss, else worst at-risk ROAS, else best scale opportunity.
        """
        self._db_requirements()
        rows = self.top_campaigns_db(client_id=client_id, days=days, top_n=200, sort="profit")
        paid = MarketingService._paid_rows_for_signals(rows)
        if not paid:
            return None

        loss_campaigns = [c for c in paid if str(c.get("status", "")) == "loss"]
        if loss_campaigns:
            pick = min(loss_campaigns, key=lambda x: float(x.get("profit", 0) or 0))
            title = "Největší problém dnes"
            icon = "🔥"
        else:
            at_risk = [c for c in paid if str(c.get("status", "")) == "at_risk"]
            if at_risk:
                be = float(at_risk[0].get("break_even_roas", 0) or 0)

                def _roas_gap(c: dict[str, object]) -> float:
                    ro = float(c.get("roas", 0) or 0)
                    b = float(c.get("break_even_roas", 0) or be or 0)
                    return (b - ro) if b > 0 else -ro

                pick = max(at_risk, key=_roas_gap)
                title = "Největší problém dnes"
                icon = "🔥"
            else:
                profitable = [c for c in paid if str(c.get("status", "")) == "profitable"]
                if not profitable:
                    return None
                pick = max(profitable, key=lambda x: float(x.get("profit", 0) or 0))
                title = "Největší příležitost dnes"
                icon = "🚀"

        rec = pick.get("recommendation") if isinstance(pick.get("recommendation"), dict) else {}
        reason_row = str(pick.get("reason", "") or "").strip()
        reason_rec = str(rec.get("reason_short", "") or "").strip()
        dt = int(rec.get("days_total", 0) or 0)
        dil = int(rec.get("days_in_loss", 0) or 0)
        dws = int(rec.get("days_with_spend", 0) or 0)
        st_pick = str(pick.get("status", ""))
        ro_pick = float(pick.get("roas", 0) or 0)
        be_pick = float(pick.get("break_even_roas", 0) or 0)

        def _primary_certitude_label() -> str:
            if dt >= 14 and dws >= 8:
                return "Vysoká jistota"
            if dt >= 7 or dws >= 5:
                return "Střední jistota"
            return "Nízká jistota"

        display_action = str(rec.get("action_label", "") or "")
        if st_pick == "loss":
            display_action = "Omezit / pozastavit"
        elif st_pick == "at_risk":
            display_action = "Testovat opatrně"
        elif st_pick == "profitable":
            good_share = (dt - dil) / float(dt) if dt > 0 else 0.0
            if be_pick > 0 and ro_pick >= be_pick * 1.2 and good_share >= 0.8:
                display_action = "Škálovat (silná příležitost)"
            else:
                display_action = "Testovat opatrně"

        confidence_label = _primary_certitude_label()
        return {
            "title": title,
            "icon": icon,
            "severity": str(rec.get("severity", "info")),
            "campaign": str(pick.get("campaign", "Kampaň")),
            "text": str(rec.get("message", "")),
            "impact_text": str(rec.get("impact_text", "")),
            "reason": reason_row or reason_rec,
            "rec_status": str(rec.get("rec_status", "") or ""),
            "rec_action": str(rec.get("rec_action", "") or ""),
            "rec_reason": str(rec.get("rec_reason", "") or ""),
            "action_label": display_action,
            "confidence_label": confidence_label,
            "days_in_loss": dil,
            "days_total": dt,
            "days_above_break_even_roas": int(rec.get("days_above_break_even_roas", 0) or 0),
            "days_with_spend": int(rec.get("days_with_spend", 0) or 0),
            "roas_vs_break_even": str(rec.get("roas_vs_break_even", "")),
            "decision_label": str(pick.get("decision_label", "—")),
            "action_steps": str(rec.get("action_steps", "") or ""),
        }

    def build_daily_recommendations(self, client_id: int, days: int) -> list[dict[str, object]]:
        """
        Top-of-dashboard action lines: STOP / FIX / SCALE with proof + impact (from service layer).
        """
        self._db_requirements()
        rows = self.top_campaigns_db(client_id=client_id, days=days, top_n=200, sort="profit")
        paid = MarketingService._paid_rows_for_signals(rows)
        out: list[dict[str, object]] = []

        def _from_row(r: dict[str, object], sev: str, icon: str) -> dict[str, object]:
            rec = r.get("recommendation") if isinstance(r.get("recommendation"), dict) else {}
            return {
                "severity": sev,
                "icon": icon,
                "text": str(rec.get("message", "")),
                "impact_text": str(rec.get("impact_text", "")),
                "rec_status": str(rec.get("rec_status", "") or ""),
                "rec_action": str(rec.get("rec_action", "") or ""),
                "rec_reason": str(rec.get("rec_reason", "") or ""),
                "action_label": str(rec.get("action_label", "") or ""),
                "days_in_loss": int(rec.get("days_in_loss", 0) or 0),
                "days_total": int(rec.get("days_total", 0) or 0),
                "roas_vs_break_even": str(rec.get("roas_vs_break_even", "")),
                "campaign": str(r.get("campaign", "")),
            }

        losses = [r for r in paid if str(r.get("status", "")) == "loss"]
        losses.sort(key=lambda x: float(x.get("profit", 0) or 0))
        for r in losses[:3]:
            out.append(_from_row(r, "critical", "❌"))

        risks = [r for r in paid if str(r.get("status", "")) == "at_risk"]
        risks.sort(key=lambda x: float(x.get("roas", 0) or 0))
        for r in risks[:2]:
            out.append(_from_row(r, "warning", "⚠️"))

        wins = [r for r in paid if str(r.get("status", "")) == "profitable"]
        wins.sort(key=lambda x: float(x.get("profit", 0) or 0), reverse=True)
        if wins:
            out.append(_from_row(wins[0], "positive", "✅"))

        if not out:
            out.append(
                {
                    "severity": "info",
                    "icon": "ℹ️",
                    "text": "Žádné silné signály — nahrajte data nebo zkuste delší období.",
                    "impact_text": "",
                    "days_in_loss": 0,
                    "days_total": 0,
                    "roas_vs_break_even": "",
                    "campaign": "",
                }
            )
        return out[:5]

    @staticmethod
    def detect_trends(
        revenue_trend: list[object],
        cost_trend: list[object],
        roas_trend: list[object],
    ) -> list[dict[str, str]]:
        alerts: list[dict[str, str]] = []

        def is_decreasing(values: list[float], days: int = 3) -> bool:
            if len(values) < days:
                return False
            recent = values[-days:]
            return all(recent[i] > recent[i + 1] for i in range(len(recent) - 1))

        def is_increasing(values: list[float], days: int = 3) -> bool:
            if len(values) < days:
                return False
            recent = values[-days:]
            return all(recent[i] < recent[i + 1] for i in range(len(recent) - 1))

        revenue_values = MarketingService._finite_series_values(list(revenue_trend))
        cost_values = MarketingService._finite_series_values(list(cost_trend))
        roas_values = MarketingService._finite_series_values(list(roas_trend))

        if is_decreasing(roas_values, 5):
            alerts.append(
                {
                    "type": "negative_trend",
                    "metric": "roas",
                    "message": "ROAS klesá posledních 5 dní",
                    "severity": "warning",
                }
            )

        if is_decreasing(revenue_values, 3):
            alerts.append(
                {
                    "type": "negative_trend",
                    "metric": "revenue",
                    "message": "Tržby klesají poslední 3 dny",
                    "severity": "warning",
                }
            )

        if is_increasing(cost_values, 3):
            alerts.append(
                {
                    "type": "cost_growth",
                    "metric": "cost",
                    "message": "Náklady rostou poslední 3 dny",
                    "severity": "info",
                }
            )

        return alerts

    @staticmethod
    def _finite_series_values(series: list[object]) -> list[float]:
        """Strip null/invalid points so trend heuristics never treat gaps as zeros."""
        out: list[float] = []
        for x in series:
            if x is None:
                continue
            try:
                out.append(float(x))
            except (TypeError, ValueError):
                continue
        return out

    @classmethod
    def kpis(
        cls,
        *,
        spend: float,
        revenue: float,
        clicks: int,
        conversions: int,
    ) -> dict[str, float]:
        # ``profit`` here is revenue − spend (gross before margin). Do NOT use as marketing zisk —
        # dashboard / campaigns use ``calculate_campaign_metrics`` → revenue × margin − spend.
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
        if not self._session or not self._campaign_repo or not self._metric_repo or not self._client_repo:
            raise InternalMisuseError("MarketingService requires a Session for DB operations.")

    def _margin_for_client(self, client_id: int) -> float:
        self._db_requirements()
        cid = require_positive_client_id(client_id)
        client = self._client_repo.get_by_id_for_client(cid)  # type: ignore[union-attr]
        if client is None:
            raise NotFoundError("Client not found")
        margin = getattr(client, "margin", DEFAULT_MARGIN)
        return self._validated_margin(margin)

    def _scenarios(self, *, revenue: float, spend: float) -> list[dict[str, float]]:
        return [
            {"margin": 0.4, "profit": round(revenue * 0.4 - spend, 2)},
            {"margin": 0.6, "profit": round(revenue * 0.6 - spend, 2)},
            {"margin": 0.7, "profit": round(revenue * 0.7 - spend, 2)},
        ]

    def _db_metrics_for_client(self, *, client_id: int, days: int | None = None):
        self._db_requirements()
        cid = require_positive_client_id(client_id)

        if days is None:
            return self._metric_repo.list_for_client(cid, offset=0, limit=500_000)  # type: ignore[union-attr]

        date_from = date.today() - timedelta(days=max(int(days), 1) - 1)
        return self._metric_repo.get_metrics_since_for_client(cid, date_from)  # type: ignore[union-attr]

    @staticmethod
    def _detect_incomplete_trailing_calendar_day(
        metrics: list[object],
        *,
        window_start: date,
        window_end: date,
    ) -> date | None:
        """
        If the last calendar day in the window has much lower activity than recent days,
        treat it as incomplete (partial sync / day in progress).

        Rule: volume(last) < 50% of mean volume over prior calendar days in window that had
        activity (spend+revenue > 0), requiring at least two such baseline days.
        """
        rev: dict[date, float] = defaultdict(float)
        spend: dict[date, float] = defaultdict(float)
        for m in metrics:
            md = MarketingService._normalize_metric_day(getattr(m, "metric_date", None))
            if md is None or md < window_start or md > window_end:
                continue
            rev[md] += MarketingService._non_negative_money(float(getattr(m, "revenue", 0) or 0))
            spend[md] += MarketingService._non_negative_money(float(getattr(m, "spend", 0) or 0))

        def vol(d: date) -> float:
            return float(rev.get(d, 0.0) + spend.get(d, 0.0))

        last = window_end
        if last < window_start:
            return None

        baseline_vols: list[float] = []
        for k in (1, 2, 3):
            d = last - timedelta(days=k)
            if d < window_start:
                continue
            v = vol(d)
            if v > 0:
                baseline_vols.append(v)

        if len(baseline_vols) < 2:
            return None

        avg_b = sum(baseline_vols) / len(baseline_vols)
        if avg_b <= 0:
            return None

        v_last = vol(last)
        if v_last < 0.5 * avg_b:
            return last
        return None

    def _metrics_for_client_window(
        self,
        *,
        client_id: int,
        days: int | None,
    ) -> tuple[list[object], dict[str, Any]]:
        """
        Metrics for the rolling window, optionally excluding a trailing day that looks incomplete.
        Returns (metrics, ctx) where ctx has has_partial_data (bool) and excluded_date (date | None).
        """
        cid = require_positive_client_id(client_id)
        raw = self._db_metrics_for_client(client_id=cid, days=days)
        ctx: dict[str, Any] = {"has_partial_data": False, "excluded_date": None}
        if days is None:
            return raw, ctx

        wd = max(int(days), 1)
        end = date.today()
        start = end - timedelta(days=wd - 1)
        excl = MarketingService._detect_incomplete_trailing_calendar_day(
            raw,
            window_start=start,
            window_end=end,
        )
        if excl is None:
            return raw, ctx

        filtered = [
            m for m in raw if MarketingService._normalize_metric_day(getattr(m, "metric_date", None)) != excl
        ]
        ctx["has_partial_data"] = True
        ctx["excluded_date"] = excl
        return filtered, ctx

    def campaign_performance(self, *, client_id: int) -> list[dict[str, object]]:
        """
        Returns campaign-level performance aggregated over all CampaignMetric rows.
        Requires MarketingService(session=...).
        """
        self._db_requirements()
        cid = require_positive_client_id(client_id)
        margin = self._margin_for_client(cid)

        campaigns = self._campaign_repo.list_for_client(cid, offset=0, limit=100_000)  # type: ignore[union-attr]
        campaigns_by_id = {c.id: c for c in campaigns if c.id is not None}
        metrics = self._db_metrics_for_client(client_id=cid, days=None)

        agg: dict[int, dict[str, float | int]] = defaultdict(lambda: {"spend": 0.0, "revenue": 0.0, "clicks": 0, "conversions": 0})
        for m in metrics:
            camp = campaigns_by_id.get(m.campaign_id)
            if camp is None:
                continue
            a = agg[m.campaign_id]
            a["spend"] = float(a["spend"]) + float(m.spend)
            a["revenue"] = float(a["revenue"]) + float(m.revenue)
            a["clicks"] = int(a["clicks"]) + int(m.clicks)
            a["conversions"] = int(a["conversions"]) + int(m.conversions)

        out: list[dict[str, object]] = []
        for campaign_id, totals in agg.items():
            camp = campaigns_by_id[campaign_id]
            k = self.kpis(
                spend=float(totals["spend"]),
                revenue=float(totals["revenue"]),
                clicks=int(totals["clicks"]),
                conversions=int(totals["conversions"]),
            )
            metrics_view = self.calculate_campaign_metrics(
                revenue=float(k["revenue"]),
                cost=float(k["spend"]),
                margin=margin,
            )
            recommendation = self.generate_campaign_recommendation(metrics_view, camp.name)
            MarketingService._log_recommendation_consistency(camp.name, metrics_view, recommendation)
            status_details = metrics_view.get("status_details", {})
            if not isinstance(status_details, dict):
                status_details = {}
            row = {
                "campaign_id": int(campaign_id),
                "name": camp.name,
                "campaign": camp.name,
                "spend": round(k["spend"], 2),
                "cost": round(float(metrics_view["cost"]), 2),
                "revenue": round(k["revenue"], 2),
                "roas": float(metrics_view["roas"]),
                "marketing_profit": round(float(metrics_view["marketing_profit"]), 2),
                "contribution_profit": round(float(metrics_view["contribution_profit"]), 2),
                "profit": round(float(metrics_view["profit"]), 2),
                "break_even_roas": float(metrics_view["break_even_roas"]),
                "status": str(metrics_view["status"]),
                "status_reason": str(metrics_view["status_reason"]),
                "status_details": status_details,
                "recommendation": recommendation,
                "source": "organic" if self._is_organic_campaign(camp.name) else "paid",
                "cpa": round(k["cpa"], 4),
            }
            MarketingService._attach_decision_fields(row)
            out.append(row)
        out.sort(
            key=lambda x: (
                1 if str(x.get("source", "paid")) == "organic" else 0,
                -float(x["revenue"]),
            )
        )
        return out

    def dashboard_overview_db(self, *, client_id: int, days: int | None = None) -> dict[str, Any]:
        """
        DB-only: aggregated KPIs for a client (optionally over last N days).
        Returns: total_spend, total_revenue, total_profit, average_roas
        """
        cid = require_positive_client_id(client_id)
        metrics, partial_ctx = self._metrics_for_client_window(client_id=cid, days=days)
        excluded_day: date | None = partial_ctx.get("excluded_date")  # type: ignore[assignment]
        margin = self._margin_for_client(cid)
        total_spend = float(sum(MarketingService._non_negative_money(float(m.spend)) for m in metrics))
        total_revenue = float(sum(MarketingService._non_negative_money(float(m.revenue)) for m in metrics))
        # This is NOT real profit (does not include COGS, VAT, logistics).
        total_marketing_profit = total_revenue * margin - total_spend
        total_contribution_profit = total_revenue * margin - total_spend
        break_even_roas = round((1 / margin) if margin > 0 else 0.0, 4)

        paid_campaign_ids = {
            c.id
            for c in self._campaign_repo.list_for_client(cid, offset=0, limit=100_000)  # type: ignore[union-attr]
            if c.id is not None and not self._is_organic_campaign(c.name)
        }
        date_from: date | None = None
        if days is not None:
            date_from = date.today() - timedelta(days=max(int(days), 1) - 1)
        paid_metrics = (
            self._metric_repo.list_metrics_for_campaign_ids_for_client(  # type: ignore[union-attr]
                cid,
                paid_campaign_ids,
                date_from=date_from,
            )
            if paid_campaign_ids
            else []
        )
        if excluded_day is not None:
            paid_metrics = [
                m
                for m in paid_metrics
                if MarketingService._normalize_metric_day(getattr(m, "metric_date", None)) != excluded_day
            ]
        paid_revenue = float(sum(MarketingService._non_negative_money(float(m.revenue)) for m in paid_metrics))
        paid_spend = float(sum(MarketingService._non_negative_money(float(m.spend)) for m in paid_metrics))
        average_roas = float(self._safe_div(paid_revenue, paid_spend))
        be_for_status = MarketingService._safe_div(1.0, margin)
        average_roas_status = MarketingService.portfolio_roas_status(average_roas, paid_spend, be_for_status)

        paid_rev_by_day: dict[date, float] = defaultdict(float)
        paid_spend_by_day: dict[date, float] = defaultdict(float)
        for m in paid_metrics:
            d = MarketingService._normalize_metric_day(getattr(m, "metric_date", None))
            if d is None:
                continue
            paid_rev_by_day[d] += MarketingService._non_negative_money(float(m.revenue))
            paid_spend_by_day[d] += MarketingService._non_negative_money(float(m.spend))
        portfolio_days_with_spend = 0
        portfolio_days_roas_above_be = 0
        if break_even_roas > 0 and paid_metrics:
            window_days = max(int(days), 1) if days is not None else None
            if window_days is not None:
                end_d = date.today()
                start_d = end_d - timedelta(days=window_days - 1)
                for step in range(window_days):
                    d = start_d + timedelta(days=step)
                    s = float(paid_spend_by_day.get(d, 0.0))
                    if s <= 0:
                        continue
                    portfolio_days_with_spend += 1
                    r = float(paid_rev_by_day.get(d, 0.0))
                    if r / s >= break_even_roas:
                        portfolio_days_roas_above_be += 1
        if (
            days is not None
            and break_even_roas > 0
            and paid_spend > 0
            and average_roas > break_even_roas
            and portfolio_days_with_spend > 0
            and portfolio_days_roas_above_be == 0
        ):
            logger.warning(
                "Dashboard trust check: portfolio average_roas=%.4f > break_even=%.4f but no calendar day "
                "in window has paid daily ROAS >= BE (often revenue on days without attributed spend). "
                "paid_days_with_spend=%s window_days=%s",
                average_roas,
                break_even_roas,
                portfolio_days_with_spend,
                max(int(days), 1),
            )

        marketing_profit_pct_vs_prior_period: float | None = None
        revenue_change_pct: float | None = None
        spend_change_pct: float | None = None
        profit_change_pct: float | None = None
        roas_change_pct: float | None = None
        prior_period_available = False

        if days is not None and self._metric_repo is not None:
            wd_cmp = max(int(days), 1)
            curr_start_cmp = date.today() - timedelta(days=wd_cmp - 1)
            prior_end_cmp = curr_start_cmp - timedelta(days=1)
            prior_start_cmp = prior_end_cmp - timedelta(days=wd_cmp - 1)
            if prior_end_cmp >= prior_start_cmp:
                prior_rows_cmp = self._metric_repo.list_metrics_in_date_range_for_client(  # type: ignore[union-attr]
                    cid,
                    prior_start_cmp,
                    prior_end_cmp,
                )
                if prior_rows_cmp:
                    prior_period_available = True
                    pr_rev = float(
                        sum(MarketingService._non_negative_money(float(m.revenue)) for m in prior_rows_cmp),
                    )
                    pr_spend = float(
                        sum(MarketingService._non_negative_money(float(m.spend)) for m in prior_rows_cmp),
                    )
                    prior_profit_cmp = pr_rev * margin - pr_spend
                    revenue_change_pct = MarketingService._pct_change_vs_prior(
                        total_revenue, pr_rev, min_prior_abs=1.0
                    )
                    spend_change_pct = MarketingService._pct_change_vs_prior(
                        total_spend, pr_spend, min_prior_abs=1.0
                    )
                    profit_change_pct = MarketingService._pct_change_vs_prior(
                        total_marketing_profit, prior_profit_cmp, min_prior_abs=1e-2
                    )
                    if abs(prior_profit_cmp) >= 1e-2:
                        marketing_profit_pct_vs_prior_period = profit_change_pct

                    ppr = 0.0
                    pps = 0.0
                    for m in prior_rows_cmp:
                        if int(m.campaign_id) not in paid_campaign_ids:
                            continue
                        ppr += MarketingService._non_negative_money(float(m.revenue))
                        pps += MarketingService._non_negative_money(float(m.spend))
                    if pps > 1e-2:
                        prior_roas = ppr / pps
                        if prior_roas > 1e-6:
                            roas_change_pct = round((average_roas - prior_roas) / prior_roas * 100.0, 1)

        prior_period_has_comparisons = any(
            x is not None for x in (revenue_change_pct, spend_change_pct, profit_change_pct, roas_change_pct)
        )

        wd_for_cov = max(int(days), 1) if days is not None else 0
        distinct_data_days = len(
            {
                md
                for m in metrics
                if (md := MarketingService._normalize_metric_day(getattr(m, "metric_date", None))) is not None
            }
        )
        if days is not None and wd_for_cov > 0:
            coverage = distinct_data_days / float(wd_for_cov)
            hp_flag = bool(partial_ctx.get("has_partial_data"))
            if coverage >= 0.85 and not hp_flag:
                data_reliability = "high"
            elif coverage >= 0.5:
                data_reliability = "medium"
            else:
                data_reliability = "low"
        else:
            data_reliability = "low"
        reliability_labels = {"high": "Vysoká", "medium": "Střední", "low": "Nízká"}
        data_reliability_label_cs = reliability_labels.get(str(data_reliability), "Střední")

        out: dict[str, float | str | list | None | bool] = {
            "total_spend": round(total_spend, 2),
            "total_revenue": round(total_revenue, 2),
            "total_marketing_profit": round(total_marketing_profit, 2),
            "total_contribution_profit": round(total_contribution_profit, 2),
            "total_profit": round(total_contribution_profit, 2),  # backward compatibility
            "average_roas": round(average_roas, 4),
            "break_even_roas": break_even_roas,
            "margin_used": round(margin, 4),
            "margin": round(margin, 4),
            "average_roas_status": average_roas_status,
            "portfolio_days_with_paid_spend": portfolio_days_with_spend,
            "portfolio_days_roas_above_break_even": portfolio_days_roas_above_be,
            "explanation": self._margin_explanation(),
            "scenarios": self._scenarios(revenue=total_revenue, spend=total_spend),
            "marketing_profit_pct_vs_prior_period": marketing_profit_pct_vs_prior_period,
            "has_partial_data": bool(partial_ctx.get("has_partial_data")),
            "prior_period_available": prior_period_available,
            "prior_period_has_comparisons": prior_period_has_comparisons,
            "revenue_change_pct": revenue_change_pct,
            "spend_change_pct": spend_change_pct,
            "profit_change_pct": profit_change_pct,
            "roas_change_pct": roas_change_pct,
            "data_reliability": data_reliability,
            "data_reliability_label_cs": data_reliability_label_cs,
            "data_coverage_days": distinct_data_days,
        }
        return out

    def revenue_trend_db(self, *, client_id: int, days: int = 30) -> dict[str, list]:
        metrics, _ = self._metrics_for_client_window(client_id=client_id, days=days)
        present = self._metric_dates_in_window(metrics)
        by_day: dict[date, float] = defaultdict(float)
        for m in metrics:
            d = MarketingService._normalize_metric_day(getattr(m, "metric_date", None))
            if d is None:
                continue
            by_day[d] += MarketingService._non_negative_money(float(getattr(m, "revenue", 0) or 0))
        sparse = [{"date": d, "value": v} for d, v in by_day.items()]
        filled = self._calendar_window_series(sparse, days, present_days=present)
        return {
            "labels": [str(r["date"]) for r in filled],
            "revenue": [r["value"] for r in filled],
        }

    def spend_trend_db(self, *, client_id: int, days: int = 30) -> dict[str, list]:
        metrics, _ = self._metrics_for_client_window(client_id=client_id, days=days)
        present = self._metric_dates_in_window(metrics)
        by_day: dict[date, float] = defaultdict(float)
        for m in metrics:
            d = MarketingService._normalize_metric_day(getattr(m, "metric_date", None))
            if d is None:
                continue
            by_day[d] += MarketingService._non_negative_money(float(getattr(m, "spend", 0) or 0))
        sparse = [{"date": d, "value": v} for d, v in by_day.items()]
        filled = self._calendar_window_series(sparse, days, present_days=present)
        return {
            "labels": [str(r["date"]) for r in filled],
            "spend": [r["value"] for r in filled],
        }

    def profit_trend_db(self, *, client_id: int, days: int = 30) -> dict[str, list]:
        """
        Daily profit = tržby×marže − náklady na den (stejná marže jako v KPI).

        Dny se spendem > 0 a bez tržeb do řady nezahrnujeme (mezera místo falešného propadu).
        """
        metrics, _ = self._metrics_for_client_window(client_id=client_id, days=days)
        margin = self._margin_for_client(client_id)
        present_raw = self._metric_dates_in_window(metrics)
        rev_by_day: dict[date, float] = defaultdict(float)
        spend_by_day: dict[date, float] = defaultdict(float)
        for m in metrics:
            d = MarketingService._normalize_metric_day(getattr(m, "metric_date", None))
            if d is None:
                continue
            rev_by_day[d] += MarketingService._non_negative_money(float(getattr(m, "revenue", 0) or 0))
            spend_by_day[d] += MarketingService._non_negative_money(float(getattr(m, "spend", 0) or 0))
        present_profit: set[date] = set()
        for d in present_raw:
            r = float(rev_by_day.get(d, 0.0))
            s = float(spend_by_day.get(d, 0.0))
            if s > 1e-9 and r < 1e-9:
                continue
            present_profit.add(d)
        sparse: list[dict[str, object]] = []
        for d in sorted(present_profit):
            r_d = float(rev_by_day.get(d, 0.0))
            s_d = float(spend_by_day.get(d, 0.0))
            prof = r_d * margin - s_d
            sparse.append({"date": d, "value": round(prof, 2)})
        filled = self._calendar_window_series(sparse, days, present_days=present_profit)
        return {
            "labels": [str(r["date"]) for r in filled],
            "profit": [r["value"] for r in filled],
        }

    def roas_trend_db(self, *, client_id: int, days: int = 30) -> dict[str, list]:
        metrics, _ = self._metrics_for_client_window(client_id=client_id, days=days)
        present = self._metric_dates_in_window(metrics)
        rev_by_day: dict[date, float] = defaultdict(float)
        spend_by_day: dict[date, float] = defaultdict(float)
        for m in metrics:
            d = MarketingService._normalize_metric_day(getattr(m, "metric_date", None))
            if d is None:
                continue
            rev_by_day[d] += MarketingService._non_negative_money(float(getattr(m, "revenue", 0) or 0))
            spend_by_day[d] += MarketingService._non_negative_money(float(getattr(m, "spend", 0) or 0))
        n = max(int(days), 1)
        end = date.today()
        if present:
            end = min(end, max(present))
        start = end - timedelta(days=n - 1)
        labels: list[str] = []
        values: list[float | None] = []
        for i in range(n):
            d = start + timedelta(days=i)
            labels.append(str(d))
            if d not in present:
                values.append(None)
                continue
            r = float(rev_by_day.get(d, 0.0))
            s = float(spend_by_day.get(d, 0.0))
            if s <= 0:
                values.append(None)
            else:
                values.append(round(r / s, 4))
        return {"labels": labels, "roas": values}

    def top_campaigns_db(
        self,
        *,
        client_id: int,
        days: int = 30,
        top_n: int = 5,
        sort: str = "revenue",
    ) -> list[dict[str, object]]:
        """
        DB-only: campaigns in the last ``days`` window. ``sort`` is ``revenue`` (default, high first)
        or ``profit`` (lowest profit first — surfaces burners for the decision table).
        """
        self._db_requirements()
        cid = require_positive_client_id(client_id)
        margin = self._margin_for_client(cid)

        campaigns = self._campaign_repo.list_for_client(cid, offset=0, limit=100_000)  # type: ignore[union-attr]
        campaigns_by_id = {c.id: c for c in campaigns if c.id is not None}
        metrics, _ = self._metrics_for_client_window(client_id=cid, days=days)
        day_stats_map = self._campaign_day_stats_map(cid, days, metrics=metrics)

        agg: dict[int, dict[str, float | int]] = defaultdict(lambda: {"spend": 0.0, "revenue": 0.0, "clicks": 0, "conversions": 0})
        for m in metrics:
            if m.campaign_id not in campaigns_by_id:
                continue
            a = agg[m.campaign_id]
            a["spend"] = float(a["spend"]) + float(m.spend)
            a["revenue"] = float(a["revenue"]) + float(m.revenue)
            a["clicks"] = int(a["clicks"]) + int(m.clicks)
            a["conversions"] = int(a["conversions"]) + int(m.conversions)

        rows: list[dict[str, object]] = []
        wd = max(int(days), 1)
        for campaign_id, totals in agg.items():
            camp = campaigns_by_id[campaign_id]
            k = self.kpis(
                spend=float(totals["spend"]),
                revenue=float(totals["revenue"]),
                clicks=int(totals["clicks"]),
                conversions=int(totals["conversions"]),
            )
            metrics_view = self.calculate_campaign_metrics(
                revenue=float(k["revenue"]),
                cost=float(k["spend"]),
                margin=margin,
            )
            ds = day_stats_map.get(
                int(campaign_id),
                {
                    "days_total": 0,
                    "days_in_loss": 0,
                    "days_below_be_roas": 0,
                    "days_above_break_even_roas": 0,
                    "days_with_spend": 0,
                },
            )
            recommendation = self.generate_campaign_recommendation(
                metrics_view,
                camp.name,
                window_days=wd,
                day_stats=ds,
            )
            MarketingService._log_recommendation_consistency(camp.name, metrics_view, recommendation)
            status_details = metrics_view.get("status_details", {})
            if not isinstance(status_details, dict):
                status_details = {}
            row = {
                "campaign_id": int(campaign_id),
                "name": camp.name,
                "campaign": camp.name,
                "spend": round(k["spend"], 2),
                "cost": round(float(metrics_view["cost"]), 2),
                "revenue": round(k["revenue"], 2),
                "roas": float(metrics_view["roas"]),
                "marketing_profit": round(float(metrics_view["marketing_profit"]), 2),
                "contribution_profit": round(float(metrics_view["contribution_profit"]), 2),
                "profit": round(float(metrics_view["profit"]), 2),
                "break_even_roas": float(metrics_view["break_even_roas"]),
                "status": str(metrics_view["status"]),
                "status_reason": str(metrics_view["status_reason"]),
                "status_details": status_details,
                "recommendation": recommendation,
                "reason": str(recommendation.get("reason_short", "")),
                "impact_text": str(recommendation.get("impact_text", "")),
                "days_in_loss": int(recommendation.get("days_in_loss", 0) or 0),
                "days_total": int(recommendation.get("days_total", 0) or 0),
                "days_above_break_even_roas": int(
                    recommendation.get("days_above_break_even_roas", 0) or 0
                ),
                "days_with_spend": int(recommendation.get("days_with_spend", 0) or 0),
                "roas_vs_break_even": str(recommendation.get("roas_vs_break_even", "")),
                "source": "organic" if self._is_organic_campaign(camp.name) else "paid",
                "cpa": round(k["cpa"], 4),
                "table_reason": (
                    NO_AD_SPEND_TABLE_REASON if str(metrics_view.get("status", "")) == "no_ad_spend" else ""
                ),
            }
            MarketingService._attach_decision_fields(row)
            rows.append(row)

        paid_rows = [r for r in rows if str(r.get("source", "paid")) != "organic"]
        if sort == "profit":
            paid_rows.sort(key=lambda x: float(x.get("profit", 0) or 0))
        else:
            paid_rows.sort(key=lambda x: float(x["revenue"]), reverse=True)
        return paid_rows[: max(int(top_n), 0)]

    @staticmethod
    def _campaign_row_counts_toward_loss_kpi(row: dict[str, object]) -> bool:
        """
        True if this campaign row should add to the portfolio loss KPI.

        Uses the same economic definition as the table: ``contribution_profit`` (marže × tržby − náklady).
        Includes ``loss`` and ``at_risk`` rows with negative contribution (e.g. ROAS pod bodem zvratu
        ale stále v „buffer“ pásmu 0.9–1.1× BE). Excludes organic and insufficient_data.
        """
        if str(row.get("source", "paid")) == "organic":
            return False
        if str(row.get("status", "")) == "insufficient_data":
            return False
        contribution_profit = float(row.get("contribution_profit", row.get("profit", 0)) or 0)
        return contribution_profit < 0

    def loss_summary(self, *, client_id: int, days: int = 30) -> dict[str, float | int]:
        """
        Same time window and campaign rows as the table (``top_campaigns_db``).

        Sums ``|contribution_profit|`` for paid campaigns with **negative** contribution in the window.
        This matches rows that are economically below break-even, including ``at_risk``
        (mírně pod bodem zvratu) when profit after margin is still negative — not only ``loss`` (ROAS < 0.9× BE).
        """
        self._db_requirements()
        cid = require_positive_client_id(client_id)
        rows = self.top_campaigns_db(client_id=cid, days=days, top_n=50_000, sort="profit")
        total_loss = 0.0
        loss_count = 0

        for c in rows:
            if not MarketingService._campaign_row_counts_toward_loss_kpi(c):
                continue
            contribution_profit = float(c.get("contribution_profit", c.get("profit", 0)) or 0)
            total_loss += abs(contribution_profit)
            loss_count += 1

        return {
            "total_loss": round(total_loss, 2),
            "loss_count": loss_count,
            "potential_gain": round(total_loss, 2),
            "message": (
                "Všechny placené kampaně jsou v tomto období nad bodem zvratu (nezáporný příspěvek po marži)."
                if loss_count == 0
                else "Alespoň jedna placená kampaň je pod bodem zvratu — viz tabulka kampaní."
            ),
        }

    def _trust_meta(self, *, client_id: int, days: int) -> dict[str, object]:
        """Transparency block: window, freshness, nominal sources (extend when integrations expose real source)."""
        self._db_requirements()
        cid = require_positive_client_id(client_id)
        metrics, _ = self._metrics_for_client_window(client_id=cid, days=days)
        dates = [
            md
            for m in metrics
            if (md := MarketingService._normalize_metric_day(getattr(m, "metric_date", None))) is not None
        ]
        last_metric = max(dates) if dates else None
        wd = max(int(days), 1)
        return {
            "window_days": wd,
            "window_description": f"Data za posledních {wd} dní",
            "last_metric_date": last_metric.isoformat() if last_metric else None,
            "computed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            # Omit Google Ads until the integration is production-ready (trust strip is user-facing).
            "sources": ["Meta Ads", "CSV / manuální import"],
        }

    def dashboard_full_db(
        self,
        *,
        client_id: int,
        days: int = 30,
        top_n: int = 5,
        calc_debug: bool = False,
    ) -> dict[str, object]:
        """
        DB-only: One payload powering the whole dashboard.
        """
        margin = self._margin_for_client(client_id)
        overview = self.dashboard_overview_db(client_id=client_id, days=days)
        revenue_trend = self.revenue_trend_db(client_id=client_id, days=days)
        spend_trend = self.spend_trend_db(client_id=client_id, days=days)
        profit_trend = self.profit_trend_db(client_id=client_id, days=days)
        roas_trend = self.roas_trend_db(client_id=client_id, days=days)
        alerts = self.detect_trends(
            revenue_trend=revenue_trend.get("revenue", []),
            cost_trend=spend_trend.get("spend", []),
            roas_trend=roas_trend.get("roas", []),
        )
        top_campaigns = self.top_campaigns_db(client_id=client_id, days=days, top_n=top_n, sort="revenue")
        table_limit = min(100, max(int(top_n), 30))
        campaign_table = self.top_campaigns_db(
            client_id=client_id, days=days, top_n=table_limit, sort="profit"
        )
        primary_recommendation = self.build_primary_recommendation(client_id, days)
        daily_raw = self.build_daily_recommendations(client_id=client_id, days=days)
        daily_recommendations = MarketingService.dedupe_daily_against_primary(
            primary_recommendation,
            daily_raw,
        )
        primary_action = (
            {
                "type": str(primary_recommendation.get("severity", "")),
                "campaign": primary_recommendation.get("campaign"),
                "message": primary_recommendation.get("text"),
            }
            if primary_recommendation
            else self.determine_primary_action(campaign_table)
        )
        loss = self.loss_summary(client_id=client_id, days=days)
        trust = self._trust_meta(client_id=client_id, days=days)
        payload: dict[str, object] = {
            "overview": overview,
            "revenue_trend": revenue_trend,
            "spend_trend": spend_trend,
            "profit_trend": profit_trend,
            "top_campaigns": top_campaigns,
            "campaign_table": campaign_table,
            "daily_recommendations": daily_recommendations,
            "primary_recommendation": primary_recommendation,
            "primary_action": primary_action,
            "alerts": alerts,
            "loss_summary": loss,
            "margin_used": round(margin, 4),
            "margin": round(margin, 4),
            "trust": trust,
            "explanation": self._margin_explanation(),
            "scenarios": self._scenarios(
                revenue=float(overview.get("total_revenue", 0.0)),
                spend=float(overview.get("total_spend", 0.0)),
            ),
            "meta": {
                "date_range": f"last_{max(int(days), 1)}_days",
                "window_days": max(int(days), 1),
                "currency": "CZK",
                "margin_used": round(margin, 4),
                "margin": round(margin, 4),
                "note": self._margin_explanation(),
                "dataset_note": (
                    "KPI, grafy, tabulka kampaní, doporučení a poznámky používají stejné okno "
                    f"{max(int(days), 1)} dní."
                ),
            },
        }
        if calc_debug:
            payload["calc_debug"] = {
                "window_days": days,
                "margin_used": round(margin, 4),
                "overview_snapshot": {
                    "total_revenue": overview.get("total_revenue"),
                    "total_spend": overview.get("total_spend"),
                    "total_marketing_profit": overview.get("total_marketing_profit"),
                    "average_roas": overview.get("average_roas"),
                    "break_even_roas": overview.get("break_even_roas"),
                },
                "definitions": {
                    "roas": "revenue / spend (0 if spend is 0)",
                    "contribution_profit": "revenue × margin − spend",
                    "break_even_roas": "1 / margin (margin as decimal, e.g. 0.4 = 40 %)",
                    "average_roas_dashboard": "sum(paid revenue) / sum(paid spend) ve stejném okně jako přehled",
                    "campaign_roas_bands": (
                        "no_ad_spend if revenue>0 and spend=0 (ROAS n/a); else loss if ROAS < 0.9×BE; "
                        "profitable if ROAS > 1.1×BE; else at_risk"
                    ),
                },
            }
        return payload

    def get_insights(self, client_id: int, days: int = 30) -> list[str]:
        """
        Jen trend — bez opakování doporučení (horní karta) a bez čísel z tabulky.
        """
        insights: list[str] = []

        trend = self.revenue_trend_db(client_id=client_id, days=days)
        values = MarketingService._finite_series_values(list(trend.get("revenue", [])))
        if len(values) >= 4:
            mid = len(values) // 2
            prev_period = sum(values[:mid])
            last_period = sum(values[mid:])
            if prev_period > 0 and last_period < prev_period:
                insights.append("📉 Trend tržeb klesá.")
            elif last_period > prev_period:
                insights.append("📈 Tržby rostou.")

        roas_trend = self.roas_trend_db(client_id=client_id, days=days)
        roas_vals = MarketingService._finite_series_values(list(roas_trend.get("roas", [])))
        if len(roas_vals) >= 4:
            r_mid = len(roas_vals) // 2
            ra = sum(roas_vals[:r_mid]) / max(r_mid, 1)
            rb = sum(roas_vals[r_mid:]) / max(len(roas_vals) - r_mid, 1)
            if ra > 0 and rb < ra * 0.92:
                insights.append("📉 Trend ROAS klesá.")
            elif rb > ra * 1.08:
                insights.append("📈 Trend ROAS roste.")

        if not insights:
            insights.append("ℹ️ Trend vidíte v grafech níže.")

        return insights[:5]

    def campaigns_overview(self, campaigns: list[Campaign]) -> list[CampaignOut]:
        result: list[CampaignOut] = []
        for c in campaigns:
            metrics_view = self.calculate_campaign_metrics(revenue=c.revenue, cost=c.spend, margin=self._client_margin)
            result.append(
                CampaignOut(
                    campaign=c.name,
                    spend=round(c.spend, 2),
                    revenue=round(c.revenue, 2),
                    profit=round(float(metrics_view["profit"]), 2),
                    roas=float(metrics_view["roas"]),
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

