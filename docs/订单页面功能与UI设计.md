# 订单页面 · 功能与 UI 设计规范（Orders.tsx）

> 适用范围：主系统前端 `frontend/src/pages/Orders.tsx`（约 783 行，单页 + 详情抽屉 + 4 个 Modal）。
> 依据：直接读取现有组件代码，并对照后端 `backend/app/orders.py`、`backend/app/wms.py`、`backend/app/inventory_allocation.py`、`backend/app/storefront/service.py` 验证业务边界。
> 目标：在「已有成熟实现」基础上，沉淀**功能 + UI 设计规范**，统一信息架构、交互与 demo / 真实数据标注，并**把两个审计 P0 边界（超卖 G-02、不真实收款 P0-03）的当前真实状态讲清楚**，给出可见化改进建议。
> 配套：全系统页面地图见 `docs/全系统页面功能地图.md`；模板来源 `docs/LIM页面功能与UI设计.md`。

---

## 0. 总原则（全页统一，沿用 LIM 规范）

1. **演示数据必须标来源**：凡非真实业务数据（独立站演示订单）使用橙色 `演示` 角标 + 文案双重标识，绝不伪装成真实接口数据。
2. **安全 / 业务边界可视化**：权限（RBAC）、库存预留状态、真实收款 vs 模拟收款，必须用颜色 + 文案双重标识，不能仅靠纯文字。
3. **浅色通透、内容清晰**：白卡片 + 柔和描边 + 留白；状态用统一色板；禁止空壳页。
4. **现状已较完整**：本页已是功能级实现（接 `/orders` 真实接口，含详情、付款核对、审计补录、审核、发货、取消）。本规范以「补标注、补可见化、补一致性」为主。

---

## 1. 功能定位

订单是**核心履约链路**的入口：查询、审核、申请发货、取消、出库，并承载**付款登记与人工核对**。它是连接「销售 → 库存预留 → 发货 → 收款」的主干页面。

业务状态机（后端 `orders.py` 已强制）：
`draft（待审核）→ approved（已审核）→ shipping_requested（待出库/已申请发货）→ fulfilled（已发货）`，并可从 `draft/approved/shipping_requested` 取消为 `cancelled（已取消）`；另有 `after_sale（售后中）`。

---

## 2. 信息架构（现状）

### 2.1 列表区（主 Card）
- 顶部：标题「销售订单」+ 副标题「查询、审核与维护店铺订单」；右侧「导入订单」「新建订单」。
- 权限不足时两条 `warning` Alert：缺 `orders:write` 相关子权限、或缺 `warehouses:read`。
- Tab 分状态：`全部订单` + 6 个状态（`statusMap`：待审核/已审核/待出库/已发货/已取消/售后中）。
- 筛选：`搜索来源单号或客户` + `店铺 Select` + `创建日期 RangePicker` + 刷新/重置。
- 表格列：来源单号 / 店铺 / 渠道 / 客户 / 应付金额 / 状态 Tag / 创建时间 / 操作。
- 操作按钮按状态与权限动态显隐：详情、编辑（`draft/approved` 且非 storefront）、审核（`draft`）、申请发货（`approved`）、取消（前三个状态）。

### 2.2 详情抽屉（Drawer，width min(720px,100vw)）
- 顶部：独立站演示订单橙色告警 + 「商城收货快照」Descriptions（name/email/address）。
- 订单主信息 Descriptions：来源单号、渠道、真实下单时间（可补录）、状态、客户、联系方式、备注、总金额。
- **商品明细表**：SKU / 名称 / 数量 / 行金额。
- **付款记录表**（需 `payment_records:read`）：类型 Tag（真实/模拟/历史）、核对状态 Tag、毛额/手续费/净额、方式、来源、凭据（下载/缺失/待恢复）、付款时间、操作（核对）。
- **登记付款表单**（需 `payment_records:write`）：收款类型（模拟/真实）→ 真实须上传 PDF/PNG/JPG 凭据 → 毛额/手续费/净额推算/方式/来源/付款时间/备注。

### 2.3 四个 Modal
1. **新建销售订单**：店铺→币种联动、渠道、单号、预选仓（可选）、客户、商品明细 `Form.List`（SKU 不可重复）、备注、业务下单时间。
2. **审核订单**：仅选「履约仓库」（必填）。
3. **补录真实下单时间**：ISO 时间 + 来源引用，仅能补空值，记入审计。
4. **编辑订单**：复用 `OrderEditDrawer`（外部组件）。

### 2.4 权限闸门（已实现，良好）
- `canWrite = admin || orders:write`
- `canCreate = canWrite && shops:read && dictionaries:read && skus:read`（缺任一则禁用新建并提示缺哪些）
- `canApprove = canWrite && warehouses:read`
- `canReadPayments / canWritePayments = payment_records:*`
- 后端 `orders.py` 另用 `ensure_warehouse_scope(user, warehouse_id)` 做**仓库级数据范围隔离**——权限模型已落地，不是空壳。

---

## 3. 核心交互（现状）

| 动作 | 前端 | 后端 | 备注 |
|---|---|---|---|
| 查询列表 | `api.get('/orders', {params})` | 分页 + 状态/店铺/关键词/日期过滤 | 四路 `Promise.allSettled` 并行加载依赖 |
| 新建 | `createOrder` → `POST /orders` | 状态置 `draft` | 创建时不占库存 |
| 审核 | `approve` → `POST /{id}/approve` | 置 `approved` + 记录 `warehouse_id` | 仅选仓，不预留 |
| 申请发货 | `ship` → `POST /{id}/shipment-request` | **调 `wms.reserve_order_stock` → `reserve()`** | 此处才预留，不足抛 422 |
| 取消 | `cancel` → `POST /{id}/cancel` | 若已 `shipping_requested` 先 `release_order_stock` 释放预留 | |
| 登记付款 | `addPayment` → `/payments/real` 或 `/payments` | 真实类型须 `evidence` 文件 | 模拟标 `record_type:simulated` |
| 核对收款 | `reconcilePayment` → `/payments/{id}/reconcile` | 人工确认后计入正式金额 | |
| 补录下单时间 | `backfillTime` → `POST /{id}/ordered-at` | 仅补空值，记审计 | 不改状态/库存 |

---

## 4. 数据真实性标注（关键：两个审计 P0 的当前真实状态）

> 以下结论**已对照后端源码逐条核实**，非推测。

### 4.1 真实业务数据 ✅
- 列表、详情、商品明细、付款记录、审核/发货/取消 —— 全部读写主 ERP 业务库（`SalesOrder` / `SalesOrderItem` / `ShipmentOrder` / `PaymentRecord`）。
- 付款「真实/模拟」之分来自 `record_type` 字段，**真实收款须上传凭据并人工核对**，核对前不计入正式金额（`canReconcilePayment` 校验）。这是**真实但受控**的收款流程，不是伪装。

### 4.2 超卖边界（G-02，INTEGRATION_GAPS.md）——已部分闭环，但前端不可见
- **后端现状**（已核实 `wms.py:58`、`inventory_allocation.py:29`、`orders.py:536`）：
  - 结账/下单**只校验 available，不预留**（`storefront/service.py` 仅 `checkout()` 校验，`status='draft'`，无 `reserve` 调用）。
  - 预留发生在 **申请发货** 时：`request_shipment` → `wms.reserve_order_stock` → 对每个 SKU 调 `reserve()`；`reserve()` 在 `on_hand - reserved < quantity` 时抛 `422`。
  - 取消已申请发货的订单会 `release_order_stock` 释放预留。
- **结论**：
  - ✅ 超卖**不会真正发货**（发货前被 422 拦截）。
  - ⚠️ 但创建/审核阶段**不占库存**，两个已审核订单可争抢同一库存，**其中一个会在「申请发货」时 422 失败**（E2E 报告实证：2+9 两单 draft 都 201，第二单 shipment_request 返回 422）。
  - ⚠️ **前端在审核阶段无任何库存预警**——用户直到点「申请发货」拿到 422 才知道会超卖。当前 catch 静默依赖请求拦截器，未把 422 解释为「库存不足，无法预留」。

### 4.3 不真实收款边界（P0-03）——已落地，正确 ✅
- `storefront/service.py:113` 硬编 `'payment_status': 'not_charged'`，独立站演示订单不扣款、不作真实履约。
- 前端已正确体现：
  - 详情顶部橙色告警「独立站演示订单 · 未真实收款 … 出库仅演示，不会通知真实承运商」。
  - 列表/详情对 `storefront_demo` 订单**禁用编辑**（行内 `row.source_channel !== 'storefront_demo'` 判定）。
  - 审核时强制使用站点指定履约仓（后端 `orders.py:519/543` 同样拦截）。
- 这是**已落地的 demo 边界**，符合「演示数据标来源」约定。

### 4.4 其他边界
- 订单权限（P0-01）已通过 `orders:write` + 子资源细粒度 + `ensure_warehouse_scope` 落地，非空壳。
- 付款「真实收款」要求上传平台结算凭据，且核对前不计入正式统计——防止把模拟当真实。

---

## 5. 设计建议 / 改进项

> 按性价比排序；每条标注「前端 / 后端」归属与优先级。

### P1 — 库存预留状态可见化（直接回应 G-02 前端盲区）
- **问题**：审核/发货前无法预知超卖风险。
- **建议**：
  - 订单详情（或列表新增「库存」列）展示本单每个 SKU 的「在库 / 已预留 / 可售」与「本单需预留」对比。数据来自 `GET /inventory/availability?warehouse_id=&skus=`（后端 `inventory_allocation.available` 已实现，需确认是否暴露接口）。
  - 审核 Modal 增加「预计预留后余量」提示；若任一 SKU 预计不足 → 按钮变橙 + 文案「预计库存不足，发货时可能被拦截，建议先补货或拆单」。
- **归属**：前端为主（需后端补一个按仓+SKU 的批量可用量接口，或复用现有 `/inventory`）。

### P1 — shipment_request 422 文案化
- **问题**：当前 `ship()` catch 静默依赖拦截器，422 含义未解释；订单状态停留 `approved`，用户不知可否重试。
- **建议**：捕获 422，显式提示「库存不足，无法预留：SKU {code} 可售仅 {n}，需 {m}」。保留订单在 `approved`，补货后可直接重试「申请发货」。
- **归属**：前端（`ship` 内 `try/catch` 解析 `e.response.data.detail`）。

### P2 — 已审核未发货订单的库存占用提示
- **问题**：因为预留仅在发货申请时发生、取消时释放，运营看「可售」时容易误判（已审核大批订单尚未占库存）。
- **建议**：库存页/订单页增加「已审核待发货占用」汇总卡或提示，与 `InventoryAllocation` 的 `order/reserved` 状态联动。
- **归属**：前端 + 后端聚合接口。

### P2 — storefront_demo 订单的付款区处理
- **问题**：详情页对 storefront 仍可能显示「登记付款」表单（`canWritePayments` 仅看权限，不看渠道）。但对演示订单收款无意义，易误导。
- **建议**：`source_channel === 'storefront_demo'` 时，付款区改为只读展示「演示订单 · 不收款」，隐藏「真实收款」类型与登记按钮。
- **归属**：前端。

### P3 — 取消原因 UX
- **问题**：`cancel` 用 `window.prompt` 收集原因，体验弱、无结构化。
- **建议**：改为 Modal 输入 + 可选原因标签（缺货/客户要求/风控），与取消审计一致。
- **归属**：前端。

### P3 — 批量操作一致性
- **问题**：列表无批量审核/发货/取消；与 OMS 19 页能力不对齐（OMS 独有导出/打印）。
- **建议**：列表增加多选 + 批量「申请发货」（仅 `approved`）；批量动作前先做 P1 的库存预检。
- **归属**：前端为主。

---

## 6. 一致性清单（评审用）

| 项 | 要求 | 现状 |
|---|---|---|
| 演示数据标注 | 橙色 `演示` 角标 + 文案 | storefront_demo 订单已标 ✅；其余无演示数据 |
| 不真实收款边界 | 显式标注 | storefront 详情橙色告警 + 禁编辑 ✅ |
| 超卖边界 | 前端可见/可预警 | ❌ 仅在发货 422 拦截，审核期不可见（见 §5 P1） |
| 权限闸门 | 颜色 + 文案 + 后端校验 | RBAC + `ensure_warehouse_scope` ✅ |
| 真实/模拟收款 | 类型 Tag + 核对流程 | `record_type` + 人工核对 ✅ |
| 空壳页 | 禁止 | 本页内容充实 ✅ |
| 审计可追溯 | 关键动作留痕 | approve/ship/cancel/补录时间均 `record_audit` ✅ |

---

## 7. 下一步建议

1. **优先做 §5 P1 两条**（预留可见化 + 422 文案化）：成本低、直接关闭 G-02 的前端盲区，且不影响后端 reservation 逻辑。
2. **后端补一个轻量接口**：`GET /inventory/availability?warehouse_id=&skus=a,b,c` 返回 `{sku_id, on_hand, reserved, available}`，供前端预检与库存页复用。
3. **逐页推进**：按 `docs/全系统页面功能地图.md` 优先级，下一页做 `Inventory.tsx` / `InventoryAllocation.tsx`（与本条 §5 的预留可见化强相关，可一并设计）。
4. **OMS 对齐**：独立 OMS 的 `OrdersPage.tsx` 在主系统合并决策（CODE_REDUNDANCY_AUDIT.md P0）后再统一设计，避免重复建设。

---

> 已核实来源：
> - `frontend/src/pages/Orders.tsx`（组件实现）
> - `backend/app/orders.py:516-580`（approve / shipment_request / cancel）
> - `backend/app/wms.py:58-114`（reserve_order_stock / release_order_stock / ship_order）
> - `backend/app/inventory_allocation.py:19-83`（available / reserve / finish）
> - `backend/app/storefront/service.py:113`（not_charged）
