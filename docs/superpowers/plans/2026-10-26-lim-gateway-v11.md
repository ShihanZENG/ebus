# LIM 网关 V1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在现有网关补齐调用记录隔离、共享限流与配额、有限容错、可解释的观测。

**Architecture:** 保留 FastAPI、SQLAlchemy 与 completion 对外签名；治理独立模块，Redis 原子脚本实现共享准入，本地内存模式明确标注仅单进程。调用仍是一条最终记录，增加场景与脱敏的 attempts 明细；HTTP 使用可取消异步传输，由同步入口适配。

**Tech Stack:** Python / FastAPI / Pydantic / SQLAlchemy / httpx / redis-py / React。

**Spec:** 本聊天已确认的 V1.1：权限、限流配额、故障恢复、观测贯通；缓存和写工具执行隔离不在本次。

## Global Constraints
- 已有业务 completion 返回协议和 MODEL_* 错误码保留；不存提示词、密钥和供应商响应正文。
- 保留工作区已有修改，在当前 checkout 实施，只修改本轮文件，不自动提交混合工作区。
- 未配置 Redis 时使用单进程模式；配置 Redis 后故障必须拒绝准入，不能暗中退回内存。
- Token 配额是保守预留预算，不宣称精确计费；用量未知的已发送尝试保留预留额。
- 默认每用户每分钟 60 次、同时 3 次、每日预算 1000000 Token；最多 2 次模型尝试，熔断阈值 3 次、冷却 30 秒；配置必须有界。
- 缓存、价格计算、多租户、通用工具强制终止延后；不将未实现指标显示为零。

## Review Focus
- 多个并发请求共享配额，不超卖；释放只能释放自己的租约。
- Redis 断连及无身份内部调用不能绕过治理。
- 非重试错误不切换；停用模型永不被备用策略重新启用。
- 请求总超时包含所有网络尝试与退避；超时传输必须取消。
- 调用日志及统计一致过滤身份，未知用量不冒充零，审计失败明确记录脱敏告警。

### Task 1: 权限与指标
Files: backend/app/lim_routes.py, backend/app/lim_gateway_metrics.py, backend/tests/test_gateway_governance.py
- [x] 添加真实 API 测试：普通身份只看自身调用，管理员看全部，统计同范围，未知用量单独计数。
- [x] 运行测试确认缺口；实现共享过滤函数及 /model-metrics 聚合。
- [x] 验证旧接口兼容，不修改既有工具指标含义。

### Task 2: 原子治理
Files: backend/app/lim_governance.py, backend/tests/test_lim_governance.py, backend/requirements.txt, backend/compose.yaml, backend/.env.example
Interface: acquire(actor_id, reservation, lease_seconds) -> lease; settle(lease, charged_tokens); circuit_allowed/key success/failure。
- [x] 先测配额并发、并发租约释放、窗口过期、存储失败和熔断。
- [x] 实现内存与 Redis 等价的原子状态机，配置校验及脱敏错误。
- [x] 真实 Redis 脚本测试；添加部署说明。

### Task 3: 路由容错和调用观测
Files: backend/app/lim_model_gateway.py, backend/app/lim_models.py, backend/migrations/versions/0047_lim_gateway_governance.py, backend/tests/test_gateway_resilience.py
Interface: complete 保持原签名；resolve 保留首选路由接口；新增候选集合与 attempts 记录。
- [x] 先测主模型 503 后备用成功、401 不重试、总期限取消、熔断跳过、配额拒绝不发请求。
- [x] 实现最多两次尝试、同模型退避重试/备用、共享熔断、每日预算预留结算、父调用审计。
- [x] 验证旧模型网关用例与迁移，审计故障记录结构化日志而不泄露异常正文。

### Task 4: 可见交付与验证
Files: frontend/src/api/lim.ts, frontend/src/pages/LimConsolePage.tsx, docs/LIM网关V1.1运行说明.md
- [x] 界面显示当前治理模式、限额、模型汇总及尝试次数；管理操作按已有权限隐藏。
- [x] 运行 LIM 与业务模型相关回归、前端构建和现有测试；独立审查本轮改动。
- [x] 记录实际验证结果、部署前提、尚未实施能力。

## Ledger
- 2026-10-26：用户已授权开始优化；沿用当前工作区，避免新 checkout 遗漏已有迁移及业务改动。不再次请求计划审批。
- 基线：上轮相关测试 28 passed；现存 storefront / navigation 修改不属于本轮。
- 2026-10-26：TDD 首轮复现权限隔离、限流、路由优先级、未知用量和熔断窗口缺口后逐项修复；独立审查确认的两项 P2 已修复并由回归覆盖。
- 验证：网关及治理专项 24 passed；全后端首轮 346 passed / 8 skipped / 1 failed，唯一失败为新增用例误用了 `detail` 响应格式；改为项目统一 `error.code` / `error.message` 后，专项包含该用例再次全部通过。依赖当前时间生成节点 ID 的 order_time_backfill 另行串行 30 passed。前端构建成功（原有 bundle size warning），前端测试 25 passed。没有为仅改变测试断言重复耗费整套约 20 分钟回归。
- 独立审查：发现熔断过滤后错误索引会跳过下一路由，以及成功 fallback 会隐藏此前未知用量；已测试修复。内存熔断失败状态过期差异同时补齐。
- 部署：已先备份本机 `127.0.0.1:15432/erp`，再启用本机 compose Redis、追加 `.env` 的 Redis 地址、应用迁移 0047 并重启本地后端。`/ready` 返回 0047，Redis healthcheck healthy，管理员鉴权访问 `/model-metrics` 和 `/model-calls` 均为 200，模式为 redis。全程未发起模型调用。
- 边界：模型尝试截止时间没有覆盖数据库结算及独立事务审计写入，说明中已明确。
