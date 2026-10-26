# 企业工作区门户实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 PRD G1 门户入口，以服务端权限决定 ERP、AI Operations 工作区的可见性和深链。

**Architecture:** FastAPI 通过现有会话和角色权限生成门户工作区列表；React 新增独立门户页并复用现有业务路由。OMS 在独立身份授权接入前保持不可点击。

**Tech Stack:** FastAPI、SQLAlchemy、React、TypeScript、React Router、Ant Design。

**Spec:** `docs/superpowers/specs/2026-10-21-enterprise-portal-design.md`

**Scope note:** PRD G0 的 B/A/O/P 全量实现状态清单与证据台账仍未完成，应在进入 G2 前另行交付。

## Global Constraints

- OMS 保持独立身份/数据库边界。
- 后端服务端校验是授权依据；前端隐藏入口只是体验层。
- 不跨币种汇总金额；本阶段不新增经营指标。
- 不把模拟、导入或缺失数据标记为实时。
- 深链不得传输 ERP token 或敏感筛选条件。

## Review Focus

- 无效或过期会话调用门户 API：返回 401。
- 用户无某工作区权限：工作区列表不包含该项，且其业务 API 仍由既有权限守卫拒绝访问。
- OMS 地址缺失或无效：门户不生成可执行外链，显示未配置状态。
- OMS 独立登录：跳转不携带 ERP token。
- 管理员与普通用户权限不同：接口返回范围符合角色权限。

## File Map

- Create `backend/app/portal.py`：认证门户工作区 API。
- Modify `backend/app/main.py`：注册门户 API。
- Create `frontend/src/api/portal.ts`：门户响应类型和查询函数。
- Create `frontend/src/pages/WorkspacePage.tsx`：工作区卡片及状态视图。
- Modify `frontend/src/App.tsx`：保护门户路由并调整登录后入口。
- Modify `frontend/src/pages/LoginPage.tsx`：登录成功后导航到门户（先核对现有成功跳转逻辑）。
- Modify `frontend/src/layouts/MainLayout.tsx`：提供返回工作区入口。
- Modify `frontend/.env.example` 或 `frontend/vite.config.ts`（按现有环境变量约定）：配置独立 OMS URL。
- No schema migration is required.

## Tasks

### Task 1: Permission-aware portal API

- [x] Define stable workspace payload `{ id, name, description, deep_link, identity_note }`.
- [x] Add `GET /api/v1/portal/workspaces`, requiring current authenticated user.
- [x] Resolve role server-side; admin sees ERP and AI; ordinary users see ERP for an ERP read permission and AI for `assistant:read` or `purchase_agent:read`.
- [x] Return OMS as unavailable without an actionable deep link until OMS identity and authorization can be verified.
- [x] Register the router and document its response shape.

### Task 2: Portal page and navigation

- [x] Add a typed portal API client.
- [x] Add a responsive card page with loading, failure, empty, unavailable OMS and identity-boundary states.
- [x] Navigate only to returned ERP/AI local routes; render OMS unavailable and never attach ERP credentials.
- [x] Protect `/workspace`, route the authenticated root and post-login success to `/workspace`, retain legacy ERP routes.
- [x] Add a visible portal return action in the existing ERP shell.

### Task 3: Verification and handoff

- [x] Review the changed route/API contracts against the design spec and existing role model.
- [x] Run Python import/route checks and frontend type/build verification where the environment permits.
- [x] Record exact commands and results, including any unverified authorization scenario.
- [x] Update project README with the portal entry route and OMS independence note.

## Verification Record

- Backend route import: `backend/.venv/Scripts/python.exe -B -c "from app.portal import router; print([(route.path, sorted(route.methods)) for route in router.routes])"` succeeded and reported `GET /api/v1/portal/workspaces`.
- Frontend build: a parallel developer in the shared workspace reported `npm run build` exited 0; TypeScript check passed, Vite transformed 3155 modules, and the build emitted the existing large-chunk warning.
- The local build attempt was stopped after Vite transformed 3155 modules because another build was running concurrently. Tests were not run.
- Authorization negative cases were reviewed against the existing backend `current_user` and route-level permission guards, but were not exercised as automated tests.
- OMS remains unavailable because no cross-system identity/authorization mapping exists; ERP permissions are not used to infer OMS access.
