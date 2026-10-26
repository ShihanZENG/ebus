import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, DatePicker, Descriptions, Empty, Select, Space, Table, Tag, Typography, message } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { request } from '../api/client'
import { limApi, type LimAgent, type LimRun, type LimTool } from '../api/lim'
import { useAuth } from '../auth/AuthProvider'

type Profile = { id: string; name: string; sku_id: string; shop_id: string; destination_id: string }
type RunResult = LimRun & { output_summary?: Record<string, unknown> }
type TraceResult = Record<string, unknown>
const REPLENISHMENT_AGENT = 'erp.replenishment'
const REPLENISHMENT_TOOL = 'erp.replenishment.evidence'
const today = dayjs().format('YYYY-MM-DD')
const pretty = (value: unknown) => JSON.stringify(value, null, 2)

export default function LimReplenishmentPage() {
  const { user } = useAuth()
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [agents, setAgents] = useState<LimAgent[]>([])
  const [tools, setTools] = useState<LimTool[]>([])
  const [profileId, setProfileId] = useState<string>()
  const [businessDate, setBusinessDate] = useState<Dayjs | null>(dayjs(today))
  const [run, setRun] = useState<RunResult | null>(null)
  const [trace, setTrace] = useState<TraceResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [profilesLoading, setProfilesLoading] = useState(true)
  const [profilesError, setProfilesError] = useState<string | null>(null)
  const [toolsLoading, setToolsLoading] = useState(false)
  const [toolsError, setToolsError] = useState<string | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [traceError, setTraceError] = useState<string | null>(null)
  const agent = useMemo(() => agents.find((row) => row.agent_id === REPLENISHMENT_AGENT && row.status === 'validated'), [agents])
  const tool = useMemo(() => tools.find((row) => row.tool_id === REPLENISHMENT_TOOL), [tools])
  const canReadAssistant = user?.role === 'admin' || user?.permissions.includes('assistant:read')

  const refresh = useCallback(async () => {
    setProfilesLoading(true)
    setProfilesError(null)
    try {
      const [p, a] = await Promise.all([
        request<{ items: Profile[] }>('/purchase-agent/profiles'),
        limApi.agents(),
      ])
      setProfiles(p.items)
      setAgents(a.items)
      if (!profileId && p.items.length) setProfileId(p.items[0].id)
    } catch (error) { setProfilesError(error instanceof Error ? error.message : '加载补货配置或 LIM Agent 失败') }
    finally { setProfilesLoading(false) }
  }, [profileId])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    setTools([])
    setToolsError(null)
    if (!agent) { setToolsLoading(false); return }
    let cancelled = false
    setToolsLoading(true)
    limApi.agentTools(agent.agent_id, agent.version)
      .then((result) => { if (!cancelled) setTools(result.items) })
      .catch((error) => { if (!cancelled) setToolsError(error instanceof Error ? error.message : '读取补货 Agent 的只读工具失败') })
      .finally(() => { if (!cancelled) setToolsLoading(false) })
    return () => { cancelled = true }
  }, [agent?.agent_id, agent?.version])

  const start = async () => {
    if (!canReadAssistant) { message.error('运行补货证据还需要 assistant:read 权限'); return }
    if (!profileId || !businessDate || !agent || !tool) { message.warning('请先选择补货配置，并由管理员在 LIM 运行治理中登记并验证补货 Agent/Tool'); return }
    setBusy(true)
    setRunError(null)
    setRun(null)
    setTrace(null)
    setTraceError(null)
    try {
      const result = await limApi.run({
        agent_id: agent.agent_id,
        agent_version: agent.version,
        goal: `只读采集补货证据并进行确定性测算：${profileId}，业务截止日 ${businessDate.format('YYYY-MM-DD')}`,
        tool_invocation: {
          tool_id: tool.tool_id,
          tool_version: tool.version,
          arguments: { profile_id: profileId, business_date: businessDate.format('YYYY-MM-DD') },
        },
      })
      setRun(result as RunResult)
      message.success(`补货证据 Run ${result.status}`)
    } catch (error) { setRunError(error instanceof Error ? error.message : '补货证据采集失败') }
    finally { setBusy(false) }
  }

  const openTrace = async () => {
    if (!run?.trace_id) return
    setTraceError(null)
    try { setTrace(await limApi.trace(run.trace_id)) }
    catch (error) { setTraceError(error instanceof Error ? error.message : '读取 Trace 失败') }
  }

  const output = run?.output_summary ?? {}
  const blockers = Array.isArray(output.blockers) ? output.blockers as Array<Record<string, unknown>> : []
  return <div aria-busy={profilesLoading || busy} style={{ padding: 24 }}>
    <Space style={{ justifyContent: 'space-between', width: '100%', marginBottom: 16 }}>
      <div><Typography.Title level={3} style={{ margin: 0 }}>LIM 补货证据</Typography.Title><Typography.Text type="secondary">从 ERP 业务源读取补货证据并运行确定性规则；本页面不会创建或审批采购草稿。</Typography.Text></div>
      <Button onClick={() => void refresh()} loading={profilesLoading}>刷新</Button>
    </Space>
    {profilesError && <Alert role="alert" type="error" showIcon message="补货配置加载失败" description={profilesError} action={<Button size="small" loading={profilesLoading} onClick={() => void refresh()}>重试</Button>} style={{ marginBottom: 16 }} />}
    {profilesLoading && <span role="status" aria-live="polite" className="visually-hidden">正在加载补货配置</span>}
    {!canReadAssistant && <Alert type="warning" showIcon message="当前账号可查看补货配置；运行证据还需要 assistant:read 权限。" style={{ marginBottom: 16 }} />}
    {toolsLoading && <span role="status" aria-live="polite" className="visually-hidden">正在读取补货工具</span>}
    {toolsError && <Alert role="alert" type="error" showIcon style={{ marginBottom: 16 }} message="读取补货工具失败" description={toolsError} action={<Button size="small" onClick={() => { if (agent) { setToolsError(null); setToolsLoading(true); void limApi.agentTools(agent.agent_id, agent.version).then(r => setTools(r.items)).catch(e => setToolsError(e instanceof Error ? e.message : '读取补货 Agent 的只读工具失败')).finally(() => setToolsLoading(false)) } }}>重试</Button>} />}
    {!toolsLoading && !toolsError && (!agent || !tool) && <Alert type="info" showIcon style={{ marginBottom: 16 }} message="补货工具尚未就绪" description={<span>请管理员在 <a href="/lim-console">LIM 运行治理</a> 注册并校验 Agent <code>{REPLENISHMENT_AGENT}</code> 和只读 Tool <code>{REPLENISHMENT_TOOL}</code>（版本 1.0.0），再将 Tool 绑定到 Agent。</span>} />}
    {runError && <Alert role="alert" type="error" showIcon message="补货证据采集失败" description={runError} style={{ marginBottom: 16 }} />}
    <Card title="采集条件" style={{ marginBottom: 16 }}>
      <Space wrap>
        <Select aria-label="补货配置" style={{ width: 360 }} placeholder="选择补货配置" value={profileId} onChange={setProfileId} options={profiles.map((p) => ({ value: p.id, label: `${p.name} · SKU ${p.sku_id.slice(0, 8)}` }))} />
        <DatePicker aria-label="业务截止日期" value={businessDate} onChange={setBusinessDate} format="YYYY-MM-DD" disabledDate={(d) => d.isAfter(dayjs(today), 'day')} />
        <Button type="primary" loading={busy} disabled={!agent || !tool || !profileId || !canReadAssistant} onClick={() => void start()}>运行只读证据采集</Button>
      </Space>
    </Card>
    {traceError && <Alert role="alert" type="error" showIcon message="读取 Trace 失败" description={traceError} style={{ marginBottom: 16 }} />}
    {run && <Card title="最近一次运行" extra={<Button onClick={() => void openTrace()}>查看 Trace</Button>}>
      <Descriptions column={2} items={[
        { key: 'status', label: '状态', children: <Tag color={run.status === 'COMPLETED' ? 'green' : 'red'}>{run.status}</Tag> },
        { key: 'run', label: 'Run ID', children: run.run_id },
        { key: 'hash', label: '证据哈希', children: String(output.evidence_hash ?? '无') },
        { key: 'trace', label: 'Trace ID', children: run.trace_id },
      ]} />
      {blockers.length > 0 && <><Typography.Title level={5}>阻断项</Typography.Title><Table rowKey={(_, i) => String(i)} size="small" pagination={false} dataSource={blockers} columns={[
        { title: '字段', dataIndex: 'field' }, { title: '问题', dataIndex: 'message' }, { title: '责任人', dataIndex: 'owner' },
      ]} /></>}
      {output.calculation != null && <><Typography.Title level={5}>确定性测算</Typography.Title><pre tabIndex={0} role="region" aria-label="确定性测算结果" style={{ maxHeight: 360, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{pretty(output.calculation)}</pre></>}
      {output.evidence != null && <details><summary>展开证据快照</summary><pre tabIndex={0} role="region" aria-label="补货证据快照" style={{ maxHeight: 480, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{pretty(output.evidence)}</pre></details>}
      {trace && <><Typography.Title level={5}>Trace</Typography.Title><pre tabIndex={0} role="region" aria-label="运行 Trace" style={{ maxHeight: 480, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{pretty(trace)}</pre></>}
      <Alert type="info" showIcon message="建议仅供复核" description="如需形成采购建议或待审批草稿，请进入现有采购 Agent 工作台重新采集并按原审批流程处理。" action={<Button size="small" href="/purchase-agent">打开采购 Agent</Button>} style={{ marginTop: 12 }} />
    </Card>}
    {!profilesLoading && !profilesError && !profiles.length && <Empty description="当前范围内没有可读取的补货配置" />}
  </div>
}
