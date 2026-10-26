# 跨系统业务闭环审计

审计日期：2026-10-21。审计对象是当前未提交工作树中的代码；运行证据来自一次性 SQLite 测试库，未访问现有演示库或生产库。`E2E_TEST_REPORT.md` 记录命令和原始数值。

## 结论与边界

**Storefront → 独立 OMS → ERP 没有形成一条业务链。** Storefront 通过 `/api/storefront/v1/checkout` 直接在主 ERP 后端写入 `SalesOrder(source_channel='storefront_demo')`，然后由同一个后端的订单和 WMS 路由处理审核、预占、出库和取消；独立 OMS 的前端、后端及数据库是另一套实现。[storefront/src/main.tsx:376](storefront/src/main.tsx#L376)、[backend/app/storefront/routes.py:249](backend/app/storefront/routes.py#L249)、[backend/app/storefront/service.py:132](backend/app/storefront/service.py#L132)、[oms/frontend/src/api.ts:3](oms/frontend/src/api.ts#L3)、[oms/backend/app/database.py:5](oms/backend/app/database.py#L5)

这不是纯前端假订单：隔离运行中，结账后在**主 ERP 数据库**查到了真实订单行，消费者凭订单专属 token 可查询；同时启动的独立 OMS 隔离实例订单总数与同公开单号匹配数均为 0。现有 ERP/OMS 对账功能是读取双方 JSON 后在浏览器比较，不提交或同步订单。[backend/app/reconciliation_prep.py:1](backend/app/reconciliation_prep.py#L1)、[frontend/src/pages/OmsReconciliationPrepPage.tsx:20](frontend/src/pages/OmsReconciliationPrepPage.tsx#L20)

## 五套逻辑系统在本链路中的角色

| 系统 | 本轮核实的代码职责 | 证据 |
| --- | --- | --- |
| Storefront | React 商城；商品目录、结账和查单调用主后端的公共 API；购物车与查单凭据保存在浏览器会话。 | [storefront/src/main.tsx:60](storefront/src/main.tsx#L60)、[storefront/src/main.tsx:78](storefront/src/main.tsx#L78)、[storefront/src/main.tsx:376](storefront/src/main.tsx#L376) |
| 独立 OMS | 自己的订单、支付记录、库存和履约模型及 API；前端指向 `18090/api/v1`，后端读取 `OMS_DATABASE_URL`。 | [oms/frontend/src/api.ts:3](oms/frontend/src/api.ts#L3)、[oms/backend/app/database.py:5](oms/backend/app/database.py#L5)、[oms/backend/app/main.py:215](oms/backend/app/main.py#L215) |
| ERP 主后端 | Storefront 站点和商品表引用 ERP 商品/SKU；结账直接创建主库订单；主库 WMS 管理库存。 | [backend/app/storefront/models.py:18](backend/app/storefront/models.py#L18)、[backend/app/storefront/service.py:53](backend/app/storefront/service.py#L53)、[backend/app/storefront/service.py:161](backend/app/storefront/service.py#L161)、[backend/app/wms.py:58](backend/app/wms.py#L58) |
| LIM | 在本链路中没有结账、订单或库存写调用。其 Sandbox 路径明确接收 Mock 响应且不调用业务 handler。 | [backend/app/storefront/service.py:132](backend/app/storefront/service.py#L132)、[backend/app/lim_sandbox.py:1](backend/app/lim_sandbox.py#L1) |
| AI 智能经营应用 | 企业门户入口指向助手页面，并说明建议需证据与审批；结账调用路径中没有 AI 请求。这里没有审计 AI 自身功能质量。 | [backend/app/portal.py:76](backend/app/portal.py#L76)、[backend/app/storefront/routes.py:249](backend/app/storefront/routes.py#L249) |

## 实际调用和数据所有权

| 步骤 | 前端或入口 | 后端与数据 | 运行结果 |
| --- | --- | --- | --- |
| 商品列表 | `loadCatalogue` 正常模式请求 `/site`、`/products`。 | 公共路由查 Storefront `Product/Variant`，关联 ERP `Product/SKU`，库存由 ERP `InventoryBalance`/归属计算。 | 测试商品出现在列表，详情可售 10。[storefront/src/main.tsx:215](storefront/src/main.tsx#L215)、[backend/app/storefront/routes.py:185](backend/app/storefront/routes.py#L185)、[backend/app/storefront/service.py:53](backend/app/storefront/service.py#L53) |
| 商品详情 | 列表内从已有对象打开；深链缺失时请求 `/products/{slug}`。 | 后端只返回已发布且 ERP 主商品启用的记录。 | 商品详情 API 返回测试商品。[storefront/src/main.tsx:296](storefront/src/main.tsx#L296)、[backend/app/storefront/routes.py:239](backend/app/storefront/routes.py#L239) |
| 购物车 | `addItem`、`repriceCart`；浏览器 `sessionStorage`。 | 无服务端购物车数据所有者。 | 本地计算逻辑可运行；跨会话持久性未提供。[storefront/src/cart.mjs:11](storefront/src/cart.mjs#L11)、[storefront/src/main.tsx:78](storefront/src/main.tsx#L78) |
| 结账 | POST `/checkout`，发送规格、数量、商品版本、地址和两个幂等凭据。 | 主库同一事务写 `SalesOrder`、订单行、`OrderMeta`、`Submission`；状态 `draft`，不扣款。 | 买 2 件返回 201，主 ERP 订单数 1，库存仍为在库 10、预占 0、可售 10。[storefront/src/main.tsx:376](storefront/src/main.tsx#L376)、[backend/app/storefront/service.py:132](backend/app/storefront/service.py#L132) |
| 查单 | Bearer 订单专属 token GET `/orders/{public_id}`。 | 读取主库订单、出库单、审计状态；不查独立 OMS。 | 草稿、取消和已出库状态可由消费者查询。[backend/app/storefront/routes.py:260](backend/app/storefront/routes.py#L260)、[backend/app/storefront/service.py:76](backend/app/storefront/service.py#L76) |
| 审核与预占 | ERP 员工 POST `/api/v1/orders/{id}/approve` 后再 POST `/shipment-request`。 | 主库 WMS 只在申请发货时 `reserve_order_stock`。 | 2 件预占后在库 10、预占 2、可售 8。[backend/app/orders.py:517](backend/app/orders.py#L517)、[backend/app/orders.py:537](backend/app/orders.py#L537)、[backend/app/inventory_allocation.py:29](backend/app/inventory_allocation.py#L29) |
| 出库或取消 | ERP 员工确认出库或取消未出库订单。 | `finish(..., ship=True)` 扣在库和预占；取消已预占订单释放预占。 | 出库 2 件后在库 8、预占 0；另一个测试订单取消后预占从 2 恢复 0。[backend/app/wms.py:98](backend/app/wms.py#L98)、[backend/app/orders.py:570](backend/app/orders.py#L570)、[backend/app/inventory_allocation.py:58](backend/app/inventory_allocation.py#L58) |

## 跨系统契约现状

Storefront 商品发布使用 ERP `product_id`/`sku_id`，但另存站点 `slug`、文案、版本与售价；订单使用公开 `public_id` 与主库 `SalesOrder.id` 两种标识，并由 `OrderMeta` 保存消费者地址快照和访问凭据哈希。[backend/app/storefront/models.py:18](backend/app/storefront/models.py#L18)、[backend/app/storefront/models.py:48](backend/app/storefront/models.py#L48)、[backend/app/storefront/service.py:161](backend/app/storefront/service.py#L161)

独立 OMS 与主后端都暴露 `/api/v1/orders`，但连接不同数据库，订单模型也不同：主库订单有 `ordered_at`，独立 OMS 订单另有配送字段。相同 URL 结构不代表同一数据契约。[backend/app/models.py:219](backend/app/models.py#L219)、[oms/backend/app/models.py:202](oms/backend/app/models.py#L202)、[backend/app/main.py:236](backend/app/main.py#L236)、[oms/backend/app/main.py:215](oms/backend/app/main.py#L215)

主后端和独立 OMS 均有自己的付款记录、预占、释放及出库实现。主后端收款还区分 `legacy/simulated/real` 及凭据核对；独立 OMS 的付款接口是手工登记，二者没有本轮代码中可证实的同步映射。[backend/app/orders.py:589](backend/app/orders.py#L589)、[backend/app/payment_evidence.py:106](backend/app/payment_evidence.py#L106)、[oms/backend/app/orders.py:626](oms/backend/app/orders.py#L626)、[oms/backend/app/wms.py:46](oms/backend/app/wms.py#L46)

## 不能外推的范围

本轮没有连接生产部署、真实支付网关、外部物流或既有 PostgreSQL 数据；也没有在浏览器里完成可视化点击。运行结论仅适用于报告中的隔离 SQLite 配置。独立 OMS 只验证了隔离实例的登录后订单读取与“未收到商城订单”；其自身创建、付款和履约状态机尚未运行验证。
