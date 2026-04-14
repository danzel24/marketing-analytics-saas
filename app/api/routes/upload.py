from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.deps import get_current_user
from app.database import get_session
from app.models.db_models import User
from app.repositories.campaign_metric_repository import CampaignMetricRepository
from app.repositories.campaign_repository_sql import CampaignRepository
from app.services.csv_service import CSVService
from app.services.multi_source_csv_service import MultiSourceCSVService

router = APIRouter(prefix="/api/v1/upload", tags=["upload"])


class ClearImportedIn(BaseModel):
    confirm: str = Field(..., min_length=1, description="Must equal the server constant for this action.")


@router.post("/revenue-csv/preview")
async def preview_revenue_csv_upload(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Parse CSV and return sample rows without persisting (same rules as import)."""
    raw = await file.read()
    campaign_repo = CampaignRepository(session)
    metric_repo = CampaignMetricRepository(session)
    service = CSVService(campaign_repo, metric_repo)
    return service.preview_revenue_csv_bytes(raw)


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


@router.post("/clear-imported")
def clear_imported_data(
    body: ClearImportedIn,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, int]:
    campaign_repo = CampaignRepository(session)
    metric_repo = CampaignMetricRepository(session)
    service = CSVService(campaign_repo, metric_repo)
    return service.clear_imported_data_for_client(current_user.client_id, body.confirm)


# --- Multi-source CSV (pilot; unified flow above stays unchanged) ---


@router.post("/multi/orders/preview")
async def preview_multi_orders_csv(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    raw = await file.read()
    campaign_repo = CampaignRepository(session)
    metric_repo = CampaignMetricRepository(session)
    service = MultiSourceCSVService(campaign_repo, metric_repo)
    return service.preview_orders_csv_bytes(raw)


@router.post("/multi/orders")
async def upload_multi_orders_csv(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    raw = await file.read()
    campaign_repo = CampaignRepository(session)
    metric_repo = CampaignMetricRepository(session)
    service = MultiSourceCSVService(campaign_repo, metric_repo)
    return service.import_orders_csv_bytes(raw, current_user.client_id)


@router.post("/multi/meta/preview")
async def preview_multi_meta_csv(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    raw = await file.read()
    campaign_repo = CampaignRepository(session)
    metric_repo = CampaignMetricRepository(session)
    service = MultiSourceCSVService(campaign_repo, metric_repo)
    return service.preview_meta_csv_bytes(raw)


@router.post("/multi/meta")
async def upload_multi_meta_csv(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    raw = await file.read()
    campaign_repo = CampaignRepository(session)
    metric_repo = CampaignMetricRepository(session)
    service = MultiSourceCSVService(campaign_repo, metric_repo)
    return service.import_meta_csv_bytes(raw, current_user.client_id)


@router.post("/multi/google/preview")
async def preview_multi_google_csv(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    raw = await file.read()
    campaign_repo = CampaignRepository(session)
    metric_repo = CampaignMetricRepository(session)
    service = MultiSourceCSVService(campaign_repo, metric_repo)
    return service.preview_google_csv_bytes(raw)


@router.post("/multi/google")
async def upload_multi_google_csv(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    raw = await file.read()
    campaign_repo = CampaignRepository(session)
    metric_repo = CampaignMetricRepository(session)
    service = MultiSourceCSVService(campaign_repo, metric_repo)
    return service.import_google_csv_bytes(raw, current_user.client_id)
