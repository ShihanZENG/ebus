# G3/G4 Enterprise Diagnostics and Reconciliation Preparation Plan

> **For agentic workers:** Follow this plan task by task. Keep the implementation within the accepted read-only boundary; do not add or run tests unless explicitly requested.

**Goal:** Add a scoped cross-domain ERP diagnostic snapshot through the existing LIM single-Tool runtime, then add read-only ERP↔OMS reconciliation preparation without inventing system identity mappings.

**Architecture:** G3 provides five versioned read-only Tool adapters with LIM-standard evidence refs; LIM owns Workflow DAG, scheduling, parent/child traces and aggregation. G4 is a local comparison preview over scope-filtered ERP and authenticated OMS JSON exports; it does not create a service-to-service link or write business data.

**Tech Stack:** Existing FastAPI/SQLAlchemy LIM and ERP services; React/TypeScript/Ant Design.

**Specs:** `docs/superpowers/specs/2026-10-21-g3-business-diagnostic-design.md`, `docs/superpowers/specs/2026-10-21-g4-oms-reconciliation-preparation-design.md`

## Global Constraints

- Preserve shared worktree edits and read current versions before modifying shared files.
- Use existing LIM Run/Trace; do not introduce a second registry, state machine, or multi-agent claim.
- Use server-side permission and scope checks separately for each source domain.
- Do not write business data, call external platforms, or combine incompatible currency/period metrics.
- G4 upload parsing must stay client-side and discard PII/unsupported columns.

## Review Focus

- G3 requested shop outside Run scope must not leak whether it exists.
- Missing one domain permission must not grant it through `assistant:read` or block unrelated permitted evidence.
- G3 source gaps and incompatible time/currency must remain visible, never become zeros.
- G4 duplicate and ambiguous candidates must not auto-select a match.
- G4 cross-currency amount and cross-system status disagreements must never be silently normalized.

## Tasks

### Task 1: G3 domain Tool adapters and LIM registration contract

**Files:** Create `backend/app/business_evidence_tools.py`, modify `backend/app/lim_runtime.py`, create `docs/lim/business-diagnostic-tool-contract.md`, update the G0 ledger.

- [x] Add read-only adapters for order period summary, ads campaign performance, shop-allocated inventory availability, recorded payments and ads/inventory alignment Finding.
- [x] Return versioned LIM `evidence_refs` with subject, claim_key, value, unit, observation time, period basis and subject-bound content hash.
- [x] Enforce each source permission and the server-side shop/warehouse scope inside its adapter.
- [x] Register handlers in the existing read Tool allowlist and document the single-Agent Workflow input/DAG contract.

### Task 2: G3 platform handoff

**Files:** Create `docs/lim/business-diagnostic-tool-contract.md`; update G0 ledger.

- [x] Publish exact tool IDs, input fields, claim keys/units/time bases and the first Workflow definition for platform registration.
- [x] Keep parent Workflow ownership and execution in LIM; use existing `/api/v1/lim/workflows` and `/workflow-runs` APIs.

### Task 3: G4 export and local comparison

**Files:** Create an ERP read-only export route/service, add an authenticated read-only JSON export to the OMS order page/API, create `frontend/src/pages/OmsReconciliationPrepPage.tsx`, modify route/menu and document the export format.

- [x] Export only scoped minimal ERP fields from both systems with provenance metadata.
- [x] Parse the OMS 1.0.0 JSON schema in the browser and reject truncated or invalid files.
- [x] Require temporary shop mapping; match by shop/channel/order/currency and report amount/status differences and ambiguity.
- [x] Offer a local JSON report download without any POST back to the ERP API.

### Task 4: Handoff and verification

- [x] Update the G0 ledger with implemented versus blocked status and exact OMS integration prerequisites.
- [x] Run ERP and OMS frontend production builds and backend app import/route inspection; do not run tests unless requested.
- [x] Record that registry registration and real-source end-to-end behavior still require a configured user/database.
