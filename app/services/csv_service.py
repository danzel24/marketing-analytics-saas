from __future__ import annotations

import csv
import re
from datetime import date, datetime
from io import StringIO
import logging
import unicodedata

from sqlalchemy.exc import IntegrityError

from app.core.domain_errors import InvalidOperationError, ValidationError
from app.core.error_codes import ErrorCode
from app.models.db_models import Campaign, CampaignMetric
from app.repositories.campaign_metric_repository import CampaignMetricRepository
from app.repositories.campaign_repository_sql import CampaignRepository
from app.repositories.tenant_scope import require_positive_client_id

DEFAULT_IMPORT_CAMPAIGN_NAME = "Imported Data"
# API body must send this exact string in ``confirm`` to clear CSV-imported rows.
CLEAR_IMPORTED_CONFIRMATION = "DELETE_IMPORTED_DATA"

logger = logging.getLogger(__name__)
MAX_CSV_UPLOAD_BYTES = 15 * 1024 * 1024


class CSVService:
    def __init__(
        self,
        campaign_repo: CampaignRepository,
        metric_repo: CampaignMetricRepository,
    ) -> None:
        self.campaign_repo = campaign_repo
        self.metric_repo = metric_repo

    @staticmethod
    def _require_tenant_client_id(client_id: int) -> int:
        return require_positive_client_id(client_id)

    def clear_imported_data_for_client(self, client_id: int, confirmation: str | None) -> dict[str, int]:
        """
        Remove all CSV-imported campaigns and their metrics for ``client_id``.

        Only rows with ``Campaign.platform == \"imported\"`` are removed (integration campaigns untouched).
        Users and Client row are never deleted.
        """
        cid = self._require_tenant_client_id(client_id)
        if (confirmation or "").strip() != CLEAR_IMPORTED_CONFIRMATION:
            raise InvalidOperationError(
                "Pro smazání importovaných dat odešlete v těle požadavku pole "
                f'"confirm": "{CLEAR_IMPORTED_CONFIRMATION}".',
                code=ErrorCode.INVALID_CONFIRMATION,
            )
        # Single transaction: both repos must share the same Session (FastAPI get_session).
        session = self.metric_repo.session
        try:
            metrics_deleted = self.metric_repo.delete_metrics_for_imported_campaigns(cid, commit=False)
            campaigns_deleted = self.campaign_repo.delete_imported_campaigns_for_client(cid, commit=False)
            session.commit()
        except Exception:
            session.rollback()
            raise
        logger.info(
            "imported_data_cleared client_id=%s metrics_deleted=%s campaigns_deleted=%s",
            cid,
            metrics_deleted,
            campaigns_deleted,
        )
        return {
            "metrics_deleted": metrics_deleted,
            "campaigns_deleted": campaigns_deleted,
        }

    def import_revenue_csv_bytes(self, raw: bytes, client_id: int) -> dict[str, int | str | list[dict[str, object]]]:
        if not isinstance(raw, (bytes, bytearray)):
            raise ValidationError("Soubor není načten.", code=ErrorCode.CSV_NOT_LOADED)
        if len(raw) > MAX_CSV_UPLOAD_BYTES:
            raise ValidationError("CSV je příliš velké (max. 15 MB).", code=ErrorCode.CSV_TOO_LARGE)
        try:
            content_str = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValidationError("CSV musí být v kódování UTF-8.", code=ErrorCode.CSV_ENCODING) from exc
        return self.import_revenue_csv(content_str, client_id)

    def import_revenue_csv(self, content: str, client_id: int) -> dict[str, int | str | list[dict[str, object]]]:
        self._require_tenant_client_id(client_id)
        raw_lines = content.splitlines()
        header_line = next(
            (
                line
                for line in raw_lines
                if line.strip() and not all(c in ";, \t" for c in line)
            ),
            "",
        )
        if not header_line:
            raise ValidationError("CSV je prázdné nebo neobsahuje hlavičku.", code=ErrorCode.CSV_HEADER_MISSING)

        delimiter = ","
        if header_line.count(";") > header_line.count(","):
            delimiter = ";"
        elif "\t" in header_line:
            delimiter = "\t"

        cleaned_lines: list[str] = []
        for line in raw_lines:
            stripped = line.strip()
            if not stripped:
                continue
            if all(c in ";, \t" for c in stripped):
                continue
            cleaned_lines.append(stripped)

        if not cleaned_lines:
            raise ValidationError("CSV neobsahuje žádná data.", code=ErrorCode.CSV_NO_DATA)

        reader = csv.DictReader(StringIO("\n".join(cleaned_lines)), delimiter=delimiter)
        rows = list(reader)
        headers = reader.fieldnames or []
        if not headers:
            raise ValidationError("CSV je prázdné nebo neobsahuje hlavičku.", code=ErrorCode.CSV_HEADER_MISSING)

        normalized_headers = [self._normalize_header(h) for h in headers]
        normalized_set = set(normalized_headers)
        header_map = {self._normalize_header(h): h for h in headers}
        detected_format = self._detect_format(normalized_set, header_map)

        normalized_rows: list[dict[str, object]] = []
        errors: list[dict[str, object]] = []
        skipped = 0

        for index, row in enumerate(rows, start=2):
            parsed, reason = self._parse_row(
                row=row,
                fmt=detected_format,
                header_map=header_map,
                client_id=client_id,
                row_index=index,
            )
            if parsed is None:
                skipped += 1
                errors.append(
                    {
                        "row": index,
                        "reason": reason or "Nevalidní řádek nebo nepodporovaný formát hodnot.",
                        "data": row,
                    }
                )
                continue
            if index <= 5:
                logger.info(
                    "CSV parsed row %s: revenue=%r spend=%r",
                    index,
                    parsed.get("revenue"),
                    parsed.get("spend"),
                )
            normalized_rows.append(parsed)

        if normalized_rows and sum(float(r.get("spend") or 0) for r in normalized_rows) == 0:
            logger.warning(
                "CSV import: všechny řádky mají náklady 0 — zkontrolujte sloupec spend / cost / ad_spend "
                "(hlavičky: %s)",
                list(header_map.values()),
            )

        imported, updated = self._upsert_normalized_rows(normalized_rows, client_id=client_id, errors=errors)
        skipped += max(0, len(normalized_rows) - imported - updated)
        logger.info("CSV import: %s imported, %s updated, %s skipped", imported, updated, skipped)
        response_format = "custom" if detected_format.startswith("custom") else detected_format
        distinct_campaign_ids = {
            int(r["campaign_id"])
            for r in normalized_rows
            if isinstance(r.get("campaign_id"), int)
        }
        return {
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
            "campaigns_in_import": len(distinct_campaign_ids),
            "errors": errors,
            "detected_format": response_format,
        }

    def _upsert_normalized_rows(
        self,
        rows: list[dict[str, object]],
        *,
        client_id: int,
        errors: list[dict[str, object]],
    ) -> tuple[int, int]:
        imported = 0
        updated = 0
        to_create: list[CampaignMetric] = []
        to_update: list[CampaignMetric] = []

        for index, row in enumerate(rows, start=2):
            metric_date = row["date"]
            revenue = row["revenue"]
            spend = row["spend"]
            campaign_id = row["campaign_id"]

            if not isinstance(metric_date, date) or not isinstance(campaign_id, int):
                errors.append({"row": index, "reason": "Nevalidní normalizovaná data.", "data": row})
                continue

            campaign = self.campaign_repo.get_by_id_for_client(campaign_id, client_id)
            if campaign is None:
                errors.append({"row": index, "reason": "Kampaň nepatří aktuálnímu klientovi.", "data": row})
                continue

            existing_metric = self.metric_repo.get_by_campaign_and_date_for_client(
                client_id, campaign_id, metric_date
            )
            if existing_metric:
                existing_metric.revenue = float(revenue)
                existing_metric.spend = float(spend)
                to_update.append(existing_metric)
                continue

            to_create.append(
                CampaignMetric(
                    campaign_id=campaign_id,
                    metric_date=metric_date,
                    revenue=float(revenue),
                    spend=float(spend),
                    clicks=0,
                    conversions=0,
                )
            )

        updated += self.metric_repo.save_many_for_client(client_id, to_update)
        try:
            imported += self.metric_repo.bulk_create_for_client(client_id, to_create)
        except IntegrityError:
            self.metric_repo.session.rollback()
            logger.warning(
                "CSV bulk_create hit integrity constraint (possible duplicate campaign_id+date); retrying row-wise",
            )
            imported += self._bulk_create_metrics_fallback(to_create, client_id=client_id)
        return imported, updated

    def _bulk_create_metrics_fallback(
        self,
        metrics: list[CampaignMetric],
        *,
        client_id: int,
    ) -> int:
        """If a unique index exists, concurrent CSV imports may collide — upsert individually."""
        n = 0
        for m in metrics:
            campaign = self.campaign_repo.get_by_id_for_client(int(m.campaign_id), client_id)
            if campaign is None:
                continue
            existing = self.metric_repo.get_by_campaign_and_date_for_client(
                client_id, int(m.campaign_id), m.metric_date
            )
            if existing:
                existing.revenue = float(m.revenue)
                existing.spend = float(m.spend)
                self.metric_repo.save_for_client(client_id, existing)
                n += 1
            else:
                fresh = CampaignMetric(
                    campaign_id=int(m.campaign_id),
                    metric_date=m.metric_date,
                    revenue=float(m.revenue),
                    spend=float(m.spend),
                    clicks=int(m.clicks or 0),
                    conversions=int(m.conversions or 0),
                )
                try:
                    self.metric_repo.create_for_client(client_id, fresh)
                    n += 1
                except IntegrityError:
                    self.metric_repo.session.rollback()
                    again = self.metric_repo.get_by_campaign_and_date_for_client(
                        client_id, int(m.campaign_id), m.metric_date
                    )
                    if again:
                        again.revenue = float(m.revenue)
                        again.spend = float(m.spend)
                        self.metric_repo.save_for_client(client_id, again)
                        n += 1
                    else:
                        logger.warning(
                            "CSV metric insert failed after integrity error campaign_id=%s date=%s",
                            m.campaign_id,
                            m.metric_date,
                        )
        return n

    def _spend_column_original(self, header_map: dict[str, str]) -> str | None:
        """Resolve CSV column for ad spend (stored as ``CampaignMetric.spend``)."""
        return self._find_header(
            header_map,
            [
                "spend",
                "cost",
                "ad spend",
                "ad_spend",
                "ad cost",
                "amount spent",
                "advertising spend",
                "total spend",
                "marketing spend",
            ],
        )

    def _parse_spend_value(self, spend_raw: str, *, row_index: int = 0) -> tuple[float | None, str | None]:
        """Parse spend/cost cell; None spend means invalid number (not missing column)."""
        raw = (spend_raw or "").strip()
        if not raw:
            return 0.0, None
        parsed = self.parse_currency(raw)
        if parsed is None:
            logger.warning("CSV row %s: spend/cost hodnota nejde parsovat: %r", row_index, spend_raw)
            return None, "Neplatná hodnota nákladů (spend/cost)."
        return float(parsed), None

    def _parse_row(
        self,
        *,
        row: dict[str, str],
        fmt: str,
        header_map: dict[str, str],
        client_id: int,
        row_index: int = 0,
    ) -> tuple[dict[str, object] | None, str | None]:
        if fmt == "custom_id":
            date_raw = self._cell(row, header_map.get("date"))
            campaign_id_raw = self._cell(row, header_map.get("campaign id"))
            revenue_raw = self._cell(row, header_map.get("revenue"))
            spend_col = self._spend_column_original(header_map)
            spend_raw = self._cell(row, spend_col)

            metric_date = self._parse_date(date_raw)
            revenue = self.parse_currency(revenue_raw)
            spend, spend_err = self._parse_spend_value(spend_raw, row_index=row_index)
            campaign_id, reason = self._resolve_campaign_id(campaign_id_raw, client_id)
            if metric_date is None:
                return None, "Neplatné datum."
            if revenue is None:
                return None, "Neplatná hodnota revenue."
            if spend_err:
                return None, spend_err
            if spend is None:
                return None, "Neplatná hodnota nákladů."
            if campaign_id is None:
                return None, reason or "Neplatné campaign_id."
            return {"date": metric_date, "campaign_id": campaign_id, "revenue": revenue, "spend": spend}, None

        if fmt == "custom_name":
            date_raw = self._cell(row, header_map.get("date"))
            campaign_name = self._cell(row, header_map.get("campaign"))
            revenue_raw = self._cell(row, header_map.get("revenue"))
            spend_col = self._spend_column_original(header_map)
            spend_raw = self._cell(row, spend_col)

            metric_date = self._parse_date(date_raw)
            revenue = self.parse_currency(revenue_raw)
            spend, spend_err = self._parse_spend_value(spend_raw, row_index=row_index)
            campaign_id = self._resolve_campaign_by_name(campaign_name, client_id)
            if metric_date is None:
                return None, "Neplatné datum."
            if revenue is None:
                return None, "Neplatná hodnota revenue."
            if spend_err:
                return None, spend_err
            if spend is None:
                return None, "Neplatná hodnota nákladů."
            if campaign_id is None:
                return None, "Nepodařilo se určit kampaň."
            return {"date": metric_date, "campaign_id": campaign_id, "revenue": revenue, "spend": spend}, None

        if fmt == "shopify":
            created_at = self._cell(row, self._find_header(header_map, ["created at"]))
            total_raw = self._cell(row, self._find_header(header_map, ["total", "subtotal"]))
            metric_date = self._parse_shopify_date(created_at)
            revenue = self.parse_currency(total_raw)
            default_campaign = self.get_or_create_default_campaign(client_id)
            campaign_id = default_campaign.id
            if metric_date is None:
                return None, "Neplatné datum Shopify."
            if revenue is None:
                return None, "Neplatná hodnota revenue (Shopify)."
            if campaign_id is None:
                return None, "Nepodařilo se vytvořit výchozí kampaň."
            return {"date": metric_date, "campaign_id": campaign_id, "revenue": revenue, "spend": 0.0}, None

        if fmt == "shoptet":
            date_raw = self._cell(row, self._find_header(header_map, ["datum"]))
            revenue_raw = self._cell(row, self._find_header(header_map, ["trzba", "tržba", "cena celkem"]))
            metric_date = self._parse_date(date_raw)
            revenue = self.parse_currency(revenue_raw)
            default_campaign = self.get_or_create_default_campaign(client_id)
            campaign_id = default_campaign.id
            if metric_date is None:
                return None, "Neplatné datum Shoptet."
            if revenue is None:
                return None, "Neplatná hodnota revenue (Shoptet)."
            if campaign_id is None:
                return None, "Nepodařilo se vytvořit výchozí kampaň."
            return {"date": metric_date, "campaign_id": campaign_id, "revenue": revenue, "spend": 0.0}, None

        return None, "Nepodporovaný formát."

    def _detect_format(self, normalized_set: set[str], header_map: dict[str, str]) -> str:
        if {"date", "campaign id", "revenue"}.issubset(normalized_set):
            return "custom_id"
        if {"date", "campaign", "revenue"}.issubset(normalized_set):
            return "custom_name"

        shopify_created = self._find_header(header_map, ["created at"])
        shopify_total = self._find_header(header_map, ["total", "subtotal"])
        if shopify_created and shopify_total:
            return "shopify"

        shoptet_date = self._find_header(header_map, ["datum"])
        shoptet_revenue = self._find_header(header_map, ["trzba", "tržba", "cena celkem"])
        if shoptet_date and shoptet_revenue:
            return "shoptet"

        raise ValidationError("Nepodporovaný CSV formát.", code=ErrorCode.CSV_UNSUPPORTED_FORMAT)

    def _resolve_campaign_by_name(self, name: str, client_id: int) -> int | None:
        campaign_name = (name or "").strip()
        if not campaign_name:
            default_campaign = self.get_or_create_default_campaign(client_id)
            return default_campaign.id

        existing = self.campaign_repo.get_by_name_and_platform(client_id, campaign_name, "imported")
        if existing:
            return existing.id

        return self._create_named_import_campaign_or_get_existing(campaign_name, client_id)

    def _create_named_import_campaign_or_get_existing(self, campaign_name: str, client_id: int) -> int | None:
        """
        Create a tenant-scoped campaign for CSV import, or return existing on race / duplicate.

        Uses platform ``imported``; never assigns rows to another client's campaigns.
        """
        cid = self._require_tenant_client_id(client_id)
        try:
            created = self.campaign_repo.create_for_client(
                cid,
                Campaign(
                    name=campaign_name,
                    platform="imported",
                    client_id=cid,
                ),
            )
            return created.id
        except IntegrityError:
            self.campaign_repo.session.rollback()
            again = self.campaign_repo.get_by_name_and_platform(cid, campaign_name, "imported")
            if again is not None:
                return again.id
            logger.exception(
                "CSV campaign create failed with IntegrityError and no matching row after rollback name=%r client_id=%s",
                campaign_name,
                cid,
            )
            return None

    def _resolve_campaign_id(self, campaign_id_raw: str | None, client_id: int) -> tuple[int | None, str | None]:
        campaign_id = None
        if campaign_id_raw:
            try:
                campaign_id = int(campaign_id_raw)
            except ValueError:
                return None, "campaign_id není číslo."
            campaign = self.campaign_repo.get_by_id_for_client(campaign_id, client_id)
            if campaign is None:
                return None, "Kampaň nepatří klientovi nebo neexistuje."
            return campaign_id, None

        default_campaign = self.get_or_create_default_campaign(client_id)
        return default_campaign.id, None

    def get_or_create_default_campaign(self, client_id: int) -> Campaign:
        campaign = self.campaign_repo.get_by_name_and_platform(
            client_id, DEFAULT_IMPORT_CAMPAIGN_NAME, "imported"
        )
        if campaign:
            return campaign
        return self.campaign_repo.create_for_client(
            client_id,
            Campaign(
                name=DEFAULT_IMPORT_CAMPAIGN_NAME,
                platform="imported",
                client_id=client_id,
            ),
        )

    @staticmethod
    def _normalize_header(h: str) -> str:
        normalized = str(h).replace("\ufeff", "").strip().lower().replace("_", " ")
        normalized = " ".join(normalized.split())
        normalized = unicodedata.normalize("NFKD", normalized)
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return normalized

    def _find_header(self, mapped_headers: dict[str, str], aliases: list[str]) -> str | None:
        normalized_aliases = [self._normalize_header(a) for a in aliases]
        for alias in normalized_aliases:
            if alias in mapped_headers:
                return mapped_headers[alias]
        for key in mapped_headers:
            if "lineitem" in key:
                continue
            for alias in normalized_aliases:
                if alias in key:
                    return mapped_headers[key]
        return None

    @staticmethod
    def _cell(row: dict[str, str], key: str | None) -> str:
        if not key:
            return ""
        return str(row.get(key) or "").strip()

    @staticmethod
    def _parse_shopify_date(created_at_raw: str) -> date | None:
        try:
            # Example: 2026-03-01T10:15:00+00:00
            return datetime.fromisoformat(created_at_raw).date()
        except ValueError:
            # Fallback for non-standard timezone formats.
            try:
                return datetime.strptime(created_at_raw[:10], "%Y-%m-%d").date()
            except ValueError:
                return None

    @staticmethod
    def _parse_date(value: str) -> date | None:
        raw = (value or "").strip()
        if not raw:
            return None
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(raw).date()
        except ValueError:
            pass
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

    @staticmethod
    def parse_currency(value: str | None) -> float | None:
        if value is None:
            return None

        normalized = value.replace("\u00a0", " ").strip()
        if not normalized:
            return 0.0

        # Strip common currency tokens (avoid silent parse failures on e.g. "1 234 Kč")
        normalized = re.sub(
            r"(?i)\s*(kč|czk|eur|€|usd|\$)\s*$",
            "",
            normalized,
        ).strip()
        normalized = re.sub(r"(?i)^\s*(€|\$)\s*", "", normalized).strip()

        normalized = normalized.replace(" ", "").replace("\t", "")

        if "," in normalized and "." in normalized:
            if normalized.find(",") < normalized.find("."):
                # 1,234.56 -> remove thousands comma
                normalized = normalized.replace(",", "")
            else:
                # 1.234,56 -> remove thousands dot and normalize decimal comma
                normalized = normalized.replace(".", "").replace(",", ".")
        else:
            # 1234,56 -> normalize decimal comma
            normalized = normalized.replace(",", ".")

        try:
            return float(normalized)
        except ValueError:
            return None
