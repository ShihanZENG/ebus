# LIM Local Handler Observability Implementation Plan

> **For agentic workers:** Implement inline in the current shared checkout; preserve unrelated dirty files.

**Goal:** Expose permission-filtered local Tool invocation counts, status, and measured handler latency by UTC day, Agent/Agent version, Tool/Tool version, and execution mode, with JSON and CSV export.

**Architecture:** Add a pure aggregation service over persisted `LimRun` and `LimToolInvocation` rows and small read/export routes guarded by `assistant:read`. Reuse existing `_run_visible` authorization before aggregation. Sandbox rows remain a separate mode and never contribute their synthetic zero to live latency; unavailable token, cost, cache, and tenant metrics are declared unavailable.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, Python CSV/JSON responses.

**Spec:** Attached AI Platform Admin PRD, LIM-FR-020; supervisor-approved local handler observability acceptance.

## Global Constraints
- Do not invent token, cost, cache-hit, or tenant data.
- Keep Sandbox distinct from live handler observations.
- Keep aggregation limited to authorized visible Runs.
- Do not modify enterprise FR-011 files.

## Review Focus
- UTC midnight boundary maps an invocation to exactly one day.
- Blocked rows are separate from handler call count.
- Null latency and Sandbox synthetic zero are excluded from live latency samples.
- Exact Agent/Tool version joins are preserved.
- Export cannot reveal out-of-scope Runs and marks unavailable metrics explicitly.

---

### Task 1: Add deterministic aggregation and API acceptance tests

**Files:**
- Create: `backend/tests/test_lim_metrics.py`
- Test fixture: isolated temporary SQLite with migrated schema; seed Runs and invocations with fixed timestamps and distinct versions.

**Interfaces:**
- Query: `GET /api/v1/lim/metrics/tool-invocations?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`
- Export: `GET /api/v1/lim/metrics/tool-invocations/export?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&format=json|csv`

- [x] Test UTC day, Agent/Tool version, and execution-mode grouping plus all invocation statuses.
- [x] Test handler count, latency sample count/mean/nearest-rank percentiles, null exclusion, and Sandbox zero exclusion.
- [x] Test reader visibility, denied permission, JSON parity, CSV columns, and unavailable metrics.
- [x] Run focused tests and confirm expected missing-route failure before implementation.

### Task 2: Implement aggregation and protected endpoints

**Files:**
- Create: `backend/app/lim_metrics.py`
- Modify: `backend/app/lim_routes.py`

- [x] Aggregate only visible Runs for the bounded inclusive UTC date range.
- [x] Return separate live/sandbox groups; count blocked states separately from handler attempts.
- [x] Compute latency only from non-null live `elapsed_ms`; empty samples return null statistics.
- [x] Expose unavailable token/cost/cache/tenant fields as unavailable, never numeric zero.
- [x] Export the same JSON aggregate or equivalent CSV with explicit unavailable status.

### Task 3: Verify and document

**Files:**
- Modify: `docs/lim/g0-capability-inventory.md`

- [ ] Run focused metrics tests, complete LIM suite, backend suite in isolated SQLite, and frontend typecheck if the Console changes.
- [ ] Review diff and ensure no enterprise FR-011 files changed.
