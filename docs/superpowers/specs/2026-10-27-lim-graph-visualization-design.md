# LIM 证据关系图可视化 设计规格

> 对应计划：`docs/superpowers/plans/2026-10-27-lim-graph-visualization.md`
> 权威台账：`docs/lim/g0-capability-inventory.md`（LIM-FR-014 状态以台账为准）

## 1. 目标与边界

把 `/api/v1/lim/v2/live/runs/{run_id}/graph` 从「JSON 文本转储」变成**可读、可交互、可追溯的证据关系图**。

**做**：
- 实体可读化：UUID → `code · name`
- 实体归一：`sku_id` 与 `sku_code` 合并为单个 SKU 节点
- 关系边：基于 ERP 真实外键推导实体间关系
- 时间维度：按 checkpoint 版本观察时间过滤
- 前端 SVG 渲染、聚焦交互、图例、明细面板

**不做（越界即错误）**：
- 不实现 Temporal GraphRAG 生产能力（多跳查询服务、valid-time 业务有效期、Neo4j 已验证链路）。台账 `LIM-FR-014` 保持 `未实现`。
- 不把 `lim_graphrag.py` 的 6 个种子节点（示例数据）混入真实运行视图。该文件自带注释：`The packaged graph contains example data only. Never report it as ERP evidence.`
- 不新增运行时依赖（v1 零新依赖，见 §6）。

## 2. 现状基线（实测，2026-10-27）

对 live 库 5 次已完成运行实测 `/graph`：

| run | SKU 数 | entities | claims | edges | 实体类型分布 |
|---|---|---|---|---|---|
| cbdc52e5 | 2 | 11 | 8 | 28 | shop1 sku_id2 sku_code2 product2 po1 supplier1 warehouse1 campaign1 |
| a94e1ec4 | 2 | 7 | 4 | 14 | shop1 sku_id2 sku_code2 product2 |
| 364dcbcf | 3 | 16 | 11 | 46 | shop1 sku_id3 sku_code3 product3 po4 supplier1 warehouse1 |
| 1d12ed7e | 2 | 11 | 8 | 28 | 同 cbdc52e5 |
| 207db7d9 | 1 | 0 | 0 | 0 | 空（跨市场 SKU，无范围内证据） |

关系类型全集：`{HAS_EVIDENCE}`——**只有实体→claim，没有实体→实体**。

claim_key 分布：`product.active`、`inventory.shop_available_qty`、`procurement.unreceived_quantity`、`ads.spend`、`ads.attributed_sales`、`ads.attributed_order_count`。

### 2.1 缺陷 D1：同一 SKU 生成两个节点

`graph_snapshot()` 以 `entity_id = sha256(f'{key}:{value}')[:32]` 建节点，而 `subject` 同时含 `sku_id` 与 `sku_code`。因此 2 个真实 SKU 产生 4 个节点（`sku_id:a6a5eb…` 与 `sku_code:BT-EARBUDS-BLK` 指向同一 SKU），视觉上是重复实体。

**证据**：每个 SKU 承载的 subject 都同时含 `sku_id` 与 `sku_code`：

- `product.active` → `{shop_id, sku_id, sku_code, product_id}`
- `inventory.shop_available_qty` → `{shop_id, sku_id, sku_code}`
- `procurement.unreceived_quantity` → `{purchase_order_id, supplier_id, warehouse_id, sku_id, sku_code, status}`
- `ads.*` → `{shop_id, campaign_id, sku_code, currency}`（**仅** sku_code）
- `finance.*` → `{shop_id, warehouse_id, currency}`（两者皆无）

结论：`sku_code` 出现在全部 SKU 承载 subject 中，`sku_id` 恒为冗余。

### 2.2 缺陷 D2：缺实体间关系

图里没有 SKU→供应商→采购单→仓库 这类链路，而这恰是业务最有价值的部分。关系并非不存在，而是 `graph_snapshot()` 从未推导——ERP 模型里有现成外键（见 §4.2）。

### 2.3 缺陷 D3：节点标签是原始 UUID

`shop_id`、`sku_id`、`product_id`、`purchase_order_id`、`supplier_id`、`warehouse_id` 的 `value` 均为 UUID36。仅 `sku_code` 与 `campaign_id` 天然可读。

### 2.4 容量上限推导

- `MAX_SKU_CODES = 20`（`lim_live_tools.py`），单次运行 SKU 上限 20
- `refs[:100]`：单域 claim 上限 100（`lim_live_tools.normalized_read`）
- 采购行 `.limit(101)` 截断到 100
- 推导最坏情形 ≈ 200 claims、120 entities；叠加 §4.2 的 8 类关系边 ≈ 400 条关系边

上限设为 **entities 300 / edges 800**，超限必须显式标记 `truncated`，绝不静默截断。

## 3. API 契约变更

`GET /api/v1/lim/v2/live/runs/{run_id}/graph`（`query`、`as_of` 参数保持不变）响应扩展：

```jsonc
{
  "run_id": "...",
  "backend": "erp_database",          // 保持：非 neo4j
  "entities": [
    {
      "id": "<sha256(key:value)[:32]>",  // 保持原语义
      "type": "sku_code",                 // 类型集合见 §4.1（移除 sku_id 节点）
      "value": "BT-EARBUDS-BLK",
      "label": "BT-EARBUDS-BLK · 蓝牙耳机",   // 新增
      "label_resolved": true,                // 新增：false 表示回退为原始 ID
      "canonical_id": "sku:BT-EARBUDS-BLK",   // 新增：前端归并键
      "aliases": ["a6a5eb5d-bf41-4dc4-ad15-5bd268f84346"]  // 新增：被合并的原始 id
    }
  ],
  "claims": [ /* 不变 */ ],
  "edges":  [ /* 不变，实体→claim HAS_EVIDENCE */ ],
  "relations": [                        // 新增：实体→实体
    {
      "source": "<entity id>",
      "target": "<entity id>",
      "relation": "supplies",
      "relation_label": "供应",
      "derived_from": "supplier_skus.supplier_id→supplier_skus.sku_id",
      "basis": "erp_foreign_key"        // 恒为 erp_foreign_key，不做推断
    }
  ],
  "time_basis": "checkpoint recorded_at (observation time)",
  "retrieval": "scoped SQL snapshots + keyword filter",
  "limitations": [ /* 保持 */ ],
  "stats": { "entity_count": 9, "claim_count": 8, "edge_count": 24, "relation_count": 12 },
  "truncated": false,
  "truncated_kinds": []
}
```

**不变量（后端测试必须覆盖）**：
1. 每条 `relations` 边的 `source`/`target` 都存在于 `entities` 中。
2. 每条 `edges` 边的 `source`/`target` 都存在于 `entities`/`claims` 中。
3. `query` 过滤后，仍满足不变量 1、2（被滤掉的实体其关系边一并丢弃）。
4. `as_of` 过滤后，claims 只含 `checkpoint.created_at <= as_of` 的检查点。
5. `graph_snapshot(db, user, run)` 两次调用结果相等（现有 `test_lim_live.py:143` 已断言，不得破坏）。
6. `entities`/`claims`/`edges` 现有字段只增不删——`lim_live_connections.export_graph` 依赖 `id`/`type`/`value` 与 `source`/`target`。

## 4. 标签解析与关系推导

### 4.1 实体类型与标签映射

| 节点 type | 数据来源 | label 组成 | 中文名（图例） |
|---|---|---|---|
| `shop_id` | `shops` | `code · name` | 店铺 |
| `warehouse_id` | `warehouses` | `code · name` | 仓库 |
| `product_id` | `products` | `code · name` | 商品 |
| `sku_code` | `skus` by code | `code · name` | SKU |
| `supplier_id` | `suppliers` | `code · name` | 供应商 |
| `purchase_order_id` | `purchase_orders` | `po_no` | 采购单 |
| `campaign_id` | `ads_campaign_daily` | `campaign_id`（本身可读，附 `campaign_name`） | 广告活动 |
| ~~`sku_id`~~ | — | **不再作为节点**，并入 `sku_code` 节点的 `aliases` | — |

回退规则：查不到行时 `label = value`（UUID 截断至前 8 位 + `…`），`label_resolved = false`，UI 以「未解析」标记并在 tooltip 展示原始 ID。

### 4.2 关系映射（全部来自真实外键，不做语义推断）

| relation | 起点 → 终点 | derived_from | 中文 |
|---|---|---|---|
| `has_sku` | product → sku | `skus.product_id→products.id` | 归属 |
| `supplies` | supplier → sku | `supplier_skus.supplier_id→sku_id`（`is_active`） | 供应 |
| `ordered_in` | sku → purchase_order | `purchase_order_items.sku_id→po_id` | 采购于 |
| `po_from_supplier` | purchase_order → supplier | `purchase_orders.supplier_id→suppliers.id` | 采购自 |
| `po_to_warehouse` | purchase_order → warehouse | `purchase_orders.warehouse_id→warehouses.id` | 入库至 |
| `stocked_at` | sku → warehouse | `inventory_balances.sku_id+warehouse_id` | 库存于 |
| `advertised_in` | sku → campaign | `ads_campaign_daily.sku_code+campaign_id` | 广告投放 |
| `campaign_in_shop` | campaign → shop | `ads_campaign_daily.shop_id→shops.id` | 投放于 |

`supplies` 与 `ordered_in` 同时连接 supplier 与 sku，语义不同：前者是主数据供应关系，后者是实际采购单关系。两者都保留。

### 4.3 作用域铁律

关系推导必须与 `authorized_run` 同作用域：`live.shop_id` / `live.warehouse_id` / 该运行的 SKU 集合。

- **只解析已出现在范围内的实体 ID**，绝不因为要取标签而扩大查询范围。
- `stocked_at` 限定 `inventory_balances.warehouse_id = live.warehouse_id`。
- `advertised_in` / `campaign_in_shop` 限定 `ads_campaign_daily.shop_id = live.shop_id` 且落在运行日期区间内。
- `ordered_in` / `po_from_supplier` / `po_to_warehouse` 只跟随证据中已出现的 `purchase_order_id`，不按 SKU 反查全量采购单。
- 范围外实体在标签解析阶段同样不可见。

## 5. 时间维度

- 每条 claim 带 `version`（checkpoint 序号 1–5）与 `recorded_at`。
- 每条 `HAS_EVIDENCE` 边带 `version`。
- UI 提供版本滑块，过滤到 `version <= N`。
- 措辞必须是「**观察时间版本**」，禁止写成「业务有效期」。现有 `limitations` 首条已声明 `观察快照不推断业务有效期`，UI 必须原样展示该数组。

## 6. 前端实现

### 6.1 依赖决策：v1 零新依赖

**结论：不引入 cytoscape / react-force-graph-2d / d3-force。**

理由：
1. 本图规模 ≤ 300 节点 / 800 边，且是**二部图 + 有限关系图**，确定性分层/环形布局的可读性优于力学布局（力学布局在二部图上会糊成球）。
2. 仓库现有惯例是手写图元（`frontend/src/pages/workspace.css` 的 `.co-mini-map` / `.co-mapnode` / `.co-maparrow`）。
3. 纯函数布局可直接用 `node --test` 单测；力学模拟非确定性且需浏览器环境，测试成本高一个量级。
4. 避免为一个受限规模引入 30–350 kB 运行时依赖。

**切换触发条件**：单次运行 entities > 150 或 edges > 400，且分层布局出现明显视觉重叠时，再评估 `d3-force`（仅需 `d3-force` 一个包）替换 `graphView.ts` 中的布局函数。

### 6.2 纯逻辑层 `src/components/graphView.ts`

`buildGraphView(payload, options)` → `{ nodes, edges, relations, legend, stats, notices, truncated }`

职责：
- 按 `canonical_id` 归并实体节点（吸收 `aliases`）
- 标签回退与「未解析」标记
- 节点类型 → 图例颜色/中文名映射
- claim 分组（按领域：product / inventory / procurement / ads / finance）
- 关系边两端存在性过滤
- 布局坐标计算（确定性）
- 1 跳邻接表（供聚焦交互）

**必须可单测的纯函数**，不得在组件内做布局计算。

### 6.3 渲染层 `src/components/GraphCanvas.tsx`

SVG，两个视图模式：

**证据视图（默认，二部分层）**
- 左列实体，按类型固定顺序 `shop → warehouse → product → sku → supplier → purchase_order → campaign`，组内按 label 排序
- 右列 claim，按领域顺序 `product → inventory → procurement → ads → finance`
- 边：实体右缘 → claim 左缘的贝塞尔曲线
- 节点尺寸：实体高 28px 单行；claim 高 40px 双行（claim_key / value+unit）

**关系视图（径向）**
- 中心：当前聚焦 SKU
- 一环：`product`、`supplier`、`purchase_order`、`warehouse`、`campaign`
- 二环：一环节点的其他关联（如同一 product 的其他 SKU、同一 supplier 的其他 PO）
- 确定性角度分配：邻居按 `(type, label)` 排序，角度 = 起始角 + i×(360/n)
- 边：直线；关系中文名在 hover / 选中时显示

**交互**
- 点击节点 → 1 跳邻接高亮，其余降到低透明度
- 点击空白 → 复位
- hover → tooltip 显示 label、类型、值/单位、observed_at、content_hash 前缀
- 图例：节点类型配色 + 关系类型说明
- 状态：加载 / 空（`207db7d9` 场景：范围内无证据，明确提示「当前范围没有业务证据」）/ 错误 / 截断提示

**明细面板**：选中节点旁列出其 claim 行（claim_key、value、unit、observed_at、source、content_hash 前 8 位），保证图不是唯一入口，数字仍可读可核。

### 6.4 页面接入

`frontend/src/pages/LimLiveWorkbenchPage.tsx` 的「图谱与证据」Tab：
- 保留现有 query 输入框（沿用 `readView('graph?query=…')` 调用方式）
- 新增视图切换：证据视图 / 关系视图
- 挂载 `GraphCanvas`
- 原始 JSON 收进可折叠「原始数据」区，**不删除**（可追溯性要求）
- 顶部固定展示 API 返回的 `backend`、`retrieval`、`time_basis` 与 `limitations` 原文

不新增路由、不改 `menu.ts`（LIM_NAV 现有 12 项不变）。

### 6.5 前端测试

`frontend/tests/graphView.test.mjs`，沿用 `import test from 'node:test'` + 直接导入 `../src/components/graphView.ts` 惯例（先例：`tests/diagnosisView.test.mjs`）。

> **运行环境约束（实测）**：Node **22.12.0 无法** 直接导入 `.ts`（`ERR_UNKNOWN_FILE_EXTENSION`）；Node **22.22.2 / 24.19.0 可以**。本项目 `node --test` 脚本需在 Node ≥ 22.18 下运行，或显式加 `--experimental-strip-types`。

## 7. 台账与文档

`docs/lim/g0-capability-inventory.md`：**LIM-FR-014 状态不变，保持 `未实现`**。

只在 G4 相关行补充一条事实性说明：「证据关系可视化已实现（单次运行观察快照 + ERP 外键推导关系；无 valid-time、无多跳查询服务、Neo4j 未验证）」。台账规则要求「只标记经过业务链路测试验证的能力」，故此条须在 §8 端到端验证通过后才写入。

## 8. 验证要求

### 8.1 后端
- `backend/tests/test_lim_graph_view.py`：
  - 标签解析正确（UUID → `code · name`）
  - 标签回退（查不到行 → `label_resolved=false`）
  - `sku_id` 已并入 `sku_code` 节点 `aliases`，entities 数量相应减少
  - 关系推导与 DB 外键一致（每类关系至少一条断言）
  - 作用域：范围外 SKU / 仓库不出现在 entities 与 relations
  - 不变量 1–6 全部成立
  - 截断：`truncated=true` 且 `truncated_kinds` 非空
- 既有 `backend/tests/test_lim_live.py` 不得回归（其 `graph_snapshot == old` 断言仍然成立）
- `backend/tests/test_lim_five_pillars_integration.py` 继续通过（其遍历 `'/graph'` 路径）

### 8.2 前端
- `node --test tests/graphView.test.mjs` 全绿（Node ≥ 22.18）
- `tsc --noEmit && vite build` 通过
- 既有前端测试全绿

### 8.3 浏览器端到端
在 `127.0.0.1:18080`（后端）+ `127.0.0.1:15173`（前端）实跑：
1. 打开 `/lim-workbench`，运行 DEMO-SHOP + CN-DEMO + [TEACH-SUPPLY-001, BT-EARBUDS-BLK]
2. 切到「图谱与证据」Tab，确认**渲染出图形节点与连线**，不再只是 JSON
3. 节点标签为可读名称，无裸 UUID
4. 证据视图与关系视图均可用；聚焦交互正常
5. 空范围运行（如 SKU-UK-DRESS-001）显示明确空状态
6. `limitations` 与 `backend: erp_database` 在页面上可见
7. 全程无 console 报错；后端日志无 5xx

## 9. 不做清单（明确排除）

- Temporal GraphRAG / valid-time / 多跳查询服务
- Neo4j 接入与 `export_graph` 写入关系边（Neo4j 未配置，属另一任务）
- 向量 / 语义检索
- `lim_graphrag.py` 种子数据接入
- 新增运行时依赖
- 新路由 / 菜单项
- 任何对 `lim_graphrag.py` 沙盘能力的对外表述升级
