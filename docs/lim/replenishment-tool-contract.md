# LIM 补货证据 Tool 接入契约

经营端补货证据页面复用 LIM Runtime 的固定版本只读 Run，不自建 Agent 调度或采购写入能力。

## 受控服务端适配器

- Tool：`erp.replenishment.evidence`，版本 `1.0.0`，只读、低风险。
- 参数：`profile_id` 和 `business_date`。
- 适配器：`backend/app/lim_replenishment.py`。
- 复用业务服务：`supply_agent.profile_get`、`collect_evidence`、`calculate_supply`。
- 只有证据无阻断项时才运行规则测算；证据哈希、阻断项、快照与结果写入脱敏 Trace。
- 除 `assistant:read` 外，服务端还要求 `purchase_agent:read`，并继续执行店铺/仓库范围校验。
- 不创建草稿、不审批、不调用外部服务。

## 管理员注册

在 LIM 运行治理页面按以下顺序粘贴 JSON 创建 Tool 草稿、校验 Tool，再创建并校验 Agent：

```json
{
  "tool_id": "erp.replenishment.evidence",
  "version": "1.0.0",
  "service": "erp.supply_agent",
  "domain": "replenishment",
  "operation_kind": "read",
  "risk_tier": "low",
  "timeout_ms": 30000,
  "idempotency_mode": "not_applicable",
  "scope_policy": {"shop": "server_scope", "warehouse": "server_scope"},
  "input_schema": {
    "type": "object",
    "properties": {"profile_id": {"type": "string"}, "business_date": {"type": "string"}},
    "required": ["profile_id", "business_date"],
    "additionalProperties": false
  },
  "output_schema": {
    "type": "object",
    "properties": {"source": {"type": "string"}, "profile_id": {"type": "string"}, "business_date": {"type": "string"}, "evidence_hash": {"type": "string"}, "blockers": {"type": "array"}, "evidence": {"type": "object"}, "calculation": {"type": "object"}},
    "required": ["source", "profile_id", "business_date", "evidence_hash", "blockers", "evidence", "calculation"],
    "additionalProperties": false
  }
}
```

```json
{
  "agent_id": "erp.replenishment",
  "version": "1.0.0",
  "display_name": "补货证据采集",
  "business_domain": "replenishment",
  "description": "按授权的补货配置采集 ERP 证据并运行确定性测算，不创建采购草稿。",
  "capability_tags": ["replenishment", "evidence", "read_only"],
  "input_schema": {
    "type": "object",
    "properties": {"profile_id": {"type": "string"}, "business_date": {"type": "string"}},
    "required": ["profile_id", "business_date"],
    "additionalProperties": false
  },
  "output_schema": {
    "type": "object",
    "properties": {"evidence_hash": {"type": "string"}, "blockers": {"type": "array"}},
    "required": ["evidence_hash", "blockers"],
    "additionalProperties": false
  },
  "allowed_tools": ["erp.replenishment.evidence"],
  "risk_tier": "low",
  "runtime_profile": "read_only"
}
```

## API 路径

管理台通过 `GET /api/v1/lim/agents`、`GET /api/v1/lim/agents/{agent_id}/tools?version=1.0.0` 获取已验证版本；启动时使用 `POST /api/v1/lim/runs`，参数为 `{profile_id, business_date}`；Trace 使用 `GET /api/v1/lim/traces/{trace_id}`。

## 后续采购流

此 Run 是只读分析记录。采购建议/草稿仍须回到现有采购 Agent 工作台重新读取当前数据，并按既有草稿审批流程办理。
