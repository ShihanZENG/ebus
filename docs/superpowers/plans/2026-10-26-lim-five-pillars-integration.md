# LIM 五大能力集成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将五大 LIM 能力与工作台安全接入现有项目，并为 Storefront → ERP → OMS 的库存、订单和支付状态建立可验证的数据库基础。

**Architecture:** 现有主 ERP 数据库是订单和库存权威源；独立 OMS 通过事务 Outbox 接收版本化事件。新增 LIM 模块复用现有权限与治理 API，外部 Neo4j、Redis 和支付网关均通过显式适配器接入；没有外部服务时仅运行受控沙盘。

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL/SQLite tests, React, TypeScript, LangGraph, Neo4j, OpenTelemetry.

**Spec:** `docs/superpowers/specs/2026-10-26-lim-five-pillars-integration-design.md`

## Global Constraints

- 保留旧接口和测试；真实状态不得依赖进程内字典。
- 新 `/api/v1/lim/v2` 接口必须鉴权并强制店铺/仓库范围。
- 模拟付款不构成真实付款凭证；未验证真实付款不能发货。
- 外部交易 ID、Outbox 幂等键必须由数据库唯一约束保证。
- 台账只标记经过业务链路测试验证的能力。

## Review Focus

- 同一交易 ID 不同订单或金额的重复请求应冲突。
- 两个结账请求争抢最后库存时，最多一个成功。
- 订单与 Outbox 必须同事务提交或回滚。
- 超时与取消重复释放 Hold，库存只增加一次。
- 范围外用户不能通过自报店铺 ID 获取或写入跨店数据。

---

### Task 1: LIM 受控路由和五大模块

**Files:** `backend/app/lim_*.py`, `backend/app/main.py`, `backend/tests/test_lim_five_pillars_integration.py`, `backend/requirements.txt`

**Interfaces:** `router` prefix `/api/v1/lim/v2`; authenticated read endpoints and explicit sandbox execution.

- [ ] 写未授权请求、跨店铺请求和管理员沙盘请求测试，确认先失败。
- [ ] 引入压缩包模块并修正默认数据、作用域及无声降级问题。
- [ ] 在 `create_app` 内挂载路由，并合并依赖而不覆盖现有固定版本。
- [ ] 运行新测试和既有 LIM 测试。

### Task 2: 订单权威源、Hold、Outbox

**Files:** `backend/app/models.py`, `backend/app/storefront/service.py`, `backend/app/orders.py`, `backend/app/wms.py`, `backend/migrations/versions/0048_*.py`, `backend/tests/test_storefront_bridge.py`

**Interfaces:** 主库事务写订单、Hold、库存占用和版本化 Outbox；OMS 消费接口以事件 ID 去重。

- [ ] 写库存竞争、重复结账、到期释放、取消及 Outbox 回滚测试，确认先失败。
- [ ] 建立 Hold 与 Outbox 模型及迁移，增加可重试消费状态。
- [ ] 结账时原子占用库存；发货申请转换占用；取消/到期只释放一次。
- [ ] 运行 Storefront、WMS、OMS 测试。

### Task 3: 支付证据与发货门禁

**Files:** `backend/app/models.py`, `backend/app/payment_evidence.py`, `backend/app/orders.py`, `backend/app/wms.py`, `backend/migrations/versions/0048_*.py`, `backend/tests/test_payment_evidence.py`

**Interfaces:** `external_transaction_id` 可空且真实付款时必填，数据库唯一；真实订单发货须有已验证凭证。

- [ ] 写相同交易重放、不同内容冲突、未支付发货与模拟支付隔离测试，确认先失败。
- [ ] 增加唯一约束、付款登记幂等逻辑与最终出库门禁。
- [ ] 运行付款与仓储回归测试。

### Task 4: 工作台与文档

**Files:** `frontend/src/pages/LimEnterpriseWorkbenchPage.tsx`, `frontend/src/App.tsx`, `frontend/src/config/menu.ts`, `frontend/package.json`, `docs/lim/g0-capability-inventory.md`, `REPAIR_BACKLOG.md`

**Interfaces:** `/lim-workbench` 在 LIM 导航可访问；前端通过鉴权 API 读取，演示数据标注为沙盘。

- [ ] 写路由/权限与 API 状态测试，确认先失败。
- [ ] 接入页面，补齐加载/失败/空状态并安装所需前端依赖。
- [ ] 根据实际测试证据更新台账，保留未完成的外部服务契约条目。
- [ ] 运行全量后端测试与前端构建，检查 Git diff。
