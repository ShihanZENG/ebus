# LIM Trace 访问审计实施计划

## 目标

补齐 LIM-FR-021 中 Trace 读取缺少访问审计的本地缺口。复用现有 `AuditLog`，不新增表或保留期限策略。

## 范围与验收

- `GET /api/v1/lim/traces/{trace_id}` 成功返回时记录 `lim_traces` / `read` / `allowed`。
- 已认证且有 `assistant:read` 的用户因 Trace 不存在或不在可见范围而收到 404 时，记录 `lim_traces` / `read` / `denied`，不暴露 Trace 是否存在。
- 审计事件仅存 actor、请求 Trace ID 引用和结果，不存 Span、工具参数/响应、PII 或密钥。
- 自动化 API 测试验证允许读取、越权拒绝、审计事件落库和元数据不含 Trace 内容。
- 不改变认证依赖拒绝（401/403）的审计行为；不设保留期或删除策略，具体期限仍待业务确认。

## 实施步骤

1. 先添加 API 回归测试并确认当前实现失败。
2. 在 Trace 读取路由中记录并提交允许/拒绝事件，复用 `record_audit`。
3. 更新 LIM FR-021 能力盘点，运行 API 与 LIM 回归、`git diff --check`，并进行只读代码复核。
