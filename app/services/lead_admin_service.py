from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

try:
    import tzdata  # noqa: F401 — Windows / minimal builds need IANA data from PyPI
except ImportError:
    pass

from sqlalchemy import case, or_
from sqlmodel import Session, select

from app.core.domain_errors import NotFoundError
from app.models.db_models import Lead, LeadInteraction, utcnow

PRAGUE = ZoneInfo("Europe/Prague")

STATUS_CLOSED_NO = "closed_no"
STATUS_WARM_NOT_NOW = "warm_not_now"

_VALID_FOLLOWUP_FILTERS = frozenset({"all", "today", "overdue", "due", "none"})


def today_prague() -> date:
    return datetime.now(PRAGUE).date()


class LeadAdminService:
    """Admin Lead OS persistence (SQLite + PostgreSQL)."""

    def get_lead_or_404(self, session: Session, lead_id: int) -> Lead:
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise NotFoundError("Lead nenalezen")
        return lead

    def list_interactions(self, session: Session, lead_id: int) -> list[LeadInteraction]:
        stmt = (
            select(LeadInteraction)
            .where(LeadInteraction.lead_id == lead_id)
            .order_by(LeadInteraction.created_at.desc())  # type: ignore[union-attr]
        )
        return list(session.exec(stmt))

    def list_leads(
        self,
        session: Session,
        *,
        status: str | None,
        signal_strength: str | None,
        followup: str,
        q: str | None,
    ) -> list[Lead]:
        ft = followup.strip().lower() if followup else "all"
        if ft not in _VALID_FOLLOWUP_FILTERS:
            ft = "all"

        stmt = select(Lead)
        if status:
            stmt = stmt.where(Lead.status == status)
        if signal_strength:
            stmt = stmt.where(Lead.signal_strength == signal_strength)

        today = today_prague()
        if ft == "today":
            stmt = stmt.where(Lead.next_follow_up_at == today)
        elif ft == "overdue":
            stmt = stmt.where(Lead.next_follow_up_at.is_not(None)).where(Lead.next_follow_up_at < today)
        elif ft == "due":
            stmt = stmt.where(Lead.next_follow_up_at.is_not(None)).where(Lead.next_follow_up_at <= today)
        elif ft == "none":
            stmt = stmt.where(Lead.next_follow_up_at.is_(None))

        if q and q.strip():
            pat = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    Lead.company_name.ilike(pat),  # type: ignore[arg-type]
                    Lead.contact_name.ilike(pat),  # type: ignore[arg-type]
                    Lead.contact_email.ilike(pat),  # type: ignore[arg-type]
                )
            )

        stmt = stmt.order_by(
            Lead.created_at.desc(),  # type: ignore[union-attr]
        )
        return list(session.exec(stmt))

    def list_followups_today(self, session: Session) -> list[Lead]:
        today = today_prague()
        stmt = (
            select(Lead)
            .where(Lead.status != STATUS_CLOSED_NO)
            .where(
                or_(
                    Lead.status != STATUS_WARM_NOT_NOW,
                    Lead.next_follow_up_at.is_not(None),
                )
            )
            .where(Lead.next_follow_up_at.is_not(None))
            .where(Lead.next_follow_up_at <= today)
            .order_by(
                case((Lead.next_follow_up_at < today, 0), else_=1),  # type: ignore[arg-type]
                Lead.next_follow_up_at.asc(),  # type: ignore[union-attr]
            )
        )
        return list(session.exec(stmt))

    def create_lead(self, session: Session, *, data: dict[str, object]) -> Lead:
        now = utcnow()
        payload = dict(data)
        payload["created_at"] = now
        payload["updated_at"] = now
        lead = Lead.model_validate(payload)
        session.add(lead)
        session.commit()
        session.refresh(lead)
        return lead

    def update_lead(self, session: Session, lead_id: int, *, data: dict[str, object]) -> Lead:
        lead = self.get_lead_or_404(session, lead_id)
        for key, value in data.items():
            setattr(lead, key, value)
        lead.updated_at = utcnow()
        session.add(lead)
        session.commit()
        session.refresh(lead)
        return lead

    def add_interaction(
        self,
        session: Session,
        lead_id: int,
        *,
        channel: str,
        direction: str,
        message_summary: str,
    ) -> LeadInteraction:
        summary = message_summary.strip()
        if not summary:
            summary = "(prázdná poznámka)"

        lead = self.get_lead_or_404(session, lead_id)
        row = LeadInteraction(
            lead_id=lead_id,
            channel=channel,
            direction=direction,
            message_summary=summary,
        )
        session.add(row)
        lead.updated_at = utcnow()
        session.add(lead)
        session.commit()
        session.refresh(row)
        return row
