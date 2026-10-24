# LIM 智能中间层 · 页面功能与 UI 设计规范

> 适用范围：LIM Console（`frontend/src/pages/LimConsolePage.tsx`，单页 + 9 个分区 tab；外加独立页 `LimReplenishmentPage.tsx`）。
> 依据：直接读取现有组件代码（590 行）与 `docs/lim/g0-capability-inventory.md` 能力盘点。
> 目标：在「已有可用实现」基础上，沉淀一份**功能 + UI 设计规范**，统一信息架构、交互与 demo / 真实数据标注，作为后续逐模块开发计划与视觉落地的基线。
> 配套可查看原型：`outputs/lim-ui-prototype.html`

---

## 0. 总原则（全页统一）

1. **演示数据必须标来源**：凡非真实业务数据的占位，使用橙色 `演示` 角标；真实接口但为受限能力（如 Token / 费用不可用）用 `不可用` 明确占位，**绝不编造估算值**。
2. **安全边界可视化**：Tool 的 `read / write`、Skill 状态机、Sandbox 仿真，必须用颜色 + 文案双重标识，不能仅靠纯文字。
3. **浅色通透、内容清晰**：白卡片 + 柔和描边 + 留白；状态用统一色板；禁止空壳页（每个分区都有实质表格 / 指标 / 操作）。
4. **现状已较完整**：LIM Console 当前已是功能级实现（接 `limApi` 真实接口）。本规范以「补规范、补标注、补一致性」为主，不是从零重画。

---

## 1. 平台总览（overview）

**功能定位**：注册资源的一屏概览，给管理员快速判断 LIM 当前「有多少东西在跑」。

**信息架构**
- 8 张统计卡：Agent 版本 / Tool 版本 / Workflow / 运行记录 / 评测数据集 / 知识源 / 有效技能 / 待处理告警。
- 「平台能力」入口卡片：跳转到其余 8 个分区。

**核心交互**：统计卡只读；入口按钮 `navigate` 到对应路由（见 `LIM_SECTION_ROUTES`）。

**数据真实性**：计数来自各注册表聚合（真实接口）。**Token / 费用 / 缓存命中 / 租户维度在此明确标「不可用」**，不展示任何估算。

**设计建议**
- 待处理告警卡若为 0，角标不显示；>0 显红点（已在 tabs 的 `运行告警` 同步红点）。
- 顶部常驻一条 `info` 提示：「模型调用量、Token、费用、租户级指标尚未接入，本页不展示估算值」。

---

## 2. Agent 运行时（agentRuntime）

**功能定位**：Agent 定义的注册、固定版本管理与校验入口。

**信息架构**：单表 `agentColumns`——Agent（展示名 + `agent_id · v版本`）/ 业务域 / 状态 Tag / 校验按钮；右上「创建 Agent 草稿」。

**核心交互**
- `doValidate('agent', …)`：调用 `limApi.validateAgent`，有效则成功 toast，无效弹 modal 列出 issues。
- 创建：`prompt` 粘贴 JSON（当前实现，建议后续改为结构化表单）。

**数据真实性**：`agents()` 真实接口；`status` 取值 `validated / draft / invalid`。

**设计建议**
- 行内必须同时展示「展示名 + agent_id·版本」，版本是唯一标识。
- 状态色板统一：validated=绿，draft=蓝，invalid=橙。
- 「运行」入口（见运行区）对未 `validated` 版本禁用并提示原因。
- 草稿创建建议从「粘贴 JSON」升级为分步表单（降低出错，符合「页面不空壳」要求）。

---

## 3. 工具注册中心（toolRegistry）

**功能定位**：Tool Schema、操作类型、版本的注册登记；是 LIM 安全边界的核心。

**信息架构**：单表 `toolColumns`——Tool ID（含 `v版本 · service`）/ 领域 / 类型 Tag / 状态 / 校验。

**核心交互**：`doValidate('tool', …)`；创建 Tool 草稿（`prompt` JSON）。

**数据真实性**：`tools()` 真实接口。`operation_kind ∈ {read, write}`。

**设计建议**
- **`read/write` 是安全边界**：write 用红色 Tag，运行时强制走 Sandbox（与运行区联动）。
- 校验失败时弹 issues 列表，而非仅 toast。

---

## 4. 运行与追踪（runs）

**功能定位**：只读运行的启动、Trace 三栏分析、本地 Tool 观测。是 LIM 最复杂的分区。

**信息架构（三块）**
1. **启动只读运行**：Agent 版本 Select（仅 validated）+ Tool 版本 Select + 目标输入 + `运行` / `Sandbox 仿真` + 参数 `TextArea`。
2. **Trace 分析**（三栏 grid）：运行目录（搜索 + 模式筛选 + 运行列表）/ 执行时间线（Span 树 + 耗时）/ 追踪详情（属性 + 脱敏数据 Tab）。
3. **本地 Tool 观测**：UTC 日期范围 + 查询/导出(JSON/CSV)；表含调用数、状态计数、延迟样本；下方 `Token/费用/缓存/租户 = 不可用`。

**核心交互**
- `run()`：仅允许 validated Agent + read Tool；write Tool 拦截并提示「写 Tool 仅可使用 Sandbox 仿真」。
- `runSandbox()`：`prompt` 粘贴 Mock 响应，不调用真实 handler。
- `openTraceWorkspace(run)`：加载 `trace_id` 填三栏；默认选中首个运行。
- `exportTrace / exportToolInvocationMetrics`：浏览器下载。

**数据真实性**
- `runs()/trace()` 真实接口；Trace 保存**脱敏摘要**。
- 延迟只统计本地同步 Tool handler 实测；Sandbox 的 0ms 不计入延迟样本。
- Token / 费用 / 缓存 / 租户维度明确「不可用」。

**设计建议**
- 三栏布局在窄屏应堆叠（当前 `overflowX:auto` 已可横向滚动，建议加响应式断点）。
- Trace 详情的「脱敏数据」用深色代码块，与「属性」Tab 区分，强化「已脱敏」语义。
- 运行目录的 `live / sandbox` 用蓝 / 金 Tag 区分，与观测表一致。

---

## 5. 评测与回归（eval）

**功能定位**：固定数据集上的本地确定性回归评测，与固定版本比较报告。

**信息架构（三块）**
1. **数据集评测**：创建数据集版本 + 选数据集 + `运行评测`；数据集表。
2. **最近一次评测报告**：Agent / 数据集 / 本地断言指标。
3. **固定版本比较**：基线 + 候选 Eval Run Select + 三项阈值（通过率下降 / 用例回归 / 关键回归）+ `生成比较报告`；报告含版本、通过率、回归/改善、阈值判定、逐用例表（含 Trace 链接）。

**核心交互**：`evaluate()` 要求数据集 + validated Agent；`compareEvaluations()` 用两次已完成 Eval。

**数据真实性**：`evalRuns()/evaluate()/compareEvals()` 真实接口；报告含 `integrity_valid` 完整性校验。

**设计建议**
- 比较报告顶部用大号 `PASS / FAIL / 阈值未通过` 状态 Tag。
- 逐用例表固定「用例 / 风险 / 基线→候选 / 分类(REGRESSION 红)/ 失败原因变化 / Trace」，列宽可横向滚动。
- 强调「本地确定性回归 ≠ 生产发布门禁」，避免答辩误读。

---

## 6. 知识源管理（knowledge）

**功能定位**：本地 Markdown 知识源的同步、版本、激活/归档与词面检索预览。

**信息架构**：知识源目录表（来源 / 分类 / 状态 Tag / 权限 / 操作：编辑·版本·激活·归档）+ 知识检索预览（输入 + 结果 `pre`）。

**核心交互**：`syncKnowledge()` 同步目录；`editKnowledge()` 改元数据；`activateKnowledge()` 激活待审版本（可设有效期）；`archiveDraftKnowledgeVersion()`；`runKnowledgeSearch()`。

**数据真实性**：`knowledgeSources()/knowledgeVersions()/searchKnowledge()` 真实接口；内容来自 `docs/功能章节`、`docs/oms` 本地 Markdown。

**设计建议**
- 状态区分「已归档 / 存在 / 文件缺失」三态 + 「active 版本号」子 Tag。
- 检索结果明确标注「词面匹配，非向量召回；golden dataset 指标未建立」。
- 激活流程的「有效期」输入应给日期选择器，而非自由文本 prompt。

---

## 7. 工作流编排（workflow）

**功能定位**：固定版本只读 DAG 的登记、校验、运行；父 Run + 子 Trace。

**信息架构**：Workflow Registry 表（Workflow / 版本 Tag / 操作：校验 draft·运行 validated）+ 最近一次 Workflow Run 结果卡（含 `output_summary`）。

**核心交互**：`createWorkflow()`（JSON 草稿）；`validateWorkflow()`；`runWorkflow()` 仅允许 validated 版本。

**数据真实性**：`workflows()/validateWorkflow()/runWorkflow()` 真实接口。当前**单进程同步执行，无重启恢复**。

**设计建议**
- 版本 Tag：validated=绿，draft=蓝；运行按钮对 draft 禁用。
- 结果卡标注「证据冲突只分类，不自动选取结论」。
- 后续：可视化 DAG 编辑（Studio）与崩溃恢复，属 PRD G3，本轮未做。

---

## 8. 运行告警（alerts）

**功能定位**：本地告警的记录、确认/关闭与阈值规则管理。

**信息架构**：告警规则表（规则 / 启用 Switch / 触发次数 InputNumber / 窗口秒 InputNumber / 保存）+ 告警记录表（告警 / 状态 Tag / 次数·最近 / 链路 Trace / 确认·关闭）。

**核心交互**：`saveAlertRule()`（admin 或 `lim:manage`）；`changeAlert('acknowledge'|'close')`。

**数据真实性**：`alerts()/alertRules()/acknowledgeAlert()/closeAlert()` 真实接口。

**设计建议**
- 非管理员时 Switch / InputNumber / 保存按钮只读（当前已实现 `canManageAlerts` 判断）。
- 标签页 `运行告警` 在有关联 OPEN 告警时显红点（已挂 `alerts.filter(OPEN).length`）。
- 明确标注：「邮件/Slack/PagerDuty 等生产通知尚未配置」。

---

## 9. 记忆与技能治理（skills）

**功能定位**：Skill 候选的登记、审核、验证、版本状态机管理（**不自动写入 Memory 或执行**）。

**信息架构**：Skill Registry 表 `skillColumns`——Skill（展示名 + `skill_id·v版本·memory_level`）/ 状态 Tag / 来源·证据 / 验证·有效期 / 计数（使用·纠错）/ 操作（查看·按状态迁移）。

**核心交互**：`createSkill()`（受控模板 + 引用元数据，拒自由文本）；`transitionSkill()` 按 `targets` 状态机迁移（需填理由）；`editSkillCandidate()`（仅 CANDIDATE 可改，审核后锁定）。

**数据真实性**：`skills()/createSkill()/transitionSkill()/updateSkillCandidate()` 真实接口。使用量/纠错量保持真实记录值。

**设计建议**
- 状态色板：ACTIVE=绿，CANDIDATE/UNDER_REVIEW/VERIFIED=蓝，DEGRADED=橙，REVOKED=红。
- 状态机显式展示：`CANDIDATE → UNDER_REVIEW → VERIFIED → ACTIVE / DEGRADED / FROZEN → REVOKED`，每步需理由。
- 强调「内容不会自动写入 Memory、拼入提示词或执行」，防止演示误读为已上线能力。

---

## 10. 独立页：LIM 采购补货（LimReplenishmentPage）

**功能定位**：LIM 在采购域的落地用例页（136 行），与 `purchase_agent` 联动。

**设计建议**：归入「LIM 用例页」一类，后续与采购计划 / 变更页统一信息架构；本规范不展开，待采购域模块开发计划时一并设计。

---

## 11. 一致性清单（评审用）

| 项 | 要求 | 现状 |
|---|---|---|
| 演示数据标注 | 橙色 `演示` 角标 | 总览告警数已标；其余占位需补 |
| 不可用指标 | 显式 `不可用`，不估算 | Token/费用等已正确标注 ✅ |
| read/write 视觉区分 | 颜色 + 文案 | Tool 用红/绿 Tag ✅ |
| Skill 状态机 | 色板 + 显式状态机 | ✅ |
| 空壳页 | 禁止 | 各区均有实质内容 ✅ |
| 响应式 | 窄屏可读 | Trace 三栏需加断点 ⚠ |

---

## 12. 下一步建议

1. **优先**：把「演示 / 不可用」标注从代码级 Alert 提升为统一的页面级角标组件，保证 9 区一致。
2. **草稿创建表单化**：Agent/Tool/Workflow/Skill 的 `prompt(JSON)` 改为分步表单，降低出错、提升可用性。
3. **逐模块开发计划**：结合 `g0-capability-inventory.md` 的 FR-001~024，为 LIM 每个模块（Registry / Runtime / Workflow / Eval / Knowledge / Skills / Alerts / Trace / Metrics）补「范围·接口·验收」开发计划（即你对话里说的『每个模块怎么开发』）。
4. **扩展到其余系统**：本规范只覆盖 LIM Console；ERP/OMS/WMS/SCM/Storefront 共约 80 页的「功能 + UI 设计」按同样模板批量产出（见后续排期）。
