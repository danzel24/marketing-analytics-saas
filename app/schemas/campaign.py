from __future__ import annotations

from pydantic import BaseModel, Field


class CampaignOut(BaseModel):
    campaign: str = Field(..., examples=["facebook_ads"])
    spend: float = Field(..., ge=0)
    revenue: float = Field(..., ge=0)
    profit: float
    roas: float


class MetricsOut(BaseModel):
    total_spend: float
    total_revenue: float
    total_profit: float
    average_roas: float
    campaigns_count: int

