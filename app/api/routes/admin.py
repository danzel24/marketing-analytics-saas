from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.routes.admin_leads import router as admin_leads_router
from app.core.deps import require_admin
from app.core.web_templates import template_response
from app.database import get_session
from app.models.db_models import User
from app.services.admin_service import AdminService

router = APIRouter(tags=["admin"])
logger = logging.getLogger(__name__)

router.include_router(admin_leads_router)


class ClearDataIn(BaseModel):
    confirm: str = Field(
        ...,
        description="Pro smazání dat je nutné poslat confirm='CLEAR'",
        examples=["CLEAR"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {"confirm": "CLEAR"},
        }
    }


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, _current_user: User = Depends(require_admin)) -> HTMLResponse:
    return template_response(request=request, name="admin.html")


@router.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(
    request: Request,
    session: Session = Depends(get_session),
    _current_user: User = Depends(require_admin),
) -> HTMLResponse:
    users = AdminService().list_registered_users_overview(session)
    return template_response(request=request, name="admin_users.html", context={"users": users})


@router.post("/api/v1/admin/clear-data")
def clear_data(
    payload: ClearDataIn | None = Body(
        default=None,
        description="Pro smazání dat je nutné poslat confirm='CLEAR'",
        examples={
            "potvrzeni": {
                "summary": "Potvrzení smazání",
                "value": {"confirm": "CLEAR"},
            }
        },
    ),
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    confirm = payload.confirm if payload is not None else None
    deleted = AdminService().clear_tenant_campaign_metrics(
        session,
        client_id=current_user.client_id,
        confirmation=confirm,
    )

    logger.warning(
        "admin clear-data executed user_id=%s client_id=%s deleted=%s at=%s",
        current_user.id,
        current_user.client_id,
        deleted,
        datetime.now(timezone.utc).isoformat(),
    )
    return {"status": "cleared"}
