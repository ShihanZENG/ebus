# 端到端验证报告

执行日期：2026-10-21。执行对象是当前工作树。测试只使用 `docs/audit/flow_audit_probe.py` 创建的一次性 SQLite 数据库，自动执行主后端迁移并建立虚构账号、店铺、商品与顾客；数据库在进程退出后移除。未使用 `backend/.env` 指向的数据库、独立 OMS 现有数据库、生产服务或真实支付网关。

## 执行方式与环境

```powershell
cd E:\06-接口与数据\跨境电商系统开发
backend\.venv\Scripts\python.exe -u docs\audit\flow_audit_probe.py
cd storefront
npm test
```

FastAPI `TestClient` 在默认文件系统沙箱中启动失败，最小示例堆栈停在 Windows `asyncio` 的本地 `socketpair`。本次隔离脚本获准在可使用本机回环 socket 的执行环境运行；脚本先把 `DATABASE_URL` 强制设置为 `outputs/flow-audit-*/erp-isolated.db`，且清除 `TEST_DATABASE_URL`，再导入应用。最终一次完整执行退出码 **0**；Storefront Node 测试 **12/12 通过**。探针脚本的断言、虚构数据和调用顺序见 [docs/audit/flow_audit_probe.py](docs/audit/flow_audit_probe.py)。

## 场景与实际结果

| 场景 | 执行与观察 | 判定 |
| --- | --- | --- |
| 10 件测试商品 | 隔离库初始化 ERP 商品/SKU，入库 10 件，发布 Storefront 商品；GET `/api/storefront/v1/products` 列表找到该商品，GET 详情返回可售 10；ERP 库存 API 为在库 10、预占 0。 | **API 和数据库通过**。未在浏览器渲染页面核对。 |
| Storefront 购买 2 件 | POST `/api/storefront/v1/checkout` 返回 **201**、状态 `draft`、`payment_status=not_charged`；主 ERP `SalesOrder` 中按公开单号查到 1 条 `storefront_demo` 订单。库存仍在库 10、预占 0、公开可售 10。 | **主 ERP 订单写入通过；结账即时预占不成立。** |
| 独立 OMS 产生订单 | 同一探针启动独立 OMS 的另一临时 SQLite 实例，登录后 GET `/api/v1/orders` 返回 **200**；列表总数 **0**，按 Storefront 公开单号查库匹配 **0**。主 ERP 中该单号匹配 **1**。 | **未通过跨系统闭环判定**。双库隔离配置下商城订单没有进入独立 OMS；未测试现有部署中的外部同步作业。 |
| 消费者查单 | 用结账响应中的 Bearer 凭据 GET `/api/storefront/v1/orders/{public_id}`，草稿、取消与已出库状态均返回 **200**。 | **公共查单 API 通过**；浏览器会话丢失后的找回未验证。 |
| 相同结账请求重复提交 | 同一 `Idempotency-Key`、恢复凭据和 payload 再 POST，返回 **200**、相同 `public_id`，主 ERP 对应订单数仍为 **1**。 | **结账重放幂等通过**。 |
| 库存不足 | 库存 10 时提交数量 11，返回 **409**，预占仍为 0。 | **单次库存校验通过**。 |
| 累计超卖 | 先提交 2 件，再用新幂等键提交 9 件，两次均返回 **201**；开放订单合计 11 件，库存仍在库 10、预占 0、公开可售 10。第一单申请发货预占 2 后，第二单申请发货返回 **422**，第二单仍为 `approved`。 | **复现 P0 缺口**；该场景是顺序请求，尚未测试并发争抢。 |
| 预占与取消恢复 | 第一单审核并申请发货后在库 10、预占 2、可售 8；员工取消返回 **200**，消费者查单状态 `cancelled`，在库 10、预占 0、可售 10；重复取消返回 **422**。 | **主 ERP 预占释放及公共状态读取通过**；顾客主动取消 API 不存在。 |
| 实际出库扣减 | 另建 2 件测试订单，审核、申请发货、确认出库；消费者查单 `fulfilled`、测试物流号可见；ERP 库存在库 **8**、预占 **0**、公开可售 **8**。 | **主 ERP 履约路径通过**；没有调用独立 OMS 或真实物流。 |
| API 不可用 | 在同一隔离应用中关闭 `storefront_enabled`，GET 商品 API 返回 **404**，主 ERP 订单数前后不变；重新启用后继续测试。 | **特性开关失败路径通过**；网络超时、代理 5xx、重试未验证。 |
| 重复模拟付款 | 对另一张未取消订单，两次调用员工付款 API，明确使用 `record_type=simulated`；两次均 **201**，付款记录列表为 **2**。 | **复现重复记录**；这不是支付回调，也不代表银行实际收款。 |
| 数据同步失败 | 独立 OMS 不在该下单路径中；现有对账页面只读比较 JSON。 | **无可注入的自动同步步骤**，故未执行消息丢失、重试或补偿测试。 |

## 其他已执行检查

`storefront` 的 `npm test`：12 项通过、0 失败，覆盖本地分析开关、购物车、金额、重试凭据、单飞提交和 SEO 元数据。另用 Node 直接调用 `repriceCart`：购物车含规格 `v1`，当前商品结果只含 `v2` 时，得到 `lines=[]`、`changed=true`、`removed=["A"]`，对应 `INTEGRATION_GAPS.md` 的 G-04。[storefront/src/cart.mjs:23](storefront/src/cart.mjs#L23)

## 未验证内容

- 没有浏览器点击/视觉渲染验证、真实前端网络请求抓包或移动端检查；本报告的“读取并展示”仅验证商品 API 返回和前端对应渲染代码。[storefront/src/main.tsx:472](storefront/src/main.tsx#L472)
- 没有访问独立 OMS 的现有库，也未在隔离 OMS 实例中执行创建、付款或履约状态机；仅验证了登录后订单读取与商城订单缺席。其状态机实现判断来自代码审查。[oms/backend/app/orders.py:273](oms/backend/app/orders.py#L273)
- 没有真实支付回调、网关签名、退款、真实物流、PostgreSQL 并发事务或跨服务网络中断验证。当前商城 API 明确为演示无扣款。[backend/app/storefront/service.py:113](backend/app/storefront/service.py#L113)
- 没有运行完整 ERP/OMS 后端测试集合；本次只执行针对闭环的隔离探针和 Storefront 的 12 项 Node 测试。
