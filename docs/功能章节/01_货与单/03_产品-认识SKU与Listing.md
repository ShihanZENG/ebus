# 产品：认识 SKU 与 Listing

## 页面用途

本项目把“商品”和“SKU”作为内部货品主数据，把 Listing 作为店铺渠道商品与内部 SKU 的本地映射。商品描述货品族及单位；SKU 是可库存、可下单的具体规格；Listing 记录某店铺上的 Listing ID、ASIN、Channel SKU、标题并指向一个内部 SKU。Listing 页面明确不调用平台 API，也不会自动导入、同步或刊登商品。

入口：商品中心 > 商品（`/products`）、SKU（`/skus`）、Listing 映射（`/listings`）。商品和 SKU 共用 `Products` 页面不同标签，Listing 使用独立页面。见 [`App.tsx`](../../../frontend/src/App.tsx)、[`Products.tsx`](../../../frontend/src/pages/Products.tsx)、[`ListingsPage.tsx`](../../../frontend/src/pages/ListingsPage.tsx)。

## 数据关系与关键字段

| 对象 | 关键字段 | 作用与约束 |
|---|---|---|
| 商品 Product | `code`、`name`、`unit_id`、`description`、`is_active` | 商品编码唯一；单位引用单位字典。停用不会删除历史业务引用。 |
| SKU | `code`、`name`、`product_id`、`attributes`、`is_active` | 编码唯一，必须关联商品；规格属性是键值文本 JSON。订单/FBA 明细会保存 SKU 编码和名称快照。 |
| Listing | `shop_id`、`sku_id`、`listing_id`、`asin`、`channel_sku`、`title`、`status` | 每条记录表示单个店铺与内部 SKU 的映射；店铺和 SKU 必须有效，`status` 为 active/inactive。 |

商品和 SKU 主表定义见 [`models.py`](../../../backend/app/models.py)，Listing 独立模型及校验见 [`listings.py`](../../../backend/app/listings.py)。页面新建商品需要商品写入及单位字典读取；新建 SKU 需要 SKU 写入，通常还需商品读取来选择所属商品。编辑已有 SKU 的所属商品不可改，只改名称、属性和启停状态。

## 操作流程

1. 先在“币种与单位”维护有效单位，再到“商品”新建商品编码、名称、单位和描述。
2. 切到 SKU 标签，新增 SKU 编码、名称、所属商品及规格属性；商品列表分页，SKU 页面当前只取最多 100 条且没有分页控件。
3. 到 Listing 映射，选择店铺与 SKU，录入渠道 Listing 标识、ASIN、Channel SKU 和标题；可搜索、按店铺和状态筛选，查看详情，编辑、启用或停用。
4. 之后订单行、采购行、库存余额引用内部 SKU ID；Listing 映射本身不创建订单，不产生库存，也不更新平台。

## 数据来源、权限与边界

| 页面/API | 权限 | 当前能力 |
|---|---|---|
| `GET/POST/PATCH /api/v1/products` | `products:read/write` | 商品查询、新建、编辑及启停；编码编辑时锁定。 |
| `GET/POST/PATCH /api/v1/skus` | `skus:read/write` | SKU 查询、新建、编辑；列表可分页但前端 SKU 标签固定请求最多 100 条。 |
| `/api/v1/listings` 及详情、启停动作 | `listings:read/write` | 本地映射查询维护，服务端按店铺范围过滤/校验。 |
| 关联选项 | `shops:read`、`skus:read`、`dictionaries:read` | 页面用于店铺、SKU、单位下拉框。 |

管理员由前端视为具备权限；其他角色需要相应读取/写入权限。后端接口也校验权限，不能仅靠隐藏按钮。Listing 页面创建还依赖店铺与 SKU 查看权限。权限及店铺范围逻辑见 [`security.py`](../../../backend/app/security.py) 和 [`listings.py`](../../../backend/app/listings.py)。

### 实现状态

**已实现：** 商品/SKU 本地主数据维护；SKU 规格键值；Listing 与内部 SKU 的本地映射、搜索筛选、启停及操作审计；下游订单/FBA 快照字段。

**部分实现：** 商品支持关键词、启停筛选和分页；SKU 页面无搜索筛选，固定最多读取 100 条。Listing 依赖当前用户可读的店铺/SKU选项；基础资料多于 100 条时页面选项可能不全。Listing 标识字段仅作本地文本，没有校验平台真实性。

**尚未实现：** Amazon 等平台 API 授权、Listing 自动导入/发布/同步、平台库存与价格同步、SKU 自动匹配、条码/图片/多语言变体管理。不要把本地 Listing 映射当作已连接平台。

## 人工验收

以下为可执行的人工检查，文档编写时未运行：

1. 用有 `products:read/write` 和 `dictionaries:read` 的账号新增一个商品；缺少单位字典读取权限时确认新增入口不可用或无法完成单位选择。
2. 新增带两个属性的 SKU，保存后在 SKU 标签检查属性显示；刷新后仍存在。尝试重复编码应由后端唯一约束拒绝。
3. 创建一条店铺 Listing 映射，填写示例 ASIN/渠道 SKU，检查详情正确指向该内部 SKU；关键词及店铺筛选能定位记录。
4. 停用 Listing 后筛选 inactive 可见；检查操作日志中有创建/更新/状态变更记录。确认平台并未因此发生变化。
5. 使用无权账号分别直接访问页面/API，确认读写权限由路由和后端拒绝；店铺范围外的映射不可读取。
