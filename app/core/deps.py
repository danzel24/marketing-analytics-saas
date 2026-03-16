from __future__ import annotations

from functools import lru_cache
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request

from app.core.config import Settings, csv_path_for_tenant, get_settings
from app.repositories.campaign_repository import CampaignRepository
from app.services.marketing_service import MarketingService


@lru_cache(maxsize=1)
def settings_dep() -> Settings:
    return get_settings()


def tenant_id_dep(
    request: Request,
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id"),
) -> Optional[str]:
    """
    Tenant resolution strategy:
    1. Explicit X-Tenant-Id header (highest priorita)
    2. Subdoména v Host headeru, např. demo.api.example.com -> tenant "demo"
    """
    if x_tenant_id:
        return x_tenant_id

    host = request.headers.get("host", "")
    hostname = host.split(":", 1)[0]
    parts = hostname.split(".")
    if len(parts) >= 3:
        subdomain = parts[0]
        if subdomain not in {"www", "api"}:
            return subdomain

    return None


def campaign_repo_dep(
    settings: Settings = Depends(settings_dep),
    tenant_id: Optional[str] = Depends(tenant_id_dep),
) -> CampaignRepository:
    csv_path = csv_path_for_tenant(settings, tenant_id)
    if not csv_path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "ads_report_csv_not_found",
                "csv_path": str(csv_path),
                "tenant_id": tenant_id,
            },
        )
    return CampaignRepository(csv_path=csv_path)


def marketing_service_dep() -> MarketingService:
    return MarketingService()

