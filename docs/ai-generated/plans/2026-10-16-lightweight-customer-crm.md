# 轻量客户档案 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add shop-scoped customer profiles that can be linked to existing and new sales orders and support tickets.

**Architecture:** Add a customer master table and nullable customer foreign keys to orders and tickets. A dedicated customer API enforces shop scope and records audit events; the frontend gets a customer list, profile editor, and linked order/ticket view. Existing records remain unlinked until a user explicitly associates them.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, React, TypeScript, Ant Design, pytest.

**Spec:** `docs/统一系统与八模块规划.md` (customer and support module boundary).

## Global Constraints

- Customers are isolated by shop; all reads and writes obey `shop_scope`.
- Do not merge legacy orders or tickets by matching names or contact strings.
- Keep existing order customer name/contact snapshots intact when associating a profile.
- No hard delete of customer profiles; keep foreign key references and audit history.
- Link an order or ticket only when it belongs to the same shop as the customer.

## Review Focus

- A user with an empty shop scope must see no customers and cannot create or link records.
- A customer/order/ticket cross-shop association must fail without changing either record.
- Existing records with null customer IDs must continue to list and operate normally.
- Duplicate customer names and contact values are allowed; no automatic identity merge.
- A caller with customer permission alone must not see linked order/ticket details without the corresponding read permissions.

---

### Task 1: Customer API and persistent links

**Files:**
- Create: `backend/app/customers.py`
- Create: `backend/migrations/versions/0021_customer_profiles.py`
- Modify: `backend/app/models.py`, `backend/app/customer_tickets.py`, `backend/app/schemas.py`, `backend/app/main.py`
- Test: `backend/tests/test_customer_profiles.py`

**Interfaces:**
- `Customer(shop_id, name, contact, notes, is_active)` is a shop-owned master record.
- `GET/POST /api/v1/customers`, `GET/PATCH /api/v1/customers/{id}`, and `GET /api/v1/customers/{id}/links`.
- `POST /api/v1/customers/{id}/orders/{order_id}` and `/tickets/{ticket_id}` explicitly associate records.
- Customer profile access uses `customers:read/write`; linked order/ticket details and associations additionally require their own module permissions.

- [x] Write tests for shop-scope filtering, empty scope, cross-shop rejection, linked order/ticket views, and related-permission boundaries.
- [x] Run tests first and verify expected missing-route failures.
- [x] Add customer table and nullable `customer_id` foreign keys with downgrade support.
- [x] Implement customer API with audit events and same-shop validation.
- [x] Run the focused tests and existing order/ticket suites (`30 passed`; the corrected CRM permission-scope test was re-run in the focused 3-test suite).

### Task 2: Customer directory UI

**Files:**
- Create: `frontend/src/pages/CustomersPage.tsx`
- Modify: `frontend/src/config/menu.ts`, `frontend/src/App.tsx`
- Test: production frontend build and browser verification.

- [x] Add a permission-guarded Customers route and sidebar item.
- [x] Build profile search/create/edit, shop scope, and a details drawer for linked orders and tickets.
- [x] Add explicit association controls for unlinked same-shop orders/tickets; preserve legacy snapshots.
- [x] Build frontend and verify customer listing route in browser; permission and cross-shop behavior covered by API tests.

### Task 3: Create-time linking and handoff

**Files:**
- Modify: `backend/app/schemas.py`, `backend/app/orders.py`, `backend/app/customer_tickets.py`, `frontend/src/pages/Orders.tsx`, `frontend/src/pages/CustomerTicketsPage.tsx`, `docs/统一系统与八模块规划.md`.
- Test: `backend/tests/test_customer_profiles.py`, focused OMS and ticket suites.

- [x] Accept optional `customer_id` on order and ticket creation and validate same-shop scope.
- [x] Order/ticket API snapshots expose the profile foreign key; the customer directory displays both linked record sets.
- [x] Run focused backend tests, frontend build, and browser verification.
- [x] Record shipped scope, permission requirements, and remaining CRM boundaries in the roadmap.
