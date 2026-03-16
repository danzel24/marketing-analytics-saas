from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.database import get_session
from app.services.marketing_service import MarketingService

router = APIRouter(tags=["dashboard"])

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"  # app/templates
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/api/v1/dashboard/overview")
def dashboard_overview(
    client_id: int = Query(..., description="Client ID"),
    days: int | None = Query(None, ge=1, description="Počet dní pro agregaci (volitelné)"),
    session: Session = Depends(get_session),
) -> dict[str, float]:
    svc = MarketingService(session=session)
    return svc.dashboard_overview_db(client_id=client_id, days=days)


@router.get("/api/v1/dashboard/revenue-trend")
def dashboard_revenue_trend(
    client_id: int = Query(..., description="Client ID"),
    days: int = Query(30, ge=1, description="Počet dní pro revenue trend"),
    session: Session = Depends(get_session),
) -> dict[str, list]:
    svc = MarketingService(session=session)
    return svc.revenue_trend_db(client_id=client_id, days=days)


@router.get("/api/v1/dashboard/spend-trend")
def dashboard_spend_trend(
    client_id: int = Query(..., description="Client ID"),
    days: int = Query(30, ge=1, description="Počet dní pro spend trend"),
    session: Session = Depends(get_session),
) -> dict[str, list]:
    svc = MarketingService(session=session)
    return svc.spend_trend_db(client_id=client_id, days=days)


@router.get("/api/v1/dashboard/top-campaigns")
def dashboard_top_campaigns(
    client_id: int = Query(..., description="Client ID"),
    days: int = Query(30, ge=1, description="Počet dní pro vyhodnocení kampaní"),
    top_n: int = Query(5, ge=1, description="Počet kampaní v žebříčku"),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    svc = MarketingService(session=session)
    return svc.top_campaigns_db(client_id=client_id, days=days, top_n=top_n)


@router.get("/api/v1/dashboard/full")
def dashboard_full(
    client_id: int = Query(..., description="Client ID"),
    days: int = Query(30, ge=1, description="Počet dní pro dashboard"),
    top_n: int = Query(5, ge=1, description="Počet top kampaní"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    svc = MarketingService(session=session)
    return svc.dashboard_full_db(client_id=client_id, days=days, top_n=top_n)

