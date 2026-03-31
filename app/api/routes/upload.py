from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from sqlmodel import Session

from app.core.deps import get_current_user
from app.database import get_session
from app.models.db_models import User
from app.repositories.campaign_metric_repository import CampaignMetricRepository
from app.repositories.campaign_repository_sql import CampaignRepository
from app.services.csv_service import CSVService

router = APIRouter(prefix="/api/v1/upload", tags=["upload"])


@router.post("/revenue-csv")
async def upload_revenue_csv(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    raw = await file.read()
    campaign_repo = CampaignRepository(session)
    metric_repo = CampaignMetricRepository(session)
    service = CSVService(campaign_repo, metric_repo)
    return service.import_revenue_csv_bytes(raw, current_user.client_id)
