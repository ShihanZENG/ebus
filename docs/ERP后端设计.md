# ERP 后端设计

## 结构

app/config.py 读取本地配置，db.py 管理数据库连接，models.py 定义实体，schemas.py 定义请求约束，security.py 实现会话和权限，resources.py 提供基础资料接口，orders.py 提供 OMS 订单业务接口，main.py 注册身份、账号、订单和日志接口。migrations 保存版本化结构变更，bootstrap 显式初始化。

启动服务不自动建表，先执行 Alembic 升级。修改模型后新增迁移，不在请求中变更数据库结构。

## 核心实体

| 表 | 主要字段 | 约束 |
| --- | --- | --- |
| roles | code、name、permissions | code 唯一，admin 为保留角色 |
| users | username、password_hash、role_id、is_active、shop_scope、warehouse_scope | 用户名唯一，角色外键有效 |
| auth_sessions | token_hash、user_id、expires_at、revoked | 不保存原始 token |
| dictionaries | kind、code、name、is_active | kind + code 唯一 |
| products | code、name、description、unit_id | code 唯一，unit_id 引用单位 |
| skus | code、name、product_id、attributes | code 唯一，product_id 引用商品 |
| shops | code、name、channel、market、timezone、currency_id | code 唯一，时区和币种有效 |
| warehouses | code、name、warehouse_type、country、address | code 唯一，类型为国内或海外 |
| suppliers | code、name、contact_name、phone、email | code 唯一 |
| audit_logs | actor_id、resource、record_id、action、before、after、created_at | 保存安全字段快照，与业务修改同事务提交 |
| sales_orders | shop_id、source_channel、source_order_no、status、currency_id、金额、warehouse_id、客户信息 | shop_id+source_channel+source_order_no 唯一 |
| sales_order_items | order_id、sku_id、SKU 快照、quantity、unit_price、discount、line_total | order 级联删除，sku 外键 RESTRICT |
| payment_records | order_id、amount、currency_id、method、source、paid_at | 付款标明来源，币种与订单一致 |
| after_sales | order_id、type(return/refund)、reason、status、quantity、amount | 售后分别记录退货与退款 |
| inventory_balances | warehouse_id、sku_id、on_hand_qty、reserved_qty | 仓库+SKU 唯一，可售=on_hand-reserved |
| inventory_transactions | warehouse_id、sku_id、txn_type、on_hand_delta、reserved_delta、order_id、reference_no | 所有库存变动留痕 |
| inbound_orders / items | warehouse_id、supplier_id、status、明细 | 手工入库确认后增加在库 |
| shipment_orders / items | order_id、warehouse_id、status、tracking_no、明细 | 订单唯一对应出库单 |
| supplier_skus | supplier_id、sku_id、supply_price、lead_time_days | 供应商-SKU 供货关系 |
| purchase_orders / items | po_no、supplier_id、warehouse_id、status、金额、明细 | 采购单及明细 |
| purchase_receipts / items | receipt_no、po_id、合格数量、不合格数量 | 分批收货记录 |
| replenishment_suggestions | sku_id、warehouse_id、建议数量、公式参数、状态 | 补货建议可追溯 |

基础档案与账号角色采用 UUID 字符串主键，并保存创建、更新时间。编码区分大小写，不在保存时隐式转换。产品只管理描述与计量单位，库存、价格、采购供货关系由后续模块负责。

## 订单状态机

```
draft(待审核) --approve--> approved(已审核) --shipment-request--> shipping_requested(已预留待拣货)
   |                            |                                        |
   --cancel--> cancelled       --cancel--> cancelled                    --confirm-ship--> fulfilled(已发货)
                                                                          |
                                                          取消(shipping_requested)--> cancelled(释放预留)
```

- 取消必须填写原因；已申请发货的订单取消时自动释放预留库存。
- 发货申请时 WMS 按 SKU 加行锁检查可售库存，不足则整单失败并回滚；成功后创建出库单并预留。
- 确认出库时扣减在库和预留，写 outbound 流水，订单状态变为 fulfilled。
- 金额使用 Numeric(12,2)，按行计算：行金额 = 数量 × 单价 - 行优惠；订单总额 = 各行金额之和。
- 订单币种必须与店铺币种一致；付款币种必须与订单币种一致，不跨币种汇总。
- 批量导入按来源单号分组，同店铺同渠道同单号已存在则跳过；错误行返回行号和原因。

## 库存口径

- 在库 on_hand：仓库实际物理数量。
- 预留 reserved：已被订单锁定但未出库的数量。
- 可售 available = on_hand - reserved。
- 所有库存变动在数据库事务内通过 `SELECT ... FOR UPDATE` 锁定库存行，防止并发超卖。
- 重复入库、重复出库、重复确认发货均不重复累计（出库单状态校验）。
- 盘点调整直接修改在库数量，写 adjust 流水并保留原因。

## 状态与引用

基础资料统一以 is_active 启停用。已经存在的关系保持可查询，新建关系必须指向启用资料。数据库外键采用 RESTRICT，没有物理删除业务接口。

引用保护当前覆盖 SKU 到商品、商品到单位、店铺到币种以及身份关联。OMS 订单引用店铺、SKU、币种和仓库，订单创建时校验启用状态。WMS、SCM 接入时追加对应外键与停用规则。

## 数据权限

账号关联单个角色，角色管理功能权限，账号管理店铺和仓库范围。每次请求读取当前角色和账号状态，因此撤权无需等待 token 到期。

店铺与仓库列表先追加范围条件，再计算 total 和分页；详情、更新同样校验。创建新的店铺和仓库需要该资源写权限及全范围授权。订单按 shop_scope 过滤，受限店铺看不到也不能创建该店铺订单。无法进行行级过滤的全局审计接口对范围受限用户返回 403。

## 前端接入约定

前端通过 Bearer token 调用接口。启动后先查询 auth/me，获取角色、权限和范围，用于导航和按钮展示，实际授权仍由后端执行。

前端不要从编码推算数据库 ID；引用统一传 id。列表使用统一分页结果。出现 401 重新登录，403 提示无权限，409 提示重复或引用冲突，422 根据字段错误定位输入。

当前未开放跨域，后续前端开发服务器优先通过同源代理转发 /api。需要跨域时只配置具体来源。

## 后续边界

本批不包含前端业务页面、外部数据同步、真实库存扣减、资金结算和 AI。WMS 接通后 shipping_requested 状态会由实际出库回执更新为 fulfilled；当前部署绑定本机，适合作为后续开发的基础。
