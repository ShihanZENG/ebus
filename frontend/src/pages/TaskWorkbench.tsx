import { useState } from 'react'
import { Alert, Button, Card, Descriptions, Empty, Input, InputNumber, Select, Space, Table, Tabs, Tag, Timeline, Typography } from 'antd'
import dayjs from 'dayjs'
import { Link } from 'react-router-dom'
import { nextStage, stages } from './taskWorkflow'

type Event = { at: string; actor_id: string; action: string; reason?: string }
export type Risk = { id: string; risk_type: string; severity: string; status: string; detected_at: string; business_date: string;
  metrics: { net_gap: number; time_shortfall: number; first_shortage_date: string | null; daily_sales: number };
  source: { sku_code: string; sku_id: string; system: string; evidence_hash: string; inventory_basis: string }; history: Event[] }
export type Task = { id: string; risk_id: string; objective: string; status: string; created_at: string; selected_version: string | null; selected_scenario?: number;
  execution: { id?: string; plan_no?: string; status?: string; quantity?: number }; history: Event[] }
type Calculation = { purchase_qty: number; shipping_qty: number; purchase_amount: string; total_amount: string; currency: string;
  time_shortfall: number; first_shortage_date: string; horizon_days: number; issues: { message: string }[];
  trajectory: { date: string; opening: number; arrivals: number; demand: number; closing: number; shortfall: number }[] }
type Scenario = { name: string; hypothetical: boolean; demand_factor: number; assumption: string; calculation: Calculation; constraints_satisfied: boolean; limitations: string[] }
type Version = { id: string; version: number; evidence_hash: string; calculation_version: string; expires_at: string;
  snapshot: Record<string, unknown>; scenarios: Scenario[] }
export type Detail = { task: Task; risk: Risk; versions: Version[] }
export const names: Record<string, string> = { OPEN: '待处理', IN_PROGRESS: '处理中', RESOLVED: '已解决', DISMISSED: '已忽略', DRAFT: '待生成 / 待提交', SUBMITTED: '待审批', APPROVED: '已批准，待执行', REJECTED: '已驳回', EXECUTED: '已生成 ERP 草案', CONFIRMED: '已核对 ERP 记录', DETECTED: '检测到风险', CREATED: '创建任务', SIMULATED: '保存仿真版本', PRECHECK_PASSED: '执行前校验通过', RESULT_CONFIRMED: 'ERP 结果确认', STRATEGY_CREATED: '关联策略任务' }
export const status = (value: string) => <Tag color={value === 'APPROVED' || value === 'CONFIRMED' ? 'green' : value === 'SUBMITTED' ? 'orange' : 'blue'}>{names[value] || value}</Tag>
export const formatTime = (value: string) => dayjs(value.endsWith('Z') ? value : `${value}Z`).format('YYYY-MM-DD HH:mm:ss')
export const eventItems = (events: Event[]) => events.map((e, i) => ({ key: `${e.at}-${i}`, children: <><b>{names[e.action] || e.action}</b><div>{formatTime(e.at)} · {e.actor_id}</div>{e.reason && <div>{e.reason}</div>}</> }))


type Props = { detail: Detail; busy: boolean; error: string; stage: string; versionId?: string;
  can: (permission: string) => boolean; onStage: (stage: string) => void; onVersion: (id: string) => void;
  onAction: (action: string, body?: unknown) => Promise<void> }
export default function TaskWorkbench({ detail, busy, error, stage, versionId, can, onStage, onVersion, onAction }: Props) {
  const [factor, setFactor] = useState<number | null>(1)
  const [assumption, setAssumption] = useState('')
  const [reason, setReason] = useState('')
  const version = detail.versions.find(v => v.id === versionId)
  const setVersionId = onVersion
  const act = onAction
  const run = async (fn: () => Promise<void>) => { await fn() }
  const next = nextStage(detail.task.status, detail.versions.length)
  const selected = version?.scenarios[detail.task.selected_scenario ?? 0]
  const decisionSummary = <Card size="small" title="本次审批与执行方案">
    {version && ['SUBMITTED', 'APPROVED', 'EXECUTED', 'CONFIRMED'].includes(detail.task.status) && detail.task.selected_version && selected ? <Descriptions column={{ xs: 1, sm: 2 }} items={[
      { key: 'version', label: '已提交版本', children: `版本 ${version.version} · ${selected.name}` },
      { key: 'quantity', label: '采购数量', children: `${selected.calculation.purchase_qty} 件` },
      { key: 'amount', label: '采购金额', children: `${selected.calculation.purchase_amount} ${selected.calculation.currency}` },
      { key: 'total', label: '采购与运费合计', children: `${selected.calculation.total_amount} ${selected.calculation.currency}` },
      { key: 'expiry', label: '有效期至', children: formatTime(version.expires_at) },
    ]} /> : <Typography.Text>尚未提交方案，请先在仿真对比中选择基准方案。</Typography.Text>}
    <Button type="link" onClick={() => onStage('simulation')}>查看完整仿真与证据</Button>
  </Card>
  const contents: Record<string, React.ReactNode> = {
    risk: <Card title="风险与证据"><Descriptions column={1} bordered items={[
      { key: 'sku', label: 'SKU', children: detail.risk.source.sku_code },
      { key: 'source', label: '来源与库存口径', children: `${detail.risk.source.system} · ${detail.risk.source.inventory_basis}` },
      { key: 'date', label: '业务日期', children: detail.risk.business_date },
      { key: 'gap', label: '目标缺口 / 时效缺口', children: `${detail.risk.metrics.net_gap} / ${detail.risk.metrics.time_shortfall} 件` },
      { key: 'hash', label: '证据摘要', children: detail.risk.source.evidence_hash },
    ]} /><Button style={{ marginTop: 16 }} onClick={() => onStage('strategy')}>进入策略生成</Button></Card>,
    strategy: <>
        {['DRAFT', 'REJECTED'].includes(detail.task.status) && <Card title="生成候选方案并确定性仿真">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space wrap><Typography.Text>人工需求倍率（选填，基准 1 始终保留）</Typography.Text><InputNumber aria-label="人工需求倍率" min={0.01} max={3} step={0.1} value={factor} onChange={setFactor} /></Space>
            <Input.TextArea aria-label="需求情景假设" placeholder="使用非 1 倍率时，填写人工假设；例如：活动收缩后需求暂按基准的 80% 估算" value={assumption} onChange={e => setAssumption(e.target.value)} maxLength={500} />
            <Button type="primary" loading={busy} disabled={!can('purchase_agent:write') || (!!factor && factor !== 1 && !assumption.trim())} onClick={() => void run(() => act('versions', { demand_factors: factor && factor !== 1 ? [1, factor] : [1], assumption }))}>生成并保存新版本</Button>
          </Space>
        </Card>}
      {!['DRAFT', 'REJECTED'].includes(detail.task.status) && <Alert type="info" message="当前版本已提交，不能直接修改；需驳回后重新生成并审批。" />}
      {!!detail.versions.length && <Button onClick={() => onStage('simulation')}>查看仿真与对比</Button>}
    </>,
    simulation: <>
        {version ? <>
          <Space wrap><Select aria-label="策略版本" disabled={busy || ['SUBMITTED', 'APPROVED', 'EXECUTED', 'CONFIRMED'].includes(detail.task.status)} style={{ width: 180 }} value={version.id} onChange={setVersionId} options={detail.versions.map(v => ({ value: v.id, label: `版本 ${v.version}${v.id === detail.task.selected_version ? '（已选）' : ''}` }))} /><Typography.Text>计算版本 {version.calculation_version} · 有效期至 {formatTime(version.expires_at)}</Typography.Text></Space>
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
    </>,
    approval: <Space direction="vertical" style={{ width: '100%' }}>
      {decisionSummary}
      <Alert type="info" message={detail.task.status === 'REJECTED' ? '已驳回，请返回策略生成，修改后重新提交审批。' : '审批仅针对已提交的版本和基准补货方案；通过后仍需手动执行。'} />
          {detail.task.status === 'SUBMITTED' && <Button type="primary" loading={busy} disabled={!can('purchase_agent_drafts:write')} onClick={() => void run(() => act('approve'))}>审批通过（不执行）</Button>}
        {['SUBMITTED', 'APPROVED'].includes(detail.task.status) && <Space><Input aria-label="驳回理由" placeholder="驳回理由" value={reason} onChange={e => setReason(e.target.value)} maxLength={500} /><Button danger disabled={busy || !reason.trim() || !can('purchase_agent_drafts:write')} onClick={() => void run(() => act('reject', { reason }))}>驳回</Button></Space>}
      <Timeline items={eventItems(detail.task.history.filter(e => ['SUBMITTED', 'APPROVED', 'REJECTED'].includes(e.action)))} />
    </Space>,
    execution: <Space direction="vertical" style={{ width: '100%' }}>
      {decisionSummary}
      <Alert type="warning" message="仅创建 ERP 采购草案" description="执行时重新校验库存、销量、报价、版本有效期和重复采购。请求失败或超时后，请先刷新任务核对结果。" />
          {detail.task.status === 'APPROVED' && <Button type="primary" loading={busy} disabled={!can('purchase_agent_drafts:write') || !can('purchase_plans:write')} onClick={() => void run(() => act('execute'))}>执行前校验并生成 ERP 采购草案</Button>}
      {detail.task.status !== 'APPROVED' && <Typography.Text>当前状态：{names[detail.task.status] || detail.task.status}。只有审批通过的任务可执行。</Typography.Text>}
    </Space>,
    result: <Space direction="vertical" style={{ width: '100%' }}>
          {detail.task.status === 'EXECUTED' && <Button type="primary" loading={busy} disabled={!can('purchase_agent_drafts:write')} onClick={() => void run(() => act('confirm'))}>回读并确认 ERP 记录</Button>}
        {detail.task.execution.id && <Alert type="success" message={`ERP 采购计划 ${detail.task.execution.plan_no} · ${detail.task.execution.quantity} 件`} description={<span>已生成草稿，尚未实际采购。<Link to="/purchase-plans">进入采购计划继续处理</Link></span>} />}
        <Card title="任务与执行记录"><Timeline items={eventItems(detail.task.history)} /></Card>
      {!detail.task.execution.id && <Empty description="尚未生成 ERP 采购草案" />}
    </Space>,
  }
  return <Space direction="vertical" size={20} style={{ width: '100%' }}>
    {error && <Alert type="error" showIcon message="操作未完成" description={error} />}
    <Typography.Title level={4}>{detail.task.objective} {status(detail.task.status)}</Typography.Title>
    <Typography.Text type="secondary">任务 {detail.task.id} · SKU {detail.risk.source.sku_code} · {version ? `版本 ${version.version}` : '尚无策略版本'}</Typography.Text>
    {version && <Typography.Text type="secondary">快照有效期至 {formatTime(version.expires_at)}；执行前仍会核对最新业务证据。</Typography.Text>}
    <Space wrap><Typography.Text>下一步：{stages.find(s => s.key === next)?.label}</Typography.Text><Button disabled={busy || stage === next} onClick={() => onStage(next)}>前往处理</Button></Space>
    <Tabs activeKey={stage} onChange={onStage} items={stages.map((s, i) => ({ key: s.key, label: `${i + 1}. ${s.label}`, children: contents[s.key] }))} />
  </Space>
}
