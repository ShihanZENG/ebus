# G3 首条经营 Workflow 模板契约

状态：业务侧推荐契约，供 LIM Workflow DSL/API 定型时映射；不是当前已部署的 Workflow API 请求体。

## 模板

- `workflow_id`: `erp.shop-period-diagnostic`
- `version`: `1.0.0`
- 名称：店铺周期经营与广告库存风险复核
- 目的：读取指定店铺期间订单表现和已记录收款，并检查同期广告报表 SKU 的当前店铺可用库存。仅输出带引用的证据与明确的规则 Finding。
- 输入：`shop_id`、`date_from`、`date_to`。日期为 `YYYY-MM-DD`，最长 93 个店铺本地自然日。

## 固定 DAG

三个只读 Tool 节点从同一 Workflow 输入并行启动；Join 等待所有启用节点终态，按固定节点顺序保留 outputs、gaps、evidence refs 和 Findings。

| node_id | 固定 Tool | arguments 映射 | 领域权限 | 输出用途 |
|---|---|---|---|---|
| `orders` | `erp.orders.period-summary@1.0.0` | `shop_id,date_from,date_to` 原样取自 Workflow input | `orders:read` | 订单件数与按币种订单总额，含订单时间缺失 gap |
| `payments` | `erp.finance.recorded-payments@1.0.0` | 同上 | `finance_agent:read`、`payment_records:read` | legacy 或已核验 real 收款按币种汇总；订单缺时间的收款单独 gap |
| `ad-inventory` | `erp.ads.inventory-alignment@1.0.0` | 同上 | `dashboard:read`、`inventory:read` | 广告报表 SKU 归因销售、当前店铺可用量及库存不足 Finding；广告覆盖不完整时保留 gap |

各节点继承同一 actor，并把 Workflow Scope 与该 actor 当前服务端店铺/仓库权限求交。`shop_id` 仅是业务输入，不构成授权；任意节点不得扩大父 Scope。各 Tool 自己返回领域权限 gap，不能把缺权限或缺数据改写成数值零。

## LIM Workflow DSL 对照定义

当前 ERP LIM 校验器的字段为 `input_schema`、`input_constraints`、`tasks`、`argument_mapping`、`depends_on`；节点参数映射要求直接依赖节点或 Workflow input 的 JSON Pointer。以下 JSON 使用 AI 管理端建议的单一固定 Agent `erp.shop-period-diagnostic@1.0.0`；Agent 必须注册并 Validated，且 allowlist 绑定上述 3 个 Tool。Tool contract 版本固定为 `1.0.0`，相同 Agent ID/version 用于三个并发节点。

```json
{
  "workflow_id": "erp.shop-period-diagnostic",
  "version": "1.0.0",
  "input_schema": {
    "type": "object",
    "properties": {
      "shop_id": { "type": "string" },
      "date_from": { "type": "string" },
      "date_to": { "type": "string" }
    },
    "required": ["shop_id", "date_from", "date_to"],
    "additionalProperties": false
  },
  "input_constraints": [
    { "type": "date_range", "start_pointer": "/date_from", "end_pointer": "/date_to", "max_days": 93 }
  ],
  "tasks": [
    {
      "node_id": "orders", "type": "tool_call", "depends_on": [],
      "agent_id": "erp.shop-period-diagnostic", "agent_version": "1.0.0",
      "tool_id": "erp.orders.period-summary", "tool_version": "1.0.0",
      "argument_mapping": {
        "shop_id": { "from": "input", "pointer": "/shop_id" },
        "date_from": { "from": "input", "pointer": "/date_from" },
        "date_to": { "from": "input", "pointer": "/date_to" }
      }
    },
    {
      "node_id": "payments", "type": "tool_call", "depends_on": [],
      "agent_id": "erp.shop-period-diagnostic", "agent_version": "1.0.0",
      "tool_id": "erp.finance.recorded-payments", "tool_version": "1.0.0",
      "argument_mapping": {
        "shop_id": { "from": "input", "pointer": "/shop_id" },
        "date_from": { "from": "input", "pointer": "/date_from" },
        "date_to": { "from": "input", "pointer": "/date_to" }
      }
    },
    {
      "node_id": "ad-inventory", "type": "tool_call", "depends_on": [],
      "agent_id": "erp.shop-period-diagnostic", "agent_version": "1.0.0",
      "tool_id": "erp.ads.inventory-alignment", "tool_version": "1.0.0",
      "argument_mapping": {
        "shop_id": { "from": "input", "pointer": "/shop_id" },
        "date_from": { "from": "input", "pointer": "/date_from" },
        "date_to": { "from": "input", "pointer": "/date_to" }
      }
    },
    { "node_id": "collect", "type": "join", "depends_on": ["orders", "payments", "ad-inventory"] }
  ]
}
```

按当前 AI 管理端对齐，三个 tool_call 并发运行，Join 按节点定义顺序保留 outputs、gaps、evidence_refs 和 Findings；无 `comparison_key` 的 refs 不判数值冲突。不得把自然语言 Finding 转成冲突，也要保留每个节点错误状态和子 Run 证据。

## Join 与比较规则

- Join 是确定性证据收集，不执行 LLM 摘要改写，不对不同 claim 求和或比较，不选择“赢家”。保留来源 Tool、`source_version`、原始值、单位、期间、观察时间、hash、gap 与 Finding 引用。
- 当前订单金额、广告归因销售和已记录收款是不同 claim；库存是当前快照。不得判为互相 `CONSISTENT/CONFLICT`。所有 refs 缺省 `comparison_key`/`comparable_group`。
- `ADVERTISED_SKU_NO_AVAILABLE_STOCK` 是广告 SKU 与当前店铺可用量的显式业务规则 Finding，需完整保留其广告和库存 evidence ref；它不触发暂停广告或其他写动作。
- Tool coverage gap、权限 gap 和失败状态需按原节点分别呈现。只有 Workflow 实际执行完所有启用节点且生成聚合结果，平台才能采用其终态规则；不允许将部分节点失败呈现为完整诊断。
- 同一模板可能因节点权限不同返回不同证据域；UI 应逐域显示权限/数据缺口，不因一个域缺失而抹掉其他成功域结果。

## 注册前置条件

1. LIM Registry 注册并激活以上三个只读 Tool 的不可变版本和匹配的 Agent allowlist；目前 ERP `READ_TOOL_HANDLERS` 已有服务端 handler，但真实定义激活与 Workflow 运行仍依赖运行环境/平台 Registry。
2. Workflow DSL 明确 JSON Pointer 输入映射、节点固定版本、Scope 传递、子 Run/Trace 和预算字段，再据此保存此模板定义。
3. 使用受限角色覆盖订单、财务/收款、广告和库存权限组合做验收，特别确认“缺权限 != 零结果”，以及不同来源 evidence refs 默认不可比。
