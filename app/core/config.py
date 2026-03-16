from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_csv_path: Path
    tenants_data_dir: Path


def get_settings() -> Settings:
    """
    Minimal config layer ready for SaaS extension (envs, per-tenant config, etc.).
    """
    base_dir = Path(__file__).resolve().parents[2]  # .../python-projekty
    default_csv = base_dir / "data" / "ads_report.csv"
    tenants_dir = base_dir / "data" / "tenants"
    csv_path = Path(os.getenv("ADS_REPORT_CSV_PATH", str(default_csv))).resolve()
    return Settings(data_csv_path=csv_path, tenants_data_dir=tenants_dir.resolve())


def csv_path_for_tenant(settings: Settings, tenant_id: str | None) -> Path:
    """
    Tenant routing strategy (simple, file-based):
    - default: settings.data_csv_path
    - tenant: data/tenants/<tenant_id>/ads_report.csv
    """
    if not tenant_id:
        return settings.data_csv_path
    safe = tenant_id.strip()
    if not safe:
        return settings.data_csv_path
    return (settings.tenants_data_dir / safe / "ads_report.csv").resolve()

