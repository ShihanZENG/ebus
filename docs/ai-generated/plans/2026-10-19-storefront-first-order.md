# Storefront First Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成一款女装的真实 API 演示订单闭环：顾客下单、ERP 审核/预留/出库、前台读取状态；无真实支付。

**Architecture:** 独立 React 商城和受限 FastAPI storefront 接口；复用现有订单和 WMS 服务。显式启用演示应用，单独 PostgreSQL 数据库 `erp_storefront_demo`；原应用默认不开放商城接口。

**Tech Stack:** 已有 React18、TypeScript、Vite6、FastAPI、SQLAlchemy、Alembic、PostgreSQL15；pytest + Node test。

**Spec:** `docs/superpowers/specs/2026-10-19-uk-fashion-storefront-design.md`

## Global Constraints

- 中文、GBP、固定 GB 配送，演示运费 0、无折扣、无真实税费计算；不接收付款或支付卡信息。
- 不改原库存占用时点；提交 draft，审核 approved，申请发货 shipping_requested，出库 fulfilled。
- 公共价格后端计算、Decimal 两位字符串；真实订单权限与公共查单令牌隔离。
- 此计划只实现第一笔闭环及单款发布管理；10 款扩充、全内容 CMS、真实支付/物流仍在后续范围。
- 不读取/输出凭据；运行脚本从现有配置在内存派生独立演示库地址。
- 当前不是 Git 仓库，不初始化 Git；修改前保留相关源文件副本，保留工作记录，不执行工作树/提交/清理脚本。

## Review Focus

- 并发同幂等键不能产生第二笔订单，泄露幂等键不能获得查单权限。
- 失活、下架、价格版本变化和跨店专属库存不能被旧购物袋绕过。
- 演示入口默认关闭，不能在现有未升级数据库上触发新表查询。
- ERP 编辑和换仓不能使顾客快照/可售仓规则失真。
- 页面刷新、网络重试、不同订单访问令牌、后台异常要明确反馈，不伪造成功。

## Task 1: Public catalogue + checkout + ERP round trip

**Files:** create `backend/app/storefront/{__init__,models,schemas,service,routes}.py`, `backend/migrations/versions/0027_storefront.py`, `backend/tests/test_storefront.py`; modify `backend/app/{main,orders,schemas}.py`, `backend/migrations/env.py`.

**Interfaces:** public `/api/storefront/v1/site`, `/products`, `/products/{slug}`, POST `/checkout`, GET `/orders/{public_id}`. Admin `/api/v1/storefront/site` GET/PUT and `/products` GET/POST, `/products/{id}` PATCH. DTO contains GBP amount strings, `demo:true`; checkout uses `Idempotency-Key`, `X-Checkout-Recovery`, returns one-order access token. No public ERP ids or private remarks.

- [ ] Write `test_disabled_by_default`, `test_catalogue_checkout_and_fulfilment`, `test_checkout_replay_and_order_access`, `test_price_publish_and_scope_guards`, `test_cancel_releases_only_once`; assert literal money `29.00`, no PaymentRecord, stock 3/0 → 3/1 → 2/0, no private fields.
- [ ] Run new tests; expect 404 failures before routes exist.
- [ ] Implement models, explicit migration, DTO validators and services using existing `validate_order_refs`, `build_items`, `inventory_allocation.available`, WMS flow. Atomically insert unique idempotency row; verify recovery secret before rotating returned token.
- [ ] Ensure existing ERP edits cannot rewrite storefront snapshot or select another warehouse; expose address only on authorized ERP detail.
- [ ] Run new tests and existing OMS/WMS/permissions tests; inspect output. PostgreSQL concurrency checks belong to Task 4.

## Task 2: Independent customer store and ERP publish screen

**Files:** create `storefront/{package.json,tsconfig.json,vite.config.ts,index.html,src/*,tests/*}`; modify `frontend/src/{App.tsx,config/menu.ts,pages/Orders.tsx}`; create `frontend/src/pages/StorefrontPage.tsx`.

**Interfaces:** use Task 1 DTOs; per-submission recovery credentials and idempotency key survive retry in sessionStorage, access tokens in Authorization only. ERP uses existing `/api/v1` client with `storefront:read/write` permissions.

- [ ] Write Node tests for cart merging/stock limits, currency sums and stable submission state; run RED before helper implementation.
- [ ] Implement Chinese responsive storefront with published catalogue, selected variants, cart, validated address form, explicit demo checkout and refreshable order status. No ERP token/import or admin config in storefront.
- [ ] Implement publication/price editing for seeded catalogue and site read-only operational summary. Add isolated-environment warning and address to ERP detail.
- [ ] Run Node tests, storefront production build and existing ERP typecheck/build.

## Task 3: Isolated local setup and repeatable seed

**Files:** create `backend/app/storefront/demo.py`, `backend/scripts/storefront_demo.py`, `tools/start-storefront-demo.ps1`, `storefront/README.md`; modify `frontend/vite.config.ts` only for explicit proxy target override.

**Interfaces:** initializer derives a PostgreSQL URL with database exactly `erp_storefront_demo`, only loopback host; uses original db credentials in memory, never echoes. API 18081, storefront 15174, demo ERP 15175; existing 18080/15173 left unchanged.

- [ ] Write test for seed rerun preserving prices, inventory and passwords, plus database guard; run RED.
- [ ] Create isolated database only if absent, migrate that database only, seed one product/6 variants with 3 units each and publish. Existing rows remain unchanged. Demo backend validates DB name before startup.
- [ ] Add repeatable local launcher and instructions, without killing unrelated processes. All servers bind loopback.
- [ ] Initialize twice; verify no duplicate catalogue or replenished consumed stock; start demo services.

## Task 4: Verification and handoff

**Files:** create `backend/tests/test_storefront_postgres.py` for scoped concurrency; record evidence in plan ledger.

- [ ] On dedicated test schemas, verify concurrent duplicate submit yields one order; two orders claiming last unit yield one reservation; multi-SKU reservation failure rolls back. Do not use SQLite as row-lock evidence.
- [ ] Run full backend pytest suite and Node suites, both frontend builds; report any unrelated baseline failure explicitly.
- [ ] Browser: choose variant, submit using synthetic address, see actual new order in demo ERP, approve/ship, refresh customer order; check 390px layout and error states. No real payment or external dispatch.
- [ ] Fresh independent code review (one reviewer), fix important findings with RED/GREEN tests; save startup URLs and known remaining scope.

## Self review

The full design is deliberately staged: initial usable order path now; content CMS, broad product collection and production readiness later. Source/config changes are local, database isolated. Test/consumer DTOs must stay aligned. No model-generated fulfilment decisions or actual financial actions are introduced.
