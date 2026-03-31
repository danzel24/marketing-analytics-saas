from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.deps import get_current_user
from app.database import get_session
from app.models.db_models import User
from app.services.integration_service import IntegrationService

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


@router.post("/google/sync")
def sync_google_ads(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return IntegrationService(session).sync_google_ads(current_user.client_id)
