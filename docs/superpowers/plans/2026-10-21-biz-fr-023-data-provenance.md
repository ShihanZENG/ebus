# BIZ-FR-023 Data Provenance Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in the current session. Steps use checkbox syntax for tracking.

**Goal:** Show truthful source, freshness, missing-data, and sample-classification metadata for key ERP dashboard, inventory, advertising, and finance metrics.

**Architecture:** ERP-local summaries return a common metadata object based on scoped source records and their stored `updated_at`; file-imported advertising uses its real import batch timestamp. DataLab proxy responses add query time while explicitly leaving upstream freshness unknown when the source does not provide it. Pages render those facts and keep unknown sample/production classification visible.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, React, TypeScript, Ant Design.

**Spec:** Attached enterprise management PRD, BIZ-FR-023 (`数据来源与同步标识`).

## Global Constraints

- Show real-time, import, simulated, and missing states only when the source data supports that classification.
- Never substitute request time or business date for upstream data-update time; DataLab has no documented freshness field in the current proxy contract.
- Keep sample/production status unclassified where the existing records have no such marker.
- Do not modify AI alert modules or upgrade/connect to the shared development database.
- Preserve existing response fields; metadata additions are additive.

## Review Focus

- Empty local table versus a failed request: expose missing only for a successful empty response; retain a separate unavailable/error state.
- DataLab query time versus upstream refresh time: show separate fields and keep upstream time unknown when absent.
- User shop/warehouse scope: derive freshness and row counts from the same authorized scope as the metric.
- Imported ads versus DataLab campaign snapshot: label import and warehouse snapshot as distinct sources.
- Demo/sample provenance: never infer production from absence of a simulation marker; display unclassified.

---

### Task 1: ERP Local Summary Metadata

**Files:**
- Create: `backend/app/provenance.py`
- Modify: `backend/app/orders.py`, `backend/app/wms.py`, `backend/app/scm.py`, `backend/app/profit_reconciliation.py`
- Test: `backend/tests/test_data_provenance.py`

- [x] Add focused tests for source mode, available/missing status, scoped latest `updated_at`, and finance record-origin counts where defined.
- [x] Run the new tests and confirm missing metadata fails.
- [x] Add a reusable local-record metadata builder and include additive `data_meta` in order, inventory, procurement, replenishment, and finance summary APIs.
- [x] Run the focused backend provenance tests plus existing summary tests.

### Task 2: DataLab and Imported Advertising Metadata

**Files:**
- Modify: `backend/app/datalab.py`, `backend/app/ads_reports.py`
- Test: `backend/tests/test_data_provenance.py`

- [x] Test DataLab rows with no upstream freshness field and empty rows; assert query time is separate and upstream freshness is null/unknown.
- [x] Test imported-ad metadata against the latest authorized import batch and the no-batch case.
- [x] Add additive metadata to DataLab table responses and the advertising campaign/import summary APIs, preserving existing `rows`/`items` fields.
- [x] Run focused DataLab and ads-report tests with mocked upstream responses.

### Task 3: Visible Source and Freshness in Pages

**Files:**
- Create or modify: `frontend/src/components/DataProvenance.tsx`
- Modify: `frontend/src/pages/DashboardPage.tsx`, `Dashboard.tsx`, `Inventory.tsx`, `AdCampaignsPage.tsx`, `FinanceSettlementsPage.tsx`

- [x] Add a shared presentation component that maps missing, unavailable, imported, local, and unknown-upstream states.
- [x] Render local record-change timestamps on dashboard/inventory; render import batch time for imported ads; render DataLab query time separately from unknown upstream freshness on ads/finance and BI pages.
- [x] Display missing-data and unclassified sample/production status without calling local or warehouse data production/live.
- [x] Run frontend typecheck and review the metadata copy in the pages.

### Task 4: Acceptance Evidence

**Files:**
- Modify: `docs/企业经营管理端G0功能状态台账-2026-10-21.md`

- [x] Run focused backend tests on isolated per-test databases; run DataLab/ads tests with mocked upstream data.
- [x] Record exact coverage and external freshness limitations; leave shared DB and AI alert files untouched.
