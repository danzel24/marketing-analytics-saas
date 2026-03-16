from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import campaign_repo_dep, marketing_service_dep
from app.repositories.campaign_repository import CampaignRepository
from app.schemas.campaign import CampaignOut, MetricsOut
from app.services.marketing_service import MarketingService

router = APIRouter(tags=["campaigns"])


@router.get("/campaigns", response_model=list[CampaignOut])
def get_campaigns(
    repo: CampaignRepository = Depends(campaign_repo_dep),
    svc: MarketingService = Depends(marketing_service_dep),
) -> list[CampaignOut]:
    campaigns = repo.list_campaigns()
    return svc.campaigns_overview(campaigns)


@router.get("/metrics", response_model=MetricsOut)
def get_metrics(
    repo: CampaignRepository = Depends(campaign_repo_dep),
    svc: MarketingService = Depends(marketing_service_dep),
) -> MetricsOut:
    campaigns = repo.list_campaigns()
    return svc.aggregated_metrics(campaigns)

