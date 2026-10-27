# ERP 后端

后端使用 FastAPI + SQLAlchemy + Alembic + PostgreSQL，已接入 ERP 基础资料、OMS 销售、WMS 仓储和 SCM 采购业务。接口文档可用于查看当前契约。

## 本机访问

采购 Agent 详见 [上线步骤与补充数据](../docs/采购Agent开发/08_上线能力与补充数据.md)。该阶段最初由迁移 0008 引入；当前启动应执行 `alembic upgrade head`，应用仓库内全部后续迁移。配置真实模型后使用 /api/v1/purchase-agent/chat；未配置可使用 /supply-decide 规则分析。先补齐报价有效期、合规依据、订单业务时间/数据完整范围及仓库物流配置。模型配置值存于本地 .env，示例见 .env.example。

- 接口文档：http://127.0.0.1:18080/docs
- 企业门户：登录后访问 http://127.0.0.1:15173/workspace
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

## LIM 业务证据图谱

登录后打开 `/lim-workbench`，选择店铺、仓库、真实 SKU 和日期，运行诊断后进入「图谱与证据」。完整关系图来自 PostgreSQL 中保存的检查点；输入关键词并点击「检索图谱」时，会把当前授权运行的证据同步到 Neo4j，再执行受该运行范围限制的余弦向量和关键词检索。`查看配置状态` 会显示 Neo4j 连接及向量索引是否已就绪。

新机器可在本地启动 Neo4j 5.20，并在未跟踪的 `backend/.env` 中填写与容器一致的 `LIM_NEO4J_URI`、`LIM_NEO4J_USER`、`LIM_NEO4J_PASSWORD`。本机只绑定 `127.0.0.1` 的 7687 和 7474 端口；容器数据卷为 `ebus-lim-neo4j-data`。不要提交密码或容器环境文件。Neo4j 未配置时，完整关系图仍可使用；向量检索会明确返回不可用。

目前向量由本地词元哈希产生，可做词面相似度检索，但同义词语义能力有限。图中的时间是证据观察时间，不能作为业务有效期。

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
| 企业门户 | /api/v1/portal/workspaces | 按当前角色返回 ERP/AI 工作区；OMS 保持不可点击状态，直到独立身份授权接入 |
| LIM 运行治理 | /api/v1/lim/* | Agent/Tool 版本注册与校验、只读 Run/Trace、固定 Golden Dataset 评测；写操作 Tool 不进入运行时 |
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
- 时间戳在数据库按 UTC 保存。店铺时区保存为 IANA 名称。订单、收付款、库存和采购单据已实现；具体能力与限制见上方接口分组及各业务说明。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m alembic check
```

默认测试使用临时 SQLite 文件并逐个执行迁移，不触碰演示库。PostgreSQL 验证通过 TEST_DATABASE_URL 指定连接，每例建立随机隔离 schema，并在结束时删除该 schema；需要相应 schema 权限。不要把生产数据库作为测试目标。

## LIM 首批能力

LIM 首批迁移版本为 `0028`（当前数据库可能继续应用后续迁移）。执行 `alembic upgrade head` 后可在前端“LIM 运行治理”页面使用。运行时仅连接服务端明确配置的只读适配器；当前不提供生产写执行、模型密钥管理、语义质量判定或自动发布能力。评测报告会固定数据集与 Agent 版本，语义质量指标标记为 `NOT_EVALUATED`。固定版本比较复用已有 Eval Run，提供本地确定性断言差异、逐例回归分类、报告级阈值与规范化 SHA-256 校验；它不代表真实模型效果，也不构成生产发布门禁。

LIM 知识源目录由迁移 `0031` 创建。管理员在“知识源”页首次执行同步，将仅扫描 `docs/功能章节` 和 `docs/oms` 下的本地 Markdown；首次导入版本直接生效，后续内容变更生成待审核版本，需管理员激活。缺失文件对应的历史快照会保留，管理员可归档来源。知识读取与检索要求 `assistant:read`，来源还可附加既有角色权限作为 ACL；元数据和生命周期变更写入审计日志。`POST /api/v1/lim/knowledge/search` 与助手工具共用已登记快照检索，采用词面匹配并返回稳定来源/版本/片段引用，不提供向量语义检索或联网搜索。

G3 Workflow 基础由迁移 `0033` 建立。`/api/v1/lim/workflows` 管理版本化只读 DAG，版本校验会固定 Agent/Tool 版本、检查依赖无环及只读 handler；`POST /api/v1/lim/workflow-runs` 按调用人当前 Scope 建立父 Run，并为节点建立可追溯子 Run/Trace。首版支持有界并行、JSON Pointer 参数映射、声明式条件与 Join、日期范围约束、取消标记、部分失败和证据汇总。只有业务证据显式给出 `comparison_key` 或 `comparable_group` 才参与一致性/冲突判定；缺少声明时保留原始 ref 而不比较。调度在单进程同步执行，不提供进程重启恢复或多实例 worker 保证。

G4 Skill 治理基础由迁移 `0034` 创建。`/api/v1/lim/skills` 仅登记带来源、证据、范围、校验记录和有效期的候选版本；owner 可在 `CANDIDATE` 阶段用 `PUT /api/v1/lim/skills/{skill_id}/versions/{version}` 补齐受控元数据，进入审核后锁定；`/api/v1/lim/skills/{skill_id}/versions/{version}/transition` 依据受控状态机审核、验证、激活、冻结或撤销。状态改变与新版本激活均写审计，激活前要求证据和有效期，单个 Skill 同时最多一个 active 版本。当前 Skill 定义是惰性治理数据，不会自动进入提示词、长期 Memory 或 Runtime；使用和纠错计数没有可信运行时来源时保持为 0。该交付只覆盖 LIM-FR-015 的治理基础，不表示 Temporal GraphRAG、长期记忆召回或 Skill 运行时已实现。

G4 Sandbox 由迁移 `0035` 增加 Run `execution_mode`（既有 Run 默认为 `live`）。`POST /api/v1/lim/sandbox/runs` 只校验固定版本的 Agent/Tool Schema 并记录操作者提供的 Mock 响应，不读取或调用任何 Tool handler；Scope 固定为空，预算固定为一个调用/5 秒，Evidence refs 为空。Sandbox 对参数/Mock response 按支持的 JSON Schema 约束校验；数组须声明 `items`，未知 Schema 关键字 fail closed。Trace/Run/审计只保存参数和响应的结构/类型摘要，原始 scalar 内容不持久化或回显，避免自定义字段中的业务/个人数据泄漏。该隔离是应用内无 handler 的仿真路径，不是容器或进程隔离，FR-022 仍需部署级控制验证。

## 外部资料的使用

已有 ERP 文档服务器地址为 https://47.107.76.124/lingxing-erp；工作区知识库文档给出的 data-lab 地址为 https://47.107.76.124/data-lab。

本批只参考本地文档，未登录或写入远程服务。现有 ERP 是独立模拟系统，包含大量交易与数据平台能力。本地后端提供本期最小契约，使用 /api/v1 前缀、分页与行级范围设计，但不声称与远程接口完全兼容。远程数据导入作为后续独立工作。


G4 LIM 本地运行告警由迁移 `0036` 创建。`/api/v1/lim/alerts` 提供按操作者可见范围查询；默认规则为 Agent 失败 3 次/10 分钟、Tool 超时 2 次/10 分钟、Workflow 编排级失败 3 次/10 分钟，可由具备 `lim:manage` 与 `assistant:read` 的管理员调整。告警按规则与 Agent/Tool/Workflow 维度去重，支持确认、关闭、关闭后重新累计阈值再打开，并审计规则及状态变更。Sandbox、取消、预执行拒绝和已由子 Run 记录的 Workflow 失败不进入父级阈值；告警不复制目标、参数、响应、异常文本或 Trace 内容。当前同步 handler 只能在返回后判定超时，无法中断仍阻塞的调用；邮件、Slack、PagerDuty 和值班通知未配置，FR-024 仍未达到生产验收。
