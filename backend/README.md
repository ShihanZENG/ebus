# ERP 后端

后端使用 FastAPI + SQLAlchemy + Alembic + PostgreSQL，已接入 ERP 基础资料、OMS 销售、WMS 仓储和 SCM 采购业务。接口文档可用于查看当前契约。

## 本机访问

采购 Agent 新版详见 [上线步骤与补充数据](../docs/采购Agent开发/08_上线能力与补充数据.md)。迁移升至0008；配置真实模型后使用 /api/v1/purchase-agent/chat；未配置可使用 /supply-decide 规则分析。先补齐报价有效期、合规依据、订单业务时间/数据完整范围及仓库物流配置。模型配置值存于本地 .env，示例见 .env.example。

- 接口文档：http://127.0.0.1:18080/docs
- OpenAPI：http://127.0.0.1:18080/openapi.json
- 存活检查：http://127.0.0.1:18080/health
- 数据库就绪检查：http://127.0.0.1:18080/ready

数据库由本目录 compose.yaml 管理，宿主机端口为 15432，只绑定本机。数据保存在 Docker 卷中，普通容器重启不清空数据。

## 本地启动

在本目录打开 PowerShell。首次安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 .env，填写数据库密码及本地管理员密码，并使 DATABASE_URL 与数据库配置一致。当前工作环境已经生成本地配置，重启时直接复用即可。用户名与密码读取 ERP_ADMIN_USERNAME / ERP_ADMIN_PASSWORD。此前提供的远程 ERP 账号及 data-lab Key 不属于本地登录配置。

```powershell
docker compose -p crossborder-erp up -d db
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.bootstrap --demo
.\start.ps1
```

等数据库容器健康后执行迁移。启动脚本监听 127.0.0.1:18080。初始化命令只追加不存在的基础记录，重复执行不重置已有资料或账号密码。--demo 只用于本地演示库；去掉该选项仅初始化管理员、角色和基础字典。

当前环境的虚拟环境复用了本机已有 Python 依赖，并补装 PostgreSQL 驱动；其他机器按 requirements.txt 安装。

## 接口文档使用方法

1. POST /api/v1/auth/login，输入本地管理员用户名和密码。
2. 复制响应中的 access_token。
3. 点击文档右上角 Authorize，填入 token 值。
4. 调用基础资料的查询、新增和修改接口。
5. POST /api/v1/auth/logout 后，原 token 立即失效。

不要在工单、截图或日志中粘贴 token 和 .env 内容。

## 接口分组

| 分组 | 路径 | 能力 |
| --- | --- | --- |
| 身份 | /api/v1/auth/login、me、logout | 登录、当前身份、退出 |
| 账号 | /api/v1/users、users/{id}、users/{id}/password | 分页查询、新建、角色与范围修改、启停用、密码重置 |
| 角色 | /api/v1/roles、roles/{id}、permissions | 查询、新建、权限修改、可用权限清单 |
| 商品 | /api/v1/products | 商品资料 |
| SKU | /api/v1/skus | SKU 与规格，按 product_id 筛选 |
| 店铺 | /api/v1/shops | 店铺、渠道、市场、币种、业务时区 |
| 仓库 | /api/v1/warehouses | 国内与海外仓档案 |
| 供应商 | /api/v1/suppliers | 名称、联系人、电话和邮箱 |
| 字典 | /api/v1/dictionaries | 币种与单位，按 kind 筛选 |
| 订单 | /api/v1/orders | 订单列表、详情、创建、导入 |
| 订单操作 | /api/v1/orders/{id}/approve、shipment-request、cancel | 审核、发货申请、取消 |
| 付款 | /api/v1/orders/{id}/payments | 付款记录登记与查询 |
| 售后 | /api/v1/orders/{id}/after-sales、/api/v1/after-sales/{id}/resolve | 售后创建、列表与处理 |
| 库存 | /api/v1/inventory、/api/v1/inventory/transactions | 库存余额与流水查询 |
| 入库 | /api/v1/inbound-orders | 手工入库与列表 |
| 出库 | /api/v1/shipments、/shipments/{id}/confirm | 出库单列表、详情与确认发货 |
| 盘点 | /api/v1/warehouses/{id}/inventory/adjust | 库存盘点调整 |
| 当前供货价 | /api/v1/supply-infos | 供应商-SKU 当前供货价与交期 |
| 采购 | /api/v1/purchase-orders、/{id}/approve、/{id}/cancel | 采购单创建、审批、取消 |
| 采购计划 | /api/v1/purchase-plans | 独立计划单的新建、编辑、提交、审批、驳回和转采购单 |
| 采购变更 | /api/v1/purchase-amendments | 对未收货的已审批采购单申请变更，保留前后快照及审批意见 |
| 供应商报价 | /api/v1/supplier-quotes | 报价历史；接受报价后更新当前供应商 SKU 供货价 |
| FBA 发货计划 | /api/v1/fba-plans | 草稿、审批、发货、全量签收；发货扣国内仓库存，签收增海外仓库存 |
| Listing 映射 | /api/v1/listings | 店铺与 SKU 的本地 Listing、ASIN、渠道 SKU 映射 |
| 客服工单 | /api/v1/customer-tickets | 创建、分派、处理记录、完成、重开、关闭 |
| 收货 | /api/v1/purchase-orders/{id}/receipts | 分批收货（合格/不合格） |
| 补货 | /api/v1/replenishment-suggestions/compute、/api/v1/replenishment-suggestions | 补货建议计算、调整、转采购 |
| 日志 | /api/v1/audit-logs | 人员、资源、对象和时间过滤 |

采购计划、采购变更和报价历史由 `0005_procurement_workflow` 迁移创建。已审批采购单不能直接 PATCH；须走采购变更审批。已发生收货的采购单不能申请此类明细变更。旧的 `/supply-infos` 仍表示当前供货价，历史报价查询使用 `/supplier-quotes`。新增权限为 `purchase_plans`、`purchase_amendments`、`supplier_quotes` 的 read/write；已有非管理员角色需要由管理员分配相应权限。

`0006_fba_listing_customer_tickets` 新增 FBA、Listing、客服工单表。FBA 发货与签收当前为本地全量流转，不会自动同步 Amazon；Listing 当前只维护本地映射，不发布到平台；客服工单当前为内部处理记录，不发送站内信。新增权限分别为 `fba_plans`、`listings`、`customer_tickets` 的 read/write。FBA 计划同时受店铺与来源仓、目的仓数据范围限制。

六类基础资料均支持 GET 列表、POST 新增、GET /{id} 详情和 PATCH /{id} 修改。统一以 is_active 停用，不提供物理删除接口。业务编码、字典类别、SKU 所属商品创建后不允许改写。

基础资料列表参数：q、is_active、page、page_size（1—100）。先按权限过滤，再计数分页。返回 items、total、page、page_size。账号列表支持分页。字段及必填约束以生成的 OpenAPI 为准。

错误统一返回 error.code、error.message，字段错误另有 error.fields。常见状态为 401 未登录、403 无权限、404 不存在或不可见、409 重复编码或引用冲突、422 字段无效、429 登录暂时锁定。请求错误不会回显密码输入。

## 权限与安全约定

- 管理员角色 code 为 admin，只能由管理员创建账号和维护角色。保留管理员角色不可修改，当前管理员不能停用或降权自己。
- 普通角色以 resources:read/write 控制接口权限，具体资源名见 permissions 接口。审计权限为 audit:read。
- shop_scope 与 warehouse_scope：null 表示全范围，[] 表示无范围，ID 列表表示只允许对应记录。新账号默认无店铺、仓库范围。
- 店铺、仓库列表、详情和修改均执行范围检查，受限账号不能新建店铺或仓库。商品、SKU、供应商与字典是单经营主体共用资料，按功能权限控制。
- 角色和数据范围每次请求重新读取。停用账号或重置密码撤销已有会话。
- 会话默认有效 8 小时。数据库只保存 token 摘要，密码使用随机盐 PBKDF2-SHA256（600000 轮）。同一已知账号连续失败 5 次锁定 5 分钟。
- 全局操作日志仅允许同时具有审计权限和全店铺、全仓库范围的账号查看。
- 币种和单位引用按类型校验。新建或切换引用需要启用资料；历史引用仍可读取。
- 时间戳在数据库按 UTC 保存。店铺时区保存为 IANA 名称。当前未实现金额、库存或交易单据。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m alembic check
```

默认测试使用临时 SQLite 文件并逐个执行迁移，不触碰演示库。PostgreSQL 验证通过 TEST_DATABASE_URL 指定连接，每例建立随机隔离 schema，并在结束时删除该 schema；需要相应 schema 权限。不要把生产数据库作为测试目标。

## 外部资料的使用

已有 ERP 文档服务器地址为 https://47.107.76.124/lingxing-erp；工作区知识库文档给出的 data-lab 地址为 https://47.107.76.124/data-lab。

本批只参考本地文档，未登录或写入远程服务。现有 ERP 是独立模拟系统，包含大量交易与数据平台能力。本地后端提供本期最小契约，使用 /api/v1 前缀、分页与行级范围设计，但不声称与远程接口完全兼容。远程数据导入作为后续独立工作。
