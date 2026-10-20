# Ads Campaign Diagnostics Implementation Plan

> **For agentic workers:** Execute inline, task by task, with regression tests for observable rules.

**Goal:** Add trustworthy campaign diagnostics for user-configured high-spend/no-sales thresholds, campaign-specific target ACOS, and mapped-SKU local inventory.

**Architecture:** Persist no-sales spend thresholds per shop and currency and target ACOS per shop and campaign. Extend the existing daily campaign API with target and exact SKU mapping/local available inventory; compute diagnostic labels from the filtered report rows and configured rules in the UI. Reuse the existing local inventory low-stock cutoff (available quantity <= 120) and warehouse-scope rules; do not infer an SKU mapping from names or campaign IDs.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, React, TypeScript, Ant Design, pytest.

**Spec:** User request in this conversation, clarified as: first high spend/no attributed sales, then user-set ACOS target; inventory warnings only for campaigns whose `sku_code` exactly maps to a known ERP SKU.

## Global Constraints

- No-spend threshold is store- and currency-specific; do not compare monetary values across currencies.
- Target ACOS is store- and campaign-specific; zero attributed sales has no calculable ACOS.
- Inventory shown is local warehouse available quantity (`on_hand_qty - reserved_qty`), not marketplace/FBA stock.
- Inventory diagnostics require exact ERP SKU code equality and respect the caller's warehouse scope.
- Existing read/write permission and shop-scope behavior remains enforced.

## Review Focus

- Threshold missing or zero: no high-spend warning until a positive threshold is explicitly configured.
- Spend exactly at threshold: warning is included; below threshold is excluded.
- Zero sales: ACOS is not calculated and only configured no-sales diagnostic can fire.
- Missing/unknown SKU mapping: inventory is unavailable, never guessed from text.
- Restricted warehouse scope: inventory availability sums only permitted warehouses.

---

### Task 1: Backend settings, campaign target, and mapped inventory API

**Files:** `backend/app/models.py`, `backend/app/ads_reports.py`, `backend/migrations/versions/0025_ads_campaign_diagnostics.py`, `backend/tests/test_erp.py`

**Interfaces:**
- `GET /api/v1/ads-reports/diagnostic-settings?shop_id=...` returns configured currency thresholds for that authorized shop.
- `PUT /api/v1/ads-reports/diagnostic-settings` accepts `{shop_id, currency, no_sales_spend_threshold}`; positive decimal threshold only.
- `PUT /api/v1/ads-reports/campaign-target` accepts `{shop_id, campaign_id, target_acos_percent}`; nullable target removes it; positive percentage bounded at 1000.
- Campaign list rows expose `target_acos_percent`, `mapped_sku`, and `local_available_qty`; unmapped SKU fields are null.

- [x] Add failing API tests for scope-checked settings/targets and exact SKU-to-local-inventory mapping.
- [x] Run the focused test and confirm it fails because the new behavior is absent.
- [x] Add settings/target models and migration; implement endpoints and enrich campaign rows by exact SKU code, honoring warehouse scope.
- [x] Run focused tests and confirm they pass.

### Task 2: Ads UI settings and actionable diagnostics

**Files:** `frontend/src/pages/AdCampaignsPage.tsx`

**Interfaces:** Consume the settings and enriched campaign API from Task 1.

- [x] No established React component test harness exists; API behavior tests cover the diagnostics and permission contract.
- [x] Add per-currency threshold editor, per-campaign target ACOS editor, and diagnostic column with clear local-inventory wording.
- [x] Run frontend typecheck and production build.

### Task 3: Documentation and deployment readiness

**Files:** `docs/功能章节/02_运营与结算/10_广告-推广投放.md`

- [x] Document the threshold, target ACOS, zero-sales handling, exact SKU mapping, and local-inventory semantics.
- [x] Apply the additive migration to the local database and restart the already-running backend using the repository's normal script.
- [x] Confirm the ads page loads and its configuration endpoints return successfully; no artificial business rows were created during initial implementation.

### Task 4: Manual action tracking and end-to-end acceptance

**Files:** `backend/app/models.py`, `backend/app/ads_reports.py`, `backend/migrations/versions/0026_ads_campaign_actions.py`, `frontend/src/pages/AdCampaignsPage.tsx`

- [x] Persist per-day campaign handling status and an internal note, constrained to an existing authorized daily report row.
- [x] Expose a modal from the daily report table to record checked, watching, or adjusted outcomes; saving writes an audit entry and never calls the ad platform.
- [x] Prepare a clearly named three-row simulated CSV for the demo shop and verify all three diagnostic rules through the existing report endpoints.
- [x] Apply migration 0026, restart the local backend, and verify report actions remain visible after refresh.
