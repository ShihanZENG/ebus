# G3 LIM 工作流编排契约

状态：平台侧契约；本轮 LIM 实现已覆盖 Registry、校验、运行与证据汇总基础接口。

## 边界

- LIM 是唯一工作流定义、DAG 调度、子任务 Run/Trace、取消/超时和聚合状态的所有者。
- ERP/OMS/企业管理页面只提供注册过的 Tool 适配器和领域证据字段，不自行创建第二套跨 Agent 执行器或运行状态机。
- 首批编排只调用 active、只读、固定版本的 Tool；不提供生产写执行、动态代码、任意提示词工具调用或模型自行扩图。
- 每个子任务仍通过现有 LIM Run/Tool Invocation/Span 外壳执行，继承同一 actor 的当前权限和 Scope。父 WorkflowRun 记录图版本及子 Run ID。

## 版本化定义

平台资源：

- `LimWorkflow`：稳定 `workflow_id`、显示名、业务域、状态。
- `LimWorkflowVersion`：不可变版本号、输入 JSON Schema、节点/边定义、状态（draft/validated/archived）、审核审计元数据。
- Workflow 版本引用明确的 `agent_id/version` 与 `tool_id/version`；不能在运行时漂移到“最新版本”。

最小 DAG 节点为 `tool_call` 和 `join`。每个节点有稳定 `node_id`、唯一依赖列表、固定 Agent/Tool 版本和参数映射。参数映射仅允许从经过 Schema 校验的 workflow input 或上游结果 JSON Pointer 取值，拒绝模板代码、表达式执行和动态工具名。

边条件只支持受限声明式比较：JSON Pointer 的 `exists`、`eq`、`in`，常量必须是定义内容的一部分。缺省边表示无条件依赖；join 等待所有实际启用的上游节点达到终态。环、悬空引用、write Tool、未验证版本或无效条件在 Workflow 版本验证时拒绝。

## API

- `POST /api/v1/lim/workflows`：创建 draft 定义/版本。
- `GET /api/v1/lim/workflows`、`GET /workflows/{id}/versions`：按 `assistant:read` 查询可见定义和版本。
- `POST /workflows/{id}/versions/{version}/validate`：校验 DAG、Schema、固定 Agent/Tool 版本和只读风险。
- `POST /workflow-runs`：以 `workflow_id/version/input` 创建运行；客户端不提交 actor、权限或扩大 Scope 的字段。
- `GET /workflow-runs/{run_id}`、`GET /workflow-runs/{run_id}/trace`、`POST /workflow-runs/{run_id}/cancel`：读取父运行、任务状态、子 Run/Trace 和取消。

创建请求示意：

```json
{
  "workflow_id": "cross-domain-diagnosis",
  "version": "1.0.0",
  "input": {"shop_id": "...", "business_date": "2026-10-21"}
}
```

运行服务端以调用人当前权限构建 Scope，并与父运行 Scope 取交集后传给每个子 Run；工具响应和异常均走现有 Trace 脱敏。工作流预算限制总节点数、并发度、工具调用数和时长。当前同步单进程调度在节点波次之间响应取消；不保证杀断正在执行的同步业务函数，不提供进程重启恢复或多实例 worker 语义。

## 子任务、证据及聚合

父 `WorkflowRun` 固定 workflow 版本、actor、scope snapshot、状态、预算和聚合结果。每个 DAG 节点对应一个 `WorkflowTask`，保存 node ID、条件判定、状态、子 Run ID、尝试次数和错误码。当前 MVP 不自动重试；后续若增加只读节点重试，须创建可追溯的新 attempt，不能覆盖旧 Trace。

业务 Tool 可以返回领域 evidence refs，公共字段建议为：

```json
{
  "ref_id": "domain-specific-stable-id",
  "source": "erp.inventory",
  "source_version": "...",
  "content_hash": "sha256...",
  "subject": {"sku_id": "...", "warehouse_id": "..."},
  "claim_key": "inventory.available",
  "value": 12,
  "value_type": "number",
  "unit": "piece",
  "observed_at": "2026-10-21T00:00:00Z"
}
```

仅当适配器显式提供 `comparison_key` 或 `comparable_group` 时，LIM 才按 `subject + claim_key + comparison key` 评估；默认没有比较声明的 ref 只保留原文，不做数值比较。声明可比后，值相同标记 `CONSISTENT`，不同标记 `CONFLICT`；观察时间或单位不兼容标记 `INCOMPARABLE`。预期 claim 缺失标记 `MISSING`。LIM 返回来源和原值，不选“赢家”、不推断因果，也不让 LLM 自动消解冲突。领域适配器对稳定引用、单位、时间语义、比较声明和内容哈希负责；LIM 对权限、调度、状态、冲突分类和审计负责。

父结果至少包含：

```json
{
  "status": "COMPLETED_WITH_CONFLICTS",
  "tasks": [{"node_id": "inventory", "status": "COMPLETED", "run_id": "..."}],
  "evidence_refs": [],
  "conflicts": [{"claim_key": "inventory.available", "status": "CONFLICT", "claims": []}],
  "missing": [],
  "summary": {"completed": 2, "failed": 0, "conflicts": 1}
}
```

Workflow 终态区分 `COMPLETED`、`COMPLETED_WITH_CONFLICTS`、`PARTIAL`、`FAILED`、`CANCELLED`、`BUDGET_EXCEEDED`。完成仅表示所有启用节点有终态且汇总已生成，不表示诊断结论正确或冲突已解决。

## MVP 实施顺序与不变量

1. 先补 workflow/version/task 父子数据模型、定义校验和 Trace 关联；只读节点、固定图版本。
2. 实现有并发上限的依赖波次调度、条件边、join、取消与任务失败策略；先采用单进程服务内调度，不引入消息队列。服务重启恢复/跨实例调度在加入 worker 基础设施前不得宣称可靠。
3. 定义第一批领域 evidence ref 适配器，做同主体同口径的确定性冲突汇总；企业端负责业务 claim 语义和数据来源。
4. 提供 LIM Workflow/Run UI 展示任务树、子 Trace、缺失和冲突，并完成权限/取消/失败/并发/超时的验收。

不变量：子任务不能扩大父 Scope；每个结果能回溯到版本化 Tool/Run/证据引用；部分失败不会伪装完整成功；冲突不会被静默合并；复用业务原有审批和执行回执边界。
