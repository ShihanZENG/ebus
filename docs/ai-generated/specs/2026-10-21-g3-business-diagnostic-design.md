# G3 跨域经营诊断设计

## 意图

让经营人员按店铺和日期范围读取同一份 ERP 只读诊断快照，汇总订单、库存、广告和收款证据，显式展示来源覆盖、缺失和不可比较之处，并提供不触发业务写入的复核建议。

## 目标

- 所有诊断数据来自当前 ERP 数据库和可验证的本地报表批次。
- 每个域单独显示权限、数据量、来源时间/期间、缺失状态和限制。
- 仅在范围、期间、币种和口径明确匹配时生成跨域关联，例如广告 SKU 与可用库存。
- 通过 LIM Workflow 的固定版本只读节点暴露业务证据；Workflow/父子 Run/Trace、预算、取消及冲突状态由平台端持有。
- 将缺失或冲突证据组织为可复核 Finding，并列出复核建议；不自动修改数据。

## 非目标

- 企业端不实现 Workflow/并行调度/聚合器。ERP 仓库已有 LIM Workflow API/Runner；业务 Workflow 在 Tool/Agent 固定版本激活且定义验证后运行。
- 不生成或提交采购、广告预算、退款、订单等业务写入提案。
- 不把广告归因销售与 ERP 订单/收款金额视为同一口径；不跨币种求和。
- 不把人工导入广告数据描述为平台实时连接。

## 接口与权限

- Tool IDs：`erp.orders.period-summary`、`erp.ads.campaign-performance`、`erp.inventory.shop-availability`、`erp.finance.recorded-payments`、`erp.ads.inventory-alignment`，Tool contract 固定 `1.0.0`。Evidence Ref source version 为 `1.0.1`。各域 Agent 版本由 LIM Workflow 定义固定引用。
- 所有 Tool 使用 `shop_id`；期间 Tool 另有 `date_from`/`date_to`（最多 93 天）；库存 Tool 要求 `sku_codes`（最多 200 个）。Shop 必须属于当前 Run 的服务端 shop scope。
- 日期按店铺 `timezone` 的自然日解释；订单按 `ordered_at` UTC 时间过滤。缺少 `ordered_at` 的订单单独计数，不能猜测所属期间。广告按报表自然日过滤；库存是当前快照并单独标注采集时间。
- 订单证据需要 `orders:read`；库存需要 `inventory:read` 并遵守 warehouse scope；广告需要 `dashboard:read`；财务收款需要 `finance_agent:read` 与 `payment_records:read`。每个 Tool 缺权限时返回有权限门控的 missing gap，不阻止其他 Workflow 节点。
- LIM 调用仍要求 `assistant:read`；Tool 内逐域执行权限检查，绝不使用客户端传入的授权范围。

## Finding 规则

- 证据统一返回 LIM `evidence_refs[]`：`ref_id/source/source_version/content_hash/subject/claim_key/value/value_type/unit/observed_at`；期间证据另返回 `period_start/period_end/time_basis`。
- 店铺可用量沿用 `inventory_allocation.available(db, warehouse_id, sku_id, shop_id=...)`，仅汇总当前账号可访问仓库。
- 订单按店铺时区的 `ordered_at` 过滤；缺失时间另报 gap。广告按导入 `report_date`；库存是执行时快照；收款按关联订单的 `ordered_at` 归期。期间或来源不一致不强行比较。
- 统一比较器只应在 subject、claim_key、unit 和兼容时间口径一致时判 `CONSISTENT/CONFLICT`；广告归因销售与 ERP 订单金额、收款金额是不同 claim，必须保持 `INCOMPARABLE`。跨域业务 Finding/因果规则需由平台 Workflow 的受控 Join/领域规则契约另行定义。
- 本版本不设置 `comparison_key`/`comparable_group`，平台默认保留为 `INCOMPARABLE`。未来只有业务适配器显式声明比较键并确认 subject、unit、观察时点、期间与授权仓范围一致，才允许跨来源数值比较；库存跨 Tool 引用暂不声明可比。
- 广告导入目前不提供每日完整覆盖标志；即使有报表行也会返回 `ADS_COVERAGE_UNCONFIRMED`。缺少某日期的行不能视为广告指标为零。广告/库存对齐 SKU 超过处理上限时显式 gap。

## 运行记录

企业端提供五个版本化只读 Tool handler；LIM Workflow Runner 负责组装、调度、Trace 树、gaps/findings 聚合和状态。运行时仍需管理员注册并激活 Tool、Agent 固定版本及 Workflow 定义。

## 验收边界

- 越权 shop、伪造 scope、无任一子域权限、空数据、广告报表跨期间、SKU 未映射、跨币种及库存低于/等于零时，输出隔离且口径明确。
- 只读 Run 不写业务表。所有摘要经 LIM Trace 脱敏。
- 受控 LLM planner、跨域数值 comparison_key、Proposal/审批绑定和写执行回执仍不在此 G3 范围，不得宣称 G3 已具备自动决策或写执行能力。
