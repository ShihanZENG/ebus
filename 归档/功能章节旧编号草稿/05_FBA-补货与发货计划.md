# FBA：补货与发货计划

## 页面用途

FBA（Fulfillment by Amazon）模块管理把货从国内仓库发到 Amazon 海外仓的流程。路由为 `/fba-plans`。前端实现见 [`FbaPage.tsx`](../../../frontend/src/pages/FbaPage.tsx)，后端见 [`fba.py`](../../../backend/app/fba.py)。

当前只实现了 FBA 发货计划的核心流程，FBA 货件、发货单、海外发货计划、FBA 总览、FBA 库存、FBA 对账、标签打印等子页面仍为占位页。

## FBA 计划状态机

```
draft（草稿）
  │
  ├─ 提交 → submitted
  │     │
  │     ├─ 审批通过 → approved
  │     │     │
  │     │     ├─ 发货 → shipped
  │     │     │     │
  │     │     │     └─ 确认收货 → received
  │     │     │
  │     │     └─ 取消 → cancelled
  │     │
  │     └─ 取消 → cancelled
  │
  └─ 取消 → cancelled
```

## 页面内容

### FBA 发货计划列表（/fba-plans）

| 字段 | 说明 |
|---|---|
| 计划编号 | 系统生成 |
| 目标仓库 | 目标 Amazon 仓库 |
| 状态 | draft/submitted/approved/shipped/received/cancelled |
| SKU 明细 | 各 SKU 计划发货数量 |
| 创建时间 | |

操作：新建计划、编辑草稿、提交审批、审批通过、标记发货、确认收货、取消。

## 数据来源

| 操作 | 接口 |
|---|---|
| 计划列表 | `GET /api/v1/fba-plans?status=&page=` |
| 创建计划 | `POST /api/v1/fba-plans` |
| 计划详情 | `GET /api/v1/fba-plans/{id}` |
| 编辑计划 | `PATCH /api/v1/fba-plans/{id}` |
| 提交 | `POST /api/v1/fba-plans/{id}/submit` |
| 审批通过 | `POST /api/v1/fba-plans/{id}/approve` |
| 取消 | `POST /api/v1/fba-plans/{id}/cancel` |
| 标记发货 | `POST /api/v1/fba-plans/{id}/ship` |
| 确认收货 | `POST /api/v1/fba-plans/{id}/receive` |

## 操作示例

1. 进入"FBA → 发货流程 → FBA 发货计划"。
2. 新建计划，选择目标仓库，添加 SKU 和数量，保存为草稿。
3. 提交审批，审批通过后标记发货。
4. 货物到达 Amazon 仓后，确认收货，计划状态变为 received。

## 权限说明

- `fba_plans:read`：查看 FBA 计划。
- `fba_plans:write`：创建、编辑、提交、审批、发货、收货等操作。

## 当前实现边界

### 已实现

- FBA 发货计划 CRUD 和完整状态流转。
- 明细 SKU 和数量。
- 审批流程。

### 部分实现

- FBA 库存数据目前只读 DataLab 的 `dws_inventory_sku` 表展示，不与本地库存联动。
- 发货计划确认收货后，不会自动调整 Amazon FBA 库存数量（因为 FBA 库存不在本地 WMS 管理范围内）。

### 尚未实现

- FBA 货件追踪（Shipment ID、箱号、追踪号）。
- FBA 标签打印（FNSKU、箱贴）。
- 海外仓发货计划（从一个海外仓调拨到另一个）。
- FBA 对账（Amazon 库存 vs 实际库存差异）。
- 自动补货建议（根据 FBA 库存水位自动生成发货计划）。
- 货件状态从 Amazon API 自动同步。
- 海运/空运/快递物流选择和运费预估。

## 验收步骤

1. 进入 FBA 发货计划页，确认列表加载。
2. 新建一个计划，添加 SKU 明细，保存为草稿。
3. 提交审批，审批通过，标记发货，确认收货。
4. 检查各状态流转是否正确。
