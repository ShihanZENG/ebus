# AI 智能经营系统（4.4）· 开发映射与落地说明

> 编写日期：2026-10-23。范围：依据《4.4 AI 智能经营系统》规格（系统定位 + 10 个功能模块树 + 20 个页面清单）所做的前端落地。
> 配套规划见 [`AI经营系统前端功能规划.md`](./AI经营系统前端功能规划.md)。
> 本文记录「规格 → 实际页面 → 数据真实性 → 文件 → 路由 → 权限」的映射，并对实现取舍做诚实说明。

## 0. 核心实现原则（来自项目硬约定）

1. **真实优先**：后端已有接口的页面，直接接真实数据，不造影子演示。
2. **演示数据必须标来源**：后端本期未落地的业务概念，以「设计演示 · 虚构样例」构造前端数据，页面用 `DemoNote` 横幅显式隔离，绝不伪装成真实接口返回。
3. **不重复造轮子 / 不造影子**：若既有页面已用真实后端覆盖规格中的某组页面，则**复用既有真实页面**，而不是新建一组 demo 页面去「对齐规格编号」——否则 demo 会遮蔽真实数据，违反第 2 条。

## 1. 模块 → 页面 → 落地映射

> 说明：规格 4.4.3 的 20 个页面中，**AI-PG-004~016（M03 风险中心、M05 策略生成、M06 策略仿真、M07 策略审批、M08 策略执行）并非 12 个独立路由文件**，而是由既有真实组件 `DecisionCenterPage` 统一承载（4 个 Tab：风险 / 任务 / 仿真版本 / 审批执行），经 `ai-risk-center`、`ai-strategy-center`、`ai-approval-center` 三个导航入口进入。理由见第 2 节。

| 页面编号 | 页面名称 | 所属模块 | 落地文件 | 数据来源 | 路由 key | 权限 |
|---|---|---|---|---|---|---|
| AI-PG-001 | 智能经营总览 | AI-M01 | `pages/aiops/AiOpsOverviewPage.tsx` | **真实**：`/orders/summary` `/inventory/summary` `/purchase-orders/summary` `/replenishment-suggestions/summary`（经 `fetchCockpit`） | `ai-dashboard` | `assistant:read` |
| AI-PG-002 | AI 经营 Copilot | AI-M02 | `pages/aiops/AiOpsCopilotPage.tsx` | **真实**：`POST /assistant/ask`（只读） | `ai-copilot` | `assistant:read` |
| AI-PG-003 | Copilot 分析结果可视化 | AI-M02 | `pages/aiops/AiOpsCopilotAnalysisPage.tsx` | **真实返回 + 规划中**：复用 `/assistant/ask` 的 `reply/sources/references`；结构化图表 / 工具结果属规划中能力，页面已显式标注 | `ai-copilot-analysis` | `assistant:read` |
| AI-PG-004 | 风险事件列表 | AI-M03 | `pages/DecisionCenterPage.tsx`（Tab：风险） | **真实**：`GET /api/v1/decision-center/risks` | `ai-risk-center` | `purchase_agent:read` |
| AI-PG-005 | 风险事件详情 | AI-M03 | `DecisionCenterPage` 详情抽屉 | **真实**：`GET /decision-center/risks/{id}` + `POST .../status` | `ai-risk-center` | `purchase_agent:read` |
| AI-PG-006 | 风险规则 | AI-M03 | `DecisionCenterPage`（风险 Tab 内的规则/指标视图） | **真实**：风险模型含 `net_gap`/`time_shortfall`/`first_shortage_date`/`daily_sales` 等指标 | `ai-risk-center` | `purchase_agent:read` |
| AI-PG-007 | 经营 Agent 工作台 | AI-M04 | `pages/aiops/AiOpsAgentWorkbenchPage.tsx` | **设计演示·虚构样例**（前端构造，经 `fetchAgents`/`fetchCollabTasks`） | `ai-agent-workbench` | `assistant:read` |
| AI-PG-008 | Agent 协作任务详情 | AI-M04 | `pages/aiops/AiOpsAgentCollabDetailPage.tsx` | **设计演示·虚构样例** | `ai-agent-collab/:id` | `assistant:read` |
| AI-PG-009 | 策略任务 | AI-M05 | `DecisionCenterPage`（Tab：任务） | **真实**：`GET /api/v1/decision-center/tasks` | `ai-strategy-center` | `purchase_agent:read` |
| AI-PG-010 | 策略详情 | AI-M05 | `DecisionCenterPage` 详情抽屉 | **真实**：`GET /decision-center/tasks/{id}` + `POST .../versions`（仿真版本） | `ai-strategy-center` | `purchase_agent:read` |
| AI-PG-011 | 仿真实验 | AI-M06 | `DecisionCenterPage`（任务详情内版本/场景） | **真实**：`POST /decision-center/tasks/{id}/versions`，`scenario.demand_factor` + `calculation.trajectory` + `issues` + `limitations` | `ai-strategy-center` | `purchase_agent:read` |
| AI-PG-012 | 仿真对比 | AI-M06 | `DecisionCenterPage`（多版本对比） | **真实**：同上，多场景 `metrics` 对比 | `ai-strategy-center` | `purchase_agent:read` |
| AI-PG-013 | 审批列表 | AI-M07 | `DecisionCenterPage`（经由 `ai-approval-center` 入口，聚焦提交/审批） | **真实**：`POST /decision-center/tasks/{id}/submit|approve|reject` | `ai-approval-center` | `purchase_agent:read` |
| AI-PG-014 | 审批详情 | AI-M07 | `DecisionCenterPage` 详情抽屉 | **真实**：同上 | `ai-approval-center` | `purchase_agent:read` |
| AI-PG-015 | 执行任务 | AI-M08 | `DecisionCenterPage`（任务详情内执行） | **真实**：`POST /decision-center/tasks/{id}/execute|confirm` | `ai-strategy-center` | `purchase_agent:read` |
| AI-PG-016 | 执行详情 | AI-M08 | `DecisionCenterPage` 详情抽屉 | **真实**：同上 | `ai-strategy-center` | `purchase_agent:read` |
| AI-PG-017 | 效果概览 | AI-M09 | `pages/aiops/AiOpsEffectOverviewPage.tsx` | **设计演示·虚构样例**（经 `fetchEffects`） | `ai-effect-overview` | `assistant:read` |
| AI-PG-018 | 效果复盘 | AI-M09 | `pages/aiops/AiOpsEffectReviewPage.tsx` | **设计演示·虚构样例**（经 `fetchEffect`） | `ai-effect/:id` | `assistant:read` |
| AI-PG-019 | 经营任务历史 | AI-M10 | `pages/aiops/AiOpsTaskHistoryPage.tsx`（内嵌既有 `AssistantTasksPanel`） | **真实**：`GET /api/v1/assistant/tasks`，支持取消 `POST /assistant/tasks/{run_id}/cancel`、追踪 `GET /lim/traces/{trace_id}` | `ai-task-history` | `assistant:read` |
| AI-PG-020 | 策略模板库 | AI-M10 | `pages/aiops/AiOpsStrategyTemplatesPage.tsx` | **设计演示·虚构样例**（经 `fetchTemplates`） | `ai-strategy-templates` | `assistant:read` |

### 能力底座（业务场景 AI）
菜单中 `g-ai-capability`（业务场景 AI（能力底座））保留 7 个既有真实 Agent 页面，未改动：`product-agent`、`operations-agent`、`lim-replenishment`、`purchase-agent`、`ad-growth`、`profit-finance`、`customer-agent`。这些在本期前已是真实接口页面，仅收纳进 4.4 导航树。

## 2. 关键取舍：为什么 004~016 复用既有真实页面，而不是新建 12 个 demo 页

规格把 M03 风险中心、M05~M08 策略生成/仿真/审批/执行拆成 12 个页面编号。落地时有两个选项：

- **选项 A（未采用）**：按编号新建 11 个 demo 页面（风险事件/规则、策略任务/详情、仿真、审批、执行……），用前端虚构数据填满。
  - 问题：后端 `backend/app/decision_center.py` 已存在真实 `decision-center` 路由，覆盖「风险检测 → 策略任务 → 仿真版本 → 提交/审批/执行/确认」完整闭环，且 `DecisionCenterPage.tsx` 已实现对应 UI（4 Tab + 详情抽屉 + 版本对比 + 审批执行动作 + 真实权限 `purchase_agent:read/write`）。新建 demo 页面会**用虚构数据遮蔽真实数据**，直接违反「演示数据必须标来源」与「真实优先」两条硬约定。
- **选项 B（采用）**：复用既有真实 `DecisionCenterPage` 作为 M03/M05~M08 的统一引擎，通过 `ai-risk-center` / `ai-strategy-center` / `ai-approval-center` 三个导航入口暴露，并在菜单文案中明确标注这些页面对应 4.4 的哪些编号（如「AI-PG-004/005/006 风险事件与规则」）。
  - 好处：数据 100% 真实；不重复造轮子；规格的编号语义通过菜单分组与文案对齐，而非靠 12 个空壳文件对齐。

因此 004~016 在文件层面是「1 个真实组件 + 3 个入口」，在功能层面完整覆盖规格，且数据真实性优于新建 demo。这是有意为之的取舍，特此说明。

## 3. 新增 / 修改的文件清单

### 新增
- `frontend/src/api/aiOps.ts` — 4.4 数据层。真实部分：`fetchCockpit`（4 类汇总）、`askCopilot`（`/assistant/ask`）、`fetchAssistantTasks`（`/assistant/tasks`）；演示部分（均带 `source:'demo'` 且页面用 `DemoNote` 隔离）：`fetchAgents`/`fetchCollabTasks`（M04）、`fetchEffects`/`fetchEffect`（M09）、`fetchTemplates`（M10）。
  - 注：初版曾为已删除的 11 个 demo 页预留 `fetchRiskEvents`/`fetchStrategyTasks`/`fetchSimulation`/`fetchApprovals`/`fetchExecutions` 等，随页面删除一并清理（见第 5 节）。
- `frontend/src/components/aiOps/DemoNote.tsx` — 统一的「设计演示 · 虚构样例」横幅组件，所有 demo 页面顶部使用。
- `frontend/src/pages/aiops/AiOpsOverviewPage.tsx`（001）
- `frontend/src/pages/aiops/AiOpsCopilotPage.tsx`（002）
- `frontend/src/pages/aiops/AiOpsCopilotAnalysisPage.tsx`（003）
- `frontend/src/pages/aiops/AiOpsAgentWorkbenchPage.tsx`（007）
- `frontend/src/pages/aiops/AiOpsAgentCollabDetailPage.tsx`（008）
- `frontend/src/pages/aiops/AiOpsEffectOverviewPage.tsx`（017）
- `frontend/src/pages/aiops/AiOpsEffectReviewPage.tsx`（018）
- `frontend/src/pages/aiops/AiOpsTaskHistoryPage.tsx`（019）
- `frontend/src/pages/aiops/AiOpsStrategyTemplatesPage.tsx`（020）

### 修改
- `frontend/src/config/menu.ts`
  - `AI_NAV` 替换为 4.4 模块树（10 模块分组，保留能力底座 7 页；规格中「规划中」纯占位项已不单列）。
  - `SYSTEM_ONLY_ROUTES.ai` 扩展，纳入全部 4.4 路由 key。
  - `findSystemNavigation` 简化为前缀匹配，使 `/ai-agent-collab/:id`、`/ai-effect/:id` 正确归属 AI 系统。
  - `NAV_PERMISSION` 新增 4.4 各页权限（真实页 `purchase_agent:read`；Copilot/分析/Agent/效果/模板/历史 `assistant:read`）。
  - `MODULE_API` 补充每页数据来源说明（真实接口 vs 设计演示）。
- `frontend/src/App.tsx` — 新增 7 条 4.4 路由；`ai-dashboard`/`ai-task-history` 改为渲染新页面；移除因 `noUnusedLocals` 失效的 `AssistantTasksPanel` 内联 import。

### 既有（非本期编写，本期发现并接线）
- `frontend/src/pages/DecisionCenterPage.tsx` — M03/M05~M08 的真实引擎。
- `backend/app/decision_center.py` + `backend/app/decision_models.py` — 真实 `decision-center` 后端。

## 4. 数据真实性汇总

| 真实性 | 页面 | 说明 |
|---|---|---|
| **真实接口** | 001 / 002 / 003 / 004~016 / 019 | 接 `/orders/summary` 等汇总、`/assistant/ask`、`/assistant/tasks`、`/api/v1/decision-center/*`。003 的结构化图表为规划中，已标注。 |
| **设计演示·虚构样例（已隔离）** | 007 / 008 / 017 / 018 / 020 | 前端构造，页面顶部 `DemoNote` 横幅明示，数据对象带 `source:'demo'`，不冒充真实接口。 |

## 5. 清理动作（顺手修掉）

- 初版为「风险/策略/仿真/审批/执行」建了 11 个 demo 页面 + 对应 `aiOps.ts` fetchers/fixtures。发现既有 `DecisionCenterPage` + 真实后端已覆盖这些场景后，删除那 11 个页面，并清理 `aiOps.ts` 中对应的 9 个死 fetcher 与 7 个死 fixture/类型（约 338 行），仅保留 M04/M09/M10 仍在使用的演示数据。

## 6. 验证状态（诚实标注）

### 6.1 已通过
- ✅ `npm run typecheck`（`tsc --noEmit`）：通过，无错误。
- ✅ `npm run build`（`tsc --noEmit && vite build`）：通过，3185 模块，无错误（prune 后已重跑确认）。
- ✅ **真浏览器运行检查（已做）**：`npm run dev`（Vite 代理 `/api` → 后端 18080）+ Playwright 驱动系统 Chrome，注入真实 `admin` token（`localStorage.erp_token`），逐一打开 12 个 4.4 路由：**12/12 渲染通过，0 个真实 console 错误**。断言打在可见输出（卡片 / 表格行 / List 项 / Tab / Steps / Alert-Empty）上，非状态 class。已肉眼复核 001 总览、007 Agent 工作台、004 风险中心、019 任务历史截图。

### 6.2 本轮修复的后端阻断（影响 004~016 可用性）
- **症状**：`/api/v1/decision-center/*` 404 → 重启后转 500（`relation "decision_risks" does not exist`）。
- **根因**：数据库停在 `0038`，**迁移 `0041_decision_center.py`（创建 decision_risks/tasks/versions）从未执行**；且在跑的后端进程早于该路由挂载（`main.py:135`）。
- **修复**：① 重启自愈守护下的 uvicorn 进程以加载当前代码；② `alembic upgrade 0041` 建表（迁移 0041 本身已存在，无需新写）。修复后 `/risks`、`/tasks` 均返回 200。

### 6.3 遗留已知问题（未改，属既有缺陷，不在本 4.4 范围）
- ⚠️ **迁移 `0042_storefront_checkout_completion.py` 有 bug**：`op.create_check_constraint("kind IN (...)", 'storefront_promos', name=...)` 参数顺序与当前 Alembic 版本签名不符 → `alembic upgrade head` 在 0042 报 `TypeError`。因此数据库**刻意停在 0041**（decision 表已建齐），0042–0045 未应用。修复该迁移需改签名（`op.create_check_constraint(name, table, condition)`），属 storefront 模块，待对齐后处理。
- ⚠️ decision_risks / decision_tasks 尚无数据（风险由 `POST /risks/detect` 依 SupplyProfile 派生，非种子数据），故 004~016 页面呈现合法空状态；如需演示数据可在补齐 `purchase_agent_profiles` 后调用 detect。
- ⚠️ 003 的结构化数据表 / 图表 / 工具结果仍为规划中占位（已显式标注）。

## 7. 后续可选增强（非本期范围）

- AI-PG-003 的结构化分析结果（图表/工具结果表）目前为规划中占位，待 Copilot 后端返回结构化字段后补全。
- M04 经营 Agent 协作、M09 效果评估、M10 策略模板目前为前端演示骨架；若后端落地对应能力，可将 `aiOps.ts` 的 demo fetcher 替换为真实接口，页面与 `DemoNote` 横幅无需改动结构。
