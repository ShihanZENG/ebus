# G0 LIM 能力盘点

盘点日期：2026-10-21。依据 LIM PRD v1.0 和当前代码、接口、迁移及测试文件；状态描述的是仓库证据，不等同于生产环境认证。`部分`表示已有局部能力，未覆盖 PRD 要求的完整治理链路。生产状态在没有部署、容量、安全和真实数据验证证据时一律标为“未核验”。

## 状态口径

| 状态 | 含义 |
|---|---|
| 已实现 | 仓库存在可定位的代码或数据结构 |
| 已联通 | 页面/API/业务服务之间存在实际调用链 |
| 已验收 | 有自动化测试或可复现验收记录支撑 |
| 生产可用 | 有生产部署、安全、容量和运行证据；本次静态盘点不能单独判定 |

## LIM 功能需求矩阵

| PRD | 实现 | 联通 | 验收 | 生产 | 证据与差距 |
|---|---|---|---|---|---|
| LIM-FR-001 租户与角色 | 部分 | 部分 | 部分 | 未核验 | `backend/app/security.py` 的 `current_user`、`require`、`require_scope` 和 `backend/app/models.py` 的 Role/User/shop_scope/warehouse_scope 提供本地角色及店铺/仓库范围；`backend/tests/test_erp.py::test_scope_filter_before_count_and_revocation`、`test_scoped_writer_and_role_changes` 有负向覆盖。没有明确 Tenant 实体或跨租户主键隔离，也没有 SSO。 |
| LIM-FR-002 Agent Registry | 未实现 | 未实现 | 未实现 | 未核验 | 商品/运营 Agent 是静态路由；采购有独立 `AgentRun`。没有统一版本化定义、能力标签、Schema 校验、归档/回滚 Registry。 |
| LIM-FR-003 多 Agent Workflow | 未实现 | 未实现 | 未实现 | 未核验 | 未发现节点/边/State、条件分支和 Join 的通用工作流定义或重放器；PRD 明确列为后续 G3。 |
| LIM-FR-004 Task/Run 生命周期 | 部分 | 部分 | 部分 | 未核验 | `backend/app/purchase_agent.py::AgentRun` 与供应 Agent 路由有独立状态和读取接口；商品/运营对话没有统一 Run。现有状态不覆盖统一状态机、取消、原因码与跨 Agent 审计。 |
| LIM-FR-005 State/Checkpoint | 未实现 | 未实现 | 未实现 | 未核验 | 运行结果快照和工具调用记录存在于采购专用数据模型；未发现版本化 checkpoint、安全恢复协议或重复副作用恢复证明。 |
| LIM-FR-006 Tool Registry | 未实现 | 部分 | 部分 | 未核验 | `backend/app/assistant_catalog.py`、`assistant_operations.py` 等以 Python 清单/函数注册本地工具；没有可管理的版本化 Schema、风险、超时、幂等、发布校验 Registry。 |
| LIM-FR-007 工具权限隔离 | 部分 | 部分 | 部分 | 未核验 | `assistant.py` 调用业务函数，函数按权限和 shop/warehouse scope 过滤；`assistant_catalog.py::get_product_360`、`assistant_operations.py::get_operations_snapshot` 亦做范围处理。`assistant` 和 `purchase` 测试覆盖部分权限/范围；无统一 actor/store/resource/action 工具策略层。 |
| LIM-FR-008 Harness 预算 | 部分 | 部分 | 部分 | 未核验 | `assistant.py`、`product_agent.py`、`operations_agent.py` 各自限制模型轮数/工具数量/参数长度/请求时长；没有共享 Token、费用、时长和总工具预算。 |
| LIM-FR-009 人工审批/命令门禁 | 部分 | 部分 | 部分 | 未核验 | 采购建议及 Listing/经营生成结果存在人工审核入口，见 `purchase_agent.py`、`listing_agent.py`、`generation_reviews.py` 和相应测试。没有 Agent 提案绑定配置版本、策略审批和防过期批准的通用门禁。 |
| LIM-FR-010 幂等/失败核对 | 部分 | 部分 | 部分 | 未核验 | 采购草稿使用幂等键，售后/外部操作各有局部幂等和回读路径；相关测试见 `test_purchase_agent.py`、`test_after_sales_execution.py`。没有所有 Tool 都必须声明/校验的统一执行协议；本批不开放生产写工具。 |
| LIM-FR-011 AI Gateway | 部分 | 部分 | 部分 | 未核验 | `supply_agent_llm.py` 提供模型 HTTP completion，多个 Agent 复用；尚无模型 Registry、策略路由、配额、熔断、成本标签及统一凭据托管配置。 |
| LIM-FR-012 检索源/元数据 | 部分 | 部分 | 部分 | 未核验 | `assistant_knowledge.py::search_knowledge` 搜索本地文档，业务工具查 ERP；知识来源版本、权限、有效期、索引版本管理未实现。 |
| LIM-FR-013 Hybrid/Agentic Retrieval | 部分 | 部分 | 部分 | 未核验 | 本地知识检索是关键词方式，AI 总助手可以选择多个只读工具；没有向量/混合检索计划、分路得分和统一证据命中评测。 |
| LIM-FR-014 Temporal GraphRAG | 未实现 | 未实现 | 未实现 | 未核验 | 未发现时态实体关系图、多跳查询或历史快照引用校验。属于 PRD G4 后续目标。 |
| LIM-FR-015 Memory/Skill 治理 | 未实现 | 未实现 | 未实现 | 未核验 | 当前对话按请求运行，没有候选→审核→验证→发布的长期记忆/Skill 治理表和流程。 |
| LIM-FR-016 Trace Explorer | 部分 | 部分 | 部分 | 未核验 | 采购 Agent 可查询 Run 和 ToolCall；`SupplyAgentWorkbench.tsx` 展示采购工具记录，`RunTraceDrawer.tsx` 展示专用聊天 Trace。无统一 trace/span/parent、成本/证据关联和跨 Agent 查询/脱敏导出。 |
| LIM-FR-017 Evaluation Lab | 部分 | 部分 | 部分 | 聚焦验收 | 已有固定 Dataset/Agent Eval、可复用已完成运行的固定版本比较、逐例本地确定性差异与阈值报告；PRD 全量指标、真实模型参数固定/效果评测和生产门禁仍未实现。 |
| LIM-FR-018 Security Regression | 部分 | 部分 | 部分 | 未核验 | `test_assistant_ticket_notes.py`、`test_purchase_agent.py`、`test_supply_agent.py`、`test_listing_agent.py` 等覆盖权限、范围与审批负例；没有统一注入、工具误参、幂等和安全评测集/报告。 |
| LIM-FR-019 发布/灰度治理 | 部分 | 部分 | 部分 | 未核验 | Alembic 和业务配置有版本/审核数据，但没有 Agent/Prompt/Tool/检索数据独立发布版本、评测门禁、灰度及回滚。 |
| LIM-FR-020 成本/容量 | 部分 | 部分 | 部分 | 未核验 | 局部模型超时/循环上限与采购 Tool elapsed_ms；没有跨租户/Agent/版本 token、费用、延迟、容量和导出趋势。 |
| LIM-FR-021 敏感字段/审计 | 部分 | 部分 | 部分 | 未核验 | Trace 访问现记录允许/拒绝读取元数据，既有写操作审计保留；请求校验错误不回显输入。仍缺 Trace 统一字段分类、业务确认后的最短保留/删除期限和脱敏导出审计。 |
| LIM-FR-022 Sandbox 调试 | 未实现 | 未实现 | 未实现 | 未核验 | 未发现隔离测试数据、Mock Tool、有限预算与生产写工具隔离的 Sandbox 环境。 |
| LIM-FR-023 诊断证据治理 | 部分 | 部分 | 部分 | 未核验 | 经营生成、采购草稿、业务执行结果在局部模块分开存储，见 `agent_generation.py`、`purchase_agent.py` 和业务单据/审计表；不存在统一 Finding/Proposal/ExecutionReceipt 引用契约。 |
| LIM-FR-024 运行异常告警 | 未实现 | 未实现 | 未实现 | 未核验 | 未发现错误率/成本告警、Trace 定位、确认/关闭工作流。 |

## 2026-10-26 五大能力增量接入说明

`lim_langgraph_orchestrator.py`、`lim_graphrag.py`、`lim_memory.py`、`lim_execution_guard.py`、`lim_telemetry.py` 已作为算法/沙盘模块加入；`/api/v1/lim/v2/*` 使用现有登录与权限机制，`/lim-workbench` 明确标注沙盘模式。其自带测试验证的是示例数据和进程内状态，不等于 ERP 业务数据或外部服务验收。

| 需求 | 本轮进展 | 仍需完成 |
|---|---|---|
| LIM-FR-002 Agent Registry | 保留现有 `lim_registry.py` 为权威注册表；新增编排器使用静态领域节点。 | 将领域 Agent 的版本、能力标签及回滚绑定现有 Registry。 |
| LIM-FR-003 Workflow | 新增 LangGraph 沙盘编排及冲突仲裁；现有 `lim_workflow.py` 仍负责已登记工作流。 | 将工作流定义、持久任务、人工批准与安全恢复打通。 |
| LIM-FR-005 State/Checkpoint | 新增进程内版本快照及可选 Redis 缓存。 | PostgreSQL 持久化、安全恢复和副作用幂等；当前仍未实现生产 checkpoint。 |
| LIM-FR-014 Temporal GraphRAG | 新增带时态字段的示例图谱及检索沙盘。 | 接入真实实体来源、Neo4j、历史版本与授权检索；生产 GraphRAG 未实现。 |
| LIM-FR-015 Memory/Skills Governance | 新增进程内四层记忆、衰减及 Skill 蒸馏沙盘。 | 持久化、来源证据、召回权限及现有 `lim_skills.py` 审批生命周期联通。 |

## G1–G4 实施后状态刷新（2026-10-21）

上表保留为 G0 原始基线。下表按 PRD v1.0 与当前仓库证据刷新，阶段标签不等于生产验收；未列出运行环境/供应商/真实业务口径证据的项目仍为“生产未核验”。

| PRD | 当前仓库状态 | 证据 | 仍缺的关键部分 |
|---|---|---|---|
| LIM-FR-001 租户与角色 | 部分实现/联通/验收 | `security.py`, `lim_scope.py`; `test_lim_scope.py`, `test_lim_api.py` | 无 Tenant 实体/跨租户隔离与 SSO；真实租户安全验证未做。 |
| LIM-FR-002 Agent Registry | 已实现/联通/聚焦验收 | `lim_models.py`, `lim_registry.py`, `lim_routes.py`; LIM Console Agents 页; `test_lim_registry.py`, `test_lim_api.py` | 发布、归档/回滚完整治理及能力标签/模型策略消费未闭环。 |
| LIM-FR-003 Workflow | 部分实现/联通/聚焦验收 | `lim_workflow.py`, `0033_lim_workflow_orchestration.py`; Workflow tab; `test_lim_workflow.py` | 当前单进程同步、无崩溃恢复/多实例 Worker/通用 Dry Run 与可视化 Studio。 |
| LIM-FR-004 Task/Run 生命周期 | 部分实现/联通/验收 | `lim_runtime.py`, `lim_workflow.py`; Run/Task API 与 Trace; LIM runtime/workflow tests | 未覆盖完整等待人工输入、审核、恢复、业务执行/核对状态流。 |
| LIM-FR-005 State/Checkpoint | 未实现（只有摘要快照） | `LimRun.input_summary/output_summary`, Workflow Run summaries | 无版本化 checkpoint、安全恢复和副作用重复执行证明；不得重启恢复。 |
| LIM-FR-006 Tool Registry | 已实现只读治理/联通/聚焦验收 | `LimTool`, `lim_registry.py`, `lim_runtime.py`; Tools tab; `test_lim_registry.py`, `test_lim_runtime.py` | 速率限制执行、发布流程、写工具回执协议尚未启用。 |
| LIM-FR-007 工具权限隔离 | 部分实现/联通/验收 | `lim_scope.py`, handler-level domain permission checks; scope/API tests | 缺统一 actor/store/resource/action policy evaluator 与租户隔离。 |
| LIM-FR-008 Harness 预算 | 部分实现/联通/验收 | `lim_runtime.py` and `lim_workflow.py` enforce tool/task and time limits; runtime/workflow tests | Token/费用预算与模型调用预算不可用；Run-level cost cap 不可验收。 |
| LIM-FR-009 人工审批/命令门禁 | 部分（既有业务审批） | `generation_reviews.py`, `purchase_agent.py`; business tests | LIM 没有绑定 Proposal、配置版本、审批期限和防重放的通用门禁。 |
| LIM-FR-010 幂等/失败核对 | 部分（既有业务局部能力） | `purchase_agent.py`, `after_sales_execution.py`; related tests | LIM 暂不运行写 Tool；通用写协议、外部回读/RECONCILING 未实现。 |
| LIM-FR-011 AI Gateway | 部分（现有模型客户端） | `supply_agent_llm.py`, current Agent modules | 无统一 Model Registry、策略路由、配额、熔断、成本标签、托管密钥/供应商配置。 |
| LIM-FR-012 检索源/元数据 | 部分实现/联通/验收 | `lim_knowledge.py`, migration `0031`; Knowledge tab; `test_lim_knowledge.py` | 当前治理本地 Markdown；ERP 结构化源和其他知识类型需逐源契约与 ACL。 |
| LIM-FR-013 Hybrid/Agentic Retrieval | 部分（真实运行范围内向量+关键词） | `lim_live_connections.py`：Neo4j 余弦向量、关键词排序及 RRF；`GraphEvidenceCanvas.tsx` 显示来源和得分 | 使用本地词元哈希，尚非语义模型；未做跨源动态规划和固定 Golden Dataset 评测。 |
| LIM-FR-014 Temporal GraphRAG | 部分（真实业务证据关系和观察快照） | `lim_live_views.py` 从 ERP Checkpoint 派生实体和业务关系；Neo4j 可检索已授权运行；`0049` 持久化 | 时间依据为观察时间，不代表业务 valid-time；尚无跨运行版本窗口和通用多跳推理，不能标注完整实现。 |
| LIM-FR-015 Memory/Skills Governance | 部分（Skill 治理基础已实现/联通/聚焦验收） | `lim_skills.py`, migration `0034`, Skill Console tab, `test_lim_skills.py`；候选仅收受控模板、引用和范围元数据 | Skill lifecycle 不自动写入长期 Memory/提示词；长期记忆来源、召回权限、校准集及实际使用回执仍缺。 |
| LIM-FR-016 Trace Explorer | 部分实现/联通/验收 | `LimRun/LimSpan/LimToolInvocation`, `lim_workflow.py`; `lim_live_observability.py` 聚合已保存的五领域任务、工具 Span 与证据引用；工作台展示时间线；配置 OTLP 时执行期发送父子 Span | 仍缺模型 span/cost 完整性、跨 Agent 查询过滤、统一 retention controls；外部接收平台须单独验收。 |
| LIM-FR-017 Evaluation Lab | 部分实现/联通/聚焦验收 | 固定数据集与 Agent 版本的离线 Eval；`0050` 与 `lim_live_observability.py` 额外保存真实五领域运行的版本化任务完成率、工具匹配率和已记录安全拦截率，逐项附分子/分母/依据；无生成内容时证据忠实度标为不适用 | 缺真实模型生成内容的忠实度评测、业务结果回收、真实模型固定 Prompt/参数报告和生产发布门禁；不得将步骤完成率称为业务成功率。 |
| LIM-FR-018 Security Regression | 部分实现/聚焦验收 | 新增 `test_lim_security_regression.py`：检索到恶意 Markdown 后，模拟未授权写 Tool 调用仍被服务端 Runtime allowlist 拒绝；Tool 缺参、错类型、额外/伪造范围参数在 handler 前被拒绝；required 幂等键不能开放只读 Runtime 的写调用，相同请求重放无副作用；不同 actor 和撤销 `assistant:read` 后的调用均被拒绝。配合 `test_lim_scope.py`、LIM API/runtime 与 legacy Agent 安全测试 | 当前是隔离 pytest 安全集，不含模型级提示注入执行评测、正式冻结 Security Dataset 及持续报告/发布门禁；生产安全仍未核验。 |
| LIM-FR-019 发布/灰度治理 | 未实现（有定义版本） | Agent/Tool/Knowledge/Workflow version rows | 没有 Release Center、环境发布、评测门禁、灰度、原子回滚和发布审计链。 |
| LIM-FR-020 成本/容量 | 部分实现/本地观测纵切 | `GET /lim/metrics/tool-invocations` aggregates persisted invocation counts/status and non-null local handler elapsed_ms by UTC day, live/sandbox, Agent/Agent version, Tool/Tool version; permission-filtered JSON/CSV export; `test_lim_metrics.py` | 不包含模型/上游端到端指标；token、cost、cache-hit、tenant 明确 unavailable；Sandbox 单独分组且其 mock 零耗时不进入延迟样本；无真实计费、缓存埋点或 tenant 身份映射。 |
| LIM-FR-021 敏感字段/审计 | 部分实现/验收 | `sanitize_trace_value`, `record_audit`, Trace read/export APIs; export re-sanitizes the complete shared Trace payload, emits content-free allowed/denied JSON export audit events, and is downloadable from LIM Console; `test_trace_json_export_is_sanitized_and_audited` | 缺统一字段分类策略、待业务确认的保留/删除期限；导出审计仅记录结果与格式，不包含 Trace 内容。 |
| LIM-FR-022 Sandbox 调试 | 部分实现/联通/聚焦验收 | `lim_sandbox.py`, migration `0035`, `POST /lim/sandbox/runs`, LIM Console Sandbox 仿真按钮, `test_lim_sandbox.py`; schema 子集约束与 scalar 值不持久化 | 应用内无 handler 仿真、空 Scope、固定小预算；不提供容器/进程隔离或生产部署证明，PRD 全量仍未验收。 |
| LIM-FR-023 诊断证据治理 | 部分实现 | `business_evidence_tools.py`, `aggregate_evidence`; workflow tests | 统一 Evidence refs 已有；Finding/Proposal/ExecutionReceipt 及版本与人工审批绑定缺失。 |
| LIM-FR-024 运行异常告警 | 部分实现/联通/聚焦验收 | `lim_alerts.py`、迁移 `0036`、Alerts API 与 Console；运行时/Workflow 产生阈值告警，具备去重、确认、关闭和审计 | 仅本地持久化；同步 Tool 只能在 handler 返回后识别超时，无法中断阻塞调用。邮件/Slack/PagerDuty 与值班链路未配置；未实现成本告警。 |

### 阶段门禁刷新

| 阶段 | 当前交付 | 仍未通过的 PRD 门槛 |
|---|---|---|
| G0 盘点 | FR-001–024 基线和实施后证据/缺口矩阵 | 仍为静态代码盘点；真实环境安全、容量和生产性未验证。 |
| G1 Runtime/Harness | Agent/Tool registry、server BusinessScope、只读 Run/Trace、基础 Eval | 双 Agent 统一业务行为和完整 token/cost/checkpoint 预算未达成；无生产验收。 |
| G2 知识与纵切 | 固定白名单知识源、内容哈希版本、审核激活、ACL 词面检索 | 无 Hybrid/GraphRAG；没有产品标注的 Golden Dataset 门槛结果。 |
| G3 协作编排 | 固定版本 DAG、bounded parallelism、子 Trace 和证据冲突分类 | 不具备重启恢复、多实例 worker、模型 planner/Proposal 审批绑定。 |
| G4 扩展治理 | OMS 本地只读对账准备；LIM Skill 受控治理基础与 Mock Sandbox 已实现 | Temporal GraphRAG、长期 Memory 读写/召回、生产 AI Gateway、Release Center 和生产通知/值班链路仍未完成；告警仅有本地最小闭环。GraphRAG 依赖业务 Owner 数据口径，Gateway/发布依赖生产配置及治理事实。 |

## 阶段门禁现状

| 阶段 | 当前证据 | 判定 |
|---|---|---|
| G0 盘点 | 本文对代码、迁移和测试建立基线；现存能力矩阵以前缺少 LIM FR 级状态记录 | 本盘点完成后可进入 G1 基础建设；线上联通与生产状态仍待环境验证 |
| G1 Runtime/Harness | 有采购 Run/ToolCall、商品/运营只读查询和局部权限校验；没有统一注册、运行、Scope、Trace、Eval 契约 | 未通过 |
| G2 知识与纵切 | 有本地文档关键词查询和 Listing 事实草稿；无政策版本治理及 Golden Dataset | 未通过 |
| G3 协作编排 | 有多个专业 Agent，但没有 Orchestrator 或可重放 DAG | 未通过 |
| G4 扩展治理 | 有 Skill 生命周期基础、应用内 Sandbox 和 LIM 本地告警；无 Temporal GraphRAG/长期 Memory/完整 Gateway/生产通知 | 未通过；本地子能力已交付，PRD 生产门槛仍待验收 |

## 复用与实施决策

- 复用现有 `current_user`、`require`、`role_for`、`require_scope`、`record_audit` 和 ERP 会话；LIM 不自建认证/权限旁路。
- 采购 `AgentRun`、`AgentToolCall` 仅作为现有实现证据，不作为通用 LIM 表直接扩展：其字段绑定 SKU、店铺、仓库、草稿及采购审批，无法表达通用 Agent、Trace parent/span、统一状态、评测报告；新增 lim 专属表并保留来源关联，不迁移、不删除采购历史。
- 商品和运营查询函数是可复用的只读适配器候选；当前 LLM 循环各自实现，尚未接入同一 Runtime/Trace。先封装显式已知函数映射，禁止动态导入或客户端可控 Python callable。
- 生产状态、真实模型部署/密钥管理、SSO、租户隔离、数据留存期限、数据脱敏效果及容量均无本地静态证据，必须在对应环境验收后才能升级状态。

## 验收与未核实事项

此盘点是静态仓库核验，不代替 PRD 的权限故障注入、部署审计和真实生产验证。现有测试命令为 `backend/.venv/Scripts/python.exe -m pytest`；基线运行结果记录在本计划的 SDD ledger。接下来 G1 需为 LIM 专属模型/API/页面新增可复现测试，并至少将商品与运营两个只读适配器纳入同一 Scope 和 Trace 外壳。
