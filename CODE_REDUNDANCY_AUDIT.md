# 代码冗余重复审计（2026-10-21）

> 当前状态更新（2026-10-23）：以下旧审计和历史统计保留用于追溯，不作为当前待办清单；以本节为准。独立 OMS 按用户要求暂不处理。

## 当前清理状态（2026-10-23）

- 删除前端未引用的 `MasterDataPage.tsx` 和 `ComingSoonPage.tsx`。
- 前端统一采用 `api/http.ts` 的 Axios 客户端工厂：集中 Token 和 401 失效事件处理。`api.ts` 保留 Axios 响应和业务页面错误提示；`api/client.ts` 保留类型化数据、`ApiError` 和 Blob 下载契约，JSON/下载共用发送逻辑。两种调用接口用于兼容已有页面，不再分别维护 Fetch/Axios 传输逻辑。
- 修正后端 README 中“未实现金额、库存或交易单据”的过时描述。
- 之前 `_allowed` / `_money` 已移到 `app/common.py`，一次性脚本已归档到 `scripts/oneoff/`，不重复列为本轮清理目标。
- 旧报告“角色管理与操作日志为 OMS 独有、需补主系统后端”的结论不适用于当前代码：主系统已有 `/roles`、`/users` 和 `/audit-logs` 接口。独立 OMS 的其余差异须另行核对，本轮不迁移。
- `LegacyPurchaseAgentPage` 仍在“手工参数测算”标签下使用，不是死代码，本轮保留。退役需先核对使用场景和历史草稿访问。
- 商品/运营 Agent 的工具执行流程已有差异，本轮保留各自流程，不据旧版相似度报告直接合并。
- `docs/功能章节`、`docs/oms` 是 LIM 知识源扫描目录，保留路径。构建产物、依赖环境、备份和历史一次性脚本未删除。

---

审计方式：全量扫描（非抽样）。只报有证据的项，不确定的标注「待确认」。行数为 `wc -l` 实测。

---

## 结论先行

1. **最大的重复不是小函数，而是两套半重叠的系统。** `oms/`（独立订单管理系统）与主系统的 OMS 切片高度重复：orders 模块 11 个端点完全重合、约 20 个 ORM 模型同名、两套认证 / 库存 / 售后实现各自维护。README 说明这是**有意独立部署**（端口 18090/3002 vs 18080/15173），严格说不是意外重复，但代价是同一套业务逻辑要改两遍。
2. **主系统内部是「脚手架级」重复**：公共小工具被复制（`_allowed` ×3、`_money` ×3、`_snapshot` ×4）、Agent 骨架复制粘贴、assistant 系列 4 个模块共享同一个 scope 查询骨架。这类重复最好抽，收益直接。
3. **目录卫生**：backend 根目录堆了 39 个一次性脚本 / 日志（未入 git，但占磁盘、干扰检索）；`tools/` 与 backend 根的 probe 脚本职能重叠；三套 node_modules + 两个 .venv；文档有三套入口（docs 141 篇 / lab 50 篇 / 归档 20 篇）。

## 规模盘点

| 区域 | 文件数 | 代码行数 | 备注 |
|---|---|---|---|
| `backend/app` | 70 py | 18,054 | 238 处路由装饰器；lim_* 子系统 16 文件 4,467 行，`lim_routes.py` 单文件 1,085 行 |
| `backend/tests` | 55 py | 8,503 | pytest，重构安全网 |
| `frontend/src` | 68 个页面 | 13,711 | 53/68 页面走 `src/api` 层，仅 StorefrontPage 用裸 fetch（基本规范） |
| `oms/backend/app` | 13 py | 3,299 | +tests 356 行 |
| `oms/frontend/src` | 19 页面 | 2,484 | 与主系统业务域大部分重叠 |
| `storefront/src` | 1 文件 | 516 | 单文件演示商城，OK |

## P0 — oms/ 与主系统重复（结构性问题，需要决策）

**orders 模块端点对比**（`backend/app/orders.py` vs `oms/backend/app/orders.py`）：

| 重合端点（11 个） | oms 独有 | 主系统独有 |
|---|---|---|
| 列表 / 详情 / 编辑 / 导入 / 审核 / 申请发货 / 取消 / 收款列表 / 收款登记 / 售后列表 / 售后申请 / 汇总 | export | import-batches、ordered-at、渠道同步等 |

**模型重合（约 20 个同名）**：User、Role、AuthSession、Customer、SalesOrder、SalesOrderItem、PurchaseOrder、PurchaseOrderItem、AfterSale、AuditLog、PaymentRecord、Product、Shop、Supplier、InboundOrder、InboundOrderItem、ShipmentOrder、ShipmentOrderItem、InventoryBalance、InventoryTransaction、Dictionary、Record。

**判断**：oms 的 orders/customers/tickets/refunds/core-inventory 与主系统是同一业务的两份实现；oms 多出的是 export、打印/运费模板、物流渠道、同步日志、RBAC 页面。按 `docs/统一系统与八模块规划.md` 的方向应是**合并**。

**建议**：做一个明确决策，二选一——
- A. 合并进主系统，删除 `oms/`（省一份完整的前后端 + .venv + node_modules 维护）；
- B. 保留独立部署，但在 README 写清「为什么必须双写」的边界（合规？演示？），否则每次改订单流程都要记得改两遍。

## P1 — 主系统内部可抽取的重复（小步、收益直接）

1. **权限检查复制 3 份**：`app/assistant.py:44`、`app/assistant_catalog.py:27`、`app/business_evidence_tools.py:23` 各有一份 `_allowed(db, user, permission)`。→ 提取为 `app/deps.py` 的一个依赖。
2. **金额格式化复制 3 份**：`app/agent_generation.py:170`、`app/profit_reconciliation.py:262`、`app/purchase_amendments.py:57` 各有一份 `_money()`。→ 提取为 `app/utils.py` 公共实现（含 Decimal 边界规则）。
3. **快照序列化 `_snapshot` 4 份**：`fba.py:162`、`listings.py:72`、`purchase_amendments.py:86`、`purchase_plans.py:67`。结构相似但字段各异，不必强行合并函数；建议抽出共用的「分页 + 用户摘要」子序列化。
4. **Agent 骨架复制粘贴**：`product_agent.py`(94 行) 与 `operations_agent.py`(67 行) 是同一骨架（router + AskInput + ask 端点 + `_summary` 叙事），shingle 相似度 22.4%，diff 仅 75 行。→ 抽一个 `BaseAskAgent` 基类 / 工厂，两个具体 agent 只声明工具清单和摘要文案。`purchase_agent/listing_agent` 是同族，改造时一并评估。
5. **assistant 系列 4 模块共享同一骨架**：`assistant.py`(248) / `assistant_tasks.py`(201) / `assistant_operations.py`(144) / `assistant_catalog.py`(128)，都是「scope 分区查询 + unavailable 标记 + 汇总文案」同一模式。→ 与第 4 点一起抽。
6. **lim_* 16 文件 4,467 行**：内聚尚可，但 `lim_routes.py` 1,085 行单文件偏大。建议按域拆分 routes，属优化而非去重，优先级低于上面几项。

## P2 — 目录卫生（未入 git，可安全清理）

- **backend 根目录 39 个一次性文件**：`probe_*.py` ×14、`seed_*.py` ×6、`submit_*.py` ×2、`*.log` ×17。正式替代品已存在（`scripts/seed_demo.py`，幂等走 HTTP）。建议移到 `scripts/oneoff/` 或删除。
- `tools/probe_api.py` 与 `backend/probe_api.py` 职能重叠（内容不同，一旧一新），确认后留一份。
- `backend/backups/*.dump` ×5 旧转储；`frontend/dist_verify/` 等构建产物目录。
- 三套 `node_modules`（frontend / storefront / oms/frontend）+ 两个 `.venv`（backend / oms/backend），磁盘占用大，按需清理。
- 文档三套入口：`docs/`(141) / `lab/`(50) / `归档/`(20)，建议归并层级、一个 README 索引。

## 建议动作顺序

| 优先级 | 动作 | 验证方式 |
|---|---|---|
| P0 | oms 去留决策（合并 or 写边界） | 决策本身 |
| P1 | 抽 `app/deps.py` 的 `_allowed`、`app/utils.py` 的 `_money` | pytest 55 个测试文件全绿 |
| P1 | Agent 骨架抽基类（product/operations 先行） | pytest + 前端 build + 真浏览器冒烟 |
| P2 | 清 backend 根一次性文件、文档归并 | 构建 + 冒烟回归 |

> 项目约定提醒：`npm run build` / pytest 通过 ≠ 功能可用。每次重构后用真浏览器跑一遍可见输出断言。

---

## 已执行（2026-10-21）

用户要求一次性处理；本轮完成 P1 + P2，**oms 只做计划、不盲删**（盲删会丢掉主系统还没有的功能）。

### P1 — 抽公共函数（已完成）
- 新增 `backend/app/common.py`：`allowed(db, user, permission)` 与 `money(value)`。
- 删除 6 处复制定义，改为 `from .common import allowed as _allowed` / `money as _money`：
  - `assistant.py`、`assistant_catalog.py`、`business_evidence_tools.py` 的 `_allowed`（3 份 → 1 份，顺手修了 `assistant.py` 旧版对 `role is None` 会抛异常的问题）
  - `agent_generation.py`、`profit_reconciliation.py`、`purchase_amendments.py` 的 `_money`（3 份 → 1 份，统一为 `ROUND_HALF_UP` + 字符串兜底）
- 验证：`app.main` 可导入；相关测试通过 —— `test_agent_generation` / `test_assistant_ticket_notes` / `test_business_evidence_refs` 7 passed、`test_profit_reconciliation` + `test_purchase_agent` 17 passed（共 24 passed）。

### P2 — 清理 backend 根目录（已完成）
- 把 22 个一次性脚本（`probe_*.py` ×14、`seed_*.py` ×6、`submit_*.py` ×2）移入 `backend/scripts/oneoff/`。
- 删除 backend 根目录全部 `*.log` 运行日志（gitignored，可重建）。
- 把 `api_routes.txt` 一并移入 `scripts/oneoff/`。
- 效果：backend 根从「配置 + 一堆脚本/日志」收敛为只剩 `README.md / alembic.ini / compose.yaml / pytest.ini / requirements.txt / start.ps1`。
- 顺带消除 `tools/probe_api.py` 与 backend 根 `probe_api.py` 的职能重叠（后者已降级到 oneoff）。

> 未动：前端（仅 StorefrontPage 用裸 fetch，影响极小）；文档三套入口（`docs/lab/归档`，211 篇 md，属于重组而非去重，破坏性大，留作单独决策）。

### 数据层发现（2026-10-22 补充）

- 三套库**各自独立、未打通**：`erp`（89 表）/ `oms`（29 表）/ `erp_storefront_demo`（89 表），同机同 Postgres、同 `erp` 登录角色，仅库名不同。
- `oms` 自己另存一份 `users/roles/shops/products/skus/customers/sales_orders/inventory_balances/...`，与 `erp` 同名同义但**不同库、零外键、无 API 桥接**；oms 独有 `logistics_channels/print_templates/shipping_templates/channel_sync_logs/refund_records`。主后端代码里 grep 不到任何打向 oms(18090) 的调用。
- 这是 P0 的代码重复的**数据层**版本：同一业务域被建模 2~3 遍，无单一可信源。oms 合并（方案 A）正是针对它。
- 顺带发现：主 app 的 `storefront` 板块此前 404（见下）。

### P1/P2 之外 — storefront 接回 erp 真实库（2026-10-22，方案 C）

- **问题**：主 ERP 后端 `app.main:app` 默认 `storefront_enabled=False`，`/api/storefront/v1/*` 与 `/api/v1/storefront/*` 一律 404；storefront 表虽已在 erp schema，但 erp 里这些表是空的（只在 `erp_storefront_demo` 被 seed 过）。
- **改动**：
  1. `backend/app/main.py` 模块级 `app = create_app()` 改为读 `STOREFRONT_ENABLED` 环境变量（默认仍 `False`，不动测试）。
  2. `backend/.env` 加 `STOREFRONT_ENABLED=true`。
  3. 用 `app.storefront.demo.seed_catalogue` 把演示目录（GBP 站点 `zhijian-uk`「织间」+ 1 商品 + 6 变体 + 演示店/仓）灌入 **erp** 库。
- **验证**：`/api/storefront/v1/site`、`/api/storefront/v1/products` 由 404 → 200 且返回 erp 真实数据；`/api/v1/storefront/site` 无 token→401（路由已挂载）、带 admin token→200；`tests/test_storefront.py` 19 passed。
- **边界**：storefront 是硬编码 GBP 单站点的演示功能（响应带 `demo:true`）。"接回 erp" = 主系统商城板块读真实 erp 库并可用，非多租户生产商城。**oms 仍独立未纳入**。

---

## P0 — oms 受控合并计划（待你拍板后再执行）

> 为什么不直接删：oms 的 orders/customers/tickets/core-inventory 与主系统重复，但 oms **独有**这些主系统当前没有的能力 —— 订单/售后导出（export）、打印模板、运费模板、物流渠道、渠道同步日志、RBAC 用户/角色页、操作审计日志。盲删 = 永久丢掉这些功能。正确做法是把它们迁进主系统后再删 oms。

### 功能差异清单（决定要迁什么）

| 归类 | oms 独有功能 | 落地方式 |
|---|---|---|
| 已有重复 | orders 11 端点、customer_tickets、customers、listings、core inventory | 直接复用主系统现有实现，删 oms 副本 |
| 需迁 | 订单/售后 export、打印模板、运费模板 | 主系统 orders/after_sales 模块加导出端点 + 模板表 |
| 需迁 | 物流渠道、渠道同步日志 | 并入主系统 channels 模块 |
| 需迁 | RBAC 用户/角色管理页 + 操作日志 | 并入主系统 users/audit-logs（主系统已有 UsersPage / AuditLogsPage 路由，补后端） |
| 需迁 | 退款独立流程 refunds | 并入主系统 after-sales |

### 迁移步骤（建议顺序）
1. **决策锁范围**：逐项确认上表「需迁」项是否纳入一期，删掉不做的项。
2. **后端并表**：把上表功能在 `backend/app` 对应模块补齐（同一 PostgreSQL 实例），先不碰 oms 的库。
3. **前端并页**：oms/frontend 的 `OrdersPage/RefundsPage/PrintTemplatesPage/ShippingTemplatesPage/LogisticsPage/SyncLogsPage/UsersPage/AuditLogsPage` 合并进 `frontend/src/pages`（注意主系统已有同名概念页，需做字段对齐而非复制）。
4. **数据迁移**：oms 库（端口 15432 `oms`）→ 主库。需写一次性迁移脚本，先 dump 校验行数。
5. **切换与观察**：停 oms 服务，保留 oms/ 目录与库 1 个迭代作回滚；确认主系统覆盖等价后删除 `oms/`。
6. **回归**：pytest 全绿 + 前端 build + 真浏览器冒烟（按项目约定）。

### 回滚
oms/ 目录与 `oms` 库在删除前全程保留；删除只是最后一步，可随时回退到「保持双系统」状态。

### 校验口径
- 合并前后：主系统 + oms 的公开端点差集应为空（除明确不做的项）。
- 数据：迁移后两库业务表行数一致（参考现有「备份恢复演练 27 张表行数比对」做法）。

---

## 建议动作顺序（更新版）

| 优先级 | 动作 | 状态 |
|---|---|---|
| P1 | 抽 `_allowed` / `_money` 到 `app/common.py` | ✅ 已完成 |
| P2 | 清 backend 根一次性文件与运行日志 | ✅ 已完成 |
| P1/P2 | storefront 接回 erp 真实库（404→200，seed erp） | ✅ 已完成（2026-10-22，方案 C） |
| P0 | oms 受控合并（见上计划） | ⏸ 待决策 |
| P1 | Agent 骨架抽基类（product/operations）、assistant 4 模块归并 | 未做 |
| P2 | 文档三套入口归并 | 未做（破坏性大，单独决策） |

