import { request, requestBlob } from './client'

export type PageResult<T> = { items: T[]; total: number; page: number; page_size: number }
export type LimAgent = { agent_id: string; version: string; display_name: string; business_domain: string; status: string; definition: Record<string, unknown> }
export type LimTool = { tool_id: string; version: string; service: string; domain: string; operation_kind: string; risk_tier: string; status: string; created_at: string }
export type LimRun = { run_id: string; trace_id: string; agent_id: string; agent_version: string; goal_summary: string; status: string; execution_mode?: 'live' | 'sandbox'; output_summary?: Record<string, unknown>; budget?: Record<string, unknown>; error_code?: string | null }
export type LimToolInvocationMetric = {
  day: string; execution_mode: 'live' | 'sandbox'; agent_id: string; agent_version: string
  tool_id: string; tool_version: string; invocation_count: number; handler_call_count: number
  status_counts: Record<'PENDING' | 'SUCCEEDED' | 'FAILED' | 'TIMEOUT' | 'BLOCKED', number>
  latency_sample_count: number
  latency_ms: { min: number | null; max: number | null; mean: number | null; p50: number | null; p95: number | null }
}
export type LimToolInvocationMetrics = {
  date_from: string; date_to: string; timezone: 'UTC'; items: LimToolInvocationMetric[]
  unavailable_metrics: { token_usage: 'unavailable'; cost: 'unavailable'; cache_hit: 'unavailable'; tenant: 'unavailable' }
}
export type EvalDataset = { dataset_id: string; version: string; name: string; description: string; status: string; cases: Array<{ case_id: string }> }
export type EvalReport = { eval_run_id: string; dataset_id: string; dataset_version: string; agent_id: string; agent_version: string; status: string; metrics: Record<string, unknown>; cases: Array<{ case_id: string; outcome: string; failures: string[] }> }
export type EvalComparison = { comparison_id: string; status: string; report_hash: string; integrity_valid: boolean; baseline: { eval_run_id: string; dataset_id: string; dataset_version: string; agent_id: string; agent_version: string; environment: string; metrics: Record<string, unknown> }; candidate: { eval_run_id: string; agent_version: string; metrics: Record<string, unknown> }; thresholds: Record<string, number>; summary: { pass_rate_drop: number | null; regressions: number; improvements: number; critical_case_regressions: number; baseline_average_elapsed_ms: number | null; candidate_average_elapsed_ms: number | null; threshold_checks: Record<string, boolean> }; cases: Array<{ case_id: string; risk_tier: string; baseline_outcome: string; candidate_outcome: string; classification: string; baseline_failures: string[]; candidate_failures: string[]; output_changes: Array<{ path: string; baseline: unknown; candidate: unknown }>; baseline_trace_id: string | null; candidate_trace_id: string | null }> }
export type EvalRunOption = Pick<EvalReport, 'eval_run_id' | 'dataset_id' | 'dataset_version' | 'agent_id' | 'agent_version' | 'status'> & { environment: string; actor_id: string }
export type KnowledgeSource = { source_id: string; path: string; display_name: string; category: string; summary: string; required_permissions: string[]; is_present: boolean; is_archived: boolean; active_version: { version: string; status: string } | null }
export type KnowledgeVersion = { version: string; status: string; content_hash: string; created_at: string; valid_from?: string | null; valid_until?: string | null; reviewed_at?: string | null; diff_summary?: { added_chunks: number; removed_chunks: number; unchanged_chunks: number; compared_to: string | null } }
export type LimWorkflowVersion = { workflow_id: string; version: string; status: string; definition: Record<string, unknown>; created_at?: string }
export type LimWorkflow = { workflow_id: string; display_name: string; business_domain: string; status: string; versions: LimWorkflowVersion[] }
export type LimAlert = { alert_id: string; rule_key: string; entity_key: string; entity_label: string; severity: string; status: 'OPEN' | 'ACKNOWLEDGED' | 'CLOSED'; summary: string; error_code: string; occurrence_count: number; first_seen_at: string; last_seen_at: string; actor_id: string; agent_id: string | null; tool_id: string | null; workflow_id: string | null; run_id: string | null; trace_id: string | null; workflow_run_id: string | null; acknowledged_at: string | null; closed_at: string | null }
export type LimAlertRule = { rule_key: string; display_name: string; dimension: string; enabled: boolean; threshold: number; window_seconds: number }
export type LimSkillVersion = { skill_id: string; version: string; display_name: string; owner_id: string | null; memory_level: string; definition: Record<string, unknown>; source_event: string; evidence_refs: unknown[]; business_scope: Record<string, unknown>; last_verified_at: string | null; confidence_calibration: Record<string, unknown>; usage_count: number; correction_count: number; expiry_policy: Record<string, unknown>; status: string; runtime_enabled: false; created_at: string }

export type LimModelProvider = { provider_id: string; name: string; protocol: string; base_url: string; api_key_env: string; enabled: boolean; priority: number; timeout_ms: number; status: string }
export type LimModelCatalogEntry = { alias_id: string; alias: string; provider_id: string; model_name: string; scene: string; enabled: boolean; priority: number }
export type LimModelCallRecord = { call_id: string; created_at: string; provider_id: string; model: string; status: string; error_code: string | null; latency_ms: number | null; prompt_tokens: number | null; completion_tokens: number | null; total_tokens: number | null; run_id: string | null }
export type ProviderTestResult = { ok: boolean; status_code?: number; latency_ms?: number; model?: string; reply_preview?: string; usage?: Record<string, unknown>; error?: string }
export type LimSafetyOverview = {
  generated_at: string
  runtime: {
    stage: 'read_only'
    live_write_execution: boolean
    read_tool_allowlist: string[]
    active_registered_tools: { read: number; write: number }
    write_tool_policy: string
    sandbox: { payload_limit_kib: number; budget: Record<string, number>; scalar_values_not_persisted: boolean }
  }
  run_budget_defaults: Record<string, number>
  schema_validation: { enforced: boolean; types: string[]; checks: string[] }
  redaction: { enabled: boolean; secret_key_pattern: string; pii_key_pattern: string; masking: Record<string, string>; limits: Record<string, number> }
  identity_and_scope: { runtime_permission: string; manage_permission: string; scope_model: string; tenant_isolation: string }
  state_machine: { states: string[]; terminal_states: string[] }
  audit: Array<{ resource: string; action: string; record_id: string | null; actor_id: string | null; created_at: string | null }>
  known_limits: string[]
}

export const limApi = {
  agents: () => request<PageResult<LimAgent>>('/lim/agents'),
  agentTools: (agentId: string, version: string, includeWrite = false) => request<{ agent_id: string; agent_version: string; items: LimTool[] }>(`/lim/agents/${encodeURIComponent(agentId)}/tools`, { params: { version, include_write: includeWrite } }),
  tools: () => request<PageResult<LimTool>>('/lim/tools', { params: { page_size: 100 } }),
  runs: () => request<PageResult<LimRun>>('/lim/runs'),
  datasets: () => request<PageResult<EvalDataset>>('/lim/evals/datasets'),
  createAgent: (body: unknown) => request<LimAgent>('/lim/agents', { method: 'POST', body }),
  createTool: (body: unknown) => request<LimTool>('/lim/tools', { method: 'POST', body }),
  validateAgent: (id: string, version: string) => request<{ valid: boolean; issues: Array<{ code: string; message: string }> }>(`/lim/agents/${encodeURIComponent(id)}/validate`, { method: 'POST', params: { version } }),
  validateTool: (id: string, version: string) => request<{ valid: boolean; issues: Array<{ code: string; message: string }> }>(`/lim/tools/${encodeURIComponent(id)}/validate`, { method: 'POST', params: { version } }),
  run: (body: unknown) => request<LimRun>('/lim/runs', { method: 'POST', body }),
  sandboxRun: (body: unknown) => request<LimRun>('/lim/sandbox/runs', { method: 'POST', body }),
  trace: (id: string) => request<Record<string, unknown>>(`/lim/traces/${encodeURIComponent(id)}`),
  exportTrace: (id: string) => requestBlob(`/lim/traces/${encodeURIComponent(id)}/export`),
  toolInvocationMetrics: (dateFrom: string, dateTo: string) => request<LimToolInvocationMetrics>('/lim/metrics/tool-invocations', { params: { date_from: dateFrom, date_to: dateTo } }),
  exportToolInvocationMetrics: (dateFrom: string, dateTo: string, format: 'json' | 'csv') => requestBlob('/lim/metrics/tool-invocations/export', { date_from: dateFrom, date_to: dateTo, format }),
  createDataset: (body: unknown) => request<EvalDataset>('/lim/evals/datasets', { method: 'POST', body }),
  evaluate: (body: unknown) => request<EvalReport>('/lim/evals/runs', { method: 'POST', body }),
  evalRuns: () => request<PageResult<EvalRunOption>>('/lim/evals/runs', { params: { page_size: 100 } }),
  compareEvals: (body: unknown) => request<EvalComparison>('/lim/evals/comparisons', { method: 'POST', body }),
  evalComparisons: () => request<PageResult<EvalComparison>>('/lim/evals/comparisons', { params: { page_size: 100 } }),
  knowledgeSources: () => request<PageResult<KnowledgeSource>>('/lim/knowledge/sources', { params: { page_size: 100 } }),
  syncKnowledge: () => request<Record<string, number>>('/lim/knowledge/sync', { method: 'POST' }),
  patchKnowledgeSource: (id: string, body: unknown) => request<KnowledgeSource>(`/lim/knowledge/sources/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
  knowledgeVersions: (id: string) => request<{ items: KnowledgeVersion[] }>(`/lim/knowledge/sources/${encodeURIComponent(id)}/versions`),
  activateKnowledgeVersion: (id: string, version: string, body: unknown) => request<Record<string, string>>(`/lim/knowledge/sources/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}/activate`, { method: 'POST', body }),
  archiveKnowledgeVersion: (id: string, version: string) => request<Record<string, string>>(`/lim/knowledge/sources/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}/archive`, { method: 'POST' }),
  archiveKnowledgeSource: (id: string) => request<KnowledgeSource>(`/lim/knowledge/sources/${encodeURIComponent(id)}/archive`, { method: 'POST' }),
  searchKnowledge: (query: string) => request<Record<string, unknown>>('/lim/knowledge/search', { method: 'POST', body: { query } }),
  workflows: () => request<PageResult<LimWorkflow>>('/lim/workflows'),
  createWorkflow: (body: unknown) => request<LimWorkflowVersion>('/lim/workflows', { method: 'POST', body }),
  validateWorkflow: (id: string, version: string) => request<{ valid: boolean; issues: Array<{ code: string; message: string }> }>(`/lim/workflows/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}/validate`, { method: 'POST' }),
  runWorkflow: (body: unknown) => request<Record<string, unknown>>('/lim/workflow-runs', { method: 'POST', body }),
  workflowRun: (id: string) => request<Record<string, unknown>>(`/lim/workflow-runs/${encodeURIComponent(id)}`),
  workflowTrace: (id: string) => request<Record<string, unknown>>(`/lim/workflow-runs/${encodeURIComponent(id)}/trace`),
  cancelWorkflowRun: (id: string) => request<Record<string, unknown>>(`/lim/workflow-runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  alerts: (status?: string) => request<PageResult<LimAlert>>('/lim/alerts', { params: status ? { status, page_size: 100 } : { page_size: 100 } }),
  alertRules: () => request<{ items: LimAlertRule[] }>('/lim/alerts/rules'),
  updateAlertRule: (key: string, body: Partial<Pick<LimAlertRule, 'enabled' | 'threshold' | 'window_seconds'>>) => request<LimAlertRule>(`/lim/alerts/rules/${encodeURIComponent(key)}`, { method: 'PUT', body }),
  acknowledgeAlert: (id: string) => request<LimAlert>(`/lim/alerts/${encodeURIComponent(id)}/acknowledge`, { method: 'POST' }),
  closeAlert: (id: string) => request<LimAlert>(`/lim/alerts/${encodeURIComponent(id)}/close`, { method: 'POST' }),
  skills: () => request<PageResult<LimSkillVersion>>('/lim/skills', { params: { page_size: 100 } }),
  createSkill: (body: unknown) => request<LimSkillVersion>('/lim/skills', { method: 'POST', body }),
  updateSkillCandidate: (id: string, version: string, body: unknown) => request<LimSkillVersion>(`/lim/skills/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}`, { method: 'PUT', body }),
  skillVersions: (id: string) => request<{ items: LimSkillVersion[] }>(`/lim/skills/${encodeURIComponent(id)}/versions`),
  transitionSkill: (id: string, version: string, body: { target_status: string; rationale: string }) => request<LimSkillVersion>(`/lim/skills/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}/transition`, { method: 'POST', body }),
  modelProviders: () => request<{ items: LimModelProvider[] }>('/lim/model-providers'),
  createModelProvider: (body: unknown) => request<LimModelProvider>('/lim/model-providers', { method: 'POST', body }),
  updateModelProvider: (id: string, body: unknown) => request<LimModelProvider>(`/lim/model-providers/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
  testModelProvider: (body: unknown) => request<ProviderTestResult>('/lim/model-providers/test', { method: 'POST', body }),
  modelCatalogs: () => request<{ items: LimModelCatalogEntry[] }>('/lim/model-catalogs'),
  createModelCatalog: (body: unknown) => request<LimModelCatalogEntry>('/lim/model-catalogs', { method: 'POST', body }),
  updateModelCatalog: (id: string, body: unknown) => request<LimModelCatalogEntry>(`/lim/model-catalogs/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
  disableModelCatalog: (id: string) => request<void>(`/lim/model-catalogs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  modelCalls: () => request<PageResult<LimModelCallRecord>>('/lim/model-calls', { params: { page_size: 50 } }),
  approveRun: (id: string) => request<LimRun>(`/lim/runs/${encodeURIComponent(id)}/approve`, { method: 'POST' }),
  rejectRun: (id: string, reason?: string) => request<LimRun>(`/lim/runs/${encodeURIComponent(id)}/reject`, { method: 'POST', params: reason ? { reason } : {} }),
  safetyOverview: () => request<LimSafetyOverview>('/lim/safety/overview'),
}
