# 产品：认识 SKU 与 Listing

## 页面用途

产品中心解决"我们在卖什么"这个基础问题。一个**产品（Product）**是一款商品的抽象描述，比如"纯棉圆领 T 恤"；同一个产品按颜色、尺码拆成多个 **SKU**，比如 `TEE-BK-M`（黑色 M 码）、`TEE-WHT-L`（白色 L 码）。**Listing** 则是 SKU 在某个店铺、某个渠道上的上架映射，把内部 SKU 和平台的 ASIN、渠道 SKU 对应起来。

路由为 `/products`（商品与 SKU 两个标签页）和 `/listings`（Listing 映射）。前端实现见 [`Products.tsx`](../../../frontend/src/pages/Products.tsx) 和 [`ListingsPage.tsx`](../../../frontend/src/pages/ListingsPage.tsx)。

## 概念关系

```
Product（产品）
  ├── code: TEE（产品编码，唯一）
  ├── name: 纯棉圆领 T 恤
  │
  ├── SKU: TEE-BK-M（黑色 M）  ──→ Listing: Amazon US 店铺 / ASIN=B0XXXX / active
  ├── SKU: TEE-BK-L（黑色 L）  ──→ Listing: Amazon US 店铺 / ASIN=B0YYYY / active
  └── SKU: TEE-WHT-M（白色 M）──→ Listing: Shopify 店铺 / channel_sku=TEE-WHT-M / active
```

一个产品下可以有多个 SKU；一个 SKU 在不同店铺可以有不同 Listing。

## 页面内容与操作

### 商品标签页（/products?tab=products）

| 字段 | 说明 |
|---|---|
| 编码 | 产品唯一编码，创建后不可修改 |
| 名称 | 商品名称 |
| 描述 | 商品描述（可选） |
| 单位 | 从字典中选择计量单位（件、箱等） |
| 状态 | 启用/停用开关 |

操作：新增商品、编辑商品、按编码或名称搜索、按状态筛选、分页浏览。

### SKU 标签页（/products?tab=skus）

| 字段 | 说明 |
|---|---|
| SKU 编码 | 唯一编码，如 TEE-BK-M |
| 名称 | SKU 名称 |
| 所属产品 | 下拉选择关联的 Product |
| 规格属性 | JSON 键值对，如 `{"颜色":"黑色","尺码":"M"}` |
| 状态 | 启用/停用 |

操作：新增 SKU、编辑 SKU、按编码搜索、分页浏览。

### Listing 映射页（/listings）

| 字段 | 说明 |
|---|---|
| 店铺 | 选择已授权的店铺 |
| 渠道 | 店铺对应的平台（Amazon、Shopify 等） |
| 内部 SKU | 关联本系统 SKU |
| Listing ID | 平台侧 Listing 编号（可选） |
| ASIN | Amazon 标准识别号（可选） |
| 渠道 SKU | 平台后台的 SKU 编码（可选） |
| 标题 | 上架标题 |
| 状态 | active / inactive |

操作：新增映射、编辑映射、按店铺和状态筛选、查看详情抽屉。

## 数据来源

| 数据 | 接口 | 说明 |
|---|---|---|
| 商品列表 | `GET /api/v1/products?page=&page_size=&q=&is_active=` | 分页、搜索、状态筛选 |
| 商品新增/编辑 | `POST /api/v1/products`、`PATCH /api/v1/products/{id}` | 编码唯一约束 |
| SKU 列表 | `GET /api/v1/skus?page=&page_size=&q=&product_id=` | 可按产品过滤 |
| SKU 新增/编辑 | `POST /api/v1/skus`、`PATCH /api/v1/skus/{id}` | attributes 为 JSON |
| 单位字典 | `GET /api/v1/dictionaries?kind=unit` | 商品单位下拉 |
| Listing 列表 | `GET /api/v1/listings?page=&page_size=&shop_id=&status=&q=` | 本地映射表 |
| Listing 新增/编辑 | `POST /api/v1/listings`、`PATCH /api/v1/listings/{id}` | 不调用平台 API |

后端模型见 [`models.py`](../../../backend/app/models.py)：`Product` 表字段为 code/name/description/unit_id/is_active；`SKU` 表字段为 code/name/product_id/attributes(JSON)/is_active。Listing 为独立表，记录店铺与 SKU 的映射关系。

## 操作示例

1. 在左侧菜单选择"商品中心 → 商品"，点击"新增商品"。
2. 填写编码 `TEE`、名称"纯棉圆领 T 恤"，选择单位"件"，保存。
3. 切换到"SKU"标签页，点击"新增 SKU"，填写编码 `TEE-BK-M`、名称"黑色 M 码"，选择所属产品"纯棉圆领 T 恤"，添加属性 `颜色=黑色`、`尺码=M`，保存。
4. 进入"商品中心 → Listing 映射"，新增一条映射：选择店铺、选择 SKU `TEE-BK-M`，填写 ASIN 和标题，保存。

## 权限说明

- `products:read` / `products:write`：商品的查看和新增编辑。
- `skus:read` / `skus:write`：SKU 的查看和新增编辑。
- `listings:read` / `listings:write`：Listing 映射的查看和新增编辑；创建 Listing 还需要 `shops:read` 和 `skus:read` 权限来加载下拉选项。
- `dictionaries:read`：加载单位字典。

## 当前实现边界

### 已实现

- 商品 CRUD：编码唯一、名称、描述、单位关联、启停状态。
- SKU CRUD：编码唯一、关联产品、JSON 规格属性、启停状态。
- Listing 映射 CRUD：店铺-SKU 关联、ASIN、渠道 SKU、标题、状态。
- 分页、关键词搜索、状态筛选。

### 部分实现

- SKU 的规格属性以 JSON 键值对存储，前端用动态表单录入，但没有预设颜色、尺码等属性字典。
- Listing 是本地手工维护的映射，不会自动从 Amazon/Shopify 平台拉取 Listing 数据。
- 商品没有成本价、售价、图片、重量尺寸等电商常用字段（这些字段在 DataLab 外部数据仓库的 `dim_products` 表中有，但本系统本地商品表尚未建模）。

### 尚未实现

- 批量导入商品/SKU（Excel/CSV）。
- 商品图片上传。
- 多供应商供货价关联（在"采购 → 供货价"模块中单独维护，不在商品页面内联编辑）。
- Listing 与平台 API 的自动同步。
- 商品分类、品牌、标签等维度管理。
- SKU 价格策略、促销价格。

## 验收步骤

1. 登录后进入"商品中心 → 商品"，确认列表显示已有商品。
2. 新增一个商品，填写编码和名称，保存后列表刷新出现新记录。
3. 切换到 SKU 标签页，为该商品新增一个 SKU，填写编码和属性，保存。
4. 进入 Listing 映射页，新增一条店铺-SKU 映射，填写 ASIN，保存后列表显示。
5. 编辑商品和 SKU，确认编码不可修改，其他字段可更新。
6. 停用一个商品或 SKU，确认状态切换后筛选"停用"可查到。
