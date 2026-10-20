# OMS 订单管理系统（独立部署）

面向跨境电商卖家的独立订单处理系统，覆盖 **订单中心、售后与客服、渠道、客户、财务、仓储、系统设置** 七大模块。
功能规格以 `docs/oms/` 下 35 篇文档为准，本工程为完整可运行实现。

## 技术栈

- 后端：Python 3.14 / FastAPI / SQLAlchemy 2 / PostgreSQL（本机 15432 端口 `oms` 库）
- 前端：Vite 8 / React 18 / TypeScript / Ant Design 5
- 端口：后端 18090，前端 3002（3001 被占用时自动顺延）

## 快速启动

```bash
# 1. 初始化数据库（幂等，可重复执行；含演示数据）
cd oms/backend
.venv\Scripts\python -m app.seed

# 2. 启动后端（已包含建表）
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 18090

# 3. 启动前端（另开终端）
cd oms/frontend
npm run dev
```

访问 `http://127.0.0.1:3002`，演示账号：`admin / admin12345`。

## 功能清单（对应 docs/oms 35 篇文档）

| 模块 | 功能 | 文档篇目 |
|---|---|---|
| 订单中心 | 订单总览看板、订单列表（筛选/分页）、订单详情、手动创建、批量导入、审核、编辑（改商品/数量/地址）、取消、申请发货、批量审核/取消 | 05-13 |
| 售后管理 | 售后工单列表、退款申请处理（完成/拒绝）、售后原因统计 | 14,15,18 |
| 客服工单 | 工单创建/列表/详情、分派、开始处理、处理记录、完成/重开/关闭 | 14 补充 |
| 渠道管理 | 店铺列表与授权状态、Listing/SKU 映射、渠道同步日志（导入留痕） | 19-22 |
| 客户管理 | 客户主档列表/详情、标签、客户分级（VIP/黑名单）、订单与工单聚合 | 23-25 |
| 财务管理 | 收款记录、退款记录（待审批→已批准→已执行闭环） | 26-27 |
| 仓储管理 | 库存台账（在库/预留/可售）、库存调整盘点、入库单、出库单（拣货→发货） | 30 |
| 系统设置 | 账号与角色（RBAC 权限）、仓库档案、物流渠道、运费模板、打印模板、操作日志 | 30-35 |

## 关键业务流程

```
创建订单(draft) → 审核(approved, 指定仓库) → 申请发货(shipping_requested, 预留库存)
  → 确认出库(fulfilled, 扣减库存+登记物流单号) → 售后(退款/退货) → 退款执行闭环
```

取消订单：draft / approved / shipping_requested 均可取消；已预留库存自动释放。
订单编辑：仅 draft / approved 可编辑，改明细后自动回到待审核。

## 权限模型

内置角色：admin（超管）、operator（运营）、cs（客服）、warehouse（仓管）、finance（财务）。
权限为「资源:动作」粒度（如 `orders:write`），可在「系统设置 → 账号与角色」中自定义角色。
店铺/仓库支持数据范围限制：运营、仓管账号可被限定到部分店铺/仓库。

## 数据库

- 连接串：`postgresql+psycopg2://erp:****@127.0.0.1:15432/oms`（见 `backend/.env` / `app/database.py`）
- 表：roles/users/auth_sessions/audit_logs、dictionaries/products/skus/shops/warehouses/suppliers、
  customers/customer_tickets(+events)、listings/channel_sync_logs、sales_orders(+items)/payment_records/
  after_sales/refund_records、inventory_balances/transactions、shipment_orders(+items)/inbound_orders(+items)、
  logistics_channels/shipping_templates/print_templates

## 测试

```bash
cd oms/backend
.venv\Scripts\python -m pytest tests -q    # 18 passed
```

覆盖：认证鉴权、基础资料校验、订单全流程（创建/重复单号/审核/发货/出库/取消释放库存/编辑回退）、
批量导入与批量审核、付款/售后/退款闭环、客服工单状态机、渠道映射、客户标签、库存入库与盘点、审计日志。

## 目录结构

```
oms/
├─ backend/
│  ├─ app/
│  │  ├─ main.py           # 应用入口：认证、账号角色、审计、路由注册
│  │  ├─ models.py         # 全部数据模型
│  │  ├─ schemas.py        # 输入校验
│  │  ├─ security.py       # 登录/权限/审计
│  │  ├─ resources.py      # 基础资料通用 CRUD（店铺/SKU/仓库/物流/模板等）
│  │  ├─ orders.py         # 订单/付款/售后/批量/看板
│  │  ├─ wms.py            # 库存/入库/出库
│  │  ├─ customer_tickets.py  # 客服工单
│  │  ├─ listings.py       # 渠道映射/同步日志
│  │  ├─ customers.py      # 客户主档
│  │  ├─ refunds.py        # 退款流水
│  │  ├─ seed.py           # 演示数据（幂等）
│  │  └─ database.py       # 数据库连接
│  └─ tests/test_oms.py    # 18 个自动化测试
└─ frontend/
   └─ src/
      ├─ pages/            # 20 个业务页面（看板/订单/售后/工单/渠道/客户/财务/仓储/设置）
      ├─ MainLayout.tsx    # 侧边栏+顶栏布局
      ├─ LoginPage.tsx     # 登录页
      └─ api.ts            # axios 封装（token 注入/401 跳转）
```

## 常见问题

- **后端启动失败（端口占用）**：`Get-NetTCPConnection -LocalPort 18090` 找到进程后停止，或换端口。
- **前端 3001 被占用**：Vite 会自动顺延端口，以启动日志显示的地址为准。
- **改了后端代码不生效**：uvicorn 无 `--reload` 时需手动重启进程。
