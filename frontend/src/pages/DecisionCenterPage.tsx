import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, DatePicker, Descriptions, Drawer, Empty, Input, Pagination, Select, Space, Table, Tabs, Tag, Timeline, Typography, message } from 'antd'
import dayjs from 'dayjs'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import TaskWorkbench, { type Detail, type Risk, type Task, status, names, formatTime, eventItems } from './TaskWorkbench'
import { nextStage, stages, selectedVersion, safeOrigin, taskUrl, createRequestGuard } from './taskWorkflow'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

const root = '/decision-center'
export default function DecisionCenterPage({ initialTab = 'risks' }: { initialTab?: string }) {
  const { user } = useAuth()
  const { taskId } = useParams()
  const location = useLocation()
  const requests = useRef(createRequestGuard()).current
  const route = useRef(location.pathname)
  if (route.current !== location.pathname) {
    requests.invalidate()
    route.current = location.pathname
  }
  useEffect(() => () => requests.invalidate(), [requests])
  const navigate = useNavigate()
  const [query, setQuery] = useSearchParams()
  const [drawerStage, setDrawerStage] = useState('strategy')

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
  const stage = taskId ? (stages.some(s => s.key === query.get('tab')) ? query.get('tab')! : nextStage(detail?.task.status ?? 'DRAFT', detail?.versions.length ?? 0)) : drawerStage
  const [versionId, setVersionId] = useState<string>()
  const [objective, setObjective] = useState('在采购预算与交期约束内降低 SKU 缺货风险')
  const [reason, setReason] = useState('')
  const activeVersionId = detail ? selectedVersion(detail.task.status, detail.task.selected_version, detail.versions, taskId ? query.get('versionId') : versionId) : undefined
  const changeContext = (next: string, version = activeVersionId) => {
    if (taskId) {
      const params = new URLSearchParams(query)
      params.set('tab', next)
      if (version) params.set('versionId', version); else params.delete('versionId')
      setQuery(params, { replace: true })
    } else { setDrawerStage(next); setVersionId(version) }
  }

  const refresh = async () => {
    const current = requests.capture()
    const [r, t, p] = await Promise.all([
      request<{ items: Risk[]; total: number }>(root + '/risks', { params: { page: riskPage } }),
      request<{ items: Task[]; total: number }>(root + '/tasks', { params: { page: taskPage } }),
      request<{ items: { id: string; name: string }[] }>('/purchase-agent/profiles'),
    ])
    if (current()) { setRisks(r.items); setRiskTotal(r.total); setTasks(t.items); setTaskTotal(t.total); setProfiles(p.items) }
  }
  const run = async (fn: () => Promise<void>) => {
    const current = requests.capture()
    setBusy(true); setError('')
    try { await fn() } catch (e) { if (current()) setError(e instanceof Error ? e.message : '操作失败，请重试') }
    finally { if (current()) setBusy(false) }
  }
  useEffect(() => { if (!taskId) void run(refresh) }, [riskPage, taskPage, taskId])
  useEffect(() => { setTab(initialTab) }, [initialTab])
  const openTask = async (id: string) => {
    const current = requests.capture()
    const data = await request<Detail>(root + '/tasks/' + id)
    if (!current()) return
    setDetail(data); setVersionId(selectedVersion(data.task.status, data.task.selected_version, data.versions))
    setDrawerStage(location.pathname === '/ai-approval-center' ? 'approval' : location.pathname === '/ai-execution-center' ? 'execution' : nextStage(data.task.status, data.versions.length))
  }
  useEffect(() => {
    if (!taskId) { setDetail(undefined); return }
    let cancelled = false
    setDetail(undefined); setError(''); setBusy(true)
    request<Detail>(root + '/tasks/' + encodeURIComponent(taskId))
      .then(data => { if (!cancelled) setDetail(data) })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : '无法加载任务') })
      .finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [taskId, location.pathname])
  const act = async (action: string, body?: unknown) => {
    if (!detail) return
    const current = requests.capture()
    await request(root + '/tasks/' + detail.task.id + '/' + action, { method: 'POST', body })
    if (!current()) return
    const data = await request<Detail>(root + '/tasks/' + detail.task.id)
    if (!current()) return
    setDetail(data)
    changeContext(nextStage(data.task.status, data.versions.length), selectedVersion(data.task.status, data.task.selected_version, data.versions))
    if (!taskId) await refresh()
    message.success('操作已保存')
  }
  const tasksTable = (items: Task[]) => <Table rowKey="id" dataSource={items} loading={busy} pagination={false} scroll={{ x: 800 }} columns={[
    { title: '经营目标', dataIndex: 'objective' }, { title: '任务 ID', dataIndex: 'id', ellipsis: true },
    { title: '状态', dataIndex: 'status', render: status }, { title: '创建时间', dataIndex: 'created_at', render: formatTime },
    { title: '操作', render: (_, row) => <Space><Button type="link" onClick={() => navigate(taskUrl(row.id, location.pathname === '/ai-approval-center' ? 'approval' : location.pathname === '/ai-execution-center' ? 'execution' : 'strategy', location.pathname))}>进入工作台</Button><Button disabled={busy} onClick={() => void run(() => openTask(row.id))}>快速查看</Button></Space> },
  ]} />

  const workbench = detail && (!taskId || detail.task.id === taskId) && <TaskWorkbench key={detail.task.id} detail={detail} busy={busy} error={error} can={can} stage={stage} versionId={activeVersionId} onStage={s => changeContext(s)} onVersion={id => changeContext(stage, id)} onAction={(action, body) => run(() => act(action, body))} />
  if (taskId) return <Space direction="vertical" size={20} style={{ width: '100%', padding: 24 }}>
    <Space><Link to={safeOrigin(query.get('from'))}>返回任务列表</Link><Button loading={busy} onClick={() => void run(async () => { const current = requests.capture(); const data = await request<Detail>(root + '/tasks/' + taskId); if (current()) setDetail(data) })}>刷新任务状态</Button></Space>
    <Typography.Title level={3}>补货任务工作台</Typography.Title>
    {!detail && (error ? <Alert type="error" message="无法打开任务" description={error} /> : <Card loading={busy}><Empty description="任务加载中" /></Card>)}
    {workbench}
  </Space>
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
          setRiskDetail(undefined); navigate(taskUrl(t.id, 'strategy', location.pathname))
        })}>创建策略分析任务</Button>
        <Input.TextArea aria-label="风险处理理由" placeholder="处理理由（必填）" value={reason} onChange={e => setReason(e.target.value)} maxLength={500} />
        <Space wrap>{['IN_PROGRESS', 'RESOLVED', 'DISMISSED'].map(s => <Button key={s} disabled={busy || !reason.trim() || !can('purchase_agent:write')} onClick={() => void run(async () => {
          await request(root + '/risks/' + riskDetail.risk.id + '/status', { method: 'POST', body: { status: s, reason } })
          setRiskDetail(await request(root + '/risks/' + riskDetail.risk.id)); await refresh()
        })}>{names[s]}</Button>)}</Space>
        {tasksTable(riskDetail.tasks)}<Timeline items={eventItems(riskDetail.risk.history)} />
      </Space>}
    </Drawer>
    <Drawer title="任务快速查看" width="90%" open={!!detail} onClose={() => { requests.invalidate(); setBusy(false); setDetail(undefined); setVersionId(undefined) }} extra={detail && <Space><Button loading={busy} onClick={() => void run(() => openTask(detail.task.id))}>刷新状态</Button><Link to={taskUrl(detail.task.id, stage, location.pathname, activeVersionId)}>打开完整工作台</Link></Space>}>
      {workbench}
    </Drawer>
  </Space>
}
