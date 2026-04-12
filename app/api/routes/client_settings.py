from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.deps import get_current_user
from app.core.domain_errors import NotFoundError
from app.database import get_session
from app.models.db_models import User
from app.repositories.client_repository import ClientRepository
from app.services.marketing_service import MarketingService

router = APIRouter(prefix="/api/v1/client", tags=["client"])


class ClientMarginBody(BaseModel):
    margin_percent: int = Field(..., ge=1, le=99, description="Hrubá marže v % (1–99).")


@router.patch("/margin")
def patch_client_margin(
    body: ClientMarginBody,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Update stored margin for the authenticated user's workspace (all dashboard math uses it)."""
    decimal = body.margin_percent / 100.0
    repo = ClientRepository(session)
    updated = repo.update_margin_for_client(current_user.client_id, decimal)
    if updated is None:
        raise NotFoundError("Pracovní prostor nenalezen.")
    m = MarketingService._validated_margin(updated.margin)
    return {
        "margin_percent": int(round(m * 100)),
        "margin": round(m, 4),
    }
