"""
Standalone hourly Google Ads sync loop (does not start the web app).

Run with the same environment as the API (e.g. JWT_SECRET, DATABASE_URL path via app.database).

Usage (from project root):

    python -m scripts.run_background_sync

This is the preferred way to run long-lived sync work in multi-instance deployments.
The web process only runs this loop when ENABLE_BACKGROUND_SYNC=true.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import validate_startup_config
from app.core.request_id import bind_worker_correlation_context, reset_worker_correlation_context
from app.core.structured_logging import configure_structured_logging
from app.database import create_db_and_tables
from app.jobs.google_ads_sync import run_google_ads_sync_all_clients_once

logger = logging.getLogger(__name__)


async def _hourly_loop() -> None:
    while True:
        try:
            worker_tokens = bind_worker_correlation_context()
            try:
                await asyncio.to_thread(run_google_ads_sync_all_clients_once)
            finally:
                reset_worker_correlation_context(worker_tokens)
        except Exception:
            logger.exception(
                "background_job_failed job=google_ads_sync_all_clients alert_severity=high",
                extra={
                    "job": "google_ads_sync_all_clients",
                    "alert_severity": "high",
                    "error_category": "background_job",
                },
            )
        await asyncio.sleep(3600)


async def main() -> None:
    configure_structured_logging()
    validate_startup_config()
    create_db_and_tables()
    await _hourly_loop()


if __name__ == "__main__":
    asyncio.run(main())
