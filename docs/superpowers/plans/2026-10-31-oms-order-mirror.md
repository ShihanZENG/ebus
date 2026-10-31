# Storefront OMS Order Mirror Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a Storefront order event from the ERP outbox to an independently queryable, read-only OMS mirror, with idempotent replay and retryable failures.

**Architecture:** ERP remains the order authority. OMS stores a read-only projection keyed by the ERP order ID and a versioned event key; ERP never writes directly into the OMS database. A service-authenticated OMS ingest endpoint receives the existing non-PII outbox payload. A configurable ERP worker claims pending events, posts them, and records delivery or a bounded retry. The OMS mirror never enters OMS's independent fulfillment state machine.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, httpx, pytest; existing ERP and OMS Python environments.

**Spec:** `REPAIR_BACKLOG.md` P0-01 and the user's approval to start the order handoff.

## Global Constraints

- Keep changes on `main`, as requested by the user; stage only this plan's files.
- Preserve the ERP Storefront checkout contract and existing demo database records.
- No cross-database foreign keys and no customer address/contact data in the bridge payload.
- Require an explicit shared bridge secret and an explicit OMS URL; no unauthenticated ingest or default secret.
- Replaying the same event must return the same OMS mirror; a changed payload for the same key must fail.
- OMS mirrors are read-only; OMS's existing `/orders` records remain separately owned.

## Review Focus

- Missing or wrong bridge secret must not create a mirror (Task 1 test).
- Same key with changed payload must return conflict, not overwrite (Task 1 test).
- HTTP timeout after OMS commit must be safe to retry (Tasks 1 and 2 tests).
- Concurrent worker claim must not send the same pending event twice at once (Task 2 test).
- OMS outage must leave an inspectable retry state, not mark delivery successful (Task 2 test).

---

### Task 1: OMS read-only mirror contract

**Files:** Create `oms/backend/app/order_mirror.py`; modify `oms/backend/app/models.py`, `oms/backend/app/main.py`; test `oms/backend/tests/test_order_mirror.py`.

**Interfaces:** `POST /internal/erp-order-mirrors` accepts `{event_id,idempotency_key,contract_version,event_type,payload}` with `X-OMS-Bridge-Secret`; `GET /api/v1/erp-order-mirrors/{erp_order_id}` requires `orders:read`. It returns the mirror ID, ERP order ID, source order number, digest, and received time. The payload's ERP IDs are opaque in OMS.

- [x] Write failing endpoint tests for authentication, first ingest, identical replay, changed replay, and staff readback.
- [x] Run isolated OMS test and observe failures.
- [x] Add model, schema validation, constant-time secret check, and insert/read endpoints.
- [x] Run isolated OMS test to green, then the OMS test suite.
- [x] Commit the task's files.

### Task 2: ERP outbox delivery and retry

**Files:** Create `backend/app/oms_outbox_delivery.py`, `backend/tests/test_oms_outbox_delivery.py`.

**Interfaces:** `deliver_once(session_factory, transport, oms_url, secret, now)` claims one eligible event, posts to the OMS endpoint, verifies the acknowledgment references the same ERP order and event key, and marks it delivered. Failure increments attempts, sets `next_attempt_at`, and records a bounded error. CLI `python -m app.oms_outbox_delivery --once|--loop` reads `OMS_BRIDGE_URL` and `OMS_BRIDGE_SECRET`.

- [x] Write failing tests for successful delivery, transient failure and retry, incorrect acknowledgment, and competing claim.
- [x] Run isolated ERP test and observe failures.
- [x] Implement claim, delivery, acknowledgment check, retry and CLI loop.
- [x] Run isolated ERP tests to green and the relevant Storefront bridge suite.
- [x] Commit the task's files.

### Task 3: Cross-system proof and operator instructions

**Files:** Modify `REPAIR_BACKLOG.md`; create `backend/tests/test_oms_bridge_contract.py` or equivalent isolated dual-app test; optionally add a short runbook under `docs/`.

**Interfaces:** An ERP outbox event delivered twice creates exactly one OMS mirror; a failed delivery stays retryable; staff can read the mirror by ERP order ID. Document configuration and the read-only boundary.

- [x] Write an integration contract test using isolated databases and an in-process OMS transport.
- [x] Run the test; the previously implemented contracts passed without further mapping.
- [x] Confirm no additional contract mapping is needed for the two apps to interoperate.
- [x] Run the integration test, relevant backend and OMS suites, and inspect the final diff.
- [ ] Commit only the plan's files and push `main` to `ebus`.
