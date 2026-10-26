# 收款凭据与核对实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为订单收款提供模拟/真实分类、手续费、私有凭据上传和人工核对闭环，并阻止模拟及待核对金额进入正式已收款统计。

**Architecture:** 扩展既有 PaymentRecord 和付款 API，新增兼容迁移与私有附件存储/API；付款核对保持为独立、可审计的显式动作。订单详情提供真实/模拟录入及核对界面，继续沿用现有权限、币种及订单范围校验。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy、Alembic、pytest、React、TypeScript、Ant Design、Vite。

**Spec:** `docs/superpowers/specs/2026-10-17-payment-evidence-design.md`

## Global Constraints

- 真实付款币种必须与订单币种一致。
- 手续费范围为 `0 <= fee_amount <= amount`，净额为毛额减手续费。
- 真实记录在人工核对前不计入正式已收款金额；模拟记录永不计入。
- 上传仅允许 PDF、PNG、JPG，最大 10 MiB；凭据保存在非公开本地目录。
- 附件读写使用 `payment_records:read` / `payment_records:write` 并校验订单店铺范围。
- 历史付款保持兼容且类型为 `legacy`；仅精确匹配的既有模拟样例回填为 `simulated`。

## Review Focus

- 文件扩展名与 MIME 不一致/伪造签名：后端测试拒绝并确认无文件、无记录残留。
- 超限/空附件与磁盘写入失败：API 测试确认失败时无半写付款。
- 越权订单 ID 访问附件：权限测试验证店铺范围外不可上传/读取/核对。
- 待核对与模拟记录：金额汇总测试验证其不影响正式已收款金额。
- 手续费极值、订单币种不符和重复核对：边界测试验证拒绝或幂等。

---

### Task 1: 付款领域、私有凭据 API 与兼容迁移

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/orders.py`
- Create: `backend/app/payment_evidence.py`
- Modify: `backend/app/main.py`
- Modify: `backend/migrations/env.py`
- Create: `backend/migrations/versions/0022_payment_evidence.py`
- Create: `backend/migrations/versions/0023_payment_evidence_recovery.py`
- Modify: `backend/requirements.txt` (declare the multipart parser required by FastAPI uploads)
- Test: `backend/tests/test_payment_evidence.py`

**Interfaces:**
- `PaymentRecord`: `record_type` (`legacy|simulated|real`), `fee_amount`, `reconciliation_status` (`legacy|not_required|pending|verified`), `evidence_name`, `evidence_key`, `evidence_content_type`, `evidence_size`, `evidence_sha256`, and `verified_at`.
- `POST /orders/{order_id}/payments`: preserve legacy payload compatibility; allow simulated type and fee; simulated is never verified.
- `POST /orders/{order_id}/payments/real`: one multipart request submits gross amount, fee, unique source reference, and evidence atomically; validate file bytes, actual media signature, 10 MiB cap, and shop scope.
- `GET /orders/{order_id}/payments/{payment_id}/evidence`: authorized private file response with shop scope.
- `POST /orders/{order_id}/payments/{payment_id}/reconcile`: explicit transition `pending -> verified`, require a real record and evidence; audit before/after.
- Order payment cap/progress sums gross `amount` for `legacy` plus `real/verified`; finance cash settlement sums `legacy.amount` plus `real/verified.net_amount`; neither counts `simulated` or `real/pending`.

- [ ] Write API tests for simulated exclusion, real evidence requirement, fee/currency validation, evidence upload signature/size, scope checks, interrupted-storage recovery and reconciliation transition.
- [ ] Run `python -m pytest tests/test_payment_evidence.py -q` and confirm it fails on missing schema/routes/behavior.
- [ ] Add fields and migrations with safe server defaults; add private randomized staged storage and startup recovery; add authorized upload/read routes, auditable reconciliation and non-duplicated financial aggregates.
- [ ] Run focused API tests, then `python -m pytest tests/test_oms.py tests/test_business_acceptance.py tests/test_oms_edit.py tests/test_after_sales_execution.py tests/test_payment_evidence.py -q`.
- [ ] Confirm all pass and migration upgrades/downgrades in isolated migration tests or a temporary test database.

### Task 2: Order detail UI for evidence capture and reconciliation

**Files:**
- Modify: `frontend/src/pages/Orders.tsx`
- Test: `frontend/tests/paymentEvidence.test.mjs` (pure display/validation helpers if needed)
- Modify: `frontend/package.json` only to add the focused test command if needed

**Interfaces:**
- Use Task 1 payment response fields and multipart upload API; never write payment rows before a real attachment upload succeeds.
- Simulated records require an explicit “模拟” selection and show a persistent non-real badge.
- Real records require source reference, gross amount, fee, and attachment; display computed net and pending-review state.
- Reconciliation button appears only for pending real payment with write permission; confirmation sends the dedicated reconcile request and refreshes detail.
- Table shows amount, fee, net, type, reconciliation state, evidence name, source, paid time, remark; private evidence can be opened by authorized readers.

- [ ] Add focused tests for mode-specific required fields and gross-fee net calculation.
- [ ] Run the focused frontend test first and confirm expected failure.
- [ ] Implement the order detail capture/reconcile UI and mode-specific validation.
- [ ] Run focused frontend test and `npm run build`.

### Task 3: Migration and end-to-end acceptance

**Files:**
- Modify: `docs/superpowers/specs/2026-10-17-payment-evidence-design.md` or acceptance documentation only if findings require clarification.
- Test: `backend/tests/test_payment_evidence.py` plus focused existing suites.

- [ ] Run the Alembic migration against an isolated copy/test DB and verify legacy rows survive, the exact simulated sample is labeled simulated, and no unrelated row changes classification.
- [ ] Run backend acceptance tests and frontend build afresh; inspect the resulting payment API and relevant UI states.
- [ ] Verify simulated rows are visually labeled and excluded from confirmed totals; real rows stay pending until an authorized explicit reconciliation action.
- [ ] Report any remaining limitation, especially local-only private evidence storage and absence of actual platform/bank verification.
