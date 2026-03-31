"""Google Ads integration sync (callable from web loop or standalone worker)."""

from __future__ import annotations

from sqlmodel import Session

from app.database import engine
from app.services.integration_service import IntegrationService


def run_google_ads_sync_all_clients_once() -> None:
    """One hourly tick: sync all clients (internal/unscoped — worker-only boundary)."""
    with Session(engine) as session:
        IntegrationService(session).sync_all_clients_unscoped_internal(_internal_call=True)
