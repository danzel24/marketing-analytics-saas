from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.core.config import get_settings
from app.core.deps import get_current_user
from app.database import get_session
from app.models.db_models import User
from app.services.marketing_service import MarketingService

router = APIRouter(tags=["dashboard"])

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"  # app/templates
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/")
def web_root() -> RedirectResponse:
    """Browser entry: go to dashboard (JS redirects unauthenticated users to /login)."""
    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("register.html", {"request": request})


@router.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("upload.html", {"request": request})


@router.get("/api/v1/dashboard/overview")
def dashboard_overview(
    current_user: User = Depends(get_current_user),
    days: int | None = Query(None, ge=1, description="Počet dní pro agregaci (volitelné)"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    svc = MarketingService(session=session)
    return svc.dashboard_overview_db(client_id=current_user.client_id, days=days)


@router.get("/api/v1/dashboard/revenue-trend")
def dashboard_revenue_trend(
    current_user: User = Depends(get_current_user),
    days: int = Query(30, ge=1, description="Počet dní pro revenue trend"),
    session: Session = Depends(get_session),
) -> dict[str, list]:
    svc = MarketingService(session=session)
    return svc.revenue_trend_db(client_id=current_user.client_id, days=days)


@router.get("/api/v1/dashboard/spend-trend")
def dashboard_spend_trend(
    current_user: User = Depends(get_current_user),
    days: int = Query(30, ge=1, description="Počet dní pro spend trend"),
    session: Session = Depends(get_session),
) -> dict[str, list]:
    svc = MarketingService(session=session)
    return svc.spend_trend_db(client_id=current_user.client_id, days=days)


@router.get("/api/v1/dashboard/top-campaigns")
def dashboard_top_campaigns(
    current_user: User = Depends(get_current_user),
    days: int = Query(30, ge=1, description="Počet dní pro vyhodnocení kampaní"),
    top_n: int = Query(5, ge=1, description="Počet kampaní v žebříčku"),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    svc = MarketingService(session=session)
    return svc.top_campaigns_db(client_id=current_user.client_id, days=days, top_n=top_n)


@router.get("/api/v1/dashboard/full")
def dashboard_full(
    current_user: User = Depends(get_current_user),
    days: int = Query(30, ge=1, description="Počet dní pro dashboard"),
    top_n: int = Query(5, ge=1, description="Počet top kampaní"),
    calc_debug: bool = Query(
        False,
        description="Vrátí calc_debug (jen pokud je na serveru DASHBOARD_CALC_DEBUG=1)",
    ),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    svc = MarketingService(session=session)
    debug_payload = calc_debug and get_settings().dashboard_calc_debug
    return svc.dashboard_full_db(
        client_id=current_user.client_id,
        days=days,
        top_n=top_n,
        calc_debug=debug_payload,
    )


@router.get("/api/v1/dashboard/insights")
def dashboard_insights(
    current_user: User = Depends(get_current_user),
    days: int = Query(30, ge=1, description="Počet dní pro insights"),
    session: Session = Depends(get_session),
) -> dict[str, list[str]]:
    svc = MarketingService(session=session)
    return {"insights": svc.get_insights(client_id=current_user.client_id, days=days)}

