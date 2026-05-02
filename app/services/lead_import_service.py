"""Admin-only CSV import for Lead OS (no external I/O beyond caller-provided text)."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlmodel import Session, select

from app.models.db_models import Lead, LeadInteraction, utcnow

try:
    import tzdata  # noqa: F401
except ImportError:
    pass

from zoneinfo import ZoneInfo

PRAGUE = ZoneInfo("Europe/Prague")

MAX_CSV_BYTES = 2 * 1024 * 1024  # 2 MiB

LEADS_REQUIRED_COLUMNS = frozenset(
    {
        "company_name",
        "website",
        "contact_name",
        "contact_email",
        "contact_linkedin",
        "role",
        "source",
        "status",
        "signal_strength",
        "decision_level",
        "source_of_truth",
        "last_contacted_at",
        "next_follow_up_at",
        "next_action",
        "notes",
    }
)

INTERACTIONS_REQUIRED_COLUMNS = frozenset(
    {
        "company_name",
        "channel",
        "direction",
        "message_summary",
        "created_at",
    }
)

_WS_RE = re.compile(r"\s+")


def _norm_company(value: str) -> str:
    return _WS_RE.sub(" ", (value or "").strip().lower())


def _norm_person(value: str) -> str:
    return _norm_company(value)


def _strip_row(row: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in row.items():
        key = (k or "").strip()
        out[key] = v if v is None else str(v).strip()
    return out


def _cell(row: dict[str, str], name: str) -> str:
    return (row.get(name) or "").strip()


def _opt_truncate(value: str, max_len: int) -> str | None:
    v = value.strip()
    if not v:
        return None
    return v[:max_len]


def _parse_next_follow_up(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    return date.fromisoformat(s)


def _parse_last_contacted(s: str) -> datetime | None:
    """ISO date or datetime; blank → None. Naive datetime interpreted as Europe/Prague (same as manual form)."""
    s = (s or "").strip()
    if not s:
        return None
    if "T" in s or re.search(r"\d{4}-\d{2}-\d{2} \d", s):
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=PRAGUE).astimezone(timezone.utc)
        return dt.astimezone(timezone.utc)
    d = date.fromisoformat(s)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _parse_ix_created(s: str) -> datetime:
    s = (s or "").strip()
    if not s:
        return utcnow()
    if "T" in s or re.search(r"\d{4}-\d{2}-\d{2} \d", s):
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    d = date.fromisoformat(s)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _reload_leads(session: Session) -> list[Lead]:
    return list(session.exec(select(Lead).order_by(Lead.id.asc())))  # type: ignore[arg-type]


def _find_existing_lead(
    all_leads: list[Lead],
    *,
    company_name_csv: str,
    contact_email_csv: str,
    contact_name_csv: str,
) -> tuple[Lead | None, str | None]:
    """Return (lead, error). error set if ambiguous no-email / no-name match."""
    nc = _norm_company(company_name_csv)
    em = contact_email_csv.strip().lower()
    cn = _norm_person(contact_name_csv)

    if em:
        matches = [
            L
            for L in all_leads
            if _norm_company(L.company_name) == nc
            and (L.contact_email or "").strip().lower() == em
        ]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return matches[0], "více shod company+email — použit nejnižší id"
        return None, None

    if cn:
        matches = [
            L
            for L in all_leads
            if _norm_company(L.company_name) == nc and _norm_person(L.contact_name or "") == cn
        ]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return matches[0], "více shod company+jméno — použit nejnižší id"
        return None, None

    matches = [L for L in all_leads if _norm_company(L.company_name) == nc]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, "prázdný e-mail i jméno — firma není jednoznačná"
    return None, None


def _merge_lead_from_row(lead: Lead, row: dict[str, str]) -> None:
    """Fill non-empty CSV cells into an existing lead (blank CSV cell leaves DB value)."""
    v = _cell(row, "company_name")
    if v:
        lead.company_name = v[:512]
    if _cell(row, "website"):
        lead.website = _cell(row, "website")[:512]
    if _cell(row, "contact_name"):
        lead.contact_name = _cell(row, "contact_name")[:255]
    if _cell(row, "contact_email"):
        lead.contact_email = _cell(row, "contact_email")[:255]
    if _cell(row, "contact_linkedin"):
        lead.contact_linkedin = _cell(row, "contact_linkedin")[:512]
    if _cell(row, "role"):
        lead.role = _cell(row, "role")[:255]
    if _cell(row, "source"):
        lead.source = _cell(row, "source")[:255]
    if _cell(row, "status"):
        lead.status = _cell(row, "status")[:64] or lead.status
    if _cell(row, "signal_strength"):
        lead.signal_strength = _cell(row, "signal_strength")[:32] or lead.signal_strength
    if _cell(row, "decision_level"):
        lead.decision_level = _cell(row, "decision_level")[:64]
    if _cell(row, "source_of_truth"):
        lead.source_of_truth = _cell(row, "source_of_truth")[:64]
    if _cell(row, "last_contacted_at"):
        lead.last_contacted_at = _parse_last_contacted(_cell(row, "last_contacted_at"))
    if _cell(row, "next_follow_up_at"):
        lead.next_follow_up_at = _parse_next_follow_up(_cell(row, "next_follow_up_at"))
    if _cell(row, "next_action"):
        lead.next_action = _cell(row, "next_action")[:512]
    if _cell(row, "notes"):
        lead.notes = _cell(row, "notes")


def _new_lead_from_row(row: dict[str, str]) -> Lead:
    now = utcnow()
    return Lead(
        company_name=_cell(row, "company_name")[:512],
        website=_opt_truncate(_cell(row, "website"), 512),
        contact_name=_opt_truncate(_cell(row, "contact_name"), 255),
        contact_email=_opt_truncate(_cell(row, "contact_email"), 255),
        contact_linkedin=_opt_truncate(_cell(row, "contact_linkedin"), 512),
        role=_opt_truncate(_cell(row, "role"), 255),
        source=_opt_truncate(_cell(row, "source"), 255),
        status=(_cell(row, "status")[:64] if _cell(row, "status") else "new") or "new",
        signal_strength=(
            _cell(row, "signal_strength")[:32] if _cell(row, "signal_strength") else "weak"
        )
        or "weak",
        decision_level=_opt_truncate(_cell(row, "decision_level"), 64),
        source_of_truth=_opt_truncate(_cell(row, "source_of_truth"), 64),
        last_contacted_at=_parse_last_contacted(_cell(row, "last_contacted_at")),
        next_follow_up_at=_parse_next_follow_up(_cell(row, "next_follow_up_at")),
        next_action=_opt_truncate(_cell(row, "next_action"), 512),
        notes=(_cell(row, "notes") or None),
        created_at=now,
        updated_at=now,
    )


def _find_lead_for_interaction(all_leads: list[Lead], company_name: str) -> tuple[Lead | None, str | None]:
    nc = _norm_company(company_name)
    matches = [L for L in all_leads if _norm_company(L.company_name) == nc]
    if not matches:
        return None, None
    lead = min(matches, key=lambda L: L.id or 0)
    warn = None
    if len(matches) > 1:
        warn = f"více leadů se shodnou firmou — použit id={lead.id}"
    return lead, warn


@dataclass
class CsvImportResult:
    leads_created: int = 0
    leads_updated: int = 0
    leads_skipped_blank: int = 0
    interactions_created: int = 0
    interactions_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _validate_headers(fieldnames: list[str] | None, required: frozenset[str], label: str) -> str | None:
    if not fieldnames:
        return f"{label}: chybí hlavička"
    keys = {str(h or "").strip() for h in fieldnames}
    missing = required - keys
    if missing:
        return f"{label}: chybí sloupce: {', '.join(sorted(missing))}"
    return None


def import_lead_os_csvs(
    session: Session,
    *,
    leads_csv_text: str,
    interactions_csv_text: str | None,
) -> CsvImportResult:
    """Import leads then optional interactions. Per-row rollback on failure; continues with summary."""
    result = CsvImportResult()
    leads_buf = io.StringIO(leads_csv_text)
    reader = csv.DictReader(leads_buf)
    hdr_err = _validate_headers(reader.fieldnames, LEADS_REQUIRED_COLUMNS, "Leady CSV")
    if hdr_err:
        result.errors.append(hdr_err)
        return result

    assert reader.fieldnames is not None

    all_leads = _reload_leads(session)

    row_num = 1
    for raw in reader:
        row_num += 1
        row = _strip_row(raw)
        if not any(row.values()):
            continue
        company = _cell(row, "company_name")
        if not company:
            result.leads_skipped_blank += 1
            result.errors.append(f"Lead řádek {row_num}: prázdná firma — přeskočeno")
            continue

        try:
            email = _cell(row, "contact_email")
            contact_name = _cell(row, "contact_name")
            existing, amb = _find_existing_lead(
                all_leads,
                company_name_csv=company,
                contact_email_csv=email,
                contact_name_csv=contact_name,
            )

            if amb and existing is None:
                result.leads_skipped_blank += 1
                result.errors.append(f"Lead řádek {row_num}: {amb}")
                continue

            if existing is None:
                lead = _new_lead_from_row(row)
                session.add(lead)
                session.commit()
                session.refresh(lead)
                all_leads.append(lead)
                result.leads_created += 1
            else:
                if amb:
                    result.errors.append(f"Lead řádek {row_num}: {amb}")
                _merge_lead_from_row(existing, row)
                existing.updated_at = utcnow()
                session.add(existing)
                session.commit()
                session.refresh(existing)
                result.leads_updated += 1
        except Exception as e:  # noqa: BLE001 — row-level resilience
            session.rollback()
            result.errors.append(f"Lead řádek {row_num}: {e}")

    if interactions_csv_text and interactions_csv_text.strip():
        ix_buf = io.StringIO(interactions_csv_text)
        ix_reader = csv.DictReader(ix_buf)
        ix_hdr = _validate_headers(ix_reader.fieldnames, INTERACTIONS_REQUIRED_COLUMNS, "Interakce CSV")
        if ix_hdr:
            result.errors.append(ix_hdr)
            return result

        all_leads = _reload_leads(session)
        ix_num = 1
        for raw in ix_reader:
            ix_num += 1
            row = _strip_row(raw)
            if not any(row.values()):
                continue
            company = _cell(row, "company_name")
            if not company:
                result.interactions_skipped += 1
                result.errors.append(f"Interakce řádek {ix_num}: prázdná firma — přeskočeno")
                continue
            summary = _cell(row, "message_summary")
            if not summary:
                result.interactions_skipped += 1
                result.errors.append(f"Interakce řádek {ix_num}: prázdné message_summary — přeskočeno")
                continue
            try:
                lead, warn = _find_lead_for_interaction(all_leads, company)
                if warn:
                    result.errors.append(f"Interakce řádek {ix_num}: {warn}")
                if lead is None:
                    result.interactions_skipped += 1
                    result.errors.append(
                        f"Interakce řádek {ix_num}: firma «{company}» nenalezena — přeskočeno"
                    )
                    continue
                ch = (_cell(row, "channel") or "email")[:32]
                dire = (_cell(row, "direction") or "note")[:32]
                created = _parse_ix_created(_cell(row, "created_at"))
                ix_row = LeadInteraction(
                    lead_id=lead.id,  # type: ignore[arg-type]
                    channel=ch or "email",
                    direction=dire or "note",
                    message_summary=summary[:16000],
                    created_at=created,
                )
                session.add(ix_row)
                lead.updated_at = utcnow()
                session.add(lead)
                session.commit()
                result.interactions_created += 1
            except Exception as e:  # noqa: BLE001
                session.rollback()
                result.errors.append(f"Interakce řádek {ix_num}: {e}")

    return result
