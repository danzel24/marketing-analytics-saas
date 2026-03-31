# Financial calculations (reference)

- **Margin**: decimal in DB/API (e.g. `0.4` = 40 %). Values `1–100` are treated as percent and divided by 100.
- **Contribution / marketing profit**: `revenue × margin − ad_spend` (same for totals and per campaign).
- **ROAS**: `revenue / ad_spend`; if `ad_spend == 0`, ROAS is **0** (not ∞).
- **Break-even ROAS**: `1 / margin`.
- **Campaign status** (anti-flip buffer): `insufficient_data` if no revenue and no spend; else if spend > 0: **loss** if ROAS < 0.9 × BE, **profitable** if ROAS > 1.1 × BE, else **at_risk**; if spend = 0: profitable iff contribution ≥ 0.
- **Portfolio `average_roas_status`**: same 0.9 / 1.1 bands on paid totals; `insufficient_data` if no paid spend.

## Debug payload

1. Set env: `DASHBOARD_CALC_DEBUG=1`
2. Call: `GET /api/v1/dashboard/full?calc_debug=1`

Response may include `calc_debug` with overview snapshot and formula notes.

## Legacy / CSV file repo

`CampaignRepository` (file-based) sums raw CSV numbers without margin; DB-backed `MarketingService` is authoritative for the SaaS dashboard.
