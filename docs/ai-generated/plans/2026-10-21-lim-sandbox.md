# LIM Sandbox Mock Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Deliver a bounded LIM Sandbox path that validates Agent/Tool contracts and records mock execution traces without calling business handlers.

**Architecture:** Add an execution-mode marker to the existing LIM Run, implement a dedicated mock-only runner that uses the normal Run state machine and trace records, expose an authenticated route, and add a Sandbox panel to the LIM Console. The runner never resolves or calls registered handlers.

**Tech Stack:** Existing FastAPI, SQLAlchemy, Alembic, pytest, React, TypeScript, Ant Design.

**Spec:** `docs/superpowers/specs/2026-10-21-lim-sandbox-design.md`

## Global Constraints

- Preserve shared worktree changes; inspect latest versions before editing shared files.
- Add migration `0035` after the current LIM head `0034`; do not rewrite prior revisions.
- Do not call real read/write handlers, external systems, LLMs, or business-data queries from Sandbox.
- Do not accept caller-supplied Scope or budget; persist empty sandbox Scope and fixed server budget.
- Mock results are not business evidence and must not enter evidence aggregation.
- Do not commit changes in the shared checkout.

## Review Focus

- A real handler must remain uncalled, including for Tool definitions marked write.
- Unsupported Agent/Tool version or Tool not allowed must fail before creating a Run.
- Invalid input/output Schema and oversized nested payloads must be rejected with no persisted Run.
- Caller-supplied scope/budget cannot change empty scope or fixed budget.
- Trace output containing secret/PII fields must be sanitized and carry no EvidenceRef.

## File Map

- Modify `backend/app/lim_models.py`: add `LimRun.execution_mode` defaulting to `live`.
- Create migration `0035_lim_sandbox_execution_mode.py`.
- Create `backend/app/lim_sandbox.py`: fixed-version schema validation and mock-only lifecycle orchestration.
- Modify `backend/app/lim_routes.py`: typed Sandbox Run endpoint and return execution mode in Run JSON.
- Modify `backend/tests/test_lim_sandbox.py`: handler non-invocation, access, scope, budget, schema, trace, migration checks.
- Modify `frontend/src/api/lim.ts` and `frontend/src/pages/LimConsolePage.tsx`: typed Sandbox API, mode label, and explicit mock input/output panel.
- Modify `backend/README.md`: document what Sandbox does and does not isolate.

## Tasks

### Task 1: Run execution mode and sandbox runner

- [x] Add failing tests for mock-only behavior, Schema rejection, fixed Scope/budget, sanitized trace, and read/write mock Tool handling.
- [x] Implement `execution_mode` and migration `0035` with a backward-compatible `live` default.
- [x] Implement `create_sandbox_run(db, actor, agent_id, agent_version, tool_id, tool_version, arguments, mock_response)` with fixed budget and no handler imports/lookups.
- [x] Reuse the Run state path and existing Span/Invocation; validate output, store sandbox marker, and keep Evidence refs empty.
- [x] Run sandbox and migration tests.

### Task 2: API and Console

- [x] Add `SandboxRunInput` and `POST /sandbox/runs` behind `assistant:read`.
- [x] Return `execution_mode` from Run/Trace APIs.
- [x] Add typed frontend helper and Sandbox UI; label output as mock/simulation.
- [x] Show execution mode on the existing Run and Trace views.
- [x] Run focused API tests and frontend build.

### Task 3: Verification and status refresh

- [x] Document the application-level isolation boundary in `backend/README.md` and G0 inventory.
- [x] Run LIM focused regressions, migration seed consistency, `git diff --check`, and frontend build.
- [x] Confirm PRD LIM-FR-022 remains partial until real isolation/deployment controls are proven.
