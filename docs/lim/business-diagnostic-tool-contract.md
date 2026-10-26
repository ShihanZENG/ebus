# G3 经营诊断业务 Tool 契约（供 LIM Workflow 接入）

状态：5 个 ERP 只读适配器已进入 LIM `READ_TOOL_HANDLERS`。当前 ERP 仓库已有 `/api/v1/lim/workflows`、版本校验及 `/api/v1/lim/workflow-runs` 运行/Trace 实现；能否启动此业务 Workflow 取决于 LimTool/Agent 固定版本完成注册、激活和 allowlist 校验，以及数据库中的 Workflow 定义完成校验。

## 边界

- 经营端提供固定版本的域只读 Tool；LIM 拥有 Workflow DAG、子 Run/Trace、预算、取消、重试和确定性 evidence 聚合。
- Tool contract 版本为 `1.0.0`；Evidence Ref `source_version` 为 `1.0.1`（修复不同 subject/claim 同值导致的引用 ID 碰撞）。Tool handler 在 `backend/app/business_evidence_tools.py`。
- 每个 Tool 输入都有 `shop_id`；涉及期间的 Tool 另需 `date_from`、`date_to`，格式 `YYYY-MM-DD`、最长 93 天。Tool 自行校验 actor 的持久化角色和 Run scope。
- Tool 需要 `assistant:read`（LIM 路由）以及表格中的领域权限。单域 Tool 缺少本域权限时返回 `gaps[{code:PERMISSION_REQUIRED}]` 与空 refs；广告库存对齐若有广告权限但缺库存权限，保留广告 refs 并返回库存权限 gap，不把库存当零。越权 Shop/仓库不泄漏存在性。
- 标准响应：`{source, source_version, rule_version, snapshot_at, evidence_refs, gaps, ...metadata}`。每个 evidence ref 精确包含 LIM 提案字段：`ref_id`, `source`, `source_version`, `content_hash`, `subject`, `claim_key`, `value`, `value_type`, `unit`, `observed_at`；期间 claim 另含 `period:{from,to,timezone,time_basis}`。

## Tool 列表

| Tool ID | 必需领域权限 | 输入 | Claim / subject / unit / 时间口径 |
|---|---|---|---|
| `erp.orders.period-summary` | `orders:read` | `shop_id,date_from,date_to` | `orders.units_ordered`；subject=`{shop_id,sku_id,sku_code}`；unit=`piece`；按店铺时区自然日筛选 `SalesOrder.ordered_at`，只计 `approved/shipping_requested/fulfilled/after_sale` 订单。另有 `orders.gross_amount`，subject=`{shop_id,currency}`、unit 为 ISO 币种。缺失 `ordered_at` 单独 gap，不猜入期间。 |
| `erp.ads.campaign-performance` | `dashboard:read` | `shop_id,date_from,date_to` | `ads.spend` / `ads.attributed_sales` / `ads.attributed_order_count`；subject=`{shop_id,campaign_id,sku_code?,currency}`；unit=币种或 `order`；按广告人工导入 `report_date`，并返回实际批次引用、观察到的日期和 SKU codes。最多 2,000 行，超出显式 gap；导入模型未声明每日完整性，始终提示覆盖未确认，缺行不得解释为零。 |
| `erp.inventory.shop-availability` | `inventory:read` | `shop_id,sku_codes[]`（最多 200 个） | `inventory.shop_available_qty`；subject=`{shop_id,sku_id,sku_code}`；unit=`piece`；当前快照 `observed_at`。按 `inventory_allocation.available(db,warehouse_id,sku_id,shop_id)` 汇总当前 Run 可访问仓库。 |
| `erp.finance.recorded-payments` | `finance_agent:read`,`payment_records:read` | `shop_id,date_from,date_to` | `finance.recognized_payment_amount`；subject=`{shop_id,currency}`；unit=ISO 币种；按关联订单店铺时区 `ordered_at` 归期，仅认可 legacy 或明确 verified 的 real 收款；可识别订单缺 `ordered_at` 的已认可记录并单独报 gap。 |
| `erp.ads.inventory-alignment` | `dashboard:read`,`inventory:read` | `shop_id,date_from,date_to` | 适用于首个跨域纵切：返回期间广告 SKU claims、当前 `inventory.shop_available_qty` claims，以及 `ADVERTISED_SKU_NO_AVAILABLE_STOCK` Finding（可用量 `<=0`）。Finding 同时引用广告证据和库存证据；建议复核，不暂停/修改广告。库存权限缺失时只返回广告 refs 和 permission gap，不得推断库存为零。 |

## 比较语义

- 当前 Tool 有意使用互不混淆的 claim keys。订单含税金额、广告归因销售额和已记录收款金额不能相互判数值 `CONFLICT`；比较器应返回 `INCOMPARABLE`，原因分别是指标定义不同、广告归因窗口与订单期间不同、或收款按已记录事实而非订单总额计量。
- `inventory.shop_available_qty` 是当前快照，不与日期区间内的销量/广告数值直接相等比较。`erp.ads.inventory-alignment` 已提供显式业务 Finding 和引用；平台保留原始 refs，不覆盖此 Finding。
- 本批不保证不同 Tool 的 `observed_at` 完全一致。若平台要求同一数据库快照，请 Workflow 在一个 read transaction/snapshot token 能力落地后再承诺一致性。
- `evidence_refs[].content_hash` 为该 claim 的规范化源值、期间或底层分配记录摘要 SHA-256；不含姓名、地址、电话、邮箱或支付凭据。
- 本版不为跨域引用设置 `comparison_key`/`comparable_group`。平台应缺省按 `INCOMPARABLE` 保留证据；只有业务适配器明确声明相同比较键，并验证同 subject、claim、unit、期间/观察时点及范围后，才可判 `CONSISTENT/CONFLICT`。库存对齐 Finding 是有证据支持的业务规则结果，不代表两个独立库存 Tool 的库存量已声明可比较。
- 所有 `content_hash`/`ref_id` 均绑定来源、subject、claim、单位、观察时间和期间；相同数值但不同 subject/claim 不会复用引用 ID。库存量只汇总用户当前 Run 有权访问的仓库；空仓库范围返回 gap，不输出伪零库存。

## Workflow 首次输入

```json
{"shop_id":"<ERP shop UUID>","date_from":"2026-10-01","date_to":"2026-10-21"}
```

建议节点：订单摘要、广告表现、收款摘要并行；广告库存对齐作为其自身 Tool 节点（不要再和独立库存节点重复跑相同 subject，除非要做库存结果一致性核验）。如果拆开广告与库存，Workflow 可从广告结果的 `sku_codes` 通过受限 JSON Pointer 映射给库存 Tool。LIM 输入中的 `shop_id` 必须再与父 Scope 求交，绝不将它作为授权依据。

## LIM 注册与 Workflow 运行

- Tool Upsert 的 `input_schema` 必须是 `type:object`、逐字段声明受支持的 JSON type、填写 `required` 并设置 `additionalProperties:false`；`output_schema` 也必填。Tool 的 `scope_policy` 只能写 `shop/warehouse: server_scope`，不可把模型传入的店铺/仓库当授权。
- Agent 固定推荐 `erp.shop-period-diagnostic@1.0.0`，allowlist 绑定订单摘要、收款摘要、广告库存对齐三个 Tool。模板和当前运行时 JSON Pointer / `argument_mapping` 字段见 [G3 首条 Workflow 模板](./g3-first-workflow-template.md)。
- 当前 `READ_TOOL_HANDLERS` 仅表示服务端存在 handler；它不会自动创建或激活数据库中的 `LimTool` / `LimAgent`。应通过 LIM Registry API/UI 注册固定版本、验证 Agent、创建并校验 Workflow，然后再以授权用户启动运行。

## 仍需平台契约补充

当前平台提案的 join 只比较同一 `subject+claim_key+unit`，还没有表达领域规则（例如广告 campaign 与当前库存不相等的关系）。本次通过 `erp.ads.inventory-alignment` 返回有证据引用的明确业务 Finding；将来若 LIM 支持受控规则节点，可改由平台执行该规则，但不得引入任意表达式或 LLM 自行比较。
