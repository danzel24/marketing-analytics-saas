from __future__ import annotations

import csv
import logging
import re
import unicodedata
from collections import defaultdict
from io import StringIO
from datetime import date, timedelta
from typing import Any

from app.core.csv_upload_platforms import (
    PLATFORM_CSV_GOOGLE_ADS,
    PLATFORM_CSV_META_ADS,
    PLATFORM_CSV_SHOP_ORDERS,
)
from app.core.domain_errors import ValidationError
from app.core.error_codes import ErrorCode
from app.models.db_models import Campaign, CampaignMetric
from app.repositories.campaign_metric_repository import CampaignMetricRepository
from app.repositories.campaign_repository_sql import CampaignRepository
from app.repositories.tenant_scope import require_positive_client_id
from app.services.csv_service import CSVService, DASHBOARD_DEFAULT_WINDOW_DAYS, MAX_CSV_UPLOAD_BYTES

logger = logging.getLogger(__name__)

BUCKET_SHOP = "E-shop objednávky (CSV)"
BUCKET_META = "Meta Ads (CSV soubor)"
BUCKET_GOOGLE = "Google Ads (CSV soubor)"

# Order status substrings → treat as cancelled / no revenue (MVP blacklist; extend per client if needed).
# Returned from _parse_orders_row when row is cancelled — import/preview treat as exclusion, not parse error.
_SKIP_ORDER_CANCELLED = "Zrušená / stornovaná — nezapočítáno do tržeb."

_ORDER_STATUS_CANCELLED_MARKERS = (
    "cancel",
    "cancelled",
    "canceled",
    "storno",
    "zruš",
    "zrus",
    "void",
    "refund",
    "vrácen",
    "vracen",
    "annul",
    "zamítn",
    "zamitn",
    "vrácena",
    "vracena",
)

# Czech / loose numeric dates in export footers (1.4.2026, 01.04.2026, 1. 4. 2026).
_CZ_DATE_TOKEN_RE = re.compile(
    r"\b(\d{1,2})\s*[\./]\s*(\d{1,2})\s*[\./]\s*(\d{2,4})\b",
)
# e.g. "1. března 2026" (Google UI period line) — month word after NFKD + strip combining marks.
_CZ_NAMED_MONTH_DATE_RE = re.compile(r"\b(\d{1,2})\.\s*([a-z]+)\s+(\d{4})\b", re.IGNORECASE)
_ISO_DATE_IN_TEXT_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

_CZ_MONTH_NAME_TO_NUM: dict[str, int] = {
    "ledna": 1,
    "leden": 1,
    "unora": 2,
    "unor": 2,
    "brezna": 3,
    "brezen": 3,
    "dubna": 4,
    "duben": 4,
    "kvetna": 5,
    "kveten": 5,
    "cervna": 6,
    "cerven": 6,
    "cervence": 7,
    "cervenec": 7,
    "srpna": 8,
    "srpen": 8,
    "zari": 9,
    "rijna": 10,
    "rijen": 10,
    "listopadu": 11,
    "listopad": 11,
    "prosince": 12,
    "prosinec": 12,
}


def _ascii_month_token(word: str) -> str:
    n = unicodedata.normalize("NFKD", str(word).strip().lower())
    return "".join(ch for ch in n if not unicodedata.combining(ch))


def _iso_dates_in_text(text: str) -> list[date]:
    out: list[date] = []
    for m in _ISO_DATE_IN_TEXT_RE.finditer(text or ""):
        try:
            out.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            continue
    return out


def _dates_from_czech_period_text(text: str) -> tuple[date | None, date | None]:
    """Best-effort (start, end) from free-text period lines or cells."""
    if not (text or "").strip():
        return None, None
    found: list[date] = []
    for m in _CZ_DATE_TOKEN_RE.finditer(text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            found.append(date(y, mo, d))
        except ValueError:
            continue
    nt = _ascii_month_token(text)
    nt = re.sub(r"[\u2013\u2014\-–—]", " ", nt)
    for m in _CZ_NAMED_MONTH_DATE_RE.finditer(nt):
        d_d, mon_w, y = int(m.group(1)), _ascii_month_token(m.group(2)), int(m.group(3))
        mo = _CZ_MONTH_NAME_TO_NUM.get(mon_w)
        if mo is None:
            continue
        try:
            found.append(date(y, mo, d_d))
        except ValueError:
            continue
    found.extend(_iso_dates_in_text(text))
    if not found:
        return None, None
    return min(found), max(found)


class MultiSourceCSVService(CSVService):
    """Separate uploads for orders / Meta / Google; stores under distinct ``Campaign.platform`` values."""

    def _decode_raw(self, raw: bytes) -> str:
        if not isinstance(raw, (bytes, bytearray)):
            raise ValidationError("Soubor není načten.", code=ErrorCode.CSV_NOT_LOADED)
        if len(raw) > MAX_CSV_UPLOAD_BYTES:
            raise ValidationError("CSV je příliš velké (max. 15 MB).", code=ErrorCode.CSV_TOO_LARGE)
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValidationError(
                "Soubor musí být v kódování UTF-8.",
                code=ErrorCode.CSV_ENCODING,
            ) from exc

    def _get_bucket_campaign(self, client_id: int, name: str, platform: str) -> Campaign:
        cid = require_positive_client_id(client_id)
        existing = self.campaign_repo.get_by_name_and_platform(cid, name, platform)
        if existing:
            return existing
        return self.campaign_repo.create_for_client(
            cid,
            Campaign(name=name, platform=platform, client_id=cid),
        )

    def _replace_platform_metrics(self, client_id: int, platform: str) -> None:
        """Remove existing metrics for this CSV platform so a new file replaces totals."""
        cid = require_positive_client_id(client_id)
        plat = frozenset({platform})
        self.metric_repo.delete_metrics_for_campaign_platforms(cid, plat, commit=False)
        # Drop bucket campaigns for this platform so re-import stays a clean replace
        self.campaign_repo.delete_campaigns_for_platforms(cid, plat, commit=False)

    @staticmethod
    def _period_from_dates(dates: list[date]) -> dict[str, Any] | None:
        if not dates:
            return None
        return {
            "date_min": min(dates).isoformat(),
            "date_max": max(dates).isoformat(),
        }

    @staticmethod
    def _channel_overview_window_hints(d_min: date | None, d_max: date | None) -> dict[str, Any]:
        """
        Same overlap rule as unified CSV → dashboard (``_import_dashboard_window_hints``):
        default rolling window [today−29, today]; if import range does not intersect, suggest a wider ``days``.
        """
        wd = DASHBOARD_DEFAULT_WINDOW_DAYS
        if d_min is None or d_max is None:
            return {
                "import_metric_date_min": None,
                "import_metric_date_max": None,
                "import_outside_default_channel_overview_window": None,
                "channel_overview_default_window_days": wd,
                "suggested_channel_overview_days": None,
            }
        today = date.today()
        window_end = today
        window_start = today - timedelta(days=wd - 1)
        outside = d_max < window_start or d_min > window_end
        suggested: int | None = None
        if outside:
            suggested = min(366, max(wd, (today - d_min).days + 1))
        return {
            "import_metric_date_min": d_min.isoformat(),
            "import_metric_date_max": d_max.isoformat(),
            "import_outside_default_channel_overview_window": outside,
            "channel_overview_default_window_days": wd,
            "suggested_channel_overview_days": suggested,
        }

    @staticmethod
    def _booking_honesty_note_cs(detected_file_type: str) -> str | None:
        if detected_file_type == "meta_cz_monthly_campaign":
            return (
                "Měsíční výdaje Meta jsou uloženy ke konci období reportu (jeden den v datech), ne po jednotlivých dnech."
            )
        if detected_file_type == "google_cz_campaign_period":
            return (
                "Výdaje z Google (součet Cena) jsou uloženy ke konci období z hlavičky reportu, ne po dnech."
            )
        return None

    def _attach_channel_overview_follow_up(
        self,
        payload: dict[str, Any],
        *,
        date_min: date | None,
        date_max: date | None,
        detected_file_type: str,
    ) -> dict[str, Any]:
        payload.update(self._channel_overview_window_hints(date_min, date_max))
        note = self._booking_honesty_note_cs(detected_file_type)
        if note:
            payload["import_booking_honesty_note_cs"] = note
        return payload

    @staticmethod
    def _is_order_status_cancelled(status_raw: str) -> bool:
        s = (status_raw or "").strip().lower()
        if not s:
            return False
        return any(m in s for m in _ORDER_STATUS_CANCELLED_MARKERS)

    # --- Orders (e-shop) -------------------------------------------------

    def _reject_unified_marketing_shape(self, normalized_set: set[str]) -> None:
        if {"date", "campaign", "revenue"}.issubset(normalized_set):
            raise ValidationError(
                "Tento soubor vypadá jako sjednocený marketing CSV (datum + kampaň + tržby). "
                "Pro tento typ použijte stránku „Nahrát sjednocený CSV“.",
                code=ErrorCode.CSV_UNSUPPORTED_FORMAT,
            )
        if {"date", "campaign id", "revenue"}.issubset(normalized_set):
            raise ValidationError(
                "Tento soubor vypadá jako sjednocený marketing CSV (datum + ID kampaně + tržby). "
                "Pro tento typ použijte stránku „Nahrát sjednocený CSV“.",
                code=ErrorCode.CSV_UNSUPPORTED_FORMAT,
            )

    def _classify_orders_format(
        self,
        normalized_set: set[str],
        header_map: dict[str, str],
        original_headers: list[str],
    ) -> str:
        self._reject_unified_marketing_shape(normalized_set)
        # Client pilot: code; date; statusName; currencyCode; totalPriceWithVat (often semicolon CSV)
        tpv = self._find_header(
            header_map,
            [
                "totalpricewithvat",
                "total price with vat",
                "totalprice with vat",
                "celkova cena s dph",
                "cena celkem s dph",
            ],
        )
        stc = self._find_header(header_map, ["statusname", "status name", "stav objednavky", "stav"])
        dcol = self._find_header(header_map, ["date", "datum", "order date", "datum objednavky", "datum objednávky"])
        if tpv and stc and dcol:
            return "client_orders_v1"
        shopify_created = self._find_header(header_map, ["created at"])
        shopify_total = self._find_header(header_map, ["total", "subtotal"])
        if shopify_created and shopify_total:
            return "shopify_orders"
        shoptet_date = self._find_header(header_map, ["datum"])
        shoptet_rev = self._find_header(header_map, ["trzba", "tržba", "cena celkem"])
        if shoptet_date and shoptet_rev:
            return "shoptet_orders"
        dcol = self._find_header(header_map, ["date", "order date", "datum objednávky"])
        mcol = self._find_header(
            header_map,
            ["revenue", "total", "order total", "amount", "subtotal", "cena celkem", "trzba", "tržba"],
        )
        if dcol and mcol:
            camp = self._find_header(header_map, ["campaign", "campaign name", "kampaň", "kampan"])
            if camp is None:
                return "simple_orders"
        raise ValidationError(
            self._unsupported_orders_message(original_headers),
            code=ErrorCode.CSV_UNSUPPORTED_FORMAT,
        )

    def _unsupported_orders_message(self, original_headers: list[str]) -> str:
        head_preview = ", ".join(original_headers[:12])
        if len(original_headers) > 12:
            head_preview += ", …"
        return (
            f"Objednávkový CSV nebyl rozpoznán ({len(original_headers)} sloupců: {head_preview}). "
            "Podporujeme export klienta (code, date, statusName, totalPriceWithVat), Shopify, Shoptet, "
            "nebo jednoduchý tvar datum + částka (bez kampaně)."
        )

    def _parse_orders_row(
        self,
        fmt: str,
        row: dict[str, str],
        header_map: dict[str, str],
        row_index: int,
    ) -> tuple[date | None, float | None, str | None]:
        if fmt == "client_orders_v1":
            d_raw = self._cell(
                row,
                self._find_header(
                    header_map,
                    ["date", "datum", "order date", "datum objednavky", "datum objednávky"],
                ),
            )
            st_raw = self._cell(
                row,
                self._find_header(header_map, ["statusname", "status name", "stav objednavky", "stav"]),
            )
            tpv_col = self._find_header(
                header_map,
                [
                    "totalpricewithvat",
                    "total price with vat",
                    "totalprice with vat",
                    "celkova cena s dph",
                    "cena celkem s dph",
                ],
            )
            r_raw = self._cell(row, tpv_col)
            if self._is_order_status_cancelled(st_raw):
                return None, None, _SKIP_ORDER_CANCELLED
            d = self._parse_date(d_raw)
            if d is None:
                d = self._parse_shopify_date(d_raw)
            rev = self.parse_currency(r_raw)
            if d is None:
                return None, None, "Neplatné datum."
            if rev is None:
                return None, None, "Neplatná částka (totalPriceWithVat)."
            return d, float(rev), None
        if fmt == "shopify_orders":
            created = self._cell(row, self._find_header(header_map, ["created at"]))
            total_raw = self._cell(row, self._find_header(header_map, ["total", "subtotal"]))
            d = self._parse_shopify_date(created)
            rev = self.parse_currency(total_raw)
            if d is None:
                return None, None, "Neplatné datum v Created at."
            if rev is None:
                return None, None, "Neplatná částka (Total/Subtotal)."
            return d, float(rev), None
        if fmt == "shoptet_orders":
            d_raw = self._cell(row, self._find_header(header_map, ["datum"]))
            r_raw = self._cell(row, self._find_header(header_map, ["trzba", "tržba", "cena celkem"]))
            d = self._parse_date(d_raw)
            rev = self.parse_currency(r_raw)
            if d is None:
                return None, None, "Neplatné datum."
            if rev is None:
                return None, None, "Neplatná tržba."
            return d, float(rev), None
        if fmt == "simple_orders":
            d_raw = self._cell(row, self._find_header(header_map, ["date", "order date", "datum objednávky"]))
            mcol = self._find_header(
                header_map,
                ["revenue", "total", "order total", "amount", "subtotal", "cena celkem", "trzba", "tržba"],
            )
            r_raw = self._cell(row, mcol)
            d = self._parse_date(d_raw)
            if d is None:
                d = self._parse_shopify_date(d_raw)
            rev = self.parse_currency(r_raw)
            if d is None:
                return None, None, "Neplatné datum."
            if rev is None:
                return None, None, "Neplatná částka."
            return d, float(rev), None
        return None, None, "Neznámý formát."

    def _orders_format_label_cs(self, fmt: str) -> str:
        return {
            "client_orders_v1": "Objednávky klienta (date, statusName, totalPriceWithVat; bez zrušených)",
            "shopify_orders": "Export objednávek (Shopify-like: Created at + Total)",
            "shoptet_orders": "Export objednávek (Shoptet-like: Datum + tržba)",
            "simple_orders": "Jednoduchý export objednávek (datum + částka, bez kampaně)",
        }.get(fmt, fmt)

    def _key_fields_orders(self, fmt: str, header_map: dict[str, str]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        if fmt == "client_orders_v1":
            for role, aliases in (
                ("order_date", ["date", "datum", "order date"]),
                ("status", ["statusname", "status name", "stav"]),
                ("amount_gross", ["totalpricewithvat", "total price with vat"]),
            ):
                c = self._find_header(header_map, aliases)
                if c:
                    out.append({"role": role, "column": c})
        elif fmt == "shopify_orders":
            c1 = self._find_header(header_map, ["created at"])
            c2 = self._find_header(header_map, ["total", "subtotal"])
            if c1:
                out.append({"role": "order_datetime", "column": c1})
            if c2:
                out.append({"role": "order_amount", "column": c2})
        elif fmt == "shoptet_orders":
            c1 = self._find_header(header_map, ["datum"])
            c2 = self._find_header(header_map, ["trzba", "tržba", "cena celkem"])
            if c1:
                out.append({"role": "date", "column": c1})
            if c2:
                out.append({"role": "order_amount", "column": c2})
        else:
            c1 = self._find_header(header_map, ["date", "order date", "datum objednávky"])
            c2 = self._find_header(
                header_map,
                ["revenue", "total", "order total", "amount", "subtotal", "cena celkem", "trzba", "tržba"],
            )
            if c1:
                out.append({"role": "date", "column": c1})
            if c2:
                out.append({"role": "order_amount", "column": c2})
        return out

    def preview_orders_csv_bytes(self, raw: bytes) -> dict[str, Any]:
        content = self._decode_raw(raw)
        rows, headers, header_map = self._load_orders_table(content)
        fmt = self._classify_orders_format(
            {self._normalize_header(h) for h in headers},
            header_map,
            headers,
        )
        parsed_dates: list[date] = []
        errors: list[dict[str, Any]] = []
        excluded_cancelled = 0
        for idx, row in enumerate(rows, start=2):
            d, rev, err = self._parse_orders_row(fmt, row, header_map, idx)
            if err == _SKIP_ORDER_CANCELLED:
                excluded_cancelled += 1
                continue
            if d is not None and rev is not None:
                parsed_dates.append(d)
            if err:
                errors.append({"row": idx, "reason": err})
        status = "ok" if len(errors) == 0 and len(parsed_dates) > 0 else ("partial" if parsed_dates else "invalid")
        preview_rows = self._build_orders_preview_rows(rows[:8], fmt, header_map, start_row=2)
        return {
            "source": "orders",
            "detected_file_type": fmt,
            "detected_file_type_label_cs": self._orders_format_label_cs(fmt),
            "row_count": len(rows),
            "period": self._period_from_dates(parsed_dates),
            "key_fields": self._key_fields_orders(fmt, header_map),
            "headers": headers,
            "validation_status": status,
            "validation_errors_sample": errors[:12],
            "rows_excluded_cancelled": excluded_cancelled,
            "preview_rows": preview_rows,
            "period_alignment_note_cs": (
                "V přehledu kanálů se započítají jen objednávky, jejichž datum spadá do zvoleného okna dní "
                "(stejně jako u výdajů Meta/Google z importu)."
            ),
        }

    def _load_orders_table(self, content: str) -> tuple[list[dict[str, str]], list[str], dict[str, str]]:
        return self._load_csv_table(content)

    def _build_orders_preview_rows(
        self,
        sample: list[dict[str, str]],
        fmt: str,
        header_map: dict[str, str],
        *,
        start_row: int,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i, row in enumerate(sample):
            idx = start_row + i
            d, rev, err = self._parse_orders_row(fmt, row, header_map, idx)
            out.append(
                {
                    "row": idx,
                    "parsed_date": d.isoformat() if d else None,
                    "parsed_revenue": rev,
                    "ok": err is None and d is not None and rev is not None,
                    "error": err,
                    "raw_snippet": {k: (row.get(k) or "")[:80] for k in list(row.keys())[:6]},
                }
            )
        return out

    def import_orders_csv_bytes(self, raw: bytes, client_id: int) -> dict[str, Any]:
        cid = require_positive_client_id(client_id)
        content = self._decode_raw(raw)
        rows, headers, header_map = self._load_orders_table(content)
        fmt = self._classify_orders_format(
            {self._normalize_header(h) for h in headers},
            header_map,
            headers,
        )
        by_day: dict[date, list[float]] = defaultdict(list)
        errors: list[dict[str, Any]] = []
        excluded_cancelled = 0
        for idx, row in enumerate(rows, start=2):
            d, rev, err = self._parse_orders_row(fmt, row, header_map, idx)
            if err == _SKIP_ORDER_CANCELLED:
                excluded_cancelled += 1
                continue
            if err or d is None or rev is None:
                errors.append({"row": idx, "reason": err or "Řádek se nepodařilo zpracovat.", "data": row})
                continue
            by_day[d].append(float(rev))

        if not by_day:
            return {
                "source": "orders",
                "imported_metrics": 0,
                "aggregated_days": 0,
                "source_row_count": 0,
                "skipped_rows": len(errors),
                "errors": errors[:50],
                "detected_file_type": fmt,
                "period": None,
                "validation_status": "invalid",
            }

        session = self.metric_repo.session
        try:
            self._replace_platform_metrics(cid, PLATFORM_CSV_SHOP_ORDERS)
            camp = self._get_bucket_campaign(cid, BUCKET_SHOP, PLATFORM_CSV_SHOP_ORDERS)
            to_create: list[CampaignMetric] = []
            for d, amounts in sorted(by_day.items()):
                to_create.append(
                    CampaignMetric(
                        campaign_id=int(camp.id),
                        metric_date=d,
                        revenue=float(sum(amounts)),
                        spend=0.0,
                        clicks=0,
                        conversions=int(len(amounts)),
                    )
                )
            n = self.metric_repo.bulk_create_for_client(cid, to_create) if to_create else 0
        except Exception:
            session.rollback()
            raise

        dates = list(by_day.keys())
        d_mi, d_ma = min(dates), max(dates)
        payload: dict[str, Any] = {
            "source": "orders",
            "imported_metrics": n,
            "aggregated_days": len(by_day),
            "source_row_count": len(rows) - len(errors) - excluded_cancelled,
            "skipped_rows": len(errors),
            "excluded_cancelled_orders": excluded_cancelled,
            "errors": errors[:50],
            "detected_file_type": fmt,
            "period": self._period_from_dates(dates),
            "validation_status": "ok" if not errors and dates else ("partial" if dates else "invalid"),
        }
        return self._attach_channel_overview_follow_up(
            payload,
            date_min=d_mi,
            date_max=d_ma,
            detected_file_type=fmt,
        )

    # --- Meta Ads (spend only) -------------------------------------------

    def _ensure_meta_daily_columns(self, header_map: dict[str, str], original_headers: list[str]) -> None:
        dcol = self._find_header(
            header_map,
            ["day", "date", "den", "reporting starts", "reporting start"],
        )
        scol = self._find_header(
            header_map,
            [
                "amount spent",
                "spend",
                "cost",
                "částka utracená",
                "amount spent czk",
                "spend czk",
                "náklady",
            ],
        )
        if not dcol or not scol:
            raise ValidationError(
                "Meta CSV: očekáváme buď měsíční export (Název kampaně + Vydaná částka + období reportu), "
                "nebo denní řádky se sloupcem data a výdajů (Day / Amount spent). "
                f"Nalezené sloupce: {', '.join(original_headers[:16])}{'…' if len(original_headers) > 16 else ''}",
                code=ErrorCode.CSV_UNSUPPORTED_FORMAT,
            )

    def _detect_meta_variant(self, header_map: dict[str, str], original_headers: list[str]) -> str:
        camp = self._find_header(
            header_map,
            ["název kampaně", "nazev kampane", "nazeve kampane", "campaign name"],
        )
        spend = self._find_header(
            header_map,
            [
                "vydaná částka",
                "vydana castka",
                "vydaná částka czk",
                "vydana castka czk",
                "vydaná částka (czk)",
            ],
        )
        if camp and spend:
            return "meta_cz_monthly"
        self._ensure_meta_daily_columns(header_map, original_headers)
        return "meta_daily"

    def _meta_cz_report_end_from_row(self, row: dict[str, str], header_map: dict[str, str]) -> date | None:
        z_h = self._find_header(
            header_map,
            ["začátek reportování", "zacatek reportovani", "zacatek reportování", "reporting starts"],
        )
        k_h = self._find_header(
            header_map,
            ["konce reportů", "konce reportu", "konec reportů", "konec reportu", "reporting ends"],
        )
        z_cell = self._cell(row, z_h)
        k_cell = self._cell(row, k_h)
        # ISO YYYY-MM-DD (real Meta UI) and Czech numeric / month-name text share one extractor.
        _s, end = _dates_from_czech_period_text(f"{z_cell} {k_cell}")
        if end:
            return end
        _, end2 = _dates_from_czech_period_text(k_cell)
        if end2:
            return end2
        _, end3 = _dates_from_czech_period_text(z_cell)
        return end3

    def _parse_meta_cz_detail_row(
        self,
        row: dict[str, str],
        header_map: dict[str, str],
        row_index: int,
    ) -> tuple[float | None, str | None, str | None]:
        """Returns (spend, error, skip) where skip is ``total_row`` for souhrnný řádek."""
        camp_h = self._find_header(
            header_map,
            ["název kampaně", "nazev kampane", "nazeve kampane", "campaign name"],
        )
        if not (self._cell(row, camp_h) or "").strip():
            return None, None, "total_row"
        s_raw = self._cell(
            row,
            self._find_header(
                header_map,
                [
                    "vydaná částka",
                    "vydana castka",
                    "vydaná částka czk",
                    "vydana castka czk",
                    "vydaná částka (czk)",
                    "amount spent",
                    "spend",
                ],
            ),
        )
        spend, spend_err = self._parse_spend_value(s_raw, row_index=row_index)
        if spend_err:
            return None, spend_err, None
        if spend is None:
            return None, "Neplatné náklady.", None
        return float(spend), None, None

    def _parse_meta_row(
        self,
        row: dict[str, str],
        header_map: dict[str, str],
        row_index: int,
    ) -> tuple[date | None, float | None, str | None]:
        d_raw = self._cell(
            row,
            self._find_header(
                header_map,
                ["day", "date", "den", "reporting starts", "reporting start"],
            ),
        )
        s_raw = self._cell(
            row,
            self._find_header(
                header_map,
                [
                    "amount spent",
                    "spend",
                    "cost",
                    "částka utracená",
                    "amount spent czk",
                    "spend czk",
                    "náklady",
                ],
            ),
        )
        d = self._parse_date(d_raw)
        if d is None and d_raw:
            d = self._parse_shopify_date(d_raw)
        spend, spend_err = self._parse_spend_value(s_raw, row_index=row_index)
        if d is None:
            return None, None, "Neplatné datum."
        if spend_err:
            return None, None, spend_err
        if spend is None:
            return None, None, "Neplatné náklady."
        return d, float(spend), None

    def _key_fields_meta(self, header_map: dict[str, str], *, variant: str) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        if variant == "meta_cz_monthly":
            for role, aliases in (
                ("campaign_name", ["název kampaně", "nazev kampane", "campaign name"]),
                ("ad_spend", ["vydaná částka", "vydana castka"]),
                ("report_start", ["začátek reportování", "zacatek reportovani"]),
                ("report_end", ["konce reportů", "konce reportu", "konec reportů"]),
            ):
                c = self._find_header(header_map, aliases)
                if c:
                    out.append({"role": role, "column": c})
            return out
        d = self._find_header(
            header_map,
            ["day", "date", "den", "reporting starts", "reporting start"],
        )
        s = self._find_header(
            header_map,
            [
                "amount spent",
                "spend",
                "cost",
                "částka utracená",
                "amount spent czk",
                "spend czk",
                "náklady",
            ],
        )
        if d:
            out.append({"role": "date", "column": d})
        if s:
            out.append({"role": "ad_spend", "column": s})
        return out

    def preview_meta_csv_bytes(self, raw: bytes) -> dict[str, Any]:
        content = self._decode_raw(raw)
        rows, headers, header_map = self._load_csv_table(content)
        variant = self._detect_meta_variant(header_map, headers)
        if variant == "meta_cz_monthly":
            return self._preview_meta_cz_monthly(rows, headers, header_map)
        parsed_dates: list[date] = []
        errors: list[dict[str, Any]] = []
        for idx, row in enumerate(rows, start=2):
            d, spend, err = self._parse_meta_row(row, header_map, idx)
            if d is not None:
                parsed_dates.append(d)
            if err:
                errors.append({"row": idx, "reason": err})
        status = "ok" if len(errors) == 0 and parsed_dates else ("partial" if parsed_dates else "invalid")
        preview_rows: list[dict[str, Any]] = []
        for i, row in enumerate(rows[:8]):
            idx = 2 + i
            d, spend, err = self._parse_meta_row(row, header_map, idx)
            preview_rows.append(
                {
                    "row": idx,
                    "parsed_date": d.isoformat() if d else None,
                    "parsed_spend": spend,
                    "ok": err is None and d is not None and spend is not None,
                    "error": err,
                }
            )
        return {
            "source": "meta",
            "detected_file_type": "meta_daily_rows",
            "detected_file_type_label_cs": "Meta Ads — denní řádky (datum + výdaj)",
            "row_count": len(rows),
            "period": self._period_from_dates(parsed_dates),
            "key_fields": self._key_fields_meta(header_map, variant=variant),
            "headers": headers,
            "validation_status": status,
            "validation_errors_sample": errors[:12],
            "preview_rows": preview_rows,
            "period_alignment_note_cs": (
                "Do přehledu kanálů se započítají jen řádky, jejichž datum spadá do zvoleného okna dní."
            ),
        }

    def _preview_meta_cz_monthly(self, rows: list[dict[str, str]], headers: list[str], header_map: dict[str, str]) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        total_spend = 0.0
        skipped_total = 0
        report_end: date | None = None
        for idx, row in enumerate(rows, start=2):
            if report_end is None:
                report_end = self._meta_cz_report_end_from_row(row, header_map)
            spend, err, skip = self._parse_meta_cz_detail_row(row, header_map, idx)
            if skip == "total_row":
                skipped_total += 1
                continue
            if err:
                errors.append({"row": idx, "reason": err})
                continue
            if spend is not None:
                total_spend += spend
        period = {"date_min": report_end.isoformat(), "date_max": report_end.isoformat()} if report_end else None
        preview_rows: list[dict[str, Any]] = []
        for i, row in enumerate(rows[:8]):
            idx = 2 + i
            spend, err, skip = self._parse_meta_cz_detail_row(row, header_map, idx)
            preview_rows.append(
                {
                    "row": idx,
                    "parsed_date": report_end.isoformat() if report_end else None,
                    "parsed_spend": spend if skip != "total_row" else None,
                    "ok": skip == "total_row" or (err is None and spend is not None),
                    "error": err if skip != "total_row" else "Souhrnný řádek (bez názvu kampaně) — přeskočeno",
                }
            )
        status = "ok" if not errors and report_end is not None and total_spend > 0 else ("partial" if report_end else "invalid")
        return {
            "source": "meta",
            "detected_file_type": "meta_cz_monthly_campaign",
            "detected_file_type_label_cs": "Meta — měsíční report (kampaně + Vydaná částka; souhrnný řádek přeskočen)",
            "row_count": len(rows),
            "period": period,
            "report_booking_date": report_end.isoformat() if report_end else None,
            "aggregated_spend_preview_czk": round(total_spend, 2),
            "rows_skipped_as_total": skipped_total,
            "key_fields": self._key_fields_meta(header_map, variant="meta_cz_monthly"),
            "headers": headers,
            "validation_status": status,
            "validation_errors_sample": errors[:12],
            "preview_rows": preview_rows,
            "period_alignment_note_cs": (
                "Celkové výdaje z tohoto souboru jsou uloženy na jeden den — koncové datum období reportu (sloupce "
                "Začátek/Konec reportování). V přehledu kanálů se zobrazí jen pokud toto datum spadá do zvoleného okna dní."
            ),
        }

    def import_meta_csv_bytes(self, raw: bytes, client_id: int) -> dict[str, Any]:
        cid = require_positive_client_id(client_id)
        content = self._decode_raw(raw)
        rows, headers, header_map = self._load_csv_table(content)
        variant = self._detect_meta_variant(header_map, headers)
        if variant == "meta_cz_monthly":
            return self._import_meta_cz_monthly(cid, rows, headers, header_map)
        by_day: dict[date, float] = defaultdict(float)
        errors: list[dict[str, Any]] = []
        for idx, row in enumerate(rows, start=2):
            d, spend, err = self._parse_meta_row(row, header_map, idx)
            if err or d is None or spend is None:
                errors.append({"row": idx, "reason": err or "Chyba řádku.", "data": row})
                continue
            by_day[d] += float(spend)

        if not by_day:
            return {
                "source": "meta",
                "imported_metrics": 0,
                "aggregated_days": 0,
                "source_row_count": 0,
                "skipped_rows": len(errors),
                "errors": errors[:50],
                "detected_file_type": "meta_daily_rows",
                "period": None,
                "validation_status": "invalid",
            }

        session = self.metric_repo.session
        try:
            self._replace_platform_metrics(cid, PLATFORM_CSV_META_ADS)
            camp = self._get_bucket_campaign(cid, BUCKET_META, PLATFORM_CSV_META_ADS)
            to_create = [
                CampaignMetric(
                    campaign_id=int(camp.id),
                    metric_date=d,
                    revenue=0.0,
                    spend=float(spend),
                    clicks=0,
                    conversions=0,
                )
                for d, spend in sorted(by_day.items())
            ]
            n = self.metric_repo.bulk_create_for_client(cid, to_create) if to_create else 0
        except Exception:
            session.rollback()
            raise

        dates = list(by_day.keys())
        d_mi, d_ma = min(dates), max(dates)
        payload = {
            "source": "meta",
            "imported_metrics": n,
            "aggregated_days": len(by_day),
            "source_row_count": len(rows) - len(errors),
            "skipped_rows": len(errors),
            "errors": errors[:50],
            "detected_file_type": "meta_daily_rows",
            "period": self._period_from_dates(dates),
            "validation_status": "ok" if not errors and dates else ("partial" if dates else "invalid"),
        }
        return self._attach_channel_overview_follow_up(
            payload,
            date_min=d_mi,
            date_max=d_ma,
            detected_file_type="meta_daily_rows",
        )

    def _import_meta_cz_monthly(
        self,
        cid: int,
        rows: list[dict[str, str]],
        headers: list[str],
        header_map: dict[str, str],
    ) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        total_spend = 0.0
        report_end: date | None = None
        detail_rows = 0
        for idx, row in enumerate(rows, start=2):
            if report_end is None:
                report_end = self._meta_cz_report_end_from_row(row, header_map)
            spend, err, skip = self._parse_meta_cz_detail_row(row, header_map, idx)
            if skip == "total_row":
                continue
            if err:
                errors.append({"row": idx, "reason": err, "data": row})
                continue
            if spend is not None:
                total_spend += spend
                detail_rows += 1

        if report_end is None or total_spend <= 0:
            return {
                "source": "meta",
                "imported_metrics": 0,
                "aggregated_days": 0,
                "source_row_count": 0,
                "skipped_rows": len(errors),
                "errors": errors[:50],
                "detected_file_type": "meta_cz_monthly_campaign",
                "period": None,
                "validation_status": "invalid",
            }

        session = self.metric_repo.session
        try:
            self._replace_platform_metrics(cid, PLATFORM_CSV_META_ADS)
            camp = self._get_bucket_campaign(cid, BUCKET_META, PLATFORM_CSV_META_ADS)
            to_create = [
                CampaignMetric(
                    campaign_id=int(camp.id),
                    metric_date=report_end,
                    revenue=0.0,
                    spend=float(total_spend),
                    clicks=0,
                    conversions=0,
                )
            ]
            n = self.metric_repo.bulk_create_for_client(cid, to_create)
        except Exception:
            session.rollback()
            raise

        payload = {
            "source": "meta",
            "imported_metrics": n,
            "aggregated_days": 1,
            "source_row_count": detail_rows,
            "skipped_rows": len(errors),
            "errors": errors[:50],
            "detected_file_type": "meta_cz_monthly_campaign",
            "period": {"date_min": report_end.isoformat(), "date_max": report_end.isoformat()},
            "report_booking_date": report_end.isoformat(),
            "validation_status": "ok" if not errors else "partial",
        }
        return self._attach_channel_overview_follow_up(
            payload,
            date_min=report_end,
            date_max=report_end,
            detected_file_type="meta_cz_monthly_campaign",
        )

    # --- Google Ads (spend only, CSV — not OAuth) ------------------------

    @staticmethod
    def _csv_split_line_cells(line: str, delimiter: str) -> list[str]:
        """One logical CSV row — handles quotes (unlike naive ``split(delimiter)``)."""
        try:
            row = next(csv.reader(StringIO(line), delimiter=delimiter))
        except csv.Error:
            return [p.strip() for p in line.split(delimiter)]
        return [str(c).strip() for c in row]

    def _google_ui_header_blob(self, line: str, delimiter: str) -> str:
        parts = [p for p in self._csv_split_line_cells(line, delimiter) if p]
        norms = [self._normalize_header(p) for p in parts]
        return " ".join(norms)

    def _load_google_cz_campaign_table(self, content: str) -> tuple[list[dict[str, str]], list[str], dict[str, str], date | None]:
        """
        Google UI export: title line(s), period text, then header (Kampaň, Prokliky, Zobr., Cena, …).
        """
        raw = content.splitlines()
        nonempty: list[tuple[int, str]] = []
        for i, ln in enumerate(raw):
            s = ln.strip()
            if not s or all(c in ";, \t" for c in s):
                continue
            nonempty.append((i, s))

        header_j: int | None = None
        delim = ","
        for j, (_ln_i, line) in enumerate(nonempty):
            dlm = ";" if line.count(";") > line.count(",") else ","
            blob = self._google_ui_header_blob(line, dlm)
            has_volume = (
                "proklik" in blob
                or "zobr" in blob
                or "zobrazen" in blob
                or "konverz" in blob
                or "kliknut" in blob
            )
            if "kampan" in blob and "cena" in blob and has_volume:
                header_j = j
                delim = dlm
                break

        if header_j is None:
            raise ValidationError(
                "Google Ads CSV: nenalezena hlavička kampaní (Kampaň + Cena + Prokliky/Zobrazení/Konverze).",
                code=ErrorCode.CSV_UNSUPPORTED_FORMAT,
            )

        preamble = " ".join(nonempty[k][1] for k in range(header_j))
        _, report_end = _dates_from_czech_period_text(preamble)
        if report_end is None:
            scan = " ".join(s for _, s in nonempty[: min(8, len(nonempty))])
            _, report_end = _dates_from_czech_period_text(scan)
        if report_end is None:
            raise ValidationError(
                "Google Ads CSV: z úvodních řádků se nepodařilo vyčíst koncové datum období (očekáváme např. 30. 4. 2026).",
                code=ErrorCode.CSV_UNSUPPORTED_FORMAT,
            )

        block_lines = [nonempty[k][1] for k in range(header_j, len(nonempty))]
        rows, headers, header_map = self._load_csv_table_from_line_block(block_lines, delimiter=delim)
        return rows, headers, header_map, report_end

    def _parse_google_cost(self, raw: str, row_index: int) -> tuple[float | None, str | None]:
        spend, err = self._parse_spend_value(raw, row_index=row_index)
        if err or spend is None:
            return spend, err
        raw_st = (raw or "").strip().replace(" ", "").replace("\u00a0", "")
        # Rare: cost as micros in raw integer strings from some tooling exports
        if spend >= 1_000_000 and raw_st.replace("-", "").isdigit():
            return spend / 1_000_000.0, None
        return spend, None

    def _classify_google_format(self, header_map: dict[str, str], original_headers: list[str]) -> None:
        dcol = self._find_header(header_map, ["day", "date", "den", "segments date"])
        ccol = self._find_header(
            header_map,
            ["cost", "spend", "amount spent", "cost czk", "částka utracená", "cena"],
        )
        if not dcol or not ccol:
            raise ValidationError(
                "Google Ads CSV: buď export z UI (název + období + hlavička Kampaň/Cena), "
                "nebo denní řádky se sloupcem data a nákladů (Day + Cost). "
                f"Nalezené sloupce: {', '.join(original_headers[:16])}{'…' if len(original_headers) > 16 else ''}",
                code=ErrorCode.CSV_UNSUPPORTED_FORMAT,
            )

    def _parse_google_row(
        self,
        row: dict[str, str],
        header_map: dict[str, str],
        row_index: int,
    ) -> tuple[date | None, float | None, str | None]:
        d_raw = self._cell(row, self._find_header(header_map, ["day", "date", "den", "segments date"]))
        c_raw = self._cell(
            row,
            self._find_header(
                header_map,
                ["cost", "spend", "amount spent", "cost czk", "částka utracená", "cena"],
            ),
        )
        d = self._parse_date(d_raw)
        if d is None and d_raw:
            d = self._parse_shopify_date(d_raw)
        spend, spend_err = self._parse_google_cost(c_raw, row_index=row_index)
        if d is None:
            return None, None, "Neplatné datum."
        if spend_err:
            return None, None, spend_err
        if spend is None:
            return None, None, "Neplatné náklady (Cost)."
        return d, float(spend), None

    def _parse_google_cz_row(
        self,
        row: dict[str, str],
        header_map: dict[str, str],
        row_index: int,
    ) -> tuple[float | None, str | None, str | None]:
        """(spend, err, skip) — ``skip`` is ``total_row`` when campaign name empty."""
        camp_h = self._find_header(header_map, ["kampaň", "kampan", "campaign"])
        if not (self._cell(row, camp_h) or "").strip():
            return None, None, "total_row"
        c_raw = self._cell(
            row,
            self._find_header(
                header_map,
                ["cena", "cost", "spend", "amount spent", "cost czk"],
            ),
        )
        spend, spend_err = self._parse_google_cost(c_raw, row_index=row_index)
        if spend_err:
            return None, spend_err, None
        if spend is None:
            return None, "Neplatná Cena.", None
        return float(spend), None, None

    def _key_fields_google(self, header_map: dict[str, str], *, variant: str) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        if variant == "google_cz_campaign_period":
            for role, aliases in (
                ("campaign", ["kampaň", "kampan", "campaign"]),
                ("ad_spend", ["cena", "cost", "spend"]),
            ):
                c = self._find_header(header_map, aliases)
                if c:
                    out.append({"role": role, "column": c})
            return out
        d = self._find_header(header_map, ["day", "date", "den", "segments date"])
        c = self._find_header(
            header_map,
            ["cost", "spend", "amount spent", "cost czk", "částka utracená", "cena"],
        )
        if d:
            out.append({"role": "date", "column": d})
        if c:
            out.append({"role": "ad_spend", "column": c})
        return out

    def preview_google_csv_bytes(self, raw: bytes) -> dict[str, Any]:
        content = self._decode_raw(raw)
        report_end: date | None = None
        try:
            rows, headers, header_map, report_end = self._load_google_cz_campaign_table(content)
            variant = "google_cz_campaign_period"
        except ValidationError:
            rows, headers, header_map = self._load_csv_table(content)
            self._classify_google_format(header_map, headers)
            variant = "google_daily"

        if variant == "google_cz_campaign_period" and report_end is not None:
            total = 0.0
            errors: list[dict[str, Any]] = []
            skipped = 0
            for idx, row in enumerate(rows, start=2):
                spend, err, skip = self._parse_google_cz_row(row, header_map, idx)
                if skip == "total_row":
                    skipped += 1
                    continue
                if err:
                    errors.append({"row": idx, "reason": err})
                    continue
                if spend is not None:
                    total += spend
            preview_rows: list[dict[str, Any]] = []
            for i, row in enumerate(rows[:8]):
                idx = 2 + i
                spend, err, skip = self._parse_google_cz_row(row, header_map, idx)
                preview_rows.append(
                    {
                        "row": idx,
                        "parsed_date": report_end.isoformat(),
                        "parsed_spend": spend if skip != "total_row" else None,
                        "ok": skip == "total_row" or (err is None and spend is not None),
                        "error": err if skip != "total_row" else "Souhrnný řádek — přeskočeno",
                    }
                )
            period = {"date_min": report_end.isoformat(), "date_max": report_end.isoformat()}
            status = "ok" if not errors and total > 0 else ("partial" if total > 0 else "invalid")
            return {
                "source": "google",
                "detected_file_type": "google_cz_campaign_period",
                "detected_file_type_label_cs": "Google Ads — výkon kampaní z UI (období v záhlaví; Cena jako výdaj)",
                "row_count": len(rows),
                "period": period,
                "report_booking_date": report_end.isoformat(),
                "aggregated_spend_preview_czk": round(total, 2),
                "rows_skipped_as_total": skipped,
                "key_fields": self._key_fields_google(header_map, variant=variant),
                "headers": headers,
                "validation_status": status,
                "validation_errors_sample": errors[:12],
                "preview_rows": preview_rows,
                "period_alignment_note_cs": (
                    "Součet Cena ze všech kampaní je uložen na koncové datum období vyčtené z úvodních řádků. "
                    "V přehledu kanálů se zobrazí jen pokud toto datum spadá do zvoleného okna dní."
                ),
            }

        parsed_dates: list[date] = []
        errors = []
        for idx, row in enumerate(rows, start=2):
            d, spend, err = self._parse_google_row(row, header_map, idx)
            if d is not None:
                parsed_dates.append(d)
            if err:
                errors.append({"row": idx, "reason": err})
        status = "ok" if len(errors) == 0 and parsed_dates else ("partial" if parsed_dates else "invalid")
        preview_rows = []
        for i, row in enumerate(rows[:8]):
            idx = 2 + i
            d, spend, err = self._parse_google_row(row, header_map, idx)
            preview_rows.append(
                {
                    "row": idx,
                    "parsed_date": d.isoformat() if d else None,
                    "parsed_spend": spend,
                    "ok": err is None and d is not None and spend is not None,
                    "error": err,
                }
            )
        return {
            "source": "google",
            "detected_file_type": "google_daily_rows",
            "detected_file_type_label_cs": "Google Ads — denní řádky (datum + Cost/Cena)",
            "row_count": len(rows),
            "period": self._period_from_dates(parsed_dates),
            "key_fields": self._key_fields_google(header_map, variant=variant),
            "headers": headers,
            "validation_status": status,
            "validation_errors_sample": errors[:12],
            "preview_rows": preview_rows,
            "period_alignment_note_cs": (
                "Do přehledu kanálů se započítají jen řádky, jejichž datum spadá do zvoleného okna dní."
            ),
        }

    def import_google_csv_bytes(self, raw: bytes, client_id: int) -> dict[str, Any]:
        cid = require_positive_client_id(client_id)
        content = self._decode_raw(raw)
        try:
            rows, headers, header_map, report_end = self._load_google_cz_campaign_table(content)
            variant = "google_cz_campaign_period"
        except ValidationError:
            rows, headers, header_map = self._load_csv_table(content)
            self._classify_google_format(header_map, headers)
            variant = "google_daily"
            report_end = None

        if variant == "google_cz_campaign_period" and report_end is not None:
            total_spend = 0.0
            errors: list[dict[str, Any]] = []
            detail_rows = 0
            for idx, row in enumerate(rows, start=2):
                spend, err, skip = self._parse_google_cz_row(row, header_map, idx)
                if skip == "total_row":
                    continue
                if err:
                    errors.append({"row": idx, "reason": err, "data": row})
                    continue
                if spend is not None:
                    total_spend += spend
                    detail_rows += 1
            if total_spend <= 0:
                return {
                    "source": "google",
                    "imported_metrics": 0,
                    "aggregated_days": 0,
                    "source_row_count": 0,
                    "skipped_rows": len(errors),
                    "errors": errors[:50],
                    "detected_file_type": "google_cz_campaign_period",
                    "period": None,
                    "validation_status": "invalid",
                }
            session = self.metric_repo.session
            try:
                self._replace_platform_metrics(cid, PLATFORM_CSV_GOOGLE_ADS)
                camp = self._get_bucket_campaign(cid, BUCKET_GOOGLE, PLATFORM_CSV_GOOGLE_ADS)
                to_create = [
                    CampaignMetric(
                        campaign_id=int(camp.id),
                        metric_date=report_end,
                        revenue=0.0,
                        spend=float(total_spend),
                        clicks=0,
                        conversions=0,
                    )
                ]
                n = self.metric_repo.bulk_create_for_client(cid, to_create)
            except Exception:
                session.rollback()
                raise
            payload = {
                "source": "google",
                "imported_metrics": n,
                "aggregated_days": 1,
                "source_row_count": detail_rows,
                "skipped_rows": len(errors),
                "errors": errors[:50],
                "detected_file_type": "google_cz_campaign_period",
                "period": {"date_min": report_end.isoformat(), "date_max": report_end.isoformat()},
                "report_booking_date": report_end.isoformat(),
                "validation_status": "ok" if not errors else "partial",
            }
            return self._attach_channel_overview_follow_up(
                payload,
                date_min=report_end,
                date_max=report_end,
                detected_file_type="google_cz_campaign_period",
            )

        by_day: dict[date, float] = defaultdict(float)
        errors = []
        for idx, row in enumerate(rows, start=2):
            d, spend, err = self._parse_google_row(row, header_map, idx)
            if err or d is None or spend is None:
                errors.append({"row": idx, "reason": err or "Chyba řádku.", "data": row})
                continue
            by_day[d] += float(spend)

        if not by_day:
            return {
                "source": "google",
                "imported_metrics": 0,
                "aggregated_days": 0,
                "source_row_count": 0,
                "skipped_rows": len(errors),
                "errors": errors[:50],
                "detected_file_type": "google_daily_rows",
                "period": None,
                "validation_status": "invalid",
            }

        session = self.metric_repo.session
        try:
            self._replace_platform_metrics(cid, PLATFORM_CSV_GOOGLE_ADS)
            camp = self._get_bucket_campaign(cid, BUCKET_GOOGLE, PLATFORM_CSV_GOOGLE_ADS)
            to_create = [
                CampaignMetric(
                    campaign_id=int(camp.id),
                    metric_date=d,
                    revenue=0.0,
                    spend=float(spend),
                    clicks=0,
                    conversions=0,
                )
                for d, spend in sorted(by_day.items())
            ]
            n = self.metric_repo.bulk_create_for_client(cid, to_create) if to_create else 0
        except Exception:
            session.rollback()
            raise

        dates = list(by_day.keys())
        d_mi, d_ma = min(dates), max(dates)
        payload = {
            "source": "google",
            "imported_metrics": n,
            "aggregated_days": len(by_day),
            "source_row_count": len(rows) - len(errors),
            "skipped_rows": len(errors),
            "errors": errors[:50],
            "detected_file_type": "google_daily_rows",
            "period": self._period_from_dates(dates),
            "validation_status": "ok" if not errors and dates else ("partial" if dates else "invalid"),
        }
        return self._attach_channel_overview_follow_up(
            payload,
            date_min=d_mi,
            date_max=d_ma,
            detected_file_type="google_daily_rows",
        )
