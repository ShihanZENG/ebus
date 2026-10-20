# 出库确认与运单录入 Implementation Plan

> **For agentic workers:** Inline execution was requested. Follow this plan task-by-task and use TDD.

**Goal:** Make picking shipments confirmable in the UI, require a tracking number in the UI flow, and verify that confirmation converts reserved stock into shipped stock.

**Architecture:** Preserve the existing FastAPI confirmation endpoint and its inventory transaction behavior. Correct the frontend's status contract (`picking` / `shipped` / `cancelled`), extract small pure helpers for status and tracking validation, and use them in the confirmation dialog.

**Tech Stack:** React, TypeScript, Ant Design, Node.js `node:test`, existing FastAPI/pytest acceptance suite.

**Spec:** `docs/一期完成目标与验收标准.md` — FBM: order approval → inventory reservation → warehouse dispatch → enter/sync tracking number; do not show success when a required step is missing.

## Global Constraints

- Do not fabricate or register a payment; this task covers shipment only.
- Keep the existing `/api/v1/shipments/{shipment_id}/confirm` contract and backend inventory transaction logic.
- Only confirm the explicitly identified local MANUAL-VERIFY demonstration order, using an unmistakable TEST-prefixed tracking number.
- Do not claim platform/carrier synchronization; the demo shipment is a local ERP validation.

## Review Focus

- Backend `picking` state must expose confirmation, not a completed label — unit test the helper and verify the real page.
- Empty or whitespace tracking values must be blocked in the UI — unit test validation and exercise the modal.
- Successful confirmation must not double-decrement stock — existing API test covers repeated confirmation; rerun it.
- Warehouse restrictions must remain enforced — existing WMS/API permission tests cover the endpoint; run them.
- Payment must remain absent without evidence — verify the selected order detail after shipment.

---

### Task 1: Shipment UI state and tracking validation

**Files:**
- Create: `frontend/src/pages/shipmentStatus.mjs`
- Create: `frontend/src/pages/shipmentStatus.d.mts`
- Create: `frontend/tests/shipmentStatus.test.mjs`
- Modify: `frontend/package.json`
- Modify: `frontend/src/pages/ShipmentsPage.tsx`

**Interfaces:**
- Produces `canConfirmShipment(status: string): boolean`, `isTrackingNumberValid(value: string): boolean`, and `STATUS_TAG` keyed by backend shipment states.
- `ShipmentsPage.tsx` consumes these helpers without changing API paths or payload shape.

- [ ] Write tests proving `picking` is confirmable, `shipped`/`cancelled` are not, status labels map correctly, and blank/whitespace tracking values are invalid.
- [ ] Run `npm run test:shipments` and confirm the new imports fail because the helper does not exist yet.
- [ ] Implement the helpers and type declarations; update the page to show a `确认出库` action only for `picking`, show the proper status label, and prevent submit until a nonblank tracking number is provided.
- [ ] Run `npm run test:shipments` and `npm run build` from `frontend/`.

### Task 2: End-to-end demo acceptance

**Files:**
- No additional source files; verify the existing backend and local ERP records.

**Interfaces:**
- Consume the existing confirmation API and inventory/transactions read APIs; do not create a payment record.

- [ ] Run focused backend tests: `pytest -q tests/test_wms.py tests/test_business_acceptance.py tests/test_scm_warehouse_write_scope.py` from `backend/`.
- [ ] In the local UI, confirm shipment `AD8294D3` for `MANUAL-VERIFY-IMP-001` with a clearly test-only tracking value (`TEST-AD8294D3`).
- [ ] Verify shipment is `shipped`, order is `fulfilled`, LA stock is 317 on hand / 0 reserved, and a shipment inventory transaction links to this order.
- [ ] Verify order payment details still show no payment record; do not use the payment form.
