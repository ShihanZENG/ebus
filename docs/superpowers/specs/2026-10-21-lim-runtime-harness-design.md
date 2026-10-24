# LIM Runtime 与 Harness 首批设计

## 意图

依据《CommerceOS AI 平台管理端（LIM Console）PRD v1.0》，先完成 G0 现状核验和 G1 统一运行治理的首个可验收纵切。目标是把分散的 AI 能力纳入可发现、可授权、可追踪、可评测的公共基础设施，同时继续由 ERP/OMS 业务服务持有权威业务事实。

## 批次目标

- G0：核验现有 AI/Agent/Tool/权限/运行记录/审核/审计实现，形成“已实现、已联通、已验收、生产可用”能力矩阵和差距清单。
- G1：在现有 FastAPI、SQLAlchemy、Alembic、React、TypeScript、Ant Design 中实现统一 Agent Registry、Tool Registry、只读 Scope 受控调用、Run 状态和 Trace 记录，并提供 Golden Dataset 的登记与基础离线评测入口。
- 使用至少两个现有只读 Agent 能力作为纵切样例；现有采购 Agent 的运行和工具记录需先盘点并决定复用/适配，避免重复事实源。

## 目标

- Agent 草稿可登记、查询、校验、归档；发布校验必须要求 output schema、已登记工具和风险/Scope 元数据。
- Tool 定义必须有输入/输出 JSON Schema、业务域、read/write 分类、风险、超时和幂等策略元数据；本批只允许 read 工具进入运行时。
- 每次管理端触发的只读 Run 都由后端身份和权限建立 BusinessScope；客户端或模型提供的 tenant/store/resource 字段不能扩大权限。
- Run 状态受服务端允许的状态迁移约束；失败、拒绝、预算停止有原因码并关联 Trace/span 与工具调用。
- Eval Dataset 和 Eval Run 可保存固定输入、scope、可接受输出、必需证据、禁止动作及逐例结果；不得声称测试目标已经达到。
- 前端提供 Agent、Tool、Run/Trace、Eval 的最小可操作工作台，显示数据缺失、权限拒绝和失败原因，不以空数据伪装健康。

## 非目标

- 不实现生产写工具、自动业务执行、审批执行回路或模型输出授权。
- 不实现完整 LangGraph Workflow Studio、AI Gateway 多模型路由、Temporal GraphRAG、长期记忆/Skill 生命周期、生产发布灰度或完整 LLMOps。
- 不将建议的量化门槛写成既有成绩；没有数据时展示未评测。
- 不合并 ERP 与独立 OMS 身份、数据库或业务状态。

## 安全与数据约束

- ERP 的商品、订单、库存、采购、财务仍是权威事实；LIM 只保存配置、受限摘要引用和运行观测。
- BusinessScope 从已认证服务端用户及现有店铺/仓库范围构造；工具不得信任模型传入的 tenant_id、store_id 或权限字段。
- 高风险写入维持关闭；模型密钥、数据库凭据和生产写权限不得进入浏览器或 Trace。
- Trace 默认保存最小必要摘要；对凭据和 PII 脱敏，读取与管理操作写审计日志。
- 幂等字段和回执能力只作为注册元数据；本批不执行外部副作用。
- Run 状态至少覆盖 CREATED、SCOPE_CHECKED、PLANNED、RUNNING、VERIFYING、COMPLETED、REVIEW_REQUIRED、REJECTED、FAILED、WAITING_INPUT、BUDGET_EXCEEDED。

## 实现判断

- 先审阅并复用 `purchase_agent.AgentRun`、`AgentToolCall` 和现有 `require_scope`、角色/审计机制；若其业务字段与 LIM 通用生命周期不能兼容，则新增 lim 专用表并通过来源 ID 建立可追踪关联，不迁移或删除采购历史。
- 首批 Runtime 使用确定性只读工具适配器，不让模型直接调用 ERP 数据库。管理 UI 首先支持注册/验证/查询及评测运行，不提供任意代码执行或生产发布按钮。
- 以明确 API 契约和 Alembic 迁移演进持久化模型；不引入新基础设施依赖。

## 验收

- 无 output schema、未登记工具、未知工具、write 工具或缺少 Scope 元数据时，Agent/Tool 不能进入可运行状态。
- 未登录/过期会话返回 401；缺权限返回 403；越权店铺/仓库读取不泄露资源是否存在。
- 客户端伪造 scope 字段不能读取范围外数据；只读运行中任何工具均不能产生业务写操作。
- 状态迁移非法时拒绝并审计；失败和预算终止可按 Run/Trace 查询并保留错误码。
- Trace 与 Tool Invocation 按 run/span/parent 关联；凭据、PII 不出现在 API 响应和导出摘要。
- Eval Run 固定数据集和 Agent 版本，保存逐例结果；空数据集/不完整期望值明确拒绝或标记不可评测，不生成虚假指标。
- 至少两个既有只读 Agent 接入或通过同一受控注册与 Trace 外壳运行；若现有调用契约阻止本批完整接入，交付差距并清晰标注，不宣称已统一。
