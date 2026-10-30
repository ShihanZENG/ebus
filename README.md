# EBUS · 跨境电商 ERP 与 LIM

本仓库包含跨境电商 ERP 后端与管理前端、独立 OMS、Storefront，以及 LIM 智能经营能力。后端使用 FastAPI、SQLAlchemy 和 Alembic；管理前端使用 React、TypeScript 和 Ant Design。

## 当前能力与边界

- ERP 覆盖商品、订单、库存、采购、客服工单等业务。独立 OMS 和 Storefront 有各自的前后端与文档。
- `/lim-workbench` 展示授权业务数据上的 LIM 运行、证据图谱和追踪。Neo4j 检索、模型调用和外部追踪依赖本地配置；缺少配置时界面会报告连接状态。
- `/api/v1/lim/v2/*` 是五大能力**沙盘接口**：图谱含示例数据，执行接口只模拟状态机，不会修改生产订单、库存或付款。代码见 [沙盘路由](./backend/app/lim_enterprise_routes.py)。
- 客服意图识别位于 [intent.py](./backend/app/intent.py)。工单识别会记录事件与审计；识别结果是路由建议，不会自动退款或审批。
- 独立站留言进入管理前端“独立站运营 → 客服与售后请求”。后台显示本地规则识别建议，客服可回复并更新状态；订单顾客凭订单访问凭据查看，售前顾客可在提交时的浏览器凭私密回执查看最近一次咨询。此流程仍为演示登记，不会自动发邮件或执行售后退款；它与 ERP 的 `CustomerTicket` 是两类记录。
- Storefront 持有库存预占的订单，在申请发货和确认出库时会检查已核验的真实付款，详见 [WMS 支付门禁](./backend/app/wms.py)。

## 本地启动（PowerShell）

先安装 Python、Node.js 和 Docker。后端环境变量只从 `backend/.env` 读取；请从示例文件复制并填写本地密码，不要提交真实凭据。

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# 编辑 .env：保持 DATABASE_URL 与 POSTGRES_* 的密码一致
docker compose -p crossborder-erp up -d db redis
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.bootstrap --demo
.\start.ps1
```

在另一个终端启动管理前端：

```powershell
cd frontend
npm ci
npm run dev
```

管理前端默认在 `http://127.0.0.1:15173`，后端接口文档在 `http://127.0.0.1:18080/docs`。Neo4j、OpenTelemetry 和 Langfuse 的可选配置见 [后端 README](./backend/README.md)。独立 OMS 的启动步骤见 [OMS README](./oms/README.md)；Storefront 见 [Storefront README](./storefront/README.md)。

## 验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_intent_context.py tests/test_storefront_bridge.py tests/test_external_payment_idempotency.py tests/test_lim_five_pillars.py tests/test_erp.py::test_migration_seed_persistence -q
```

```powershell
cd frontend
npm run build
```

更多业务边界和需求对照见 [LIM 能力盘点](./docs/lim/g0-capability-inventory.md)与[开发执行计划](./开发执行计划.md)。
