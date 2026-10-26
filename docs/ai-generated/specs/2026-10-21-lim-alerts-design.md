# LIM 运行异常告警设计

## 意图

补齐 PRD LIM-FR-024 的本地最小闭环：从现有 Run、ToolInvocation 和 Workflow 状态产生可追溯、可确认、可关闭的持久化告警，并由 LIM Console 查看和维护阈值。

## 目标与边界

- 持久化三个阈值规则：Agent Run 失败、只读 Tool 超时、Workflow 编排级失败。默认分别为 3 次、2 次、3 次；统计窗口均为滚动 10 分钟；管理员可启停和调整阈值/窗口。
- 只有 `live` Run 参与告警计数；Sandbox 仿真、取消、校验拒绝不计入生产运行告警。
- Run `FAILED` / `BUDGET_EXCEEDED` 仅在进入实际执行后发生时算失败事件；预执行拒绝/校验失败（包括 `TOOL_NOT_REGISTERED`、`TOOL_WRITE_BLOCKED`、`TOOL_DEFINITION_INVALID`、`TOOL_ARGUMENTS_INVALID`、`TOOL_HANDLER_UNAVAILABLE`、`SCOPE_FORBIDDEN`、`RUN_NOT_RUNNING`，以及工具调用前被拒绝的预算超限）不计入。`TOOL_TIMEOUT` 只计入 Tool 超时规则，避免同一故障双报。
- Tool 同步 handler 返回后若耗时超过 Tool `timeout_ms`，将 Invocation 标为 `TIMEOUT`、Run 标为 `FAILED/TOOL_TIMEOUT`，不保留超时结果或 EvidenceRef，并计入 Tool 超时规则。当前同步 Runtime 不能中断仍在执行的 handler；本地告警只能识别返回后超时，不能提供硬实时中止保证。
- Workflow 父级只在失败/预算超限且没有失败/超时子 Run 时记一次 Workflow 事件。子 Run 已触发的错误/超时不再重复计为父级事件。
- 告警以规则+Agent/Tool/Workflow 为稳定去重键。达到阈值时创建/更新唯一告警，记录窗口内事件数、最近相关 Run/Trace 或 Workflow Run；已关闭告警再次达到阈值时重新打开。
- 告警仅持久化受控标识、状态、时间、计数和错误码；不复制 goal、参数、Mock body、异常原文或 Trace 内容。读取遵守 `assistant:read` 与 Run actor 可见性；确认/关闭/阈值管理要求 `lim:manage`。每次治理动作写审计。
- 状态仅为 `OPEN → ACKNOWLEDGED → CLOSED`；允许 OPEN 直接关闭。新事件命中已关闭告警时清理确认/关闭人和时间并重新打开。
- 仅实现本地持久化与 Console；邮件、Slack、PagerDuty 等生产通知通道待部署配置，不冒充已接通。

## 接口与页面

- 迁移 `0036` 创建 `lim_alert_rules` 和 `lim_alerts`，并种入上述三条默认规则。
- `GET /api/v1/lim/alerts`：分页/状态筛选，非管理员仅见自己发起 Run 的告警。
- `GET /api/v1/lim/alerts/rules` 与 `PUT /api/v1/lim/alerts/rules/{rule_key}`：读取及管理持久化规则；阈值限制 1–1000，窗口 60–86400 秒。
- `POST /api/v1/lim/alerts/{alert_id}/acknowledge` 与 `/close`：管理员确认/关闭，返回最新告警。
- Alert 返回稳定 `alert_id`、规则、严重度、状态、发生次数/时间、错误码、相关 Run/Trace/Workflow Run ID；UI 通过现有 Run/Workflow Trace 查看链路，不复制 Trace 值。
- Console 增加“运行告警”页签：告警列表、状态操作、相关 Run/Trace 跳转、阈值维护和“通知未配置”提示。

## 验收

- 未到阈值无告警，达到阈值只有一条可更新告警；不同 Agent/Tool/Workflow 不互相计数。
- Tool 慢响应被标为 TIMEOUT，结果/Evidence 不进入 Run；同一超时不再生成 Run failure 告警。
- Sandbox、取消、预执行拒绝/校验失败（包括未知工具、无效参数、scope 拒绝）不产出告警；Workflow 子 Run 已报错时父 Run 不重复产告警。
- 关闭后同一维度再次达到阈值会重开；确认/关闭有操作者与审计记录。
- 普通用户只看到自己的告警；越权管理、非法阈值、非法状态迁移被拒绝。
- 错误/Trace 内容不复制到告警字段；迁移可在隔离数据库升级/回滚；LIM 后端测试和前端构建通过。
- PRD LIM-FR-024 仍标部分实现，直到生产通知和部署值班链路另行验收。
