# 跨境电商 ERP 系统 — 项目说明与使用指南

> 版本：v1.0・更新日期：2026-10-08
> 定位：领星风格的跨境电商后台管理系统，覆盖商品、订单、仓储、采购、数据看板五大业务域。



***

## 一、项目简介

本系统是一套面向跨境电商卖家的 ERP（企业资源计划）后台，参考领星 ERP 的交互风格（左侧深色导航、表格为主、蓝色企业级主题），实现了从商品建档、销售订单处理、库存管理到采购补货的完整业务闭环，并接入了 DataLab 数据仓库的经营分析数据。

### 已完成的四条业务主链路



| 链路   | 流程                                    | 状态    |
| ---- | ------------------------------------- | ----- |
| 销售发货 | 商品建档 → 订单录入 → 审核 → 库存预留 → 拣货出库 → 发货完成 | ✅ 已打通 |
| 采购补货 | 补货建议 → 审批 → 转采购单 → 分批收货 → 入库          | ✅ 已打通 |
| 售后处理 | 退货 / 退款申请 → 审核 → 库存回滚                 | ✅ 已打通 |
| 数据看板 | DataLab 数据仓库 → ADS 汇总表 → 前端可视化        | ✅ 已接入 |



***

## 二、技术架构



```
┌─────────────────────────────────────────────────┐

│  前端 (React 18 + TypeScript + Vite 6 + AntD 5) │

│  http://127.0.0.1:3000                          │

└──────────────────┬──────────────────────────────┘

&#x20;                  │ /api 代理

┌──────────────────▼──────────────────────────────┐

│  后端 (FastAPI + SQLAlchemy + Alembic)           │

│  http://127.0.0.1:18080                         │

│  ├── auth / 权限登录                             │

│  ├── products / skus / shops / warehouses       │

│  ├── orders / after-sales (OMS)                 │

│  ├── inventory / inbound / shipments (WMS)      │

│  ├── purchase-orders / receipts / replenishment │

│  └── datalab/overview (外部数据代理)             │

└──────────────────┬──────────────────────────────┘

&#x20;                  │

┌──────────────────▼──────────────────────────────┐

│  PostgreSQL 15 (Docker, port 15432)            │

│  + DataLab 外部数据仓库 (47.107.76.124)          │

└─────────────────────────────────────────────────┘
```

### 技术栈明细



| 层        | 技术                 | 版本           |
| -------- | ------------------ | ------------ |
| 前端框架     | React + TypeScript | 18 / 5.x     |
| UI 组件库   | Ant Design         | 5.x          |
| 构建工具     | Vite               | 6.x          |
| 路由       | React Router       | 6.x          |
| HTTP 客户端 | Axios              | 1.x          |
| 后端框架     | FastAPI            | 最新           |
| ORM      | SQLAlchemy         | 2.x          |
| 数据库迁移    | Alembic            | 最新           |
| 数据库      | PostgreSQL         | 15           |
| 异步 HTTP  | httpx              | 用于调用 DataLab |



***

## 三、快速启动

### 3.1 启动后端服务



```
cd E:\06-接口与数据\跨境电商系统开发\backend

.\\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18080
```

验证：浏览器访问 [http://127.0.0.1:18080/ready](http://127.0.0.1:18080/ready) ，返回 `{"status":"ready","database_revision":"0004"}` 即正常。

### 3.2 启动前端服务



```
cd E:\06-接口与数据\跨境电商系统开发\frontend

.\node\_modules\\.bin\vite.cmd --host 127.0.0.1 --port 3000
```

验证：浏览器访问 [http://127.0.0.1:3000](http://127.0.0.1:3000) ，自动跳转登录页。

### 3.3 登录账号



| 账号    | 密码   | 角色          |
| ----- | ---- | ----------- |
| admin | 1234 | 超级管理员（全部权限） |

> 登录后 token 存在 localStorage，关闭浏览器后需重新登录。



***

## 四、前端页面导航

左侧导航栏按业务域分组，与后端四大模块一一对应：

### 4.1 首页（/dashboard）



* 业务总览卡片：订单数、待审核、待出库、可用库存、低库存预警、待补货 SKU

* 销售金额按币种分布

* 订单状态分布进度条

* 运营待办快捷入口

* 库存预警列表、最近订单列表

### 4.2 商品中心



| 页面  | 路由        | 说明                   |
| --- | --------- | -------------------- |
| 商品  | /products | 商品编码、名称、分类、价格、成本、供应商 |
| SKU | /skus     | SKU 编码、规格属性、启停用状态    |

### 4.3 销售（OMS）



| 页面   | 路由           | 说明                   |
| ---- | ------------ | -------------------- |
| 销售订单 | /orders      | 订单列表、详情抽屉、审核、申请发货、取消 |
| 售后   | /after-sales | 退货 / 退款记录            |

**订单状态机**：



```
draft（待审核）→ approved（待发货）→ shipping\_requested（待出库）→ fulfilled（已完成）

&#x20;      ↓                                      ↓

&#x20;  cancelled（已取消）                    after\_sale（售后中）
```

### 4.4 仓储（WMS）



| 页面   | 路由              | 说明                       |
| ---- | --------------- | ------------------------ |
| 库存余额 | /inventory      | 在库 / 预留 / 可售数量，按仓库 + SKU |
| 入库单  | /inbound        | 手工入库登记                   |
| 出库单  | /shipments      | 出库确认记录                   |
| 库存流水 | /inventory-txns | 所有库存变动明细                 |

**核心库存逻辑**：



* 订单申请发货时，用数据库行锁预留库存，不足则整单回滚

* 确认出库扣减在库和预留，订单自动变为已完成

* 取消已预留订单自动释放库存

* 盘点调整留痕

### 4.5 采购（SCM）



| 页面          | 路由                           | 说明                 |
| ----------- | ---------------------------- | ------------------ |
| 采购计划 / 补货建议 | /purchase-plans              | 系统根据销量和库存自动建议补货量   |
| 采购单         | /purchase-orders             | 采购单创建、查看           |
| 审批工作台       | /purchase-approvals          | 待审批采购单处理           |
| 收货单         | /receiving                   | 分批收货，合格入库存，不合格单独记录 |
| 供应商         | /suppliers                   | 供应商档案              |
| 供货价         | /purchase-supplier-quotation | 供应商 - SKU 供货价、交期   |

**补货公式**：



```
建议补货量 = 日均销量 × (交期天数 + 安全库存天数) + 安全库存 - 本地可售 - FBA可售 - 在途
```

**采购单状态**：



```
draft（草稿）→ approved（已审批）→ partially\_received（部分收货）→ received（全部收货）

&#x20;               ↓

&#x20;           cancelled（已取消）
```

### 4.6 数据仓库（DataLab 接入）



| 页面   | 路由       | 说明                      |
| ---- | -------- | ----------------------- |
| 经营看板 | /datalab | 销售日报、库存健康、待采购、补货审核、数据质量 |

**数据来源**：外部 DataLab 数据仓库（`https://47.107.76.124/data-lab/`），通过 X-API-Key 认证访问，包含 141 张表（ODS/DIM/DWD/DWS/ADS 五层）。

看板展示的 ADS 汇总表：



* `ads_sales_daily` — 每日销售汇总（订单数、金额、退款、净收款）

* `ads_inventory_health` — 库存健康度（可售天数、风险等级）

* `ads_purchase_open` — 待处理采购单及到货风险

* `ads_replenishment_review` — 补货审核建议（P1/P2 紧急度）

* `ads_data_quality` — 数据完整性检查

### 4.7 基础资料



| 页面    | 路由            | 说明     |
| ----- | ------------- | ------ |
| 店铺    | /shops        | 销售店铺档案 |
| 仓库档案  | /warehouses   | 仓库档案   |
| 币种与单位 | /dictionaries | 字典管理   |

### 4.8 系统



| 页面    | 路由          | 说明          |
| ----- | ----------- | ----------- |
| 账号与角色 | /users      | 用户管理、角色权限分配 |
| 操作日志  | /audit-logs | 全系统操作审计日志   |



***

## 五、后端 API 概览

所有接口前缀：`/api/v1`，需在 Header 携带 `Authorization: Bearer <token>`。

### 5.1 认证



| 方法   | 路径           | 说明         |
| ---- | ------------ | ---------- |
| POST | /auth/login  | 登录获取 token |
| GET  | /auth/me     | 当前用户信息     |
| POST | /auth/logout | 退出登录       |

### 5.2 基础资料



| 方法       | 路径            | 说明          |
| -------- | ------------- | ----------- |
| GET/POST | /products     | 商品列表 / 新增   |
| GET/POST | /skus         | SKU 列表 / 新增 |
| GET/POST | /shops        | 店铺列表 / 新增   |
| GET/POST | /warehouses   | 仓库列表 / 新增   |
| GET/POST | /suppliers    | 供应商列表 / 新增  |
| GET/POST | /dictionaries | 字典列表 / 新增   |

### 5.3 订单（OMS）



| 方法       | 路径                            | 说明         |
| -------- | ----------------------------- | ---------- |
| GET/POST | /orders                       | 订单列表 / 创建  |
| GET      | /orders/{id}                  | 订单详情       |
| POST     | /orders/{id}/approve          | 审核订单       |
| POST     | /orders/{id}/shipment-request | 申请发货（预留库存） |
| POST     | /orders/{id}/cancel           | 取消订单       |
| POST     | /orders/{id}/payments         | 记录付款       |
| POST     | /orders/{id}/after-sales      | 创建售后       |

### 5.4 仓储（WMS）



| 方法   | 路径                      | 说明     |
| ---- | ----------------------- | ------ |
| GET  | /inventory              | 库存余额查询 |
| GET  | /inventory/transactions | 库存流水   |
| POST | /inbound-orders         | 创建入库单  |
| POST | /shipments/{id}/confirm | 确认出库   |

### 5.5 采购（SCM）



| 方法       | 路径                             | 说明          |
| -------- | ------------------------------ | ----------- |
| GET/POST | /purchase-orders               | 采购单列表 / 创建  |
| POST     | /purchase-orders/{id}/approve  | 审批          |
| POST     | /purchase-orders/{id}/receipts | 分批收货        |
| POST     | /replenishment/compute         | 计算补货建议      |
| GET/POST | /replenishment                 | 补货建议列表 / 调整 |

### 5.6 数据仓库代理



| 方法   | 路径                        | 说明       |
| ---- | ------------------------- | -------- |
| GET  | /datalab/overview         | 经营看板聚合数据 |
| GET  | /datalab/tables           | 列出所有数据表  |
| GET  | /datalab/table/{name}     | 查询指定表数据  |
| POST | /datalab/knowledge/search | 行业知识检索   |

完整交互式文档：[http://127.0.0.1:18080/docs](http://127.0.0.1:18080/docs)



***

## 六、DataLab 数据接入说明

### 6.1 外部数据源信息



| 项目      | 值                                          |
| ------- | ------------------------------------------ |
| 服务地址    | `https://47.107.76.124/data-lab/`          |
| 认证方式    | Header: `X-API-Key: <key>`                 |
| API Key | `NgWV3uEhKg_tHrY9fD06DNIkS254lKhT-jZPhxhs` |
| 数据仓库层数  | ODS → DIM → DWD → DWS → ADS（共 141 张表）      |

### 6.2 接入方式

后端 `app/datalab.py` 作为代理层：



1. 前端请求我们的后端 `/api/v1/datalab/overview`

2. 后端用 httpx 携带 X-API-Key 请求 DataLab 接口

3. 跳过 SSL 证书验证（对方是自签名证书）

4. 聚合 5 张 ADS 表数据返回给前端

这样做的好处：



* API Key 不暴露在前端

* 统一权限控制（需登录 + dashboard:read 权限）

* 前端无需关心外部服务的 SSL 和网络问题

### 6.3 可查询的核心表



| 表名                         | 层级  | 行数        | 内容           |
| -------------------------- | --- | --------- | ------------ |
| ads\_sales\_daily          | ADS | 3,652     | 每日各店铺销售汇总    |
| ads\_inventory\_health     | ADS | 548       | SKU 库存健康度与风险 |
| ads\_replenishment\_review | ADS | 362       | 补货审核建议       |
| ads\_purchase\_open        | ADS | 8         | 待处理采购单       |
| ads\_data\_quality         | ADS | 3         | 数据完整性        |
| dim\_products              | DIM | 180       | 商品维度         |
| dim\_warehouses            | DIM | 4         | 仓库维度         |
| dim\_suppliers             | DIM | 3         | 供应商维度        |
| dwd\_sales\_orders         | DWD | 1,153,826 | 销售订单明细       |
| dwd\_purchase\_orders      | DWD | 971       | 采购订单明细       |



***

## 七、项目目录结构



```
跨境电商系统开发/

├── README.md                          # 项目总说明

├── 开发执行计划.md                     # 开发计划文档

├── backend/                           # 后端

│   ├── app/

│   │   ├── main.py                    # FastAPI 入口

│   │   ├── models.py                  # 数据模型（全部表）

│   │   ├── schemas.py                 # Pydantic 请求/响应

│   │   ├── security.py                # 认证权限

│   │   ├── database.py / db.py       # 数据库连接

│   │   ├── resources.py               # 通用 CRUD

│   │   ├── orders.py                  # OMS 订单路由

│   │   ├── wms.py                     # WMS 库存路由

│   │   ├── scm.py                     # SCM 采购路由

│   │   └── datalab.py                 # DataLab 数据代理

│   ├── migrations/versions/           # Alembic 迁移

│   │   ├── 0001\_erp\_foundation.py

│   │   ├── 0002\_oms\_orders.py

│   │   ├── 0003\_wms\_inventory.py

│   │   └── 0004\_scm\_purchasing.py

│   ├── tests/                         # 自动化测试（29 项）

│   └── .venv/                         # Python 虚拟环境

├── frontend/                          # 前端

│   ├── src/

│   │   ├── main.tsx                   # 入口

│   │   ├── App.tsx                    # 路由

│   │   ├── api/                       # API 封装

│   │   ├── auth/                      # 认证状态

│   │   ├── config/menu.ts            # 导航菜单配置

│   │   ├── layouts/                   # 主布局

│   │   └── pages/                     # 业务页面

│   │       ├── DashboardPage.tsx      # 首页总览

│   │       ├── Dashboard.tsx         # DataLab 数据看板

│   │       ├── Products.tsx          # 商品

│   │       ├── Orders.tsx            # 订单

│   │       ├── Inventory.tsx         # 库存

│   │       ├── Purchase.tsx          # 采购

│   │       └── ...（其他页面）

│   ├── package.json

│   └── vite.config.ts                 # Vite 代理配置

└── docs/                              # 文档

&#x20;   ├── ERP后端设计.md

&#x20;   ├── ERP后端交付说明.md

&#x20;   └── ERP后端OpenAPI.json
```



***

## 八、测试与验证

### 后端自动化测试



```
cd backend

.\\.venv\Scripts\python.exe -m pytest tests/ -q

\# 结果：29 passed
```

### 数据库迁移



```
cd backend

.\\.venv\Scripts\python.exe -m alembic upgrade head

\# 当前版本：0004
```

### 验证清单



* [x] 登录 / 登出 /token 刷新

* [x] 商品 / SKU / 店铺 / 仓库 / 供应商 CRUD

* [x] 订单创建→审核→发货→完成全流程

* [x] 库存行锁预留与释放

* [x] 采购单审批→分批收货→入库

* [x] 补货建议计算与转采购

* [x] DataLab 数据仓库数据拉取

* [x] 前端页面渲染与交互



***

## 九、已知限制与后续方向



1. **前端为基础可用版本**：部分表单字段（如下拉选择、日期范围筛选）尚未完全实现，后续可按需完善。

2. **DataLab 数据为只读**：目前只展示外部数据仓库的汇总数据，尚未与本系统的本地数据做关联整合。

3. **未做生产构建**：当前仅 dev server 模式运行，如需部署可执行 `npm run build`。

4. **多币种汇率**：当前订单按原币统计，未做汇率折算。

5. **外部平台对接**：尚未接入 Amazon/Shopify/TikTok 等平台的自动订单同步。



***

## 十、快速访问链接



| 服务           | 地址                                                                         |
| ------------ | -------------------------------------------------------------------------- |
| 前端系统         | [http://127.0.0.1:3000](http://127.0.0.1:3000)                             |
| 后端 API 文档    | [http://127.0.0.1:18080/docs](http://127.0.0.1:18080/docs)                 |
| 后端健康检查       | [http://127.0.0.1:18080/ready](http://127.0.0.1:18080/ready)               |
| DataLab 数据平台 | [https://47.107.76.124/data-lab/](https://47.107.76.124/data-lab/)         |
| 领星参考 ERP     | [https://47.107.76.124/lingxing-erp/](https://47.107.76.124/lingxing-erp/) |



***

*文档结束。如有问题请联系开发人员。*