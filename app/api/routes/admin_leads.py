from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.core.deps import require_admin
from app.core.web_templates import template_response
from app.database import get_session
from app.models.db_models import User
from app.services.lead_admin_service import LeadAdminService, PRAGUE, today_prague

router = APIRouter(tags=["admin"])

SUGGESTED_STATUSES = (
    "new",
    "contacted",
    "followup_1",
    "followup_2",
    "waiting_reply",
    "replied",
    "export_requested",
    "call_scheduled",
    "warm_not_now",
    "closed_no",
    "pilot_candidate",
)
SIGNAL_STRENGTHS = ("weak", "medium", "strong")
DECISION_LEVELS = ("channel", "campaign", "product", "sku", "unknown")
SOURCE_OF_TRUTH = ("platforms", "ga4", "eshop", "manual", "looker_or_bi", "unknown")
INTERACTION_CHANNELS = ("email", "linkedin", "instagram", "phone", "call", "other")
INTERACTION_DIRECTIONS = ("outbound", "inbound", "note")


def _opt_str(s: str, *, max_len: int | None = None) -> str | None:
    v = (s or "").strip()
    if not v:
        return None
    return v[:max_len] if max_len is not None else v


def _parse_date(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    return date.fromisoformat(s)


def _parse_dt_prague_to_utc(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    naive = datetime.fromisoformat(s)
    if naive.tzinfo is None:
        return naive.replace(tzinfo=PRAGUE).astimezone(timezone.utc)
    return naive.astimezone(timezone.utc)


def _svc() -> LeadAdminService:
    return LeadAdminService()


def _utc_to_prague_datetime_local(dt: datetime | None) -> str:
    if dt is None:
        return ""
    u = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return u.astimezone(PRAGUE).strftime("%Y-%m-%dT%H:%M")


def _fmt_date_input(d: date | None) -> str:
    return d.isoformat() if d else ""


@router.get("/admin/leads", response_class=HTMLResponse)
def admin_leads_list(
    request: Request,
    session: Session = Depends(get_session),
    _current_user: User = Depends(require_admin),
    status: str | None = Query(None),
    signal_strength: str | None = Query(None),
    followup: str = Query("all"),
    q: str | None = Query(None),
) -> HTMLResponse:
    svc = _svc()
    leads = svc.list_leads(
        session,
        status=_opt_str(status or ""),
        signal_strength=_opt_str(signal_strength or ""),
        followup=followup or "all",
        q=q,
    )
    return template_response(
        request=request,
        name="admin_leads.html",
        context={
            "leads": leads,
            "filter_status": (status or "").strip(),
            "filter_signal_strength": (signal_strength or "").strip(),
            "filter_followup": (followup or "all").strip().lower() or "all",
            "filter_q": (q or "").strip(),
            "suggested_statuses": SUGGESTED_STATUSES,
            "signal_strengths": SIGNAL_STRENGTHS,
            "today_prague": today_prague(),
        },
    )


@router.get("/admin/leads/today", response_class=HTMLResponse)
def admin_leads_today(
    request: Request,
    session: Session = Depends(get_session),
    _current_user: User = Depends(require_admin),
) -> HTMLResponse:
    svc = _svc()
    leads = svc.list_followups_today(session)
    return template_response(
        request=request,
        name="admin_leads_today.html",
        context={
            "leads": leads,
            "today_prague": today_prague(),
        },
    )


@router.get("/admin/leads/new", response_class=HTMLResponse)
def admin_lead_new_get(
    request: Request,
    _current_user: User = Depends(require_admin),
) -> HTMLResponse:
    return template_response(
        request=request,
        name="admin_lead_form.html",
        context={
            "suggested_statuses": SUGGESTED_STATUSES,
            "signal_strengths": SIGNAL_STRENGTHS,
            "decision_levels": DECISION_LEVELS,
            "source_of_truth_opts": SOURCE_OF_TRUTH,
        },
    )


@router.post("/admin/leads/new")
def admin_lead_new_post(
    company_name: str = Form(...),
    website: str = Form(""),
    contact_name: str = Form(""),
    contact_email: str = Form(""),
    contact_linkedin: str = Form(""),
    role: str = Form(""),
    source: str = Form(""),
    status: str = Form("new"),
    signal_strength: str = Form("weak"),
    decision_level: str = Form(""),
    source_of_truth: str = Form(""),
    last_contacted_at: str = Form(""),
    next_follow_up_at: str = Form(""),
    next_action: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
    _current_user: User = Depends(require_admin),
) -> RedirectResponse:
    nm = company_name.strip()
    if not nm:
        raise HTTPException(status_code=422, detail="Firma je povinná")

    svc = _svc()
    payload = {
        "company_name": nm[:512],
        "website": _opt_str(website, max_len=512),
        "contact_name": _opt_str(contact_name, max_len=255),
        "contact_email": _opt_str(contact_email, max_len=255),
        "contact_linkedin": _opt_str(contact_linkedin, max_len=512),
        "role": _opt_str(role, max_len=255),
        "source": _opt_str(source, max_len=255),
        "status": (status or "new").strip()[:64] or "new",
        "signal_strength": (signal_strength or "weak").strip()[:32] or "weak",
        "decision_level": _opt_str(decision_level, max_len=64),
        "source_of_truth": _opt_str(source_of_truth, max_len=64),
        "last_contacted_at": _parse_dt_prague_to_utc(last_contacted_at),
        "next_follow_up_at": _parse_date(next_follow_up_at),
        "next_action": _opt_str(next_action, max_len=512),
        "notes": _opt_str(notes),
    }
    lead = svc.create_lead(session, data=payload)
    return RedirectResponse(url=f"/admin/leads/{lead.id}", status_code=303)


@router.get("/admin/leads/{lead_id}", response_class=HTMLResponse)
def admin_lead_detail_get(
    request: Request,
    lead_id: int,
    session: Session = Depends(get_session),
    _current_user: User = Depends(require_admin),
) -> HTMLResponse:
    svc = _svc()
    lead = svc.get_lead_or_404(session, lead_id)
    interactions = svc.list_interactions(session, lead_id)
    return template_response(
        request=request,
        name="admin_lead_detail.html",
        context={
            "lead": lead,
            "interactions": interactions,
            "suggested_statuses": SUGGESTED_STATUSES,
            "signal_strengths": SIGNAL_STRENGTHS,
            "decision_levels": DECISION_LEVELS,
            "source_of_truth_opts": SOURCE_OF_TRUTH,
            "interaction_channels": INTERACTION_CHANNELS,
            "interaction_directions": INTERACTION_DIRECTIONS,
            "today_prague": today_prague(),
            "last_contacted_at_input": _utc_to_prague_datetime_local(lead.last_contacted_at),
            "next_follow_up_at_input": _fmt_date_input(lead.next_follow_up_at),
        },
    )


@router.post("/admin/leads/{lead_id}")
def admin_lead_update_post(
    lead_id: int,
    status: str = Form(...),
    signal_strength: str = Form(...),
    decision_level: str = Form(""),
    source_of_truth: str = Form(""),
    last_contacted_at: str = Form(""),
    next_follow_up_at: str = Form(""),
    next_action: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
    _current_user: User = Depends(require_admin),
) -> RedirectResponse:
    svc = _svc()
    data = {
        "status": status.strip()[:64] or "new",
        "signal_strength": signal_strength.strip()[:32] or "weak",
        "decision_level": _opt_str(decision_level, max_len=64),
        "source_of_truth": _opt_str(source_of_truth, max_len=64),
        "last_contacted_at": _parse_dt_prague_to_utc(last_contacted_at),
        "next_follow_up_at": _parse_date(next_follow_up_at),
        "next_action": _opt_str(next_action, max_len=512),
        "notes": _opt_str(notes),
    }
    svc.update_lead(session, lead_id, data=data)
    return RedirectResponse(url=f"/admin/leads/{lead_id}", status_code=303)


@router.post("/admin/leads/{lead_id}/interactions")
def admin_lead_add_interaction_post(
    lead_id: int,
    channel: str = Form("email"),
    direction: str = Form("note"),
    message_summary: str = Form(""),
    session: Session = Depends(get_session),
    _current_user: User = Depends(require_admin),
) -> RedirectResponse:
    svc = _svc()
    svc.add_interaction(
        session,
        lead_id,
        channel=(channel or "email").strip()[:32] or "email",
        direction=(direction or "note").strip()[:32] or "note",
        message_summary=message_summary,
    )
    return RedirectResponse(url=f"/admin/leads/{lead_id}", status_code=303)
