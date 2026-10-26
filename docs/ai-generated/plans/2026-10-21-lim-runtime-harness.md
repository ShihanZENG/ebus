# LIM Runtime 与 Harness 首批实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 G0 AI 能力盘点，并在现有 ERP 工程交付统一的 Agent/Tool Registry、只读 Scope 控制、Run/Trace 与基础 Golden Dataset Eval 纵切。

**Architecture:** LIM 使用现有 FastAPI/SQLAlchemy/Alembic 服务和认证/审计机制，不另建微服务。新增 LIM 专属持久化模型、业务服务和 API；从现有授权上下文构造 scope，只读工具通过显式适配器调用现有业务服务。React 管理页通过同一 API 管理配置、查看运行和执行固定数据集评测。

**Tech Stack:** Python 3、FastAPI、Pydantic、SQLAlchemy、Alembic、PostgreSQL、React、TypeScript、Vite、Ant Design。

**Spec:** `docs/superpowers/specs/2026-10-21-lim-runtime-harness-design.md`

## Global Constraints

- 现有业务数据库继续作为 SKU/订单/库存/采购/财务权威来源。
- `require_scope` 和服务端登录/角色授权为数据授权依据；模型不得修改 `scope_ref`。
- 本阶段生产只读；不执行外部副作用或生产写工具。
- API Key 不进入前端；Trace 输入输出最小化并脱敏。
- GraphRAG、长期记忆、完整 Workflow Studio、生产发布灰度不属于本批。

## Review Focus

- 伪造租户、店铺或仓库标识的请求：按服务端用户范围拒绝，且不泄露资源存在性。
- 未登录、过期会话和只读审计角色写配置：分别返回 401/403 并保留必要审计。
- Agent 引用未知/写入/缺 Schema 工具：校验失败，不能运行。
- 并发或重复状态更新：只接受合法单向状态迁移，不能重复终结同一 Run。
- Trace 中出现密钥、邮箱、电话或异常输入：API/导出不得暴露原始敏感值。

## File Map

- Create `docs/lim/g0-capability-inventory.md`：以 PRD 能力 ID 为行，记录实现、联通、验收、生产状态及证据路径。
- Create `backend/app/lim_models.py`：LIM Agent/Tool/Run/Span/Invocation/Dataset/Eval 持久化模型。
- Create Alembic migration after current head：创建 LIM 专属表和索引，保留现有采购 Agent 历史。
- Modify `backend/migrations/env.py`：导入 LIM 模型以注册 metadata。
- Create `backend/app/lim_registry.py`：Agent/Tool 的 Pydantic schema、静态校验和版本规则。
- Create `backend/app/lim_scope.py`：由认证用户构造 server-side scope，并集中执行权限检查。
- Create `backend/app/lim_errors.py`：在 Scope、Runtime、API 之间共享机器可读 LIM 错误码。
- Create `backend/app/lim_runtime.py`：Run 状态机、只读工具调度、span/调用记录和脱敏。
- Create `backend/app/lim_evaluation.py`：Golden Dataset CRUD、固定版本 Eval Run 与逐例结果。
- Create `backend/app/lim_routes.py`：认证和权限保护的 LIM API。
- Modify `backend/app/main.py`：注册 LIM router。
- Tests in `backend/tests/test_lim_*.py`：隔离验证 Registry、scope、状态机、脱敏、评测 API。
- Create `frontend/src/api/lim.ts`：LIM 请求/响应类型与 API 函数。
- Create `frontend/src/pages/LimConsolePage.tsx`：Agent、Tool、Runs/Traces、Eval 的首批管理页。
- Modify `frontend/src/App.tsx` and `frontend/src/config/menu.ts`：注册 `/lim/*` 路由和权限菜单。
- Modify `backend/README.md` and `README.md` only where required：迁移、入口和能力边界说明。

## Tasks

### Task 1: G0 capability inventory

**Files:**
- Create: `docs/lim/g0-capability-inventory.md`
- Read: `backend/app/assistant.py`, `backend/app/product_agent.py`, `backend/app/operations_agent.py`, `backend/app/listing_agent.py`, `backend/app/purchase_agent.py`, `backend/app/security.py`, relevant routers, migrations, tests, frontend pages.

- [x] Map PRD LIM-FR-001–024 and phases G0–G4 into implemented, connected, accepted, production-ready columns; cite exact file/API/test evidence.
- [x] Mark unknowns as unverified; do not infer a feature from page labels or model names.
- [x] Record reuse decisions for purchase AgentRun/AgentToolCall and current role/shop/warehouse checks.
- [x] Review inventory against PRD and ensure every ID has a status and gap/next action.

### Task 2: LIM persistence and migration

**Files:**
- Create: `backend/app/lim_models.py`
- Create: `backend/migrations/versions/<next>_lim_runtime_harness.py`
- Modify: `backend/app/main.py` (model import registration only if needed by metadata discovery)
- Test: `backend/tests/test_lim_models.py` (ORM constraints and persistence)
- Test: `backend/tests/test_lim_migration.py` (Alembic upgrade and table presence)

**Interfaces:**
- `LimAgent`: stable `agent_id`, JSON definition, status, current version, owner and timestamps.
- `LimTool`: stable `tool_id`, JSON schemas, domain, operation kind, scope policy, risk, timeout, idempotency mode and status.
- `LimRun`: actor, server-generated scope reference, agent/version, status, trace ID, budget, error code and timestamps.
- `LimSpan` and `LimToolInvocation`: trace hierarchy, versioned tool reference, status, sanitized summaries, evidence refs and cost/token fields nullable when unavailable.
- `LimEvalDataset`, `LimEvalCase`, `LimEvalRun`, `LimEvalCaseResult`: immutable versioned cases and per-case results.

- [x] Write model tests for unique IDs/version keys, allowed status constraints, foreign-key behavior and JSON fields.
- [x] Run targeted tests and confirm they fail before model/migration implementation.
- [x] Implement tables with existing `Record` conventions; use indexes for IDs/status/time queries and never store API secrets or raw PII by default.
- [x] Generate migration after inspecting the current Alembic head; include reversible upgrade/downgrade and no mutation of legacy tables.
- [x] Run migration/model tests against the repository's test database configuration.

### Task 3: Agent and Tool Registry validation

**Files:**
- Create: `backend/app/lim_registry.py`
- Create: `backend/tests/test_lim_registry.py`
- Depends on: Task 2.

**Interfaces:**
- `validate_agent_definition(definition: AgentDefinition, tools: Mapping[str, LimTool]) -> list[ValidationIssue]`
- `validate_tool_definition(definition: ToolDefinition) -> list[ValidationIssue]`
- Definitions carry explicit input/output JSON Schema, allowed tool IDs, owner, version, domain, risk tier and runtime profile.

- [x] Add failing tests for missing output schema, unknown tool, write tool binding, missing scope/risk/timeout metadata and valid read-only definitions.
- [x] Implement deterministic schema and reference validation; reject production-ready status for any error.
- [x] Run registry tests and confirm each failure reports stable machine-readable codes.

### Task 4: Server-side BusinessScope and read-only runtime

**Files:**
- Create: `backend/app/lim_scope.py`
- Create: `backend/app/lim_errors.py`
- Create: `backend/app/lim_runtime.py`
- Create: `backend/tests/test_lim_scope.py`
- Create: `backend/tests/test_lim_runtime.py`
- Depends on: Tasks 2–3.

**Interfaces:**
- `build_business_scope(db, user) -> BusinessScope`: derive user ID, role, allowed shops and warehouses only from persisted identity and role data.
- `create_run(db, user, agent_id, goal, requested_scope=None) -> LimRun`: reject client scope expansion and persist CREATED then SCOPE_CHECKED/PLANNED as valid.
- `transition_run(db, run, target_status, error_code=None) -> LimRun`: enforce one explicit transition map and persist audit/trace event.
- `invoke_read_tool(db, run, tool_id, arguments) -> ToolResult`: resolve registered tool, validate schema, apply BusinessScope, refuse all write tools.
- `sanitize_trace_value(value) -> JSONValue`: recursively redact secret-like keys and PII patterns before persistence/response.

- [x] Add failing tests for forged tenant/store/warehouse IDs, out-of-scope access, unknown tool, write tool, invalid schema, illegal state transition, duplicate terminal transition and PII/secret redaction.
- [x] Implement scope and runtime as deterministic services; call existing domain read functions instead of direct arbitrary SQL or model-selected callables.
- [x] Ensure all failed checks persist stable codes such as `SCOPE_FORBIDDEN`, `TOOL_NOT_REGISTERED`, `TOOL_WRITE_BLOCKED`, `BUDGET_EXCEEDED` without raw sensitive args.
- [x] Run targeted runtime tests and inspect persisted rows for scope and redaction behavior.

### Task 5: Authenticated LIM API and evaluation service

**Files:**
- Create: `backend/app/lim_evaluation.py`
- Create: `backend/app/lim_routes.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`
- Create: `backend/tests/test_lim_api.py`
- Create: `backend/tests/test_lim_evaluation.py`
- Depends on: Tasks 2–4.

**Interfaces:**
- `GET/POST /api/v1/lim/agents`, `GET/PATCH /api/v1/lim/agents/{agent_id}`, `POST /api/v1/lim/agents/{agent_id}/validate`.
- `GET/POST /api/v1/lim/tools`, `GET /api/v1/lim/tools/{tool_id}`, `POST /api/v1/lim/tools/{tool_id}/validate`.
- `POST /api/v1/lim/runs`, `GET /api/v1/lim/runs`, `GET /api/v1/lim/runs/{run_id}`, `POST /api/v1/lim/runs/{run_id}/cancel` (cancel only before terminal state).
- `GET /api/v1/lim/traces/{trace_id}` with spans and sanitized tool invocations.
- `GET/POST /api/v1/lim/evals/datasets`, `POST /api/v1/lim/evals/runs`, `GET /api/v1/lim/evals/runs/{eval_run_id}`.
- Read endpoints require `assistant:read`; mutation endpoints additionally require admin or the existing server-side role permission `lim:manage`. Scope-filtered run/trace access returns 404 outside the user's range.

- [x] Add failing API tests for unauthenticated 401, forbidden role 403, resource scope isolation, admin registry CRUD, immutable completed evaluation report and read-only run behavior.
- [x] Add `lim:manage` to the permission catalog; keep reads under `assistant:read`, require `lim:manage` for writes, and preserve admin bypass. Implement stable response envelopes, pagination, audit entries for config/eval mutations, and no secrets in response models.
- [x] Implement eval comparator for exact required evidence/forbidden action plus deterministic acceptable-output checks; label unsupported semantic scoring as not evaluated.
- [x] Run targeted API/evaluation tests and inspect OpenAPI paths and response schemas.

### Task 6: LIM Console frontend

**Files:**
- Create: `frontend/src/api/lim.ts`
- Create: `frontend/src/pages/LimConsolePage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/config/menu.ts`
- Test: focused client/helper tests only if matching existing frontend testing conventions.
- Depends on: Task 5.

- [x] Add typed functions for registry, runs/traces and evaluation API responses.
- [x] Add `/lim/*` routes with permission guard and tabs for Agents, Tools, Runs/Traces and Eval Datasets/Reports.
- [x] Provide create/edit/validate affordances for drafts, show why invalid definitions cannot run, and never show publish/write controls in this batch.
- [x] Show loading, empty, stale/unavailable and API error states distinctly; include run status/error code, trace hierarchy, evidence refs and per-case eval outcome.
- [x] Run frontend typecheck and production build; confirm legacy routes and menu permission behavior remain intact.

### Task 7: End-to-end verification and handoff

**Files:**
- Modify: `README.md`, `backend/README.md`
- Verify: tests and build from Tasks 2–6.

- [x] Run focused LIM tests plus relevant existing agent permission tests and migrations on isolated test DB.
- [x] Run frontend typecheck/build; capture exact command and result.
- [x] Exercise one admin registration/validation path, one permitted read-only Run with Trace, one out-of-scope rejection, and one Eval Run with fixed dataset.
- [x] Document local startup, migration command, API routes, demo flow, security boundaries, G0 findings and unresolved PRD requirements.
- [x] Review diff for accidental secrets, legacy behavior regressions and claims exceeding test evidence.





