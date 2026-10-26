# CommerceOS · AI 智能经营系统 — 接管审计与重构方案（A–G）

> 状态：阶段1 审计完成 + 阶段2 设计完成；阶段3 P0 进行中（前端导航/路由/布局部分已在工作区落地，未提交）。
> 方法：先读真实文件，再设计，再实施。所有结论附真实路径。演示数据一律标来源，不伪装真实接口。
> 验证限制（诚实）：Postgres 在 Docker 中、引擎因沙箱禁 `wsl.exe` 无法启动，后端/端到端暂不可跑；前端 `tsc --noEmit` / `vite build` 不需要 DB，可验证。

---

## A. 项目理解报告

### A.1 实际读取的文件
- 前端导航/路由/布局：`frontend/src/config/menu.ts`、`frontend/src/App.tsx`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/DecisionCenterPage.tsx`、`TaskWorkbench.tsx`、`taskWorkflow.ts`、`pages/aiops/*`、`pages/*AgentPage.tsx`。
- 后端：`backend/app/decision_center.py`、`decision_models.py`、`lim_*.py`（17 个）、`assistant*.py`、`main.py`、`migrations/`（head=0046）。
- 文档：`docs/`、`outputs/ch1_extract.txt`（8 章 SRS 全文 dump）、`docs/superpowers/plans/*`、`docs/AI智能经营系统_4.4开发映射.md`。

### A.2 现有架构与实现状态
- **五套系统**：ERP（商品/SKU/库存/采购/财务，主库 `erp`）、OMS（独立 `oms/` + 库 `oms`，与 ERP 无 API 桥）、Storefront（`storefront/` + 库 `erp_storefront_demo`，checkout 直写 ERP 库）、LIM（`lim_*` 模块 + `LimConsolePage`）、AI 智能经营（`decision_center.py` + `DecisionCenterPage`）。
- **AI 智能经营后端**：决策中心 12–13 路由**全部真实实现且已测**（`test_decision_center.py` 8/8 通过），具备确定性补货计算、版本化仿真、双权限（创建 `purchase_agent:write` / 审批 `purchase_agent_drafts:write`）四眼控制、受控执行只生成 ERP 采购草案。`/assistant/ask`、`/assistant/tasks` 真实。
- **LIM 后端**：模型网关、Agent 运行时（ReAct 循环）、工具注册（8 读 + 1 写 handler）、词法知识检索、**无 GraphRAG/Neo4j、无记忆管理、限流未生效、无缓存、租户隔离未实现、无流式**。Trace/Eval/Alerts 真实。
- **前端 7 入口 IA 已在工作区落地**（未提交）：`menu.ts:142-190` 的 `AI_NAV` 已是 7 个一级；`App.tsx` 已含 `ai-execution-center`、`ai/tasks/:taskId` 路由；`MainLayout` 已有 AI 浅色侧栏渲染。

### A.3 关键更正（推翻早期记忆）
- 早期记忆称"库停在 0041、0042 迁移有 bug"——**后端审计证伪**：Alembic head 是 **0046**，`decision_risks/tasks/versions` 已在 head；`0042` 用的是合法 `sa.CheckConstraint`，无 bug。此前仅是运行实例未 migrate 到 head。

### A.4 三套互相竞争的 IA（仅 7 入口为实际生效）
1. SRS 4.4：10 模块 / 20 编号页面（需求口径）。
2. `docs/superpowers/specs/2026-10-22-ai-decision-center-user-design.txt`：12 菜单（含 7 业务场景 AI + 政策合规 AI + 执行审批中心）。
3. **已实现的 7 入口 IA**（`menu.ts`）——以它为准，SRS 编号全部保留仅菜单去编号。

---

## B. 菜单精简与页面映射表

> 旧需求编号全部保留在追踪记录中。处理方式：保留 / 合并 / 迁移 / 废弃 / 待确认。

| 旧编号 | 旧页面 | 原路由 | 新模块（7 入口） | 新页面/路由 | 处理 | 后端接口 | 数据状态 |
|---|---|---|---|---|---|---|---|
| PG-001 | 智能经营总览 | `ai-dashboard` | 经营驾驶舱 | 经营驾驶舱 `ai-dashboard` | 保留 | 4 个 `/…/summary` | 真实 |
| PG-002 | AI 经营 Copilot | `ai-copilot` | AI 经营 Copilot | AI Copilot `ai-copilot` | 保留 | `POST /assistant/ask` | 真实 |
| PG-003 | Copilot 分析详情 | `ai-copilot-analysis` | AI 经营 Copilot | 分析详情 `ai-copilot-analysis` | 保留（仅 state 可达，待补结构化图表） | 复用 `/assistant/ask` | 真实文本/图表规划中 |
| PG-004/005/006 | 风险事件与规则 | `ai-risk-center` | 风险与任务中心 | 风险事件与规则 `ai-risk-center` | 合并（单 `DecisionCenterPage` 风险 tab） | `/decision-center/risks` | 真实 |
| PG-007/008 | Agent 工作台/协作 | `ai-agent-workbench`/`ai-agent-collab/:id` | 风险与任务中心 | Agent 任务追踪 `ai-agent-workbench` | 保留（虚构样例，标来源） | 前端构造 | 演示·虚构 |
| PG-019 | 经营任务历史 | `ai-task-history` | 风险与任务中心 | 经营任务历史 `ai-task-history` | 迁移（复用 `AssistantTasksPanel`） | `/assistant/tasks` | 真实 |
| PG-009/010 | 策略任务/生成 | `ai-strategy-center` | 策略决策中心 | 策略工作台 `ai-strategy-center` | 合并（`DecisionCenterPage` 任务 tab + `TaskWorkbench` 6 阶段） | `/decision-center/tasks` + versions | 真实 |
| PG-011/012 | 仿真/方案对比 | `ai-strategy-center` | 策略决策中心 | （同上的仿真对比阶段） | 合并 | `/tasks/{id}/versions` | 真实 |
| PG-020 | 策略模板 | `ai-strategy-templates` | 策略决策中心 | 策略模板 `ai-strategy-templates` | 保留（虚构样例，标来源） | 前端构造 | 演示·虚构 |
| PG-013/014 | 策略审批 | `ai-approval-center` | 审批与执行中心 | 策略审批 `ai-approval-center` | 合并（`DecisionCenterPage` 审批阶段） | `/tasks/{id}/approve\|reject` | 真实 |
| PG-015/016 | 策略执行 | `ai-execution-center` | 审批与执行中心 | 策略执行与监控 `ai-execution-center` | 合并（执行阶段 + ERP 草案） | `/tasks/{id}/execute\|confirm` | 真实 |
| PG-017/018 | 效果评估/复盘 | `ai-effect-overview`/`ai-effect/:id` | 效果复盘中心 | 效果评估与复盘 `ai-effect-overview` | 保留（虚构样例，标来源） | 前端构造 | 演示·虚构 |
| — | 7 业务场景 AI | `product/operations/lim-replenishment/purchase/ad-growth/profit-finance/customer-agent` | 业务智能应用 | 7 卡片枢纽 `ai-capability` + 现有叶子 | 保留/枢纽化 | 各自 `/agents/*`、`/agent-generations/*` | 真实 |
| — | 政策合规 AI（12 菜单项 10） | （无） | 业务智能应用 | **待确认**（无页面/后端） | 待确认 | — | 不存在 |
| — | 统一执行审批中心（12 菜单项 11） | （无独立页） | 审批与执行中心 | 复用决策中心审批阶段 | 已覆盖 | — | — |

**废弃/清理（P0，先核引用再删）**：孤儿双 dashboard（`pages/AiDashboardPage.tsx`、`AiDashboardLiveSnapshot.tsx`、`api/aiCockpitDemo.ts`、`pages/aiCockpit.css`）——无任何 `App.tsx` 引用，仅自引用；遗留 `ai-assistant`（`AssistantEntryPage`）未入侧栏但路由可达，保留为兼容或并入 Copilot。

---

## C. 新版 AI 智能经营系统信息架构（7 入口，已落地）

1. **经营驾驶舱** `ai-dashboard`：KPI、跨系统概况、AI 风险摘要、待办与最近决策。
2. **AI 经营 Copilot** `ai-copilot` + 分析详情 `ai-copilot-analysis`：自然语言分析、跨系统查询、报告生成、发起策略分析。
3. **风险与任务中心** `g-ai-risk-task`：风险事件与规则 `ai-risk-center`、经营任务历史 `ai-task-history`、Agent 任务追踪 `ai-agent-workbench`。
4. **策略决策中心** `g-ai-strategy`：策略工作台 `ai-strategy-center`（任务/生成/仿真/方案对比）、策略模板 `ai-strategy-templates`。**经营决策引擎即此中心的计算能力**（见 E）。
5. **审批与执行中心** `g-ai-approval-execution`：策略审批 `ai-approval-center`、策略执行与监控 `ai-execution-center`（共用入口，权限/状态机/审计隔离）。
6. **效果复盘中心** `g-ai-effect`：效果评估与复盘 `ai-effect-overview`（演示·虚构，待真实化）。
7. **业务智能应用** `g-ai-capability`：商品与 Listing / 销售订单 / 库存补货 / 采购供应链 / 广告增长 / 财务利润 / 客服售后 AI；新增 `ai-capability` 枢纽页（权限过滤卡片）。

系统工作区、用户权限、全局设置归 CommerceOS 全局层（`/workspace`、ERP 设置组）。

---

## D. 前端重构方案

### D.1 目录与路由
- 路由集中在 `frontend/src/App.tsx`；导航集中在 `config/menu.ts`；布局在 `layouts/MainLayout.tsx` + `aiShell.css`。
- 决策 UI：`pages/DecisionCenterPage.tsx`（2 主 tab：风险中心 / 策略·仿真·审批·记录）+ `TaskWorkbench.tsx`（6 阶段抽屉/整页）+ `taskWorkflow.ts`（阶段/下一步/任务 URL）。
- 业务场景 AI：各 `pages/*AgentPage.tsx`，真实 `/agents/*`、`/agent-generations/*`。

### D.2 组件与 Design System
- 已有 `theme.ts`：`colorPrimary #2b5cff`、正文 14px、圆角 6、布局底色 `#f2f4f7`。**统一采用**：ERP/LIM/Storefront 深蓝灰侧栏（`#2d2d44`/`#141b2b`），AI 浅色侧栏（紫调 `aiShell.css`）。**行动项**：消除三套内容底色（`#f0f2f5`/`#f5f6fa`/`#f2f4f7`）与两套侧栏色（`#2d2d44` vs `#141b2b`），以 `theme.ts` 为准；AI 侧栏紫调与全局蓝主色需二选一（建议全局蓝，AI 仅保留浅底）。
- 优先复用 AntD；统一列表页/详情页/配置页/执行工作台的 Loading/Empty/Error/Success 状态。`DataProvenance` 已用于真实页；`DemoNote` 横幅用于虚构页。

### D.3 合并与修复（P0）
- 删除孤儿双 dashboard，统一到 `AiOpsOverviewPage`。
- 详情路由高亮：新增 `resolveNavState(pathname)` 处理 `ai-agent-collab/:id`→`g-ai-risk-task`、`ai-effect/:id`→`g-ai-effect`、`ai-copilot-analysis`→`ai-copilot`。
- 修复模板页坏链 `/ai-strategy-tasks`→`/ai-strategy-center`（`AiOpsStrategyTemplatesPage.tsx:23`）。
- 清理 `MainLayout` 死图标键 `g-ai-business`/`g-ai-execution`（不在任何 nav）。
- 新增 `ai-capability` 枢纽页（7 权限过滤卡片）。

### D.4 URL 兼容
- 旧 `/ai-assistant` 保留为兼容路由（或 301 到 `/ai-copilot`）。
- 所有既有叶子路由保持不变，仅菜单去编号、收敛分组。

---

## E. 经营决策引擎方案（位置与模块）

**定位**：不是独立业务系统，而是「策略决策中心」的计算能力。复用现有 `supply_agent.calculate_supply` 与 `DecisionCenterPage` 6 阶段，向外扩展。

### E.1 内部模块（目标，按 P0/P1 落地）
- **指标与公式库**：补货覆盖天数、时效缺口、采购量、资金、毛利——当前硬编码在 `supply_agent.py`/`TaskWorkbench` 计算展示，P1 抽成可测纯函数模块 `decision/calc.py`（SKU-1027 验收要求"LLM 不得编造成本/库存/利润"，必须由可测计算执行）。
- **参数与假设**：需求倍率（人工，基准 1 始终保留）、广告弹性（**明确标注为人工情景，非预测**）、交期、单价——已在 `TaskWorkbench` 输入，P1 结构化。
- **规则与约束**：约束满足校验（已在 `Scenario.constraints_satisfied`），P1 抽成规则引擎。
- **Simulation / Optimisation / Decision Engine**：当前为单 SKU 确定性补货仿真；P1 多目标（成本/断货风险/毛利）优化；P2 高级策略优化。
- **计算结果解释与证据追溯**：证据摘要 `evidence_hash` + 快照，已做；P1 增加自然语言解释。
- **模型版本与回放**：版本化（`decision_versions` + `expires_at`）已做；P1 增加回放对比。

### E.2 与 LIM 协作
- 所有 LLM 调用仅经 `lim_model_gateway.complete()`（已统一），AI 智能经营**不直接** `httpx`。
- 工具调用经 LIM 运行时（当前 8 读 + 1 写 handler）；补货执行复用 LIM 写工具 `erp.replenishment.create-draft`（受人工审批门控）。
- **边界**：LIM 管技术配置/运行/治理；AI 智能经营管业务问题识别、任务、策略、审批、执行、复盘。Agent 状态/业务摘要/证据在 AI 侧展示，不整体迁到 LIM。

### E.3 SKU-1027 闭环（P0 最小可运行 + 真实 seed）
- 演示数据：可售 120 / 日均 20 / 在途 0 / 提前期 10 / 成本 £8 / 售价 £20 / 广告 £60 天 / 14 天窗口。风险数学 120÷20=6 < 10 → 断货风险。三方案（A 增采 / B 调广告 / C 组合），仿真输出覆盖天数/断货日/采购量/资金/广告变动/营收/毛利/约束/假设/版本。
- **当前缺口**：全仓库零 SKU-1027 seed；P0 需新增 seed 脚本（`backend/scripts/seed_demo.py` 扩展或新建）并跑通 `detect→task→versions→submit→approve→execute→confirm`。
- 验收矩阵 AT-SKU-001…013 来自 `outputs/ch1_extract.txt` §8.8。

---

## F. 开发任务清单（P0/P1/P2）

### P0（本迭代）
1. 菜单与路由整理：7 入口 IA 收尾（详情高亮 + 业务枢纽页）。— `menu.ts`/`MainLayout`/`App.tsx` + 新 `AiCapabilityHubPage`。【进行中】
2. 页面功能合并：删孤儿双 dashboard；合并决策中心重复挂载（4→按入口语义保留 3）。— `App.tsx`/`menu.ts`。
3. 通用布局与 Design System：统一三套底色/侧栏色到 `theme.ts`。— `MainLayout`/`aiShell.css`/`theme.ts`。
4. SKU-1027 决策闭环最小可运行：seed 脚本 + 跑通闭环。— `backend/scripts/*` + 迁移/数据。
5. 基础审批状态机与必要测试：决策中心状态机已具备（`move()` CAS + 双权限），补 `page/page_size` 回声一致性 + 列表契约测试。— `decision_center.py` + `test_decision_center.py`。
6. 修复坏链/死键：`/ai-strategy-tasks`→`/ai-strategy-center`；清 `g-ai-business`/`g-ai-execution`。【进行中】
7. 验证：`tsc --noEmit` + `vite build` + 真浏览器 7 入口；后端需 Postgres 起后 `pytest test_decision_center.py`。

### P1
- 多目标优化（成本/断货/毛利）。— `decision/calc.py` + 引擎。
- Agent 执行可视化（复用 `TaskWorkbench` 6 阶段，外扩到 7 业务场景）。
- 决策结果复盘（真实化 `ai-effect-overview`，接 `decision_versions` 实际结果）。
- 模型版本与回放（对比不同假设版本）。
- 指标/公式库抽成可测纯函数（SKU-1027 验收硬要求）。

### P2
- 高级策略优化、经验记忆与 Skill 生成（LIM `lim_skills` 当前 inert）、跨场景复杂推理、高级 AI 评测与治理（语义质量当前 `NOT_EVALUATED`）、GraphRAG/Neo4j（当前缺失）。

---

## G. 实际修改结果（截至本稿）

- 阶段1 审计：完成（前端/后端/文档三路 Read-only 审计，见上文 A–E，全部附路径）。
- 阶段2 设计：完成（本文件 A–G）。
- 阶段3 P0：**进行中，尚未落盘任何修改**。本次已读全部相关前端文件确认基准，下一步落盘：坏链修复、死键清理、详情高亮、业务枢纽页、孤儿文件删除（先核引用），并以 `tsc --noEmit` 验证。
- 后端/端到端验证：待 Postgres（Docker 引擎）启动后补 `pytest` 与真浏览器闭环。
- 未验证项：任何依赖 Postgres 的运行态（seed、审批闭环、效果复盘真实化）均**未验证**，不声称通过。
