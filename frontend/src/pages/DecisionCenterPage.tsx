import { useEffect, useState } from 'react'
import { Alert, Button, Card, DatePicker, Descriptions, Drawer, Empty, Input, InputNumber, Pagination, Select, Space, Table, Tabs, Tag, Timeline, Typography, message } from 'antd'
import dayjs from 'dayjs'
import { Link } from 'react-router-dom'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

type Event = { at: string; actor_id: string; action: string; reason?: string }
type Risk = { id: string; risk_type: string; severity: string; status: string; detected_at: string; business_date: string;
  metrics: { net_gap: number; time_shortfall: number; first_shortage_date: string | null; daily_sales: number };
  source: { sku_code: string; sku_id: string; system: string; evidence_hash: string; inventory_basis: string }; history: Event[] }
type Task = { id: string; risk_id: string; objective: string; status: string; created_at: string; selected_version: string | null;
  execution: { id?: string; plan_no?: string; status?: string; quantity?: number }; history: Event[] }
type Calculation = { purchase_qty: number; shipping_qty: number; purchase_amount: string; total_amount: string; currency: string;
  time_shortfall: number; first_shortage_date: string; horizon_days: number; issues: { message: string }[];
  trajectory: { date: string; opening: number; arrivals: number; demand: number; closing: number; shortfall: number }[] }
type Scenario = { name: string; hypothetical: boolean; demand_factor: number; assumption: string; calculation: Calculation; constraints_satisfied: boolean; limitations: string[] }
type Version = { id: string; version: number; evidence_hash: string; calculation_version: string; expires_at: string;
  snapshot: Record<string, unknown>; scenarios: Scenario[] }
type Detail = { task: Task; risk: Risk; versions: Version[] }
const root = '/decision-center'
const names: Record<string, string> = { OPEN: '待处理', IN_PROGRESS: '处理中', RESOLVED: '已解决', DISMISSED: '已忽略', DRAFT: '待生成 / 待提交', SUBMITTED: '待审批', APPROVED: '已批准，待执行', REJECTED: '已驳回', EXECUTED: '已生成 ERP 草案', CONFIRMED: '已核对 ERP 记录', DETECTED: '检测到风险', CREATED: '创建任务', SIMULATED: '保存仿真版本', PRECHECK_PASSED: '执行前校验通过', RESULT_CONFIRMED: 'ERP 结果确认', STRATEGY_CREATED: '关联策略任务' }
const status = (value: string) => <Tag color={value === 'APPROVED' || value === 'CONFIRMED' ? 'green' : value === 'SUBMITTED' ? 'orange' : 'blue'}>{names[value] || value}</Tag>
const formatTime = (value: string) => dayjs(value.endsWith('Z') ? value : `${value}Z`).format('YYYY-MM-DD HH:mm:ss')
const eventItems = (events: Event[]) => events.map((e, i) => ({ key: `${e.at}-${i}`, children: <><b>{names[e.action] || e.action}</b><div>{formatTime(e.at)} · {e.actor_id}</div>{e.reason && <div>{e.reason}</div>}</> }))

export default function DecisionCenterPage({ initialTab = 'risks' }: { initialTab?: string }) {
  const { user } = useAuth()
  const can = (p: string) => user?.role === 'admin' || !!user?.permissions.includes(p)
  const [tab, setTab] = useState(initialTab)
  const [profiles, setProfiles] = useState<{ id: string; name: string }[]>([])
  const [profile, setProfile] = useState<string>()
  const [date, setDate] = useState(dayjs())
  const [risks, setRisks] = useState<Risk[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [riskTotal, setRiskTotal] = useState(0)
  const [taskTotal, setTaskTotal] = useState(0)
  const [riskPage, setRiskPage] = useState(1)
  const [taskPage, setTaskPage] = useState(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [riskDetail, setRiskDetail] = useState<{ risk: Risk; tasks: Task[] }>()
  const [detail, setDetail] = useState<Detail>()
  const [versionId, setVersionId] = useState<string>()
  const [factor, setFactor] = useState<number | null>(0.8)
  const [assumption, setAssumption] = useState('')
  const [objective, setObjective] = useState('在采购预算与交期约束内降低 SKU 缺货风险')
  const [reason, setReason] = useState('')
  const version = detail?.versions.find(x => x.id === versionId) ?? detail?.versions[0]

  const refresh = async () => {
    const [r, t, p] = await Promise.all([
      request<{ items: Risk[]; total: number }>(root + '/risks', { params: { page: riskPage } }),
      request<{ items: Task[]; total: number }>(root + '/tasks', { params: { page: taskPage } }),
      request<{ items: { id: string; name: string }[] }>('/purchase-agent/profiles'),
    ])
    setRisks(r.items); setRiskTotal(r.total); setTasks(t.items); setTaskTotal(t.total); setProfiles(p.items)
  }
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError('')
    try { await fn() } catch (e) { setError(e instanceof Error ? e.message : '操作失败，请重试') }
    finally { setBusy(false) }
  }
  useEffect(() => { void run(refresh) }, [riskPage, taskPage])
  useEffect(() => { setTab(initialTab) }, [initialTab])
  const openTask = async (id: string) => {
    const data = await request<Detail>(root + '/tasks/' + id)
    setDetail(data); setVersionId(data.task.selected_version ?? data.versions[0]?.id)
  }
  const act = async (action: string, body?: unknown) => {
    if (!detail) return
    await request(root + '/tasks/' + detail.task.id + '/' + action, { method: 'POST', body })
    await openTask(detail.task.id); await refresh()
    message.success('操作已保存')
  }
  const tasksTable = (items: Task[]) => <Table rowKey="id" dataSource={items} loading={busy} pagination={false} scroll={{ x: 800 }} columns={[
    { title: '经营目标', dataIndex: 'objective' }, { title: '任务 ID', dataIndex: 'id', ellipsis: true },
    { title: '状态', dataIndex: 'status', render: status }, { title: '创建时间', dataIndex: 'created_at', render: formatTime },
    { title: '操作', render: (_, row) => <Button onClick={() => void run(() => openTask(row.id))}>查看策略与审批</Button> },
  ]} />

  return <Space direction="vertical" size={20} style={{ width: '100%', padding: 24 }}>
    <div><Typography.Title level={3}>经营风险与策略中心</Typography.Title><Typography.Text type="secondary">从 ERP 证据发现风险，比较补货方案，经审批后生成采购草案并回读确认。</Typography.Text></div>
    {error && <Alert type="error" showIcon message="操作未完成" description={error} closable onClose={() => setError('')} />}
    <Alert type="info" showIcon message="确定性补货场景" description="需求倍率是人工假设，不代表广告效果预测。审批通过后仍需手动执行；执行只生成 ERP 采购计划草稿，后续采购与运输需继续业务流程。" />
    <Tabs activeKey={tab} onChange={setTab} items={[
      { key: 'risks', label: '风险中心', children: <Space direction="vertical" style={{ width: '100%' }} size={16}>
        <Card title="检测库存缺货风险"><Space wrap>
          <Select aria-label="补货配置" placeholder="选择已配置的 SKU 补货资料" style={{ minWidth: 280 }} value={profile} onChange={setProfile} options={profiles.map(p => ({ value: p.id, label: p.name }))} />
          <DatePicker aria-label="业务日期" value={date} allowClear={false} onChange={d => d && setDate(d)} />
          <Button type="primary" loading={busy} disabled={!profile || !can('purchase_agent:write')} onClick={() => void run(async () => {
            const r = await request<{ risk: Risk | null; issues: { message: string }[]; status: string }>(root + '/risks/detect', { method: 'POST', body: { profile_id: profile, business_date: date.format('YYYY-MM-DD') } })
            if (r.issues.length) setError(r.issues.map(x => x.message).join('；'))
            else message.info(r.risk ? '风险已登记，相同证据不会重复创建' : '当前未检测到缺货风险')
            await refresh()
          })}>检测并登记</Button>
          <Button onClick={() => void run(refresh)} loading={busy}>刷新</Button><Link to="/purchase-agent">维护补货资料</Link>
        </Space>{!profiles.length && <Empty description="暂无可用补货配置，请先维护 SKU、库存、报价及销量完整性资料" />}</Card>
        <Table<Risk> rowKey="id" dataSource={risks} loading={busy} scroll={{ x: 900 }} pagination={{ current: riskPage, pageSize: 20, total: riskTotal, showSizeChanger: false, onChange: setRiskPage }} columns={[
          { title: 'SKU / 风险 ID', render: (_, r) => <><b>{r.source.sku_code}</b><div style={{ fontSize: 11 }}>{r.id}</div></> },
          { title: '风险类型', render: () => '库存缺货' }, { title: '严重程度', dataIndex: 'severity', render: v => <Tag color={v === 'HIGH' ? 'red' : 'orange'}>{v === 'HIGH' ? '高' : '中'}</Tag> },
          { title: '目标缺口 / 时效缺口', render: (_, r) => `${r.metrics.net_gap} / ${r.metrics.time_shortfall} 件` },
          { title: '状态', dataIndex: 'status', render: status }, { title: '检测时间', dataIndex: 'detected_at', render: formatTime },
          { title: '操作', render: (_, r) => <Button onClick={() => void run(async () => { setRiskDetail(await request(root + '/risks/' + r.id)); setReason('') })}>风险详情</Button> },
        ]} />
      </Space> },
      { key: 'tasks', label: '策略 · 仿真 · 审批 · 记录', children: <Card title="策略任务" extra={<Button loading={busy} onClick={() => void run(refresh)}>刷新</Button>}>
        {tasksTable(tasks)}<Pagination current={taskPage} pageSize={20} total={taskTotal} showSizeChanger={false} onChange={setTaskPage} style={{ marginTop: 16 }} />
      </Card> },
    ]} />
    <Drawer title="风险详情与处理" width={760} open={!!riskDetail} onClose={() => setRiskDetail(undefined)}>
      {riskDetail && <Space direction="vertical" style={{ width: '100%' }} size={18}>
        {error && <Alert type="error" message={error} />}
        <Descriptions column={1} bordered items={[
          { key: 'id', label: '风险 ID', children: riskDetail.risk.id }, { key: 'sku', label: '关联 SKU', children: riskDetail.risk.source.sku_code },
          { key: 'state', label: '状态', children: status(riskDetail.risk.status) }, { key: 'source', label: '数据来源', children: riskDetail.risk.source.system },
          { key: 'basis', label: '库存口径', children: riskDetail.risk.source.inventory_basis }, { key: 'hash', label: '证据摘要', children: <Typography.Text copyable>{riskDetail.risk.source.evidence_hash}</Typography.Text> },
        ]} />
        <Typography.Text>目标缺口 {riskDetail.risk.metrics.net_gap} 件；按补货方案仍有时效缺口 {riskDetail.risk.metrics.time_shortfall} 件。</Typography.Text>
        <Input aria-label="经营目标" value={objective} onChange={e => setObjective(e.target.value)} maxLength={300} />
        <Button type="primary" loading={busy} disabled={!can('purchase_agent:write') || !objective.trim() || ['RESOLVED', 'DISMISSED'].includes(riskDetail.risk.status)} onClick={() => void run(async () => {
          const t = await request<Task>(root + '/tasks', { method: 'POST', body: { risk_id: riskDetail.risk.id, objective } })
          setRiskDetail(undefined); await openTask(t.id); setTab('tasks'); await refresh()
        })}>创建策略分析任务</Button>
        <Input.TextArea aria-label="风险处理理由" placeholder="处理理由（必填）" value={reason} onChange={e => setReason(e.target.value)} maxLength={500} />
        <Space wrap>{['IN_PROGRESS', 'RESOLVED', 'DISMISSED'].map(s => <Button key={s} disabled={busy || !reason.trim() || !can('purchase_agent:write')} onClick={() => void run(async () => {
          await request(root + '/risks/' + riskDetail.risk.id + '/status', { method: 'POST', body: { status: s, reason } })
          setRiskDetail(await request(root + '/risks/' + riskDetail.risk.id)); await refresh()
        })}>{names[s]}</Button>)}</Space>
        {tasksTable(riskDetail.tasks)}<Timeline items={eventItems(riskDetail.risk.history)} />
      </Space>}
    </Drawer>
    <Drawer title="策略方案、版本与受控执行" width="90%" open={!!detail} onClose={() => { setDetail(undefined); setVersionId(undefined) }}>
      {detail && <Space direction="vertical" style={{ width: '100%' }} size={20}>
        {error && <Alert type="error" message={error} />}
        <Typography.Title level={4}>{detail.task.objective} {status(detail.task.status)}</Typography.Title>
        <Typography.Text type="secondary">任务 {detail.task.id} · 风险 {detail.task.risk_id} · SKU {detail.risk.source.sku_code}</Typography.Text>
        {['DRAFT', 'REJECTED'].includes(detail.task.status) && <Card title="生成候选方案并确定性仿真">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space wrap><Typography.Text>人工需求倍率（选填，基准 1 始终保留）</Typography.Text><InputNumber aria-label="人工需求倍率" min={0.01} max={3} step={0.1} value={factor} onChange={setFactor} /></Space>
            <Input.TextArea aria-label="需求情景假设" placeholder="使用非 1 倍率时，填写人工假设；例如：活动收缩后需求暂按基准的 80% 估算" value={assumption} onChange={e => setAssumption(e.target.value)} maxLength={500} />
            <Button type="primary" loading={busy} disabled={!can('purchase_agent:write') || (!!factor && factor !== 1 && !assumption.trim())} onClick={() => void run(() => act('versions', { demand_factors: factor && factor !== 1 ? [1, factor] : [1], assumption }))}>生成并保存新版本</Button>
          </Space>
        </Card>}
        {version ? <>
          <Space wrap><Select aria-label="策略版本" disabled={['SUBMITTED', 'APPROVED', 'EXECUTED'].includes(detail.task.status)} style={{ width: 180 }} value={version.id} onChange={setVersionId} options={detail.versions.map(v => ({ value: v.id, label: `版本 ${v.version}${v.id === detail.task.selected_version ? '（已选）' : ''}` }))} /><Typography.Text>计算版本 {version.calculation_version} · 有效期至 {formatTime(version.expires_at)}</Typography.Text></Space>
          <Table<Scenario> rowKey="name" pagination={false} scroll={{ x: 1000 }} dataSource={version.scenarios} expandable={{ expandedRowRender: s => <>
            <Alert type="info" message={s.assumption} description={s.limitations.join(' ')} />
            {s.calculation.issues.map((x, i) => <Alert key={i} type="warning" message={x.message} />)}
            <Table rowKey="date" size="small" dataSource={s.calculation.trajectory} pagination={{ pageSize: 7 }} columns={[
              { title: '日期', dataIndex: 'date' }, { title: '期初', dataIndex: 'opening' }, { title: '到货', dataIndex: 'arrivals' },
              { title: '假设需求', dataIndex: 'demand' }, { title: '期末', dataIndex: 'closing' }, { title: '缺口', dataIndex: 'shortfall' },
            ]} />
          </> }} columns={[
            { title: '方案', dataIndex: 'name', render: (v, s) => <>{v} {s.hypothetical && <Tag>人工情景</Tag>}</> },
            { title: '采购 / 发货建议', render: (_, s) => `${s.calculation.purchase_qty ?? '—'} / ${s.calculation.shipping_qty ?? '—'} 件` },
            { title: '采购资金', render: (_, s) => `${s.calculation.purchase_amount ?? '—'} ${s.calculation.currency ?? ''}` },
            { title: '采购与运费合计', render: (_, s) => `${s.calculation.total_amount ?? '—'} ${s.calculation.currency ?? ''}` },
            { title: '时效缺口', render: (_, s) => `${s.calculation.time_shortfall ?? '—'} 件` },
            { title: '约束', render: (_, s) => <Tag color={s.constraints_satisfied ? 'green' : 'red'}>{s.constraints_satisfied ? '满足' : '不满足'}</Tag> },
            { title: '操作', render: (_, s, i) => <Button disabled={busy || detail.task.status !== 'DRAFT' || s.hypothetical || !s.constraints_satisfied || !s.calculation.purchase_qty || !can('purchase_agent:write')} onClick={() => void run(() => act('submit', { version_id: version.id, scenario_index: i }))}>提交审批</Button> },
          ]} />
          <details><summary>数据快照与证据摘要（{version.evidence_hash}）</summary><pre style={{ maxHeight: 400, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{JSON.stringify(version.snapshot, null, 2)}</pre></details>
        </> : <Empty description="尚无候选方案，请先生成版本" />}
        <Space wrap>
          {detail.task.status === 'SUBMITTED' && <Button type="primary" loading={busy} disabled={!can('purchase_agent_drafts:write')} onClick={() => void run(() => act('approve'))}>审批通过（不执行）</Button>}
          {detail.task.status === 'APPROVED' && <Button type="primary" loading={busy} disabled={!can('purchase_agent_drafts:write') || !can('purchase_plans:write')} onClick={() => void run(() => act('execute'))}>执行前校验并生成 ERP 采购草案</Button>}
          {detail.task.status === 'EXECUTED' && <Button type="primary" loading={busy} disabled={!can('purchase_agent_drafts:write')} onClick={() => void run(() => act('confirm'))}>回读并确认 ERP 记录</Button>}
        </Space>
        {['SUBMITTED', 'APPROVED'].includes(detail.task.status) && <Space><Input aria-label="驳回理由" placeholder="驳回理由" value={reason} onChange={e => setReason(e.target.value)} maxLength={500} /><Button danger disabled={busy || !reason.trim() || !can('purchase_agent_drafts:write')} onClick={() => void run(() => act('reject', { reason }))}>驳回</Button></Space>}
        {detail.task.execution.id && <Alert type="success" message={`ERP 采购计划 ${detail.task.execution.plan_no} · ${detail.task.execution.quantity} 件`} description={<span>已生成草稿，尚未实际采购。<Link to="/purchase-plans">进入采购计划继续处理</Link></span>} />}
        <Card title="任务与执行记录"><Timeline items={eventItems(detail.task.history)} /></Card>
      </Space>}
    </Drawer>
  </Space>
}
