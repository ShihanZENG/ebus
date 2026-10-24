# AI 智能经营系统 · 前端功能规划

> 规划日期：2026-10-22。范围：前端 `frontend/` 中「AI 智能经营系统」导航（`config/menu.ts` 的 `AI_NAV`）下各页面「应展示什么、真实性如何、能否本期落地」。
> 本文只做规划，不改动代码。后端能力依据《经营与客服生成能力》《G0 LIM 能力盘点》与现有接口。

## 0. 规划原则（来自项目硬约定）

1. **真实优先**：门脸页第一眼必须是真实数据，演示/虚构内容必须显式隔离、不能当主视觉。
2. **演示数据必须标来源**：虚构样例要有明确「设计演示 / 虚构样例」标识，且不应伪装成已接通的真实接口数据。
3. **可下钻**：经营指标点开要能跳到对应 ERP 业务页面（订单/库存/采购/补货）。
4. **权限与范围可见**：每个面板标注数据来源、授权范围、口径限制（已有 `DataProvenance` 组件可复用）。

## 1. 现状诊断（已核实，带证据）

| # | 问题 | 证据 |
|---|---|---|
| P1 | **门脸页以虚构看板为主视觉，真实数据藏在抽屉** | `AiDashboardPage.tsx:6` 主渲染 `aiCockpitDemo`（`:70` 标「设计演示·虚构样例」）；真实 `AiDashboardLiveSnapshot` 仅在 `:126`「已接入数据」抽屉里出现。`01 AI 经营驾驶舱` 路由指向它。 |
| P2 | **04 销售订单 AI 能力太窄且证据展示丑** | `operations_agent.py` 仅 `get_operations_snapshot`（状态计数+负库存+采购计数）；`OperationsAgentPage.tsx:58-61` 把 evidence 当原始 JSON `<pre>` 展示，无可读表格。 |
| P3 | **07/08/10/11「规划中」占位无定义内容，但部分后端已具备** | `agent_generation.py` 已有 `/profit`、`/ads`、`/customer/{id}`、`/fee-discrepancies`；`generation_reviews.py` 已有审核流。`AgentGenerationsPage.tsx` 已覆盖 profit/ads/customer 审核，但**输入靠 API/JSON，无友好录入页**。 |
| P4 | **两套并行 AI 体系** | 旧 assistant agents（`operations_agent`/`product_agent`）+ LIM 平台（`lim_*`）共存，前端分别挂在 `AI_NAV` 与 `LIM_NAV`，无收敛说明。本期不收敛，仅记录。 |

## 2. 前端功能地图（按现有导航逐页规划）

### 01 AI 经营驾驶舱（ai-dashboard）
- **现状**：主视觉为虚构 `aiCockpitDemo`；真实快照在「已接入数据」抽屉。
- **应展示（目标）**：把 `AiDashboardLiveSnapshot` 作为**主内容**——经营健康度卡（待审核订单/低库存组合/补货待处理/采购待批）、风险识别、下一步建议、数据来源与范围（`DataProvenance`）。虚构 `aiCockpitDemo` 降级为独立「概念演示」入口：顶部明确横幅，或拆成 `ai-dashboard-demo` 次级路由，默认不展示为门脸。
- **真实性**：主内容真（接 `/orders/summary` 等 4 接口）；演示明确隔离。
- **本期可落地**：✅ 纯前端路由/默认视图调整，零后端改动。
- **优先级**：🔴 最高（P1 直接修复）。

### 02 AI 决策工作台（ai-assistant）
- **现状**：`AssistantEntryPage` 默认渲染真实 `AssistantPage`（→ `/assistant/ask`），仅从演示看板带 state 才显示虚构 `DemoTaskPreview`。
- **应展示（目标）**：保持真实聊天为主；建议追问、证据引用展开、任务追踪入口（→ 12）。虚构 `DemoTaskPreview` 仅在明确「示例上下文」标识下出现。
- **真实性**：默认真；演示上下文已带 `Tag` 标识（可接受）。
- **本期可落地**：✅ 微调（默认态确认 + 标识强化），零后端改动。
- **优先级**：🟢 低（已基本正确）。

### 03 商品与 Listing AI（product-agent）
- **现状**：`ProductAgentPage` 接 `/agents/product/ask`，evidence 以结构化表格展示（已较好）。
- **应展示（目标）**：增加「按 SKU 联合核对 库存/在途/Listing 映射」场景；evidence 表格复用现有样式 + `DataProvenance`。
- **真实性**：真（本地 ERP）。
- **本期可落地**：🟡 需后端给 product agent 接更多只读工具（属昨天审计的「经营 Agent 能力做实」范围）。
- **优先级**：🟡 中（依赖后端增强）。

### 04 销售订单 AI（operations-agent）
- **现状**：仅状态计数；evidence 为原始 JSON。
- **应展示（目标）**：
  - 接上 `business_evidence_tools` 的 4 个证据工具（订单期末汇总 `/ 库存可用性 / 在途采购 / 广告表现 / 已登记费用`）。
  - 实现架构文档自列的「首个可交付场景」：**待发货订单 × 库存是否够，按 SKU 联合核对**，返回缺货项、数据更新时间、订单链接。
  - 前端 evidence 从原始 JSON 改为**结构化证据卡片**（订单状态分布、缺货清单、SKU 联合核对表），带 `DataProvenance` 来源标注。
- **真实性**：真（本地 ERP，需人员从真实报表提交广告/费用数据，页面须标注 `source_reference` 为追溯入口而非真实性证明）。
- **本期可落地**：🟡 后端增强（接证据工具 + 联合核对）+ 前端重做 evidence 渲染。
- **优先级**：🔴 高（这是「经营」一词的核心落点，当前最空）。

### 05 库存补货 AI（lim-replenishment）/ 06 采购供应链 AI（purchase-agent）
- **现状**：`LimReplenishmentPage` / `PurchaseAgentPage` 已较完整（草稿+审批流）。
- **应展示（目标）**：保持；仅补「决策依据可下钻到采购单/补货建议页」。
- **真实性**：真。
- **本期可落地**：✅ 小修。
- **优先级**：🟢 低。

### 07 广告增长 AI（规划中 → 可升级）
- **现状**：路由 `disabled`，无页面。
- **应展示（目标）**：广告表现看板（ACOS/ROAS/CVR/CTR/CPC，按活动+归因窗口）+ 文案/预算建议**草稿**（接 `/agent-generations/ads`）+ 审核队列（复用 `generation_reviews`）。明确「零分母指标为 null、零销售行花费仍计入总体」口径。
- **真实性**：真，但广告原始数据需人员从真实报表提交（页面标注来源）。
- **本期可落地**：✅ 后端已具备；前端需建录入表单 + 看板 + 接现有审核页。权限 `advertising_agent:write` / `read`。
- **优先级**：🟡 中（价值高、风险可控，建议本期做）。

### 08 财务利润 AI（规划中 → 可升级）
- **现状**：路由 `disabled`，无页面。
- **应展示（目标）**：利润与对账复算录入（净销售/贡献/已知费用/应结/差额）+ 费用差异复核（接 `/profit-reconciliations/fee-discrepancies`，可给 `CONFIRMED_OVERCHARGE`）+ 口径说明（不同口径**不合并**成「最终净利」）。审核接 `generation_reviews`，权限 `finance_agent:write/read`。
- **真实性**：真，但费用行需人员逐行登记并标识「是否已从结算扣除」。
- **本期可落地**：✅ 后端已具备；前端建录入 + 复核看板。
- **优先级**：🟡 中（财务敏感，建议与 07 一并做但加更显式审计提示）。

### 09 客服售后 AI（customer-agent）
- **现状**：`CustomerAgentPage` 接 `/agents/customer/draft/{ticket_id}`，输出 `may_send=false` 草稿。
- **应展示（目标）**：保持；增加「规则匹配说明」「安全升级标记」「需人工发送」提示。
- **真实性**：真（规则须管理员从已批准材料录入，无规则不生成）。
- **本期可落地**：✅ 小修。
- **优先级**：🟢 低。

### 10 政策合规 AI（规划中）/ 11 执行审批中心（规划中）
- **现状**：路由 `disabled`，无页面。
- **应展示（目标）**：10 = 政策/规则检索与合规检查入口（依赖 `agent_knowledge_rules` 已录入）；11 = 统一的生成/草稿审批中心（聚合 profit/ads/customer/purchase 的 pending 审核）。
- **真实性**：真（依赖已录入规则与既有审核流）。
- **本期可落地**：🟡 10 部分可建（规则检索）；11 建议**留到后期**，因需通用 Proposal→审批绑定（LIM-FR-009 未闭环）。
- **优先级**：🟡 中低（10 可做，11 暂缓）。

### 12 AI 任务历史（ai-task-history）
- **现状**：`AssistantTasksPanel` 已接 `/assistant/tasks`。
- **应展示（目标）**：保持；补「Run/Trace 可回看」「失败原因码」展示。
- **真实性**：真（当前只读任务，进程重启无自动恢复，页面须标注）。
- **本期可落地**：✅ 小修。
- **优先级**：🟢 低。

## 3. 建议落地顺序（分阶段，均不碰后端未实现能力）

1. **阶段一（纯前端、低风险、立刻可做）**
   - P1：01 门脸改为真实 `AiDashboardLiveSnapshot` 为主，虚构看板降级为带横幅的「概念演示」次级入口。
   - 02 默认态与标识确认。
   - 04 的 evidence 渲染从原始 JSON 改为结构化卡片（**仅前端**，后端仍只给快照，先改善可读性）。
2. **阶段二（后端增强 + 前端，中等风险）**
   - 04 经营 Agent 接只读证据工具 `get_pending_shipment_inventory_check`（复用 `business_evidence_tools._availability_refs` / `_shop`，按 `inventory_allocation.available` 跨「待发货订单 × 库存 SKU」联合核对）——**已完成（2026-10-22）**：pytest 4 项全过 + 真实库(erp)验收 + `/ask` 经 LLM 跑通（多店铺提示 → 选定店铺 → 出具缺货核对）。前端 `OperationsAgentPage` 新增 `PendingShipmentCheck` 渲染该证据（含订单链接、展开 SKU 明细、缺货汇总）。
   - 03 商品 Agent 增加联合核对场景。
3. **阶段三（前端建页，后端已具备）**
   - 07 广告增长 AI、08 财务利润 AI 升级出 `disabled`，建录入表单 + 看板 + 接现有 `generation_reviews`。
   - 10 政策合规 AI 建规则检索入口。
4. **阶段四（后期，依赖 LIM 治理）**
   - 11 执行审批中心、两套 AI 体系收敛。

## 4. 待你拍板的问题

- Q1：01 门脸页，你接受「真实快照为主 + 虚构看板降级为带横幅的概念演示入口」这个方向吗？还是直接移除虚构看板、只留真实？
- Q2：本期是否要推动 07/08 出 `disabled`（后端已具备，主要建前端录入页）？还是先聚焦 01+04？
- Q3：04 的「后端接证据工具 + SKU 联合核对」要现在做，还是先只做前端证据卡片美化（阶段一）？
- Q4：11 执行审批中心是否本期彻底暂缓（建议暂缓）？
