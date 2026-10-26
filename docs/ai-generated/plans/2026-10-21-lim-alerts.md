# LIM Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver the local LIM-FR-024 alert lifecycle with persisted rolling-window rules, deduplicated Run/Tool/Workflow alerts, acknowledgements, and Console management.

**Architecture:** Add two LIM tables and default rules in migration `0036`; a service records threshold crossings from terminal Run, timeout Invocation, and eligible Workflow parent events. Authenticated APIs expose alert/rule records and audited lifecycle actions; the Console adds a read/manage tab. Error and trace contents are never copied into alerts.

**Tech Stack:** Existing FastAPI, SQLAlchemy, Alembic, pytest, React, TypeScript, Ant Design.

**Spec:** `docs/superpowers/specs/2026-10-21-lim-alerts-design.md`

## Global Constraints

- Use migration `0036` after `0035`; never upgrade the shared development database.
- Alert only live runs; Sandbox and cancellations are excluded.
- Count Tool timeout only in the timeout rule; suppress duplicate Run/Workflow parent events when a child already accounts for failure.
- Do not persist goal, tool arguments/results, exception text, or Trace contents in alert records.
- Do not send external notifications; show that production notification channels are unconfigured.

## Review Focus

- Below-threshold and duplicate events: no early alert; one stable alert per rule/entity, updated on repeated events.
- Tool returns after `timeout_ms`: terminal Run fails with no result/evidence; only timeout rule counts it.
- Workflow failure caused by a failed child Run: no second parent alert.
- Sandbox, cancellation, validation rejection, and out-of-scope runs: no operational alert.
- Non-owner reads and non-manager mutations: enforce existing LIM permission and visibility rules.
- Alert summary and audits: contain no user input, error detail, or Trace payload.

## File Map

- Modify `backend/app/lim_models.py`: `LimAlertRule`, `LimAlert` persistence.
- Create migration `backend/migrations/versions/0036_lim_alerts.py`: tables, indexes, default rules, reversible downgrade.
- Create `backend/app/lim_alerts.py`: event counting, dedupe/upsert, transitions, serialization.
- Modify `backend/app/lim_runtime.py` and `backend/app/lim_workflow.py`: emit eligible failure/timeout events.
- Modify `backend/app/lim_routes.py`: list/rule/ack/close endpoints and visibility.
- Create `backend/tests/test_lim_alerts.py`; extend runtime/workflow tests only where useful.
- Modify `frontend/src/api/lim.ts` and `frontend/src/pages/LimConsolePage.tsx`: Alerts tab and rule/lifecycle actions.
- Update `backend/README.md` and `docs/lim/g0-capability-inventory.md`.

## Tasks

### Task 1: Persist rules and deduplicated alerts

- [x] Write failing tests for default rules, threshold crossing, stable dedupe, rolling windows, and no sensitive payload copies.
- [x] Add `LimAlertRule` and `LimAlert` models plus reversible migration `0036` and three seed rules.
- [x] Implement `record_run_failure`, `record_tool_timeout`, and `record_workflow_failure` using persisted rule values and rolling-window queries.
- [x] Implement `acknowledge_alert` and `close_alert`; audit actor and status only.
- [x] Verify tests against isolated SQLite; do not touch the shared database.

### Task 2: Emit from runtime and Workflow without duplicate parent alerts

- [x] Test that live execution failures count, while Sandbox/cancel/pre-execution rejection or validation failures (including unknown tool, invalid arguments, and scope rejection) and `TOOL_TIMEOUT` Run failures do not count as generic failures.
- [x] Detect post-return Tool duration above `timeout_ms`, mark Invocation TIMEOUT and Run FAILED/TOOL_TIMEOUT, discard result/evidence, and record only the Tool timeout event.
- [x] Hook terminal Run and eligible Workflow events into the alert service; skip Workflow parent event when a child Run already represents it.
- [x] Verify timeout and Workflow regression tests.

### Task 3: API, permissions, and Console

- [x] Add pagination/state filtering, rule read/update, acknowledge, and close endpoints with existing permission requirements.
- [x] Add owner-aware alert visibility and Run/Trace/Workflow references.
- [x] Add the Console Alerts tab, rule editor, lifecycle actions, links to trace views, and unconfigured-notification notice.
- [x] Run API tests and frontend production build.

### Task 4: Documentation and status

- [x] Document defaults, status workflow, sync-timeout limitation, and notification boundary.
- [x] Update G0 FR-024 to partial local implementation; keep production notification unverified.
- [x] Run focused LIM regressions, isolated `0036` upgrade/downgrade and Alembic check, and `git diff --check`.
