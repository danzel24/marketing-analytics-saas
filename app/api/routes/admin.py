from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.deps import require_admin
from app.database import get_session
from app.models.db_models import User
from app.services.admin_service import AdminService

router = APIRouter(tags=["admin"])
logger = logging.getLogger(__name__)


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
def admin_page(current_user: User = Depends(require_admin)) -> str:  # noqa: ARG001
    return """
    <!doctype html>
    <html lang="cs">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Administrace</title>
      </head>
      <body style="font-family: Arial, sans-serif; padding: 24px;">
        <h1>Administrace</h1>
        <p>Tato stránka je připravena pro administrátorské nástroje.</p>
      </body>
    </html>
    """


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
