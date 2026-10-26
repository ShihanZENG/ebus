# 跨系统修复任务清单

排序依据是实际阻断 Storefront → 独立 OMS → ERP 业务闭环的程度。证据与运行结果分别见 `BUSINESS_FLOW_AUDIT.md`、`INTEGRATION_GAPS.md`、`E2E_TEST_REPORT.md`。本轮未执行下列业务代码变更。

## P0：阻断核心闭环

1. **P0-01 确定订单权威系统并建立 Storefront → 独立 OMS 的受控订单入口。** 当前 Storefront 直接写主 ERP `SalesOrder`，独立 OMS 使用另一数据库；先明确订单 ID、店铺/SKU 映射、金额/币种、地址、权限、状态及幂等键的版本化契约，再实现单一权威写入和可追踪交接。验收：隔离双库中，同一商城提交只产生一张权威订单；OMS 查询与 ERP 关联记录共享相关 ID，重复提交不多建单；任一交接失败有可重试状态和审计记录。影响：涉及商城结账、双库订单数据所有权和已有主库订单兼容。回滚：保留原演示路径的特性开关及只读旧订单查询，停止新路径写入；已提交订单按相关 ID 对账，不做自动删除。[backend/app/storefront/service.py:161](backend/app/storefront/service.py#L161)、[oms/backend/app/database.py:5](oms/backend/app/database.py#L5)
2. **P0-02 在“接受订单成功”前原子预占或持有库存，并定义取消/超时释放。** 现在 10 件能接受合计 11 件订单，后一单在发货申请才失败。验收：两个顺序或并发订单竞争 10 件时，不会同时承诺超过可售量；成功响应后的可售数减少；取消/过期只释放一次；库存与订单失败能一致回滚。需要先依 P0-01 确定库存权威仍在 ERP 及 OMS 的调用/补偿契约。影响：结账响应时点和库存事务；回滚时先停新订单写入，核对未履约预占后逐单处理，不直接清库存表。[backend/app/storefront/service.py:152](backend/app/storefront/service.py#L152)、[backend/app/orders.py:537](backend/app/orders.py#L537)
3. **P0-03 定义支付状态门禁。** 当前商城明确“不扣款”，正式购买链路不能沿用固定 `not_charged` 作为已支付信号。验收：没有实际网关前所有页面/API 继续显示测试演示；若接网关，只有验签、去重和对账后的事件可改变权威支付状态；未支付订单的履约策略明确。影响：支付状态、履约准入和两套付款模型；回滚为关闭支付特性开关并暂停受影响订单履约，不把模拟记录改作真实收款。[backend/app/storefront/service.py:113](backend/app/storefront/service.py#L113)、[backend/app/orders.py:52](backend/app/orders.py#L52)、[oms/backend/app/orders.py:626](oms/backend/app/orders.py#L626)

## P1：可靠跨系统操作和异常处理

4. **P1-01 建立状态事件/对账与故障补偿。** 订单审核、预占、出库、取消和付款状态需要从权威系统向其余系统传播；提供去重、重试、失败队列、人工处理和审计。现有工具只在浏览器比较导出的 JSON。[backend/app/reconciliation_prep.py:1](backend/app/reconciliation_prep.py#L1)、[frontend/src/pages/OmsReconciliationPrepPage.tsx:43](frontend/src/pages/OmsReconciliationPrepPage.tsx#L43)
5. **P1-02 修复购物车重报价的目录依赖。** 按购物车规格 ID 批量查询最新报价/库存，或逐一查商品详情；商品不在当前列表页不能被判为下架。补充跨页、筛选、下架和版本变化测试。[storefront/src/cart.mjs:23](storefront/src/cart.mjs#L23)
6. **P1-03 补齐顾客取消/查单恢复契约。** 为允许取消的状态提供鉴权、幂等、库存释放和状态同步；为丢失浏览器会话的消费者设计受保护的订单找回方式。现有员工取消 API 和当前会话 token 不等于顾客服务。[backend/app/orders.py:570](backend/app/orders.py#L570)、[storefront/src/main.tsx:78](storefront/src/main.tsx#L78)
7. **P1-04 给付款登记/未来回调加外部交易标识与唯一性约束。** 当前模拟付款重复提交写出两条；先隔离真实与模拟记录，再对重复事件返回同一结果。验收包含相同回调 ID、不同内容同 ID、乱序和重试。[backend/app/schemas.py:237](backend/app/schemas.py#L237)、[backend/app/orders.py:589](backend/app/orders.py#L589)
8. **P1-05 把错误路径纳入隔离集成测试。** 包括 API 5xx/超时、OMS 或 ERP 不可用、同步延迟/失败、PostgreSQL 并发抢库存及补偿后重放。本轮只测了商城特性开关 404 和单次库存不足 409。[E2E_TEST_REPORT.md](E2E_TEST_REPORT.md)

## P2：界面与非核心功能

9. **P2-01 改进商城状态页、加载/错误提示与订单进度说明。** 状态页目前只证明 `/site` 可用；待 P0/P1 的真实事件和服务健康契约建立后再展示分项状态。[storefront/src/main.tsx:488](storefront/src/main.tsx#L488)
10. **P2-02 统一企业后台 Design System 与代表页视觉。** 在业务闭环和数据可信度达标后执行，避免用视觉完成感掩盖订单与库存缺口。

## 下一项开发任务

**先执行 P0-01：确定订单权威系统和商城订单接入契约，并在隔离双库中落地最小可验证交接。** 它是后续预占、支付状态和取消同步的共同前提；当前两个订单实现和数据库没有共享所有权。[backend/app/storefront/service.py:161](backend/app/storefront/service.py#L161)、[oms/backend/app/database.py:5](oms/backend/app/database.py#L5)
