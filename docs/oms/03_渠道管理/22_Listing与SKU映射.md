# 22 Listing 与 SKU 映射及 DataLab 展示

## 实现状态

**部分实现：本地人工映射 CRUD 已实现；DataLab 表只读展示已接入；平台 API 同步、两类数据自动匹配/写回未实现。** 此页的两个标签数据来源和权限链路不同。

## 本地映射：当前能力

- `/listings` 页面“本地映射”标签，菜单“商品中心 → Listing 映射”。可按店铺、状态筛选，按平台标识/标题搜索，查看详情，新建、改内部 SKU/标题及启停。
- 后端 `GET/POST /api/v1/listings`、`GET/PATCH /api/v1/listings/{id}`、`POST /api/v1/listings/{id}/activate|deactivate`。
- 维护字段 `shop_id`、`sku_id`、`listing_id`、`asin`、`channel_sku`、`title`、`status`。至少有一个平台标识；同店铺同类标识唯一；店铺和标识创建后固定。
- 权限为 `listings:read/write`，并按 `shop_scope` 隔离店铺。新建页面需 `shops:read` 和 `skus:read` 加载选项。

## DataLab：当前只读展示

- 页面切换到“平台 Listing（DataLab）”时调用 `GET /api/v1/datalab/table/dwd_listing_fba_dimensions?limit=100`，列出 seller SKU、产品名、FNSKU、ASIN、父 ASIN、SPU 和更新时间等返回字段；可手动刷新。
- 当前页面最多请求 100 行，表格再以 20 行分页展示；不是全量报表，也不保证固定返回 360 条。实际更新时间取决于 DataLab 数据集。
- DataLab API 的可访问性由其单独服务配置决定，不能从 `listings:read` 推断有平台授权。此页只读，不提供编辑、落成本地 `listings`、平台推送或同步作业。

## 数据来源边界

- 店铺 `channel` 是店铺资料字段；本地 `listings` 是用户创建的映射；DataLab 是查询出的数据集；平台 API 同步是当前未实现的能力。四者不能相互推定。
- 本地映射不会自动用于 `orders/import` SKU 识别；DataLab 的 seller SKU/ASIN 也没有自动写入本地映射。
- DataLab 查询结果的行数、刷新时间、列含义以接口/数据集为准，页面没有全表扫描或跨币种金额计算。

## 建议验收（未执行）

1. 本地创建映射后只在本地标签出现；DataLab 同值行不会自动生成或覆盖映射。
2. 切换到 DataLab 标签触发查询，刷新重新请求，返回超过 100 行时页面仍仅拿到接口限制的最多 100 行。
3. 无 DataLab 服务权限/服务不可用时显示加载失败或空状态，不应伪称“平台未上架”。
4. 停用本地映射不应删除 DataLab 行或更改平台 Listing。

## 后续开发方向

若需要统一对账，建议加入显式匹配候选和人工确认状态、匹配来源及时间戳；由独立同步作业保存平台来源 ID、同步批次和错误，不直接把 DataLab 快照视为实时权威值。验收需验证匹配可追踪、可撤销、只写授权店铺范围，并对数据新鲜度与上限作出可见提示。

## 代码位置

本地映射：`backend/app/listings.py`、`frontend/src/pages/ListingsPage.tsx`；DataLab 调用也在 `ListingsPage.tsx`；菜单/路由：`frontend/src/config/menu.ts`、`frontend/src/App.tsx`。
