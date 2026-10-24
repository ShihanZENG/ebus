# LIM Sandbox Mock Tool 调试设计

## 意图

补齐 PRD LIM-FR-022 的本地可交付部分：让 AI 工程师用隔离 Run、用户提供的 Mock Tool 响应和固定小预算验证 Agent/Tool Schema 与 Trace 链路。

## 目标

- 复用 LIM `LimRun` / `LimSpan` / `LimToolInvocation` 和既有 Run 状态迁移、Trace 查询。
- `POST /api/v1/lim/sandbox/runs` 接收固定版本 Agent、Tool、参数和 Mock response；后端只校验 Schema、存脱敏仿真结果，不调用任一 READ_TOOL_HANDLER 或外部服务。
- Sandbox Run 的 `execution_mode='sandbox'`、Scope 快照显式空白；用户不得提交/扩展 BusinessScope。
- 固定服务端预算：单 Tool 调用、最多 5 秒、响应摘要上限沿用 Trace 脱敏器；客户端不能修改预算。
- 仅允许已验证 Agent 绑定已激活 Tool 版本；写 Tool 也只能仿真，记录明确写入模拟状态，业务数据不变。
- Run/Trace UI 清楚区分 Sandbox 和真实只读 Run，且显示“仿真数据，不是业务证据”。

## 非目标与边界

- 不实现任意 Python/脚本执行、不执行真实工具、不访问业务数据库数据、不产生有效业务 EvidenceRef。
- 不调用模型或自动生成 Mock 输出；输入/输出由操作者手工提供。
- 不将 Sandbox 结果用于发布门禁、业务审批、成本统计或 Evidence 聚合。
- 不声明容器级或进程级隔离；隔离边界是同一应用内的无 handler 模拟路径与独立 Run 标记。

## 数据与接口规则

- `LimRun.execution_mode` 取 `live|sandbox`，现有记录默认 `live`；迁移设置数据库默认值为 `live`。
- Agent 必须是已验证固定版本；Tool 必须为已激活固定版本，且出现在 Agent `allowed_tools` 中。允许模拟 read/write 定义，但绝不解析或调用 handler。
- 先验证用户参数与 Tool input schema、Mock response 与 Tool output schema；错误返回 422 且不创建 Run。校验兑现支持的 enum、pattern、长度/数量边界、数值边界和 JSON 深层语义的 uniqueItems；每个数组都必须声明 items；未知或不支持的 schema 关键字在 Tool 校验时 fail closed。
- 创建常规 Run 状态路径 `CREATED → SCOPE_CHECKED → PLANNED → RUNNING → VERIFYING → COMPLETED`。sandbox scope 为 `{sandbox:true, shop_ids:[], warehouse_ids:[]}`，ref 由服务端生成。
- Span 标记 `sandbox=true,mocked=true`；ToolInvocation 参数/响应仅存结构/类型摘要，Evidence refs 固定为空；Run `output_summary` 包含 `sandbox=true` 与 `mock_response` 摘要。操作者输入的任何参数/Mock scalar 值不进入持久化 Trace/Run/审计，也不从 API/UI 回显；只保存字段结构及 JSON 类型摘要，以免未知字段里的客户、订单或自由文本绕过关键字脱敏。请求体仍限制 64 KiB，摘要限制深度和集合规模。
- API 只要求 `assistant:read`，与现有只读 Run 一致；Run 审计标记模拟且不回显原始敏感值。

## 验收

- 运行 Sandbox 时注册的真实 handler 未被调用；测试以会抛错的 handler 证明。
- 传入伪造 Scope 不改变空 Sandbox Scope；mock read/write 输出不写入业务数据。
- Agent/Tool 版本未启用、未绑定、参数/响应不符合 Schema 时拒绝且不创建 Run。
- trace 中 invocation/span/Run 都标识 Sandbox；不会出现可被聚合的 EvidenceRef。
- 预算固定且客户端无法修改；敏感字段和值经 Trace 脱敏。
- Run API/UI 明确显示仿真模式；迁移升级/回滚以及 LIM 回归、前端构建通过。
