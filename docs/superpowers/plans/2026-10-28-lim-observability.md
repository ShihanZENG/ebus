# LIM Live Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist a truthful live-run evaluation, expose an authorized timeline, and connect configured OpenTelemetry and Langfuse backends.

**Architecture:** Reuse existing Workflow/Run/Span/ToolInvocation records as the source of trace facts. Save a versioned evaluation snapshot on the live run. Emit OTel spans during execution, then publish metadata-only Langfuse observations and scores after commit. Show all three layers in the workbench.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, OpenTelemetry SDK, Langfuse SDK, React/Ant Design.

**Spec:** `docs/superpowers/specs/2026-10-28-lim-observability-design.md`

## Global Constraints

- Do not emit business values, credentials, raw prompts, or customer data to external telemetry.
- No LLM usage or generated-claim faithfulness score for deterministic runs.
- External outages cannot fail the ERP workflow.
- Every read and export rechecks the current actor and scope.

## Review Focus

- A resumed run must not duplicate completed domain observations.
- A partially failed run must preserve its failure in the timeline.
- Missing external configuration must be distinguishable from a verified connection.
- A revoked scope must deny historical trace access.
- Evaluation labels must describe exactly what the denominator measures.

---

### Task 1: Persisted evaluation and authorized trace

**Files:** `backend/app/lim_live_models.py`, `backend/migrations/versions/0050_lim_live_evaluation.py`, `backend/app/lim_live_observability.py`, `backend/app/lim_live.py`, `backend/tests/test_lim_live.py`.

- [x] Write failing tests for historical trace, metric basis, unavailable scores, failed/resumed runs and scope.
- [x] Run focused tests and confirm failure.
- [x] Implement the database snapshot and read route.
- [x] Run focused tests and migration check.

### Task 2: External telemetry adapters

**Files:** `backend/app/lim_live_observability.py`, `backend/app/lim_live_connections.py`, `backend/tests/test_lim_live.py`, `backend/tests/test_lim_live_otel_export.py`, `backend/.env.example`.

- [x] Add in-memory OTel, OTLP HTTP receiver, and fake Langfuse tests.
- [x] Emit nested OTel spans during execution and publish metadata-only Langfuse traces/scores after commit; preserve manual retry.
- [x] Verify failure isolation, result status and focused tests.

### Task 3: Workbench and end-to-end verification

**Files:** `frontend/src/pages/LimLiveWorkbenchPage.tsx`, `backend/README.md`, `docs/lim/g0-capability-inventory.md`.

- [x] Add timeline and metric cards with explicit basis/unavailable states.
- [x] Run TypeScript and production build.
- [x] Run backend tests, migrate local database, execute a real run through the API, and verify external receiver status honestly.

The in-app browser automation timed out twice on this host. HTTP/API smoke checks and the production build succeeded. The user has no Langfuse instance yet, so platform readback remains outside this local verification scope. Docker image registry requests for the optional local Jaeger container failed; OTLP HTTP delivery was verified against a local protocol receiver test.
