import ModelGatewayOverview from '../components/ModelGatewayOverview'
import DiagnosisSection from '../components/DiagnosisSection'
import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Input, InputNumber, Modal, Select, Space, Switch, Table, Tabs, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import ModelGatewayPlayground from '../components/ModelGatewayPlayground'
import { limApi, type EvalComparison, type EvalDataset, type EvalReport, type EvalRunOption, type KnowledgeSource, type KnowledgeVersion, type LimAgent, type LimAlert, type LimAlertRule, type LimRun, type LimSkillVersion, type LimSafetyOverview, type LimTool, type LimModelCallRecord, type LimModelCatalogEntry, type LimModelProvider, type LimToolInvocationMetric, type LimWorkflow } from '../api/lim'

const pretty = (value: unknown) => JSON.stringify(value, null, 2)
const parse = (value: string) => JSON.parse(value) as unknown
const utcDateOffset = (days: number) => {
  const value = new Date()
  value.setUTCDate(value.getUTCDate() + days)
  return value.toISOString().slice(0, 10)
}

type LimSection = 'overview' | 'agentRuntime' | 'toolRegistry' | 'workflow' | 'runs' | 'alerts' | 'eval' | 'knowledge' | 'skills' | 'modelGateway' | 'security' | 'diagnosis'

type DagTask = {
  node_id: string
  type?: string
  tool_id?: string
  depends_on?: string[]
}

function WorkflowDag({ tasks, statusMap }: { tasks: DagTask[]; statusMap?: Record<string, string> }) {
  if (!tasks || tasks.length === 0) return <div style={{ color: '#9aa3b2', fontSize: 13 }}>该版本暂无 DAG 定义（definition.tasks 为空）</div>
  const byId: Record<string, DagTask> = {}
  tasks.forEach((t) => { byId[t.node_id] = t })
  const depth: Record<string, number> = {}
  const getDepth = (id: string, seen: Set<string>): number => {
    if (depth[id] !== undefined) return depth[id]
    if (seen.has(id)) return 0
    seen.add(id)
    const deps = byId[id]?.depends_on || []
    const d = deps.length ? 1 + Math.max(...deps.map((dep) => getDepth(dep, seen))) : 0
    depth[id] = d
    return d
  }
  tasks.forEach((t) => getDepth(t.node_id, new Set()))
  const maxDepth = Math.max(...Object.values(depth))
  const cols: Record<number, string[]> = {}
  tasks.forEach((t) => { const d = depth[t.node_id]; if (!cols[d]) cols[d] = []; cols[d].push(t.node_id) })
  const maxRows = Math.max(...Object.values(cols).map((c) => c.length))
  const colW = 210, rowH = 92, padX = 30, padY = 30, nodeW = 168, nodeH = 54
  const pos: Record<string, { x: number; y: number }> = {}
  Object.keys(cols).forEach((dk) => {
    const d = Number(dk); const ids = cols[d]
    ids.forEach((id, i) => { pos[id] = { x: padX + d * colW, y: padY + i * rowH + ((maxRows - ids.length) * rowH) / 2 } })
  })
  const svgW = padX * 2 + (maxDepth + 1) * colW
  const svgH = padY * 2 + maxRows * rowH
  const colorFor = (id: string) => {
    const st = statusMap?.[id]
    if (st === 'SUCCEEDED' || st === 'success') return { fill: '#EAF3DE', stroke: '#3B6D11' }
    if (st === 'FAILED' || st === 'error') return { fill: '#FCEBEB', stroke: '#A32D2D' }
    if (st === 'RUNNING' || st === 'PENDING' || st === 'pending') return { fill: '#E6F1FB', stroke: '#185FA5' }
    return byId[id]?.type === 'join' ? { fill: '#F3F0FB', stroke: '#534AB7' } : { fill: '#E6F1FB', stroke: '#185FA5' }
  }
  return (
    <svg viewBox={`0 0 ${svgW} ${svgH}`} width="100%" style={{ maxHeight: 380 }}>
      <defs>
        <marker id="dagArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M2 1L8 5L2 9" fill="none" stroke="#5F5E5A" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </marker>
      </defs>
      {tasks.flatMap((t) => (t.depends_on || []).map((dep) => {
        const a = pos[dep]; const b = pos[t.node_id]
        if (!a || !b) return null
        return <line key={`${dep}->${t.node_id}`} x1={a.x + nodeW} y1={a.y + nodeH / 2} x2={b.x} y2={b.y + nodeH / 2} stroke="#5F5E5A" strokeWidth={1.5} markerEnd="url(#dagArrow)" />
      }))}
      {tasks.map((t) => {
        const p = pos[t.node_id]; const c = colorFor(t.node_id)
        return (
          <g key={t.node_id}>
            <rect x={p.x} y={p.y} width={nodeW} height={nodeH} rx={8} fill={c.fill} stroke={c.stroke} strokeWidth={0.5} />
            <text x={p.x + nodeW / 2} y={p.y + 21} textAnchor="middle" fontSize={12} fontWeight={500} fill={c.stroke}>{t.node_id}</text>
            <text x={p.x + nodeW / 2} y={p.y + 39} textAnchor="middle" fontSize={10} fill="#6b7280">{t.type === 'join' ? 'join 节点' : (t.tool_id || 'tool_call')}</text>
          </g>
        )
      })}
    </svg>
  )
}
type LimTraceSpan = { span_id: string; parent_span_id?: string | null; name: string; kind: string; status: string; attributes?: Record<string, unknown>; error_type?: string | null; error_code?: string | null; started_at?: string | null; ended_at?: string | null }
type LimTraceInvocation = { invocation_id: string; span_id: string; tool_id: string; tool_version: string; status: string; read_only: boolean; arguments_summary?: unknown; response_summary?: unknown; evidence_refs?: unknown[]; error_code?: string | null; elapsed_ms?: number | null }
type LimTraceData = { run_id: string; trace_id: string; execution_mode: 'live' | 'sandbox'; spans: LimTraceSpan[]; tool_invocations: LimTraceInvocation[] }

const LIM_SECTION_ROUTES: Record<LimSection, string> = {
  overview: 'lim-console', agentRuntime: 'lim-agent-runtime', toolRegistry: 'lim-tool-registry', workflow: 'lim-workflow', runs: 'lim-runs',
  alerts: 'lim-alerts', eval: 'lim-eval', knowledge: 'lim-knowledge', skills: 'lim-skills', modelGateway: 'lim-model-gateway', security: 'lim-safety', diagnosis: 'lim-diagnosis',
}

export default function LimConsolePage({ section = 'overview' }: { section?: LimSection }) {
  const navigate = useNavigate()
  const { user } = useAuth()
  const canManageAlerts = user?.role === 'admin' || Boolean(user?.permissions.includes('lim:manage'))
  const [agents, setAgents] = useState<LimAgent[]>([])
  const [tools, setTools] = useState<LimTool[]>([])
  const [agentTools, setAgentTools] = useState<LimTool[]>([])
  const [runs, setRuns] = useState<LimRun[]>([])
  const [selectedRun, setSelectedRun] = useState<LimRun>()
  const [traceData, setTraceData] = useState<LimTraceData>()
  const [selectedSpanId, setSelectedSpanId] = useState<string>()
  const [traceSearch, setTraceSearch] = useState('')
  const [traceMode, setTraceMode] = useState('all')
  const [traceBusy, setTraceBusy] = useState(false)
  const [toolMetrics, setToolMetrics] = useState<Awaited<ReturnType<typeof limApi.toolInvocationMetrics>> | null>(null)
  const [toolMetricsFrom, setToolMetricsFrom] = useState(() => utcDateOffset(-6))
  const [toolMetricsTo, setToolMetricsTo] = useState(() => utcDateOffset(0))
  const [toolMetricsBusy, setToolMetricsBusy] = useState(false)
  const [datasets, setDatasets] = useState<EvalDataset[]>([])
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState<{ title: string; value: unknown; traceId?: string } | null>(null)
  const [report, setReport] = useState<EvalReport | null>(null)
  const [evalRunOptions, setEvalRunOptions] = useState<EvalRunOption[]>([])
  const [baselineEvalRunId, setBaselineEvalRunId] = useState<string>()
  const [candidateEvalRunId, setCandidateEvalRunId] = useState<string>()
  const [comparison, setComparison] = useState<EvalComparison | null>(null)
  const [comparisonThresholds, setComparisonThresholds] = useState({ max_pass_rate_drop: 0, max_case_regressions: 0, max_critical_case_regressions: 0 })
  const [agentVersionKey, setAgentVersionKey] = useState<string>()
  const [toolVersionKey, setToolVersionKey] = useState<string>()
  const [goal, setGoal] = useState('查询业务数据')
  const [args, setArgs] = useState('{}')
  const [runAuto, setRunAuto] = useState(false)
  const [gwProviders, setGwProviders] = useState<LimModelProvider[]>([])
  const [gwCatalogs, setGwCatalogs] = useState<LimModelCatalogEntry[]>([])
  const [gwCalls, setGwCalls] = useState<LimModelCallRecord[]>([])
  const [gwMetrics, setGwMetrics] = useState<Awaited<ReturnType<typeof limApi.modelMetrics>> | null>(null)
  const [gwBusy, setGwBusy] = useState(false)
  const [gwTestResult, setGwTestResult] = useState<Record<string, unknown> | null>(null)
  const [safetyOverview, setSafetyOverview] = useState<LimSafetyOverview | null>(null)
  const [datasetVersionKey, setDatasetVersionKey] = useState<string>()
  const [knowledge, setKnowledge] = useState<KnowledgeSource[]>([])
  const [knowledgeBusy, setKnowledgeBusy] = useState(false)
  const [knowledgeQuery, setKnowledgeQuery] = useState('')
  const [knowledgeResult, setKnowledgeResult] = useState<unknown>()
  const [workflows, setWorkflows] = useState<LimWorkflow[]>([])
  const [skills, setSkills] = useState<LimSkillVersion[]>([])
  const [alerts, setAlerts] = useState<LimAlert[]>([])
  const [alertRules, setAlertRules] = useState<LimAlertRule[]>([])
  const [workflowResult, setWorkflowResult] = useState<Record<string, unknown> | null>(null)
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null)
  const [runTasks, setRunTasks] = useState<Array<{ node_id: string; status?: string }>>([])
  const selectedWorkflow = workflows.find((w) => w.workflow_id === selectedWorkflowId) || null
  const selectedAgent = agents.find((agent) => `${agent.agent_id}:${agent.version}` === agentVersionKey)
  const selectedTool = agentTools.find((tool) => `${tool.tool_id}:${tool.version}` === toolVersionKey)
  const selectedSpan = traceData?.spans.find((span) => span.span_id === selectedSpanId)
  const selectedInvocation = traceData?.tool_invocations.find((invocation) => invocation.span_id === selectedSpanId)
  const filteredTraceRuns = runs.filter((run) => {
    const matchesMode = traceMode === 'all' || (traceMode === 'sandbox' ? run.execution_mode === 'sandbox' : run.execution_mode !== 'sandbox')
    const query = traceSearch.trim().toLowerCase()
    const matchesQuery = !query || [run.goal_summary, run.agent_id, run.run_id, run.trace_id].some((value) => value?.toLowerCase().includes(query))
    return matchesMode && matchesQuery
  })

  useEffect(() => {
    setAgentTools([])
    setToolVersionKey(undefined)
    if (!selectedAgent) return
    limApi.agentTools(selectedAgent.agent_id, selectedAgent.version, true)
      .then((result) => setAgentTools(result.items))
      .catch((error) => message.error(error instanceof Error ? error.message : '读取 Agent 可用 Tool 失败'))
  }, [selectedAgent?.agent_id, selectedAgent?.version])

  const refresh = useCallback(async () => {
    setBusy(true)
    try {
      const [a, t, r, d, k, w, s, alertPage, rules, evals, gp, gc, gcall, so, gm] = await Promise.all([limApi.agents(), limApi.tools(), limApi.runs(), limApi.datasets(), limApi.knowledgeSources(), limApi.workflows(), limApi.skills(), limApi.alerts(), limApi.alertRules(), limApi.evalRuns(), limApi.modelProviders(), limApi.modelCatalogs(), limApi.modelCalls(), limApi.safetyOverview(), limApi.modelMetrics()])
      setAgents(a.items); setTools(t.items); setRuns(r.items); setDatasets(d.items); setKnowledge(k.items); setWorkflows(w.items); setSkills(s.items); setAlerts(alertPage.items); setAlertRules(rules.items); setEvalRunOptions(evals.items.filter((item) => item.status === 'COMPLETED')); setSelectedWorkflowId(w.items[0]?.workflow_id ?? null)
      setGwProviders(gp.items); setGwCatalogs(gc.items); setGwCalls(gcall.items); setSafetyOverview(so); setGwMetrics(gm)
    } catch (error) { message.error(error instanceof Error ? error.message : '加载 LIM 数据失败') }
    finally { setBusy(false) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  const doValidate = async (kind: 'agent' | 'tool', id: string, version: string) => {
    try {
      const result = kind === 'agent' ? await limApi.validateAgent(id, version) : await limApi.validateTool(id, version)
      if (result.valid) message.success('校验通过，状态已更新')
      else setModal({ title: '校验问题', value: result.issues })
      await refresh()
    } catch (error) { message.error(error instanceof Error ? error.message : '校验失败') }
  }

  const saveAlertRule = async (rule: LimAlertRule) => {
    try { await limApi.updateAlertRule(rule.rule_key, { enabled: rule.enabled, threshold: rule.threshold, window_seconds: rule.window_seconds }); message.success('告警规则已保存'); await refresh() }
    catch (error) { message.error(error instanceof Error ? error.message : '保存告警规则失败') }
  }
  const changeAlert = async (row: LimAlert, action: 'acknowledge' | 'close') => {
    try { if (action === 'acknowledge') await limApi.acknowledgeAlert(row.alert_id); else await limApi.closeAlert(row.alert_id); message.success(action === 'acknowledge' ? '告警已确认' : '告警已关闭'); await refresh() }
    catch (error) { message.error(error instanceof Error ? error.message : '更新告警失败') }
  }

  const run = async () => {
    if (!selectedAgent) { message.warning('请先选择 Agent 版本'); return }
    if (!runAuto && (!selectedTool || selectedTool.operation_kind !== 'read')) { message.warning('请选择一个只读 Tool，或开启 AI 自选工具'); return }
    try {
      const body: Record<string, unknown> = { agent_id: selectedAgent.agent_id, agent_version: selectedAgent.version, goal }
      if (!runAuto) body.tool_invocation = { tool_id: selectedTool!.tool_id, tool_version: selectedTool!.version, arguments: parse(args) }
      const result = await limApi.run(body)
      message.success(`Run ${result.status}`); await refresh()
      setModal({ title: `Run ${result.run_id}`, value: result })
    } catch (error) { message.error(error instanceof Error ? error.message : 'Run 启动失败') }
  }

  const runSandbox = async () => {
    if (!selectedAgent || !selectedTool) { message.warning('请选择 Agent 版本和 Tool 版本'); return }
    const raw = prompt('粘贴用于仿真的 Mock Tool 响应 JSON。该操作不会调用真实工具或修改业务数据。', '{}')
    if (raw === null) return
    try {
      const result = await limApi.sandboxRun({ agent_id: selectedAgent.agent_id, agent_version: selectedAgent.version,
        tool_id: selectedTool.tool_id, tool_version: selectedTool.version, arguments: parse(args), mock_response: parse(raw) })
      message.success('Sandbox 仿真完成'); await refresh()
      setModal({ title: `Sandbox Run ${result.run_id}`, value: result })
    } catch (error) { message.error(error instanceof Error ? error.message : 'Sandbox 仿真失败') }
  }

  const openTrace = async (traceId: string) => {
    try { setModal({ title: `Trace ${traceId}`, value: await limApi.trace(traceId), traceId }) }
    catch (error) { message.error(error instanceof Error ? error.message : '读取 Trace 失败') }
  }

  const createGwProvider = async () => {
    const name = prompt('供应商名称（如 DeepSeek 官方）')
    if (!name) return
    const base_url = prompt('Base URL（如 https://api.deepseek.com/v1）')
    if (!base_url) return
    const api_key_env = prompt('存放 Key 的环境变量名（如 DEEPSEEK_API_KEY）')
    if (!api_key_env) return
    const provider_id = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
    try {
      await limApi.createModelProvider({ provider_id, name, base_url, api_key_env, enabled: true })
      message.success('供应商已创建'); await refresh()
    } catch (error) { message.error(error instanceof Error ? error.message : '创建供应商失败') }
  }

  const createGwCatalog = async () => {
    const alias = prompt('别名（如 default / cheap / smart）')
    if (!alias) return
    const provider_id = prompt('供应商 ID')
    if (!provider_id) return
    const model_name = prompt('模型名（如 deepseek-chat）')
    if (!model_name) return
    const scene = prompt('业务场景：*、assistant、product、operations、listing、supply、profit、advertising、customer', '*')
    if (!scene?.trim()) return
    const priorityText = prompt('优先级（0–10000，数值越小越优先）', '100')
    if (priorityText === null) return
    const priority = Number(priorityText)
    if (!Number.isInteger(priority) || priority < 0 || priority > 10000) { message.error('优先级应为 0–10000 的整数'); return }
    try {
      await limApi.createModelCatalog({ alias, provider_id, model_name, scene: scene.trim(), priority, enabled: true })
      message.success('别名已创建'); await refresh()
    } catch (error) { message.error(error instanceof Error ? error.message : '创建别名失败') }
  }

  const testGwProvider = async (row: LimModelProvider) => {
    setGwBusy(true); setGwTestResult(null)
    try {
      const model = prompt('要测试的模型名', 'deepseek-chat')
      if (!model) return
      const result = await limApi.testModelProvider({ base_url: row.base_url, api_key_env: row.api_key_env, model })
      setGwTestResult(result as Record<string, unknown>)
      if (result.ok) message.success('连通测试成功')
    } catch (error) { message.error(error instanceof Error ? error.message : '连通测试失败') }
    finally { setGwBusy(false) }
  }

  const disableGwCatalog = async (row: LimModelCatalogEntry) => {
    try {
      await limApi.disableModelCatalog(row.alias_id); message.success('已停用别名'); await refresh()
    } catch (error) { message.error(error instanceof Error ? error.message : '停用失败') }
  }

  const approveRun = async (runId: string) => {
    try {
      await limApi.approveRun(runId); message.success('已批准，写操作执行完成'); await refresh()
    } catch (error) { message.error(error instanceof Error ? error.message : '批准失败') }
  }

  const rejectRun = async (runId: string) => {
    try {
      await limApi.rejectRun(runId); message.success('已驳回该写操作'); await refresh()
    } catch (error) { message.error(error instanceof Error ? error.message : '驳回失败') }
  }

  const openTraceWorkspace = useCallback(async (run: LimRun) => {
    setSelectedRun(run)
    setTraceData(undefined)
    setSelectedSpanId(undefined)
    setTraceBusy(true)
    try {
      const result = await limApi.trace(run.trace_id) as LimTraceData
      setTraceData(result)
      setSelectedSpanId(result.spans[0]?.span_id)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '读取运行追踪失败')
    } finally {
      setTraceBusy(false)
    }
  }, [])

  useEffect(() => {
    if (!selectedRun && runs.length) void openTraceWorkspace(runs[0])
  }, [runs, selectedRun, openTraceWorkspace])

  const loadToolMetrics = async () => {
    setToolMetricsBusy(true)
    try {
      const result = await limApi.toolInvocationMetrics(toolMetricsFrom, toolMetricsTo)
      setToolMetrics(result)
    } catch (error) { message.error(error instanceof Error ? error.message : '读取本地 Tool 观测失败') }
    finally { setToolMetricsBusy(false) }
  }

  const exportToolMetrics = async (format: 'json' | 'csv') => {
    setToolMetricsBusy(true)
    try {
      const blob = await limApi.exportToolInvocationMetrics(toolMetricsFrom, toolMetricsTo, format)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `lim-tool-metrics-${toolMetricsFrom}-${toolMetricsTo}.${format}`
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 0)
    } catch (error) { message.error(error instanceof Error ? error.message : '导出本地 Tool 观测失败') }
    finally { setToolMetricsBusy(false) }
  }

  const exportTrace = async (traceId: string) => {
    try {
      const blob = await limApi.exportTrace(traceId)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `trace-${traceId}.json`
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 0)
      message.success('Trace JSON 已下载')
    } catch (error) { message.error(error instanceof Error ? error.message : '导出 Trace 失败') }
  }

  const createAgent = async () => {
    const raw = prompt('粘贴 Agent JSON 定义')
    if (!raw) return
    try { await limApi.createAgent(parse(raw)); message.success('Agent 草稿已创建'); await refresh() }
    catch (error) { message.error(error instanceof Error ? error.message : '创建失败') }
  }
  const createTool = async () => {
    const raw = prompt('粘贴 Tool JSON 定义')
    if (!raw) return
    try { await limApi.createTool(parse(raw)); message.success('Tool 草稿已创建'); await refresh() }
    catch (error) { message.error(error instanceof Error ? error.message : '创建失败') }
  }
  const createDataset = async () => {
    const example = { dataset_id: 'golden-basic', version: '1.0.0', name: '基础只读查询', cases: [{ case_id: 'product-read-1', scenario: '查询商品', input_payload: { tool_id: 'erp.product.read', arguments: { product_id: '示例商品编码' } }, ground_truth: {}, risk_tier: 'low' }] }
    const raw = prompt('粘贴 Dataset JSON 定义', pretty(example))
    if (!raw) return
    try { const result = await limApi.createDataset(parse(raw)); setDatasetVersionKey(`${result.dataset_id}:${result.version}`); message.success('数据集版本已创建'); await refresh() }
    catch (error) { message.error(error instanceof Error ? error.message : '创建失败') }
  }
  const evaluate = async () => {
    const dataset = datasets.find((item) => `${item.dataset_id}:${item.version}` === datasetVersionKey)
    if (!dataset || !selectedAgent || selectedAgent.status !== 'validated') { message.warning('请选择数据集，并选择已验证的 Agent 版本'); return }
    try {
      const value = await limApi.evaluate({ dataset_id: dataset.dataset_id, dataset_version: dataset.version, agent_id: selectedAgent.agent_id, agent_version: selectedAgent.version })
      setReport(value); setModal({ title: `Eval ${value.eval_run_id}`, value }); await refresh()
    } catch (error) { message.error(error instanceof Error ? error.message : '评测失败') }
  }

  const compareEvaluations = async () => {
    if (!baselineEvalRunId || !candidateEvalRunId || baselineEvalRunId === candidateEvalRunId) { message.warning('请选择两次不同版本的已完成评测'); return }
    try {
      const value = await limApi.compareEvals({ baseline_eval_run_id: baselineEvalRunId, candidate_eval_run_id: candidateEvalRunId, ...comparisonThresholds })
      setComparison(value); message.success(`比较报告已生成：${value.status}`)
    } catch (error) { message.error(error instanceof Error ? error.message : '生成比较报告失败') }
  }

  const syncKnowledge = async () => {
    setKnowledgeBusy(true)
    try { const result = await limApi.syncKnowledge(); message.success(`同步完成：新增 ${result.new_source_count ?? 0} 个来源，${result.new_version_count ?? 0} 个版本`); await refresh() }
    catch (error) { message.error(error instanceof Error ? error.message : '知识源同步失败') }
    finally { setKnowledgeBusy(false) }
  }
  const editKnowledge = async (row: KnowledgeSource) => {
    const raw = prompt('编辑来源元数据 JSON（display_name/category/summary/required_permissions）', JSON.stringify({ display_name: row.display_name, category: row.category, summary: row.summary, required_permissions: row.required_permissions }, null, 2))
    if (!raw) return
    try { await limApi.patchKnowledgeSource(row.source_id, JSON.parse(raw)); message.success('来源元数据已更新'); await refresh() }
    catch (error) { message.error(error instanceof Error ? error.message : '更新失败') }
  }
  const showKnowledgeVersions = async (row: KnowledgeSource) => {
    try {
      const result = await limApi.knowledgeVersions(row.source_id)
      setModal({ title: `${row.display_name} · 版本`, value: result.items.map((v: KnowledgeVersion) => ({ ...v, 可操作: v.status === 'draft' ? '可激活' : '' })) })
    } catch (error) { message.error(error instanceof Error ? error.message : '读取版本失败') }
  }
  const activateKnowledge = async (row: KnowledgeSource) => {
    try {
      const result = await limApi.knowledgeVersions(row.source_id)
      const version = result.items.find((v) => v.status === 'draft')
      if (!version) { message.info('当前没有待激活版本'); return }
      const until = prompt('设置有效期截止时间（UTC ISO 格式），留空即确认不自动到期；取消则不激活', '')
      if (until === null) return
      const validUntil = until.trim() ? new Date(until).toISOString() : null
      await limApi.activateKnowledgeVersion(row.source_id, version.version, { valid_until: validUntil, no_expiry: !validUntil })
      message.success('版本已激活'); await refresh()
    } catch (error) { message.error(error instanceof Error ? error.message : '激活失败') }
  }
  const archiveDraftKnowledgeVersion = async (row: KnowledgeSource) => {
    try {
      const result = await limApi.knowledgeVersions(row.source_id)
      const version = result.items.find((v) => v.status === 'draft')
      if (!version) { message.info('当前没有可归档草稿'); return }
      await limApi.archiveKnowledgeVersion(row.source_id, version.version); message.success('草稿版本已归档'); await refresh()
    } catch (error) { message.error(error instanceof Error ? error.message : '归档失败') }
  }
  const runKnowledgeSearch = async () => {
    try { setKnowledgeResult(await limApi.searchKnowledge(knowledgeQuery)) }
    catch (error) { message.error(error instanceof Error ? error.message : '检索失败') }
  }
  const createWorkflow = async () => {
    const mapping = {
      shop_id: { from: 'input', pointer: '/shop_id' },
      date_from: { from: 'input', pointer: '/date_from' },
      date_to: { from: 'input', pointer: '/date_to' },
    }
    const workflowId = 'erp.shop-period-diagnostic'
    const workflowVersion = '1.0.0'
    const agent = { agent_id: 'erp.business-diagnostic', agent_version: '1.0.0' }
    const tasks = [
      { node_id: 'orders', type: 'tool_call', ...agent, tool_id: 'erp.orders.period-summary', tool_version: '1.0.0', depends_on: [], argument_mapping: mapping },
      { node_id: 'payments', type: 'tool_call', ...agent, tool_id: 'erp.finance.recorded-payments', tool_version: '1.0.0', depends_on: [], argument_mapping: mapping },
      { node_id: 'ad-inventory', type: 'tool_call', ...agent, tool_id: 'erp.ads.inventory-alignment', tool_version: '1.0.0', depends_on: [], argument_mapping: mapping },
      { node_id: 'collect', type: 'join', depends_on: ['orders', 'payments', 'ad-inventory'] },
    ]
    const example = {
      workflow_id: workflowId, version: workflowVersion, display_name: '店铺周期经营与广告库存风险复核', business_domain: 'diagnostics',
      definition: {
        workflow_id: workflowId, version: workflowVersion,
        input_schema: { type: 'object', properties: { shop_id: { type: 'string' }, date_from: { type: 'string' }, date_to: { type: 'string' } }, required: ['shop_id', 'date_from', 'date_to'], additionalProperties: false },
        input_constraints: [{ type: 'date_range', start_pointer: '/date_from', end_pointer: '/date_to', max_days: 93 }],
        tasks,
      },
    }
    const raw = prompt('粘贴 Workflow JSON 定义', pretty(example))
    if (!raw) return
    try { await limApi.createWorkflow(parse(raw)); message.success('Workflow 草稿已登记'); await refresh() }
    catch (error) { message.error(error instanceof Error ? error.message : '登记失败') }
  }
  const validateWorkflow = async (workflow: LimWorkflow, version: string) => {
    try {
      const result = await limApi.validateWorkflow(workflow.workflow_id, version)
      if (result.valid) message.success('Workflow 校验通过')
      else setModal({ title: 'Workflow 校验问题', value: result.issues })
      await refresh()
    } catch (error) { message.error(error instanceof Error ? error.message : '校验失败') }
  }
  const runWorkflow = async (workflow: LimWorkflow) => {
    const version = workflow.versions.find((item) => item.status === 'validated')
    if (!version) { message.warning('请先校验一个 Workflow 版本'); return }
    const raw = prompt('输入符合 Workflow Schema 的 JSON', '{"shop_id":"...","date_from":"2026-10-01","date_to":"2026-10-21"}')
    if (raw === null) return
    try {
      const result = await limApi.runWorkflow({ workflow_id: workflow.workflow_id, version: version.version, input: parse(raw) })
      setWorkflowResult(result)
      setSelectedWorkflowId(workflow.workflow_id)
      setRunTasks([])
      message.success(`Workflow ${String((result as { status?: string }).status)}`)
      const runId = String((result as { workflow_run_id?: string }).workflow_run_id)
      if (runId) void (async () => {
        try {
          const detail = await limApi.workflowRun(runId) as { tasks?: Array<{ node_id: string; status?: string }> }
          if (detail?.tasks) setRunTasks(detail.tasks)
        } catch { /* 单进程同步执行，稍后重试即可 */ }
      })()
    } catch (error) { message.error(error instanceof Error ? error.message : 'Workflow 运行失败') }
  }
  const openWorkflowTrace = async (id: string) => {
    try { setModal({ title: `Workflow Trace ${id}`, value: await limApi.workflowTrace(id) }) }
    catch (error) { message.error(error instanceof Error ? error.message : '读取 Workflow Trace 失败') }
  }
  const createSkill = async () => {
    const example = {
      skill_id: 'catalog-quality-review', version: '1.0.0', display_name: 'catalog_review.v1',
      memory_level: 'procedural', definition: { template_id: 'catalog_review.v1', capability_tags: ['listing_quality'] },
      source_event: 'review:ticket-123', evidence_refs: [{ ref_id: 'knowledge:catalog:v1', source_version: 'v1', content_hash: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' }],
      business_scope: { domain: 'catalog', market_codes: ['US'] },
      confidence_calibration: { method: 'human_review', sample_size: 10, score: 0.9 },
      expiry_policy: { no_expiry: true },
    }
    const raw = prompt('粘贴 Skill 候选 JSON。仅接受已登记模板及受控引用元数据；不接受自由文本、正文或原始业务行。', pretty(example))
    if (!raw) return
    try { await limApi.createSkill(parse(raw)); message.success('Skill 候选已登记'); await refresh() }
    catch (error) { message.error(error instanceof Error ? error.message : 'Skill 候选登记失败') }
  }
  const transitionSkill = async (row: LimSkillVersion, target: string) => {
    const rationale = prompt(`迁移 ${row.skill_id} v${row.version}：${row.status} → ${target}。请填写审核理由。`)
    if (!rationale?.trim()) return
    try { await limApi.transitionSkill(row.skill_id, row.version, { target_status: target, rationale }); message.success(`Skill 状态已更新为 ${target}`); await refresh() }
    catch (error) { message.error(error instanceof Error ? error.message : '状态迁移失败') }
  }
  const editSkillCandidate = async (row: LimSkillVersion) => {
    const body = { skill_id: row.skill_id, version: row.version, display_name: row.display_name,
      memory_level: row.memory_level, definition: row.definition, source_event: row.source_event,
      evidence_refs: row.evidence_refs, business_scope: row.business_scope,
      confidence_calibration: row.confidence_calibration, expiry_policy: row.expiry_policy }
    const raw = prompt('修改候选 Skill 元数据。进入审核后内容将锁定；只接受受控引用，不接受自由文本或正文。', pretty(body))
    if (!raw) return
    try { await limApi.updateSkillCandidate(row.skill_id, row.version, parse(raw)); message.success('候选 Skill 已更新'); await refresh() }
    catch (error) { message.error(error instanceof Error ? error.message : '候选 Skill 更新失败') }
  }

  const agentColumns: ColumnsType<LimAgent> = [
    { title: 'Agent', dataIndex: 'display_name', render: (v, row) => <>{v}<div style={{ color: '#888' }}>{row.agent_id} · v{row.version}</div></> },
    { title: '业务域', dataIndex: 'business_domain' }, { title: '状态', dataIndex: 'status', render: (v) => <Tag>{v}</Tag> },
    { title: '操作', render: (_, row) => <Button size="small" onClick={() => void doValidate('agent', row.agent_id, row.version)}>校验</Button> },
  ]
  const toolColumns: ColumnsType<LimTool> = [
    { title: 'Tool ID', dataIndex: 'tool_id', render: (v, row) => <>{v}<div style={{ color: '#888' }}>v{row.version} · {row.service}</div></> },
    { title: '领域', dataIndex: 'domain' }, { title: '类型', dataIndex: 'operation_kind', render: (v) => <Tag color={v === 'read' ? 'green' : 'red'}>{v}</Tag> },
    { title: '状态', dataIndex: 'status' }, { title: '操作', render: (_, row) => <Button size="small" onClick={() => void doValidate('tool', row.tool_id, row.version)}>校验</Button> },
  ]
  const toolMetricColumns: ColumnsType<LimToolInvocationMetric> = [
    { title: 'UTC 日期 / 模式', render: (_, row) => <>{row.day}<div><Tag color={row.execution_mode === 'sandbox' ? 'gold' : 'blue'}>{row.execution_mode === 'sandbox' ? 'Sandbox' : 'Live'}</Tag></div></> },
    { title: 'Agent 版本', render: (_, row) => <>{row.agent_id}<div style={{ color: '#888' }}>v{row.agent_version}</div></> },
    { title: 'Tool 版本', render: (_, row) => <>{row.tool_id}<div style={{ color: '#888' }}>v{row.tool_version}</div></> },
    { title: '调用数', render: (_, row) => <>{row.invocation_count}<div style={{ color: '#888' }}>handler 调用 {row.handler_call_count}</div></> },
    { title: '状态计数', render: (_, row) => <Space size={[4, 4]} wrap>{Object.entries(row.status_counts).map(([status, count]) => <Tag key={status}>{status} {count}</Tag>)}</Space> },
    { title: '延迟样本 / 耗时', render: (_, row) => row.latency_sample_count ? <>{row.latency_sample_count} 个样本<div style={{ color: '#555' }}>均值 {row.latency_ms.mean} ms · P50 {row.latency_ms.p50} ms · P95 {row.latency_ms.p95} ms</div></> : <>0 个样本<div style={{ color: '#888' }}>暂无 live handler 耗时</div></> },
  ]
  const skillColumns: ColumnsType<LimSkillVersion> = [
    { title: 'Skill', render: (_, row) => <>{row.display_name}<div style={{ color: '#888' }}>{row.skill_id} · v{row.version} · {row.memory_level}</div></> },
    { title: '状态', dataIndex: 'status', render: (value) => <Tag color={value === 'ACTIVE' ? 'green' : value === 'REVOKED' ? 'red' : 'blue'}>{value}</Tag> },
    { title: '来源 / 证据', render: (_, row) => <>{row.source_event}<div style={{ color: '#888' }}>{row.evidence_refs.length} 条引用</div></> },
    { title: '验证 / 有效期', render: (_, row) => <>{row.last_verified_at || '未验证'}<div style={{ color: '#888' }}>{String(row.expiry_policy.expires_at || (row.expiry_policy.no_expiry ? '不自动到期' : '未设置'))}</div></> },
    { title: '计数', render: (_, row) => `使用 ${row.usage_count} · 纠错 ${row.correction_count}` },
    { title: '操作', render: (_, row) => {
      const targets: Record<string, string[]> = { CANDIDATE: ['UNDER_REVIEW'], UNDER_REVIEW: ['VERIFIED', 'CANDIDATE', 'REVOKED'], VERIFIED: ['ACTIVE', 'REVOKED'], ACTIVE: ['DEGRADED', 'FROZEN', 'REVOKED'], DEGRADED: ['UNDER_REVIEW', 'FROZEN', 'REVOKED'], FROZEN: ['UNDER_REVIEW', 'REVOKED'] }
      return <Space wrap><Button size="small" onClick={() => setModal({ title: `${row.skill_id} v${row.version}`, value: row })}>查看</Button>{row.status === 'CANDIDATE' && <Button size="small" onClick={() => void editSkillCandidate(row)}>编辑候选</Button>}{(targets[row.status] || []).map((target) => <Button key={target} size="small" danger={target === 'REVOKED'} onClick={() => void transitionSkill(row, target)}>{target}</Button>)}</Space>
    } },
  ]

  return <div style={{ padding: 24 }}>
    <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 16 }}>
      <div><Typography.Title level={3} style={{ margin: 0 }}>LIM 智能中间层</Typography.Title><Typography.Text type="secondary">AI 工程与运行治理平台：注册、编排、追踪、评测与知识治理</Typography.Text></div>
      <Button onClick={() => void refresh()} loading={busy}>刷新</Button>
    </Space>
    <Alert type="info" showIcon style={{ marginBottom: 16 }} message="当前运行时仅开放已登记的只读适配器。Tool 写操作不会被运行；Trace 保存经过脱敏的摘要。" />
    <Tabs activeKey={section} onChange={(key) => navigate(`/${LIM_SECTION_ROUTES[key as LimSection] ?? 'lim-console'}`)} items={[
      { key: 'overview', label: '平台总览', children: <>
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message="以下为当前 LIM 已登记资源概览；模型调用量、Token、费用和租户级指标尚未接入，不在此展示估算值。" />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 12 }}>
          {[
            ['Agent 版本', agents.length], ['Tool 版本', tools.length], ['Workflow', workflows.length],
            ['运行记录', runs.length], ['评测数据集', datasets.length], ['知识源', knowledge.length],
            ['有效技能', skills.filter((item) => item.status === 'ACTIVE').length], ['待处理告警', alerts.filter((item) => item.status === 'OPEN').length],
          ].map(([label, count]) => <Card key={String(label)} size="small" title={String(label)} loading={busy}><Typography.Title level={3} style={{ margin: 0 }}>{count}</Typography.Title></Card>)}
        </div>
        <Card title="平台能力" style={{ marginTop: 16 }}><Space wrap>
          <Button onClick={() => navigate('/lim-agent-runtime')}>Agent 运行时</Button>
          <Button onClick={() => navigate('/lim-tool-registry')}>工具注册中心</Button>
          <Button onClick={() => navigate('/lim-workflow')}>工作流编排</Button>
          <Button onClick={() => navigate('/lim-runs')}>运行与追踪</Button>
          <Button onClick={() => navigate('/lim-eval')}>评测与回归</Button>
          <Button onClick={() => navigate('/lim-knowledge')}>知识源管理</Button>
          <Button onClick={() => navigate('/lim-skills')}>记忆与技能治理</Button>
          <Button onClick={() => navigate('/lim-alerts')}>运行告警</Button>
          <Button onClick={() => navigate('/lim-model-gateway')}>模型网关</Button>
        </Space></Card>
      </> },
      { key: 'agentRuntime', label: 'Agent 运行时', children: <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Alert type="info" showIcon message="管理 Agent 定义及固定版本，并查看运行状态；当前运行入口仅允许已验证版本和只读 Tool。" />
        <Card title="Agent 注册与版本" extra={<Button onClick={() => void createAgent()}>创建 Agent 草稿</Button>}><Table rowKey={(row) => `${row.agent_id}:${row.version}`} size="small" pagination={false} loading={busy} columns={agentColumns} dataSource={agents} /></Card>
      </Space> },
      { key: 'toolRegistry', label: '工具注册中心', children: <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Alert type="info" showIcon message="登记 Tool Schema、操作类型与版本。真实写操作不会被 LIM 运行；写 Tool 仅可在 Sandbox 仿真。" />
        <Card title="Tool 注册与版本" extra={<Button onClick={() => void createTool()}>创建 Tool 草稿</Button>}><Table rowKey={(row) => `${row.tool_id}:${row.version}`} size="small" pagination={false} loading={busy} columns={toolColumns} dataSource={tools} /></Card>
      </Space> },
      { key: 'runs', label: '运行与追踪', children: <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Alert type="warning" showIcon message="Sandbox 仅校验固定版本 Schema，不调用真实 Tool handler 或读取业务数据。Trace 保存脱敏摘要。" />
        <Card title="启动只读运行"><Space wrap>
          <Select placeholder="选择 Agent 版本" style={{ width: 240 }} value={agentVersionKey} onChange={setAgentVersionKey} options={agents.filter((a) => a.status === 'validated').map((a) => ({ value: `${a.agent_id}:${a.version}`, label: `${a.display_name} · v${a.version}` }))} />
          {!runAuto && <Select placeholder="选择此 Agent 可用的 Tool 版本" style={{ width: 280 }} value={toolVersionKey} onChange={setToolVersionKey} options={agentTools.map((tool) => ({ value: `${tool.tool_id}:${tool.version}`, label: `${tool.tool_id} · v${tool.version}` }))} />}
          <Input placeholder={runAuto ? '用自然语言描述你要分析什么' : '运行目标'} value={goal} onChange={(e) => setGoal(e.target.value)} style={{ width: 280 }} /><Switch checked={runAuto} onChange={setRunAuto} checkedChildren="AI 自选" unCheckedChildren="手动工具" /><Button type="primary" onClick={() => void run()}>运行</Button><Button onClick={() => void runSandbox()}>Sandbox 仿真</Button>
        </Space>{!runAuto && <Input.TextArea value={args} onChange={(e) => setArgs(e.target.value)} autoSize={{ minRows: 2, maxRows: 5 }} style={{ marginTop: 12, fontFamily: 'monospace' }} />}</Card>
        <Card title="Trace 分析" loading={traceBusy} extra={selectedRun && <Button onClick={() => void exportTrace(selectedRun.trace_id)}>导出脱敏追踪</Button>}>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 0.9fr) minmax(260px, 1.1fr) minmax(280px, 1fr)', gap: 12, alignItems: 'stretch', overflowX: 'auto' }}>
            <Card size="small" title="运行目录" style={{ minWidth: 220 }}>
              <Space direction="vertical" style={{ width: '100%' }} size="small">
                <Input.Search placeholder="搜索目标、Agent 或 ID" allowClear value={traceSearch} onChange={(event) => setTraceSearch(event.target.value)} />
                <Select aria-label="运行模式筛选" value={traceMode} onChange={setTraceMode} style={{ width: '100%' }} options={[{ value: 'all', label: '全部运行模式' }, { value: 'live', label: '只读运行' }, { value: 'sandbox', label: 'Sandbox 仿真' }]} />
                <div style={{ maxHeight: 500, overflowY: 'auto' }}>
                  {filteredTraceRuns.map((run) => {
                    const active = selectedRun?.run_id === run.run_id
                    return <div key={run.run_id} role="button" tabIndex={0} onClick={() => void openTraceWorkspace(run)} style={{ display: 'block', width: '100%', textAlign: 'left', padding: 10, marginBottom: 6, borderRadius: 6, border: active ? '1px solid #1677ff' : '1px solid #e5e7eb', background: active ? '#eaf3ff' : '#fff', cursor: 'pointer', color: '#1f2937' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><Typography.Text strong ellipsis>{run.goal_summary || '未命名运行'}</Typography.Text><Tag color={run.status === 'SUCCEEDED' ? 'green' : run.status === 'FAILED' ? 'red' : run.status === 'REVIEW_REQUIRED' ? 'orange' : 'default'}>{run.status}</Tag></div>
                      <Typography.Text type="secondary" style={{ display: 'block', marginTop: 4 }}>{run.agent_id} · v{run.agent_version}</Typography.Text>
                      <Typography.Text type="secondary" style={{ display: 'block', fontSize: 11 }}>Run {run.run_id.slice(0, 8)} · Trace {run.trace_id.slice(0, 8)}</Typography.Text>
                      {run.status === 'REVIEW_REQUIRED' && (
                        <div style={{ marginTop: 6, display: 'flex', gap: 8 }} onClick={(e) => e.stopPropagation()}>
                          <Button size="small" type="primary" onClick={(e) => { e.stopPropagation(); void approveRun(run.run_id) }}>批准执行</Button>
                          <Button size="small" danger onClick={(e) => { e.stopPropagation(); void rejectRun(run.run_id) }}>驳回</Button>
                        </div>
                      )}
                    </div>
                  })}
                  {!filteredTraceRuns.length && <Typography.Text type="secondary">没有符合条件的运行记录</Typography.Text>}
                </div>
              </Space>
            </Card>
            <Card size="small" title="执行时间线" style={{ minWidth: 260 }}>
              {selectedRun ? <>
                <Typography.Text type="secondary">{selectedRun.agent_id} · v{selectedRun.agent_version}</Typography.Text>
                <Typography.Paragraph style={{ marginTop: 8 }}>{selectedRun.goal_summary}</Typography.Paragraph>
                <div style={{ borderLeft: '2px solid #dbeafe', marginLeft: 9, paddingLeft: 14 }}>
                  {traceData?.spans.map((span) => {
                    const active = span.span_id === selectedSpanId
                    const duration = span.started_at && span.ended_at ? Math.max(0, new Date(span.ended_at).getTime() - new Date(span.started_at).getTime()) : undefined
                    return <button key={span.span_id} type="button" onClick={() => setSelectedSpanId(span.span_id)} style={{ display: 'block', position: 'relative', width: '100%', textAlign: 'left', padding: 10, margin: '0 0 10px', borderRadius: 6, border: active ? '1px solid #1677ff' : '1px solid #e5e7eb', background: active ? '#eaf3ff' : '#fff', cursor: 'pointer', color: '#1f2937' }}>
                      <span aria-hidden="true" style={{ position: 'absolute', left: -21, top: 16, width: 10, height: 10, borderRadius: '50%', background: span.status === 'FAILED' ? '#ff4d4f' : '#1677ff' }} />
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><Typography.Text strong>{span.name}</Typography.Text><Tag>{span.status}</Tag></div>
                      <Typography.Text type="secondary">{span.kind}{duration === undefined ? '' : ` · ${duration} ms`}</Typography.Text>
                    </button>
                  })}
                  {traceData && !traceData.spans.length && <Typography.Text type="secondary">该运行暂无 Span 记录</Typography.Text>}
                  {!traceData && !traceBusy && <Typography.Text type="secondary">选择左侧运行查看时间线</Typography.Text>}
                </div>
              </> : <Typography.Text type="secondary">暂无运行记录</Typography.Text>}
            </Card>
            <Card size="small" title="追踪详情" style={{ minWidth: 280 }}>
              {selectedRun ? <Tabs size="small" items={[
                { key: 'attributes', label: '属性', children: <Descriptions size="small" column={1} items={[
                  { key: 'run', label: '运行编号', children: selectedRun.run_id },
                  { key: 'trace', label: '追踪编号', children: selectedRun.trace_id },
                  { key: 'agent', label: 'Agent 版本', children: `${selectedRun.agent_id} · v${selectedRun.agent_version}` },
                  { key: 'mode', label: '运行模式', children: selectedRun.execution_mode === 'sandbox' ? 'Sandbox 仿真' : '只读运行' },
                  { key: 'status', label: '运行状态', children: selectedRun.status },
                  ...(selectedSpan ? [{ key: 'span', label: '当前 Span', children: `${selectedSpan.name} · ${selectedSpan.kind}` }] : []),
                  ...(selectedSpan?.error_code ? [{ key: 'error', label: '错误代码', children: selectedSpan.error_code }] : []),
                  ...(selectedInvocation ? [{ key: 'tool', label: 'Tool 调用', children: `${selectedInvocation.tool_id} · v${selectedInvocation.tool_version}` }] : []),
                ]} /> },
                { key: 'data', label: '脱敏数据', children: <pre style={{ maxHeight: 420, overflow: 'auto', whiteSpace: 'pre-wrap', fontSize: 11 }}>{pretty({ run: selectedRun, span: selectedSpan, toolInvocation: selectedInvocation, trace: traceData })}</pre> },
              ]} /> : <Typography.Text type="secondary">选择运行后查看属性和脱敏追踪数据</Typography.Text>}
            </Card>
          </div>
        </Card>
        <Card title="本地 Tool 观测" extra={<Space wrap>
          <Input type="date" aria-label="开始日期 UTC" value={toolMetricsFrom} onChange={(event) => setToolMetricsFrom(event.target.value)} style={{ width: 160 }} />
          <Input type="date" aria-label="结束日期 UTC" value={toolMetricsTo} onChange={(event) => setToolMetricsTo(event.target.value)} style={{ width: 160 }} />
          <Button onClick={() => void loadToolMetrics()} loading={toolMetricsBusy}>查询</Button>
          <Button onClick={() => void exportToolMetrics('json')} disabled={toolMetricsBusy}>导出 JSON</Button>
          <Button onClick={() => void exportToolMetrics('csv')} disabled={toolMetricsBusy}>导出 CSV</Button>
        </Space>}>
          <Alert type="info" showIcon message="延迟只统计本地同步 Tool handler 的实测耗时。Sandbox 单独列出，其 Mock 的 0 ms 不计入延迟样本；此页不代表模型或上游 API 耗时。" />
          <Descriptions size="small" column={4} style={{ margin: '16px 0' }} items={[
            { key: 'token', label: 'Token', children: '不可用' },
            { key: 'cost', label: '费用', children: '不可用' },
            { key: 'cache', label: '缓存命中', children: '不可用' },
            { key: 'tenant', label: '租户维度', children: '不可用' },
          ]} />
          <Table rowKey={(row) => `${row.day}:${row.execution_mode}:${row.agent_id}:${row.agent_version}:${row.tool_id}:${row.tool_version}`}
            size="small" loading={toolMetricsBusy} pagination={{ pageSize: 10 }} columns={toolMetricColumns}
            dataSource={toolMetrics?.items ?? []}
            locale={{ emptyText: toolMetrics ? '当前日期范围没有可见的调用记录' : '选择 UTC 日期范围后查询指标' }} />
        </Card>
      </Space> },
      { key: 'eval', label: '评测与回归', children: <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Alert type="info" showIcon message="本地确定性回归报告，不代表真实模型效果或生产发布门禁。比较只使用已有的已完成评测结果。" />
        <Card title="数据集评测"><Space><Button onClick={() => void createDataset()}>创建数据集版本</Button><Select placeholder="选择数据集" style={{ width: 300 }} value={datasetVersionKey} onChange={setDatasetVersionKey} options={datasets.map((d) => ({ value: `${d.dataset_id}:${d.version}`, label: `${d.name} · ${d.dataset_id} v${d.version}` }))} /><Button type="primary" onClick={() => void evaluate()}>运行评测</Button></Space><Table rowKey={(row) => `${row.dataset_id}:${row.version}`} size="small" pagination={false} style={{ marginTop: 12 }} dataSource={datasets} columns={[{ title: '数据集', dataIndex: 'name' }, { title: 'ID / 版本', render: (_, row) => `${row.dataset_id} · ${row.version}` }, { title: '状态', dataIndex: 'status' }]} /></Card>
        {report && <Card title="最近一次评测报告"><Descriptions items={[{ key: 'agent', label: 'Agent', children: `${report.agent_id} v${report.agent_version}` }, { key: 'dataset', label: '数据集', children: `${report.dataset_id} v${report.dataset_version}` }, { key: 'metrics', label: '本地断言指标', children: pretty(report.metrics) }]} /></Card>}
        <Card title="固定版本比较"><Space wrap>
          <Select placeholder="基线 Eval Run" style={{ width: 340 }} value={baselineEvalRunId} onChange={setBaselineEvalRunId} options={evalRunOptions.map((item) => ({ value: item.eval_run_id, label: `${item.agent_id} v${item.agent_version} · ${item.dataset_id} v${item.dataset_version} · ${item.environment} · ${item.eval_run_id.slice(0, 8)}` }))} />
          <Select placeholder="候选 Eval Run" style={{ width: 340 }} value={candidateEvalRunId} onChange={setCandidateEvalRunId} options={evalRunOptions.map((item) => ({ value: item.eval_run_id, label: `${item.agent_id} v${item.agent_version} · ${item.dataset_id} v${item.dataset_version} · ${item.environment} · ${item.eval_run_id.slice(0, 8)}` }))} />
          <span>允许通过率下降</span><InputNumber min={0} max={1} step={0.01} value={comparisonThresholds.max_pass_rate_drop} onChange={(value) => setComparisonThresholds((old) => ({ ...old, max_pass_rate_drop: value ?? 0 }))} />
          <span>允许用例回归</span><InputNumber min={0} max={200} value={comparisonThresholds.max_case_regressions} onChange={(value) => setComparisonThresholds((old) => ({ ...old, max_case_regressions: value ?? 0 }))} />
          <span>允许关键用例回归</span><InputNumber min={0} max={200} value={comparisonThresholds.max_critical_case_regressions} onChange={(value) => setComparisonThresholds((old) => ({ ...old, max_critical_case_regressions: value ?? 0 }))} />
          <Button type="primary" onClick={() => void compareEvaluations()}>生成比较报告</Button>
        </Space></Card>
        {comparison && <Card title="固定版本比较报告" extra={<Tag color={comparison.status === 'PASS' ? 'green' : comparison.status === 'FAIL' ? 'red' : 'orange'}>{comparison.status}</Tag>}>
          <Descriptions column={2} items={[
            { key: 'versions', label: '版本', children: `${comparison.baseline.agent_id} v${comparison.baseline.agent_version} → v${comparison.candidate.agent_version}` },
            { key: 'dataset', label: '固定数据集/环境', children: `${comparison.baseline.dataset_id} v${comparison.baseline.dataset_version} · ${comparison.baseline.environment}` },
            { key: 'baseline', label: '基线通过率 / 失败 / 未评测', children: `${comparison.baseline.metrics.pass_rate == null ? '未定义' : `${(Number(comparison.baseline.metrics.pass_rate) * 100).toFixed(1)}%`} / ${comparison.baseline.metrics.failed} / ${comparison.baseline.metrics.not_evaluated}` },
            { key: 'candidate', label: '候选通过率 / 失败 / 未评测', children: `${comparison.candidate.metrics.pass_rate == null ? '未定义' : `${(Number(comparison.candidate.metrics.pass_rate) * 100).toFixed(1)}%`} / ${comparison.candidate.metrics.failed} / ${comparison.candidate.metrics.not_evaluated}` },
            { key: 'regressions', label: '回归 / 改善 / 关键回归', children: `${comparison.summary.regressions} / ${comparison.summary.improvements} / ${comparison.summary.critical_case_regressions}` },
            { key: 'thresholds', label: '各项阈值判定', children: Object.entries(comparison.summary.threshold_checks).map(([name, passed]) => `${name}: ${passed ? '通过' : '未通过'}`).join('；') },
            { key: 'elapsed', label: '平均耗时（描述性）', children: `${comparison.summary.baseline_average_elapsed_ms ?? '—'} ms → ${comparison.summary.candidate_average_elapsed_ms ?? '—'} ms` },
            { key: 'integrity', label: '报告完整性', children: comparison.integrity_valid ? '校验通过' : '校验失败' },
          ]} />
          <Table rowKey="case_id" size="small" pagination={{ pageSize: 10 }} style={{ marginTop: 16 }} dataSource={comparison.cases} scroll={{ x: 1100 }} columns={[
            { title: '用例', dataIndex: 'case_id', fixed: 'left' }, { title: '风险', dataIndex: 'risk_tier' },
            { title: '基线 → 候选', render: (_, row) => `${row.baseline_outcome} → ${row.candidate_outcome}` },
            { title: '分类', dataIndex: 'classification', render: (value: string) => <Tag color={value === 'REGRESSION' ? 'red' : value === 'IMPROVED' ? 'green' : 'default'}>{value}</Tag> },
            { title: '失败原因变化', render: (_, row) => `${row.baseline_failures.join(', ') || '—'} → ${row.candidate_failures.join(', ') || '—'}` },
            { title: '脱敏输出差异', dataIndex: 'output_changes', render: (value: unknown) => <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{pretty(value)}</pre> },
            { title: 'Trace', render: (_, row) => <Space>{row.baseline_trace_id && <Button size="small" onClick={() => void openTrace(row.baseline_trace_id!)}>基线</Button>}{row.candidate_trace_id && <Button size="small" onClick={() => void openTrace(row.candidate_trace_id!)}>候选</Button>}</Space> },
          ]} />
        </Card>}
      </Space> },
      { key: 'knowledge', label: '知识源管理', children: <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Alert type="info" showIcon message="仅同步 docs/功能章节 与 docs/oms 下的本地 Markdown。内容变化会生成待审核版本；首次登记版本直接生效。检索为词面匹配。" />
        <Card title="知识源目录" extra={<Button type="primary" loading={knowledgeBusy} onClick={() => void syncKnowledge()}>同步文档目录</Button>}>
          <Table rowKey="source_id" size="small" pagination={{ pageSize: 10 }} dataSource={knowledge} columns={[
            { title: '来源', render: (_, row) => <>{row.display_name}<div style={{ color: '#888' }}>{row.path}</div></> },
            { title: '分类', dataIndex: 'category' },
            { title: '状态', render: (_, row) => <Space><Tag color={row.is_archived ? 'default' : row.is_present ? 'green' : 'orange'}>{row.is_archived ? '已归档' : row.is_present ? '存在' : '文件缺失'}</Tag><Tag>{row.active_version ? `active · ${row.active_version.version.slice(0, 12)}` : '无生效版本'}</Tag></Space> },
            { title: '权限', dataIndex: 'required_permissions', render: (v: string[]) => v.length ? v.join(', ') : 'assistant:read' },
            { title: '操作', render: (_, row) => <Space wrap><Button size="small" onClick={() => void editKnowledge(row)}>编辑元数据</Button><Button size="small" onClick={() => void showKnowledgeVersions(row)}>版本 / 差异</Button><Button size="small" onClick={() => void activateKnowledge(row)}>激活待审版本</Button><Button size="small" onClick={() => void archiveDraftKnowledgeVersion(row)}>归档草稿</Button><Button size="small" danger disabled={row.is_archived} onClick={async () => { try { await limApi.archiveKnowledgeSource(row.source_id); message.success('来源已归档'); await refresh() } catch (error) { message.error(error instanceof Error ? error.message : '归档失败') } }}>归档来源</Button></Space> },
          ]} />
        </Card>
        <Card title="知识检索预览"><Space.Compact style={{ width: '100%' }}><Input value={knowledgeQuery} onChange={(e) => setKnowledgeQuery(e.target.value)} onPressEnter={() => void runKnowledgeSearch()} placeholder="输入功能或操作关键词" /><Button type="primary" onClick={() => void runKnowledgeSearch()}>检索</Button></Space.Compact>{knowledgeResult !== undefined && <pre style={{ maxHeight: 360, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{pretty(knowledgeResult)}</pre>}</Card>
      </Space> },
      { key: 'workflow', label: '工作流编排', children: <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Alert type="info" showIcon message="LIM 托管固定版本的只读 DAG、父 Run 与子 Trace。当前调度为单进程同步执行；不表示服务重启后可恢复。证据冲突只分类，不自动选取结论。" />
        <Card title="Workflow Registry" extra={<Button type="primary" onClick={() => void createWorkflow()}>登记 Workflow 草稿</Button>}>
          <Table rowKey="workflow_id" size="small" pagination={false} dataSource={workflows} columns={[
            { title: 'Workflow', render: (_, row) => <>{row.display_name}<div style={{ color: '#888' }}>{row.workflow_id} · {row.business_domain}</div></> },
            { title: '版本', render: (_, row) => row.versions.map((v) => <Tag key={v.version} color={v.status === 'validated' ? 'green' : 'default'}>{v.version} · {v.status}</Tag>) },
            { title: '操作', render: (_, row) => <Space>{row.versions.filter((v) => v.status === 'draft').map((v) => <Button key={v.version} size="small" onClick={() => void validateWorkflow(row, v.version)}>校验 v{v.version}</Button>)}<Button size="small" onClick={() => setSelectedWorkflowId(row.workflow_id)}>查看 DAG</Button><Button size="small" type="primary" onClick={() => void runWorkflow(row)}>运行已验证版本</Button></Space> },
          ]} />
        </Card>
        {selectedWorkflow && (() => {
          const ver = selectedWorkflow.versions.find((v) => v.status === 'validated') || selectedWorkflow.versions[0]
          const tasks = (ver?.definition as { tasks?: DagTask[] } | undefined)?.tasks || []
          const statusMap = Object.fromEntries(runTasks.map((t) => [t.node_id, String(t.status || '')]))
          return (
            <Card title={`Workflow DAG · ${selectedWorkflow.display_name}`} extra={<Tag color={ver?.status === 'validated' ? 'green' : 'default'}>{ver?.version} · {ver?.status}</Tag>}>
              <WorkflowDag tasks={tasks} statusMap={statusMap} />
              <div style={{ color: '#9aa3b2', fontSize: 12, marginTop: 8 }}>节点颜色：蓝=tool_call，紫=join；运行后为绿=成功、红=失败。join 节点只汇合并分类证据冲突，不自动选取结论。</div>
            </Card>
          )
        })()}
        {workflowResult && <Card title="最近一次 Workflow Run" extra={<Button onClick={() => void openWorkflowTrace(String(workflowResult.workflow_run_id))}>查看 Trace</Button>}><Descriptions items={[{ key: 'workflow', label: 'Workflow', children: `${workflowResult.workflow_id} v${workflowResult.workflow_version}` }, { key: 'status', label: '状态', children: <Tag>{String(workflowResult.status)}</Tag> }, { key: 'run', label: 'Run ID', children: String(workflowResult.workflow_run_id) }]} /><pre style={{ maxHeight: 480, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{pretty(workflowResult.output_summary)}</pre></Card>}
      </Space> },
      { key: 'modelGateway', label: '模型网关', children: <Space direction="vertical" style={{ width: '100%' }} size="large">
        <ModelGatewayOverview metrics={gwMetrics} />
        <ModelGatewayPlayground onComplete={refresh} />
        <Alert type="info" showIcon message="统一模型出口：注册供应商（Key 只存环境变量名，不落库）、别名→模型按场景分流、连通性测试与调用观测。LLM 循环与采购 Agent 共用此处配置。" />
        <Card title="供应商" extra={<Space><Button disabled={!canManageAlerts} onClick={() => void createGwProvider()}>新建供应商</Button></Space>}>
          <Table rowKey="provider_id" size="small" pagination={false} loading={busy} dataSource={gwProviders} columns={[
            { title: 'ID', dataIndex: 'provider_id' },
            { title: '名称', dataIndex: 'name' },
            { title: 'Base URL', dataIndex: 'base_url' },
            { title: 'Key 环境变量', dataIndex: 'api_key_env' },
            { title: '状态', render: (_: unknown, row: LimModelProvider) => <Tag color={row.enabled ? 'green' : 'default'}>{row.enabled ? '启用' : '停用'}</Tag> },
            { title: '操作', render: (_: unknown, row: LimModelProvider) => <Button disabled={!canManageAlerts} size="small" loading={gwBusy} onClick={() => void testGwProvider(row)}>测试连通</Button> },
          ]} />
        </Card>
        <Card title="别名 → 模型" extra={<Button disabled={!canManageAlerts} onClick={() => void createGwCatalog()}>新建别名</Button>}>
          <Table rowKey="alias_id" size="small" pagination={false} loading={busy} dataSource={gwCatalogs} columns={[
            { title: '别名', dataIndex: 'alias' },
            { title: '供应商', dataIndex: 'provider_id' },
            { title: '模型', dataIndex: 'model_name' },
            { title: '场景', dataIndex: 'scene' },
            { title: '状态', render: (_: unknown, row: LimModelCatalogEntry) => <Tag color={row.enabled ? 'green' : 'default'}>{row.enabled ? '启用' : '停用'}</Tag> },
            { title: '操作', render: (_: unknown, row: LimModelCatalogEntry) => <Button disabled={!canManageAlerts} size="small" danger onClick={() => void disableGwCatalog(row)}>停用</Button> },
          ]} />
        </Card>
        {gwTestResult && <Alert type={gwTestResult.ok ? 'success' : 'warning'} showIcon closable onClose={() => setGwTestResult(null)} message={pretty(gwTestResult)} />}
        <Card title="最近模型调用" loading={busy}>
          <Table rowKey="call_id" size="small" pagination={false} dataSource={gwCalls} expandable={{
            rowExpandable: (row) => row.attempts.length > 0,
            expandedRowRender: (row) => <Table rowKey="number" size="small" pagination={false} dataSource={row.attempts} columns={[
              { title: '尝试', dataIndex: 'number' }, { title: '供应商', dataIndex: 'provider_id' },
              { title: '模型', dataIndex: 'model' }, { title: '状态', dataIndex: 'status' },
              { title: '错误码', dataIndex: 'error_code' }, { title: '耗时 (ms)', dataIndex: 'latency_ms' },
            ]} />,
          }} columns={[
            { title: '场景', dataIndex: 'scene' },
            { title: '尝试次数', dataIndex: 'attempt_count' },
            { title: '时间', dataIndex: 'created_at', render: (v: string) => new Date(v).toLocaleString() },
            { title: '供应商', dataIndex: 'provider_id' },
            { title: '模型', dataIndex: 'model' },
            { title: '状态', dataIndex: 'status', render: (v: string) => <Tag color={v === 'SUCCEEDED' ? 'green' : 'red'}>{v}</Tag> },
            { title: '耗时ms', dataIndex: 'latency_ms' },
            { title: 'Tokens', dataIndex: 'total_tokens' },
            { title: '错误', dataIndex: 'error_code' },
          ]} />
        </Card>
      </Space> },
      { key: 'security', label: '安全与治理', children: <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Alert type="info" showIcon message="本页策略值由后端从实际执行代码汇总（GET /api/v1/lim/safety/overview），与运行时强制一致，不是静态文案。只读端点，需要 assistant:read。" />
        {safetyOverview ? <>
          <Card title="运行时策略">
            <Descriptions column={{ xs: 1, sm: 2 }} size="small" items={[
              { key: 'stage', label: '阶段', children: <Tag color={safetyOverview.runtime.live_write_execution ? 'orange' : 'green'}>{safetyOverview.runtime.stage}</Tag> },
              { key: 'write', label: 'Live 写执行', children: <Tag color="red">{String(safetyOverview.runtime.live_write_execution)}</Tag> },
              { key: 'allowlist', label: '只读工具白名单', children: `${safetyOverview.runtime.read_tool_allowlist.length} 个` },
              { key: 'sandbox', label: 'Sandbox 预算', children: JSON.stringify(safetyOverview.runtime.sandbox.budget) },
            ]} />
            <div style={{ marginTop: 12 }}><Tag color="blue">只读工具</Tag>{safetyOverview.runtime.read_tool_allowlist.map((id) => <Tag key={id}>{id}</Tag>)}</div>
            <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>{safetyOverview.runtime.write_tool_policy}</Typography.Paragraph>
          </Card>
          <Card title="运行预算与状态机">
            <Descriptions column={{ xs: 1, sm: 2 }} size="small" items={[
              { key: 'budget', label: 'Run 默认预算', children: <code>{JSON.stringify(safetyOverview.run_budget_defaults)}</code> },
              { key: 'states', label: '状态', children: safetyOverview.state_machine.states.join(' → ') },
              { key: 'terminal', label: '终态', children: safetyOverview.state_machine.terminal_states.join(', ') },
            ]} />
          </Card>
          <Card title="Schema 校验与脱敏">
            <Descriptions column={{ xs: 1, sm: 2 }} size="small" items={[
              { key: 'schema', label: 'Schema 校验', children: safetyOverview.schema_validation.enforced ? <Tag color="green">强制</Tag> : '未启用' },
              { key: 'types', label: '类型', children: safetyOverview.schema_validation.types.join(', ') },
              { key: 'checks', label: '规则', children: safetyOverview.schema_validation.checks.join(', ') },
              { key: 'secret', label: '密钥字段', children: <code style={{ fontSize: 12 }}>{safetyOverview.redaction.secret_key_pattern}</code> },
              { key: 'pii', label: 'PII 字段', children: <code style={{ fontSize: 12 }}>{safetyOverview.redaction.pii_key_pattern}</code> },
              { key: 'limits', label: '脱敏上限', children: JSON.stringify(safetyOverview.redaction.limits) },
            ]} />
          </Card>
          <Card title="身份与数据范围">
            <Descriptions column={{ xs: 1, sm: 2 }} size="small" items={[
              { key: 'perm', label: '运行时权限', children: <Tag>{safetyOverview.identity_and_scope.runtime_permission}</Tag> },
              { key: 'manage', label: '管理权限', children: <Tag>{safetyOverview.identity_and_scope.manage_permission}</Tag> },
              { key: 'scope', label: '范围模型', children: safetyOverview.identity_and_scope.scope_model },
              { key: 'tenant', label: '租户隔离', children: <Tag color={safetyOverview.identity_and_scope.tenant_isolation === 'implemented' ? 'green' : 'orange'}>{safetyOverview.identity_and_scope.tenant_isolation}</Tag> },
            ]} />
          </Card>
          <Card title="近期安全审计">
            <Table rowKey={(row) => `${row.resource}:${row.action}:${row.record_id ?? ''}:${row.created_at ?? ''}`} size="small" pagination={{ pageSize: 5 }} dataSource={safetyOverview.audit} columns={[
              { title: '资源', dataIndex: 'resource' },
              { title: '动作', dataIndex: 'action' },
              { title: '对象', dataIndex: 'record_id' },
              { title: '操作者', dataIndex: 'actor_id' },
              { title: '时间', dataIndex: 'created_at', render: (v: string | null) => v ? new Date(v).toLocaleString() : '' },
            ]} />
          </Card>
          <Card title="已知限制（本阶段）"><ul style={{ margin: 0, paddingLeft: 18 }}>{safetyOverview.known_limits.map((limit) => <li key={limit}>{limit}</li>)}</ul></Card>
        </> : <Card loading>加载安全策略概览中…</Card>}
      </Space> },
      { key: 'diagnosis', label: '多智能体联合诊断', children: <DiagnosisSection /> },
      { key: 'alerts', label: `运行告警${alerts.filter((item) => item.status === 'OPEN').length ? ` (${alerts.filter((item) => item.status === 'OPEN').length})` : ''}`, children: <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Alert type="info" showIcon message="本页提供本地告警记录、确认/关闭和阈值管理。邮件、Slack、PagerDuty 等生产通知尚未配置。" />
        <Card title="告警规则"><Table rowKey="rule_key" size="small" pagination={false} dataSource={alertRules} columns={[
          { title: '规则', render: (_, row) => <>{row.display_name}<div style={{ color: '#888' }}>{row.rule_key}</div></> },
          { title: '启用', dataIndex: 'enabled', render: (value, row) => canManageAlerts ? <Switch checked={value} onChange={(checked) => setAlertRules((items) => items.map((item) => item.rule_key === row.rule_key ? { ...item, enabled: checked } : item))} /> : <Tag color={value ? 'green' : 'default'}>{value ? '启用' : '停用'}</Tag> },
          { title: '触发次数', dataIndex: 'threshold', render: (value, row) => <InputNumber disabled={!canManageAlerts} min={1} max={1000} value={value} onChange={(next) => next && setAlertRules((items) => items.map((item) => item.rule_key === row.rule_key ? { ...item, threshold: next } : item))} /> },
          { title: '统计窗口（秒）', dataIndex: 'window_seconds', render: (value, row) => <InputNumber disabled={!canManageAlerts} min={60} max={86400} step={60} value={value} onChange={(next) => next && setAlertRules((items) => items.map((item) => item.rule_key === row.rule_key ? { ...item, window_seconds: next } : item))} /> },
          { title: '操作', render: (_, row) => canManageAlerts ? <Button size="small" type="primary" onClick={() => void saveAlertRule(row)}>保存</Button> : null },
        ]} /></Card>
        <Card title="告警记录"><Table rowKey="alert_id" size="small" pagination={{ pageSize: 10 }} dataSource={alerts} columns={[
          { title: '告警', render: (_, row) => <>{row.summary}<div style={{ color: '#888' }}>{row.entity_label} · {row.error_code}</div></> },
          { title: '状态', dataIndex: 'status', render: (value) => <Tag color={value === 'OPEN' ? 'red' : value === 'ACKNOWLEDGED' ? 'blue' : 'default'}>{value}</Tag> },
          { title: '次数 / 最近发生', render: (_, row) => <>{row.occurrence_count} 次<div style={{ color: '#888' }}>{new Date(row.last_seen_at).toLocaleString()}</div></> },
          { title: '链路', render: (_, row) => <Space>{row.trace_id && <Button size="small" type="link" onClick={() => void openTrace(row.trace_id!)}>Run / Trace</Button>}{row.workflow_run_id && <Button size="small" type="link" onClick={() => void openWorkflowTrace(row.workflow_run_id!)}>Workflow Trace</Button>}</Space> },
          { title: '操作', render: (_, row) => canManageAlerts ? <Space>{row.status === 'OPEN' && <Button size="small" onClick={() => void changeAlert(row, 'acknowledge')}>确认</Button>}{row.status !== 'CLOSED' && <Button size="small" danger onClick={() => void changeAlert(row, 'close')}>关闭</Button>}</Space> : null },
        ]} /></Card>
      </Space> },
      { key: 'skills', label: '记忆与技能治理', children: <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Alert type="warning" showIcon message="本页只管理候选、审核、验证和版本状态。Skill 内容不会自动写入 Memory、拼入模型提示词或执行；当前使用量与纠错量保持真实记录值。" />
        <Card title="Skill Registry" extra={<Button type="primary" onClick={() => void createSkill()}>登记 Skill 候选</Button>}>
          <Table rowKey={(row) => `${row.skill_id}:${row.version}`} size="small" pagination={{ pageSize: 10 }} loading={busy} dataSource={skills} columns={skillColumns} />
        </Card>
      </Space> },
    ]} />
    <Modal open={!!modal} title={modal?.title} onCancel={() => setModal(null)} footer={<Space>{modal?.traceId && <Button onClick={() => void exportTrace(modal.traceId!)}>下载 JSON</Button>}<Button onClick={() => setModal(null)}>关闭</Button></Space>} width={760}>
      <pre style={{ maxHeight: '65vh', overflow: 'auto', whiteSpace: 'pre-wrap' }}>{pretty(modal?.value)}</pre>
    </Modal>
  </div>
}
