"""Platform strings for CSV uploads (unified + multi-source). Used for storage and safe clear-data scope."""

from __future__ import annotations

# Unified marketing CSV (existing flow) — one row = day × campaign with revenue + spend.
PLATFORM_CSV_UNIFIED = "imported"

# Multi-source pilot: separate files, distinct platforms (never reuse "imported" for these).
PLATFORM_CSV_SHOP_ORDERS = "csv_shop_orders"
PLATFORM_CSV_META_ADS = "csv_meta_ads"
PLATFORM_CSV_GOOGLE_ADS = "csv_google_ads"

# All user-uploaded CSV data cleared by POST /api/v1/upload/clear-imported (never API integrations).
CSV_CLEAR_PLATFORM_FROZENSET = frozenset(
    {
        PLATFORM_CSV_UNIFIED,
        PLATFORM_CSV_SHOP_ORDERS,
        PLATFORM_CSV_META_ADS,
        PLATFORM_CSV_GOOGLE_ADS,
    },
)

# Google Ads OAuth/sync integration uses this platform — must never be in CSV_CLEAR_PLATFORM_FROZENSET.
GOOGLE_ADS_INTEGRATION_PLATFORM = "google_ads"
