# LIM Demo Seed Implementation Plan

> **For agentic workers:** Implement this plan task-by-task in the current shared checkout, which the coordinating task has declared frozen for this scoped change.

**Goal:** Fresh and existing initialized environments have one idempotently seeded read-only operations Tool attached to the built-in read-only Agent, enabling a real constrained Run and Trace from the LIM Console.

**Architecture:** Reuse the existing `erp.operations.snapshot` server-side handler and LIM validation/runtime. Seed the active Tool and bind it to the built-in `business-assistant` Agent in `bootstrap`; verify bootstrap idempotency and the API Run→Trace path in the focused LIM API tests.

**Tech Stack:** Python, SQLAlchemy, FastAPI, pytest.

**Spec:** Supervisor-approved AI MVP scope from the attached AI Platform Admin PRD: a safe management loop to inspect/configure an existing Agent or Tool, run one bounded read-only demonstration, and inspect status and Trace.

## Global Constraints

- Only modify AI/LIM-related code and tests.
- Only execute registered read-only handlers; the seed Tool must use server-derived scope.
- Do not expand FR-020 or the broader PRD; do not modify enterprise order APIs.
- Keep the seed idempotent across repeated bootstrap calls.

## Review Focus

- Repeated bootstrap must not duplicate the seeded Agent or Tool.
- The built-in Agent must not become runnable until its Tool is active and attached.
- Run must complete through the real registered read handler and expose its Trace to the authorized caller.
- Trace must include tool invocation evidence while excluding sensitive credentials.
- No client-provided scope or write operation may be introduced.

### Task 1: Seed a runnable read-only demo configuration

**Files:**
- Modify: `backend/app/bootstrap.py`
- Test: `backend/tests/test_lim_api.py`

**Interfaces:**
- Reuse `erp.operations.snapshot` from `backend/app/lim_runtime.py`.
- Reuse `bootstrap(db, username, password, demo=False)` and current LIM Run/Trace APIs.

- [x] Add a failing API test that repeats bootstrap and asserts one active `erp.operations.snapshot` Tool is attached to the validated `business-assistant` Agent, including normalization of the older seed definition.
- [x] Run that focused test and verify it fails because no Tool/association is seeded.
- [x] Seed the Tool with read/low-risk policy, closed empty-object schemas, `not_applicable` idempotency, and server-side shop/warehouse scope; bind it to the existing built-in Agent.
- [x] Add/run a focused API assertion that the seeded Agent performs one actual Run to `COMPLETED`, then its Trace contains the invocation and no API key material.
- [x] Run the focused LIM API module: `python -m pytest tests/test_lim_api.py -q` → 8 passed.
