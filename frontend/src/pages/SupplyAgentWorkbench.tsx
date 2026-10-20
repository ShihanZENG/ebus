import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Checkbox, Col, Descriptions, Drawer, Form, Input, InputNumber, Modal, Row, Select, Space, Statistic, Table, Tabs, Tag, Typography, message } from 'antd'
import { Link } from 'react-router-dom'
import dayjs from 'dayjs'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import PurchaseBusinessAnalysis from './PurchaseBusinessAnalysis'
import SupplyReadiness, { type ReadinessData } from './SupplyReadiness'
import LaunchReadiness from './LaunchReadiness'
import RunTraceDrawer, { type TraceEvent } from '../components/RunTraceDrawer'

type Json = Record<string, unknown>
interface Lookup { id: string; code: string; name: string; warehouse_type?: string }
interface Lookups { skus: Lookup[]; shops: Lookup[]; warehouses: Lookup[]; suppliers: Lookup[]; currencies: Lookup[] }
interface Profile { id: string; name: string; sku_id: string; shop_id: string; warehouse_id: string; destination_id: string; supplier_id: string; config: Json }
interface Issue { field: string; message: string; owner: string; recovery: string }
interface Day { date: string; opening: number; arrivals: number; demand: number; closing: number; shortfall: number }
interface Calculation { purchase_qty: number; shipping_qty: number; time_shortfall: number; total_amount: string; currency: string; first_shortage_date: string | null; steps: string[]; warnings: string[]; trajectory: Day[] }
interface SupplyDraft { id: string; profile_name: string; draft_no: string; status: string; evidence_hash: string; expires_at: string; calculation: Calculation; snapshot: Json; generated_records: { purchase_plan?: { plan_no: string }; fba_plans?: Array<{ plan_no: string; quantity: number }> }; reason: string }
interface Decision { profile_id: string; run_id: string; status: string; evidence: Json; calculation?: Calculation; issues: Issue[]; draft?: SupplyDraft }
interface Chat { id: string; created_at: string; status: string; model: string; message: string; trace: Array<{ tool: string; status: string; elapsed_ms: number; result: Json }>; result: { reply?: string; error?: string; items?: Decision[]; events?: TraceEvent[]; elapsed_ms?: number } }
interface Run { id: string; created_at: string; status: string; case_id: string; result_payload: Json; error_message: string; tool_calls?: Array<{ id: string; tool: string; status: string; elapsed_ms: number; params: Json; result: Json }> }
const emptyLookups: Lookups = { skus: [], shops: [], warehouses: [], suppliers: [], currencies: [] }
const statusLabels: Record<string, string> = { READY: '已测算', CALCULATED: '无需补货', BLOCKED: '待补证据', CONSTRAINT_CONFLICT: '约束冲突', DRAFTED: '已生成草稿', WAITING_APPROVAL: '待审批', EXECUTED: '已生成业务草稿', REJECTED: '已驳回', COMPLETED: '已完成', FAILED: '失败', RUNNING: '运行中' }
const color = (s: string) => ['BLOCKED', 'FAILED', 'CONSTRAINT_CONFLICT'].includes(s) ? 'red' : s === 'WAITING_APPROVAL' ? 'gold' : 'blue'
const errorText = (e: unknown) => e instanceof Error ? e.message : '请求失败'
const dateText = (value: string) => new Date(value.endsWith('Z') ? value : value + 'Z').toLocaleString('zh-CN')
const options = (items: Lookup[]) => items.map(x => ({ value: x.id, label: `${x.code} ${x.name}` }))

function Trajectory({ rows }: { rows: Day[] }) {
  if (!rows.length) return null
  const max = Math.max(1, ...rows.map(x => Math.max(x.closing, x.shortfall)))
  const points = (field: 'closing' | 'shortfall') => rows.map((x, i) => `${30 + i * 640 / Math.max(1, rows.length - 1)},${150 - x[field] / max * 125}`).join(' ')
  return <>
    <Typography.Paragraph>蓝线：预计海外可售库存；红线：当日时效缺口。需求按历史加权日销估计。</Typography.Paragraph>
    <svg role="img" aria-label="海外仓逐日库存和缺货数量趋势" viewBox="0 0 700 185" style={{ width: '100%', maxHeight: 220 }}>
      <line x1="30" y1="150" x2="670" y2="150" stroke="#aaa" /><text x="0" y="25" fontSize="12">{Math.ceil(max)}</text>
      <polyline points={points('closing')} fill="none" stroke="#1677ff" strokeWidth="2" /><polyline points={points('shortfall')} fill="none" stroke="#cf1322" strokeWidth="2" />
      <text x="30" y="175" fontSize="12">{rows[0].date}</text><text x="580" y="175" fontSize="12">{rows[rows.length - 1].date}</text>
    </svg>
    <Table<Day> rowKey="date" size="small" dataSource={rows} pagination={{ pageSize: 10 }} columns={[
      { title: '日期', dataIndex: 'date' }, { title: '期初可售', dataIndex: 'opening' }, { title: '新增可售', dataIndex: 'arrivals' },
      { title: '预计需求', dataIndex: 'demand' }, { title: '期末可售', dataIndex: 'closing' },
      { title: '时效缺口', dataIndex: 'shortfall', render: v => <Typography.Text type={v > 0 ? 'danger' : undefined}>{v}</Typography.Text> },
    ]} />
  </>
}

function EvidenceView({ evidence }: { evidence: Json }) {
  const object = (value: unknown): Json => value && typeof value === 'object' && !Array.isArray(value) ? value as Json : {}
  const sales = object(evidence.sales)
  const stocks = object(evidence.stocks)
  const config = object(object(evidence.profile).config)
  const quantity = (value: unknown, unit: string) => typeof value === 'number' && Number.isFinite(value)
    ? `${value.toLocaleString('zh-CN', { maximumFractionDigits: 3 })} ${unit}` : '待补数据'
  const weight = typeof config.sales_7_weight === 'number' ? config.sales_7_weight : undefined
  const basis = sales.timestamp_field === 'sales_orders.ordered_at' ? '订单实际下单时间'
    : sales.timestamp_field === 'sales_orders.created_at' ? '订单创建时间' : '待确认'
  const method = weight !== undefined
    ? `近7天日均 × ${(weight * 100).toFixed(0)}% ＋ 近21天日均 × ${((1 - weight) * 100).toFixed(0)}%`
    : '近7天与近21天日均销量加权计算'
  return <>
    <Row gutter={[16, 16]}>
      <Col xs={24} xl={12}>
        <Card size="small" title="销量依据">
          <Descriptions size="small" column={1} labelStyle={{ width: 120 }} items={[
            { key: 'date', label: '销量统计截止日', children: typeof evidence.business_date === 'string' ? evidence.business_date : '待确认' },
            { key: 'qty7', label: '最近7天销量', children: quantity(sales.qty_7, '件') },
            { key: 'qty21', label: '最近21天销量', children: quantity(sales.qty_21, '件') },
            { key: 'orders', label: '统计订单数', children: quantity(sales.order_count, '笔') },
            { key: 'daily', label: '加权日均销量', children: <Typography.Text strong>{quantity(sales.daily_sales, '件/天')}</Typography.Text> },
            { key: 'method', label: '计算方式', children: method },
            { key: 'time', label: '订单时间依据', children: basis },
          ]} />
        </Card>
      </Col>
      <Col xs={24} xl={12}>
        <Card size="small" title="库存依据">
          <Descriptions size="small" column={1} labelStyle={{ width: 120 }} items={[
            { key: 'source', label: '国内仓可售库存', children: quantity(stocks.source, '件') },
            { key: 'free', label: '国内可用于本次发货', children: <Typography.Text strong>{quantity(stocks.source_free, '件')}</Typography.Text> },
            { key: 'destination', label: '海外仓可售库存', children: quantity(stocks.destination, '件') },
          ]} />
          <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
            {typeof evidence.inventory_basis === 'string' ? evidence.inventory_basis : '库存口径待确认'}。国内可用于本次发货的数量已扣除其他发货计划占用。
          </Typography.Paragraph>
        </Card>
      </Col>
    </Row>
    <details style={{ marginTop: 12 }}>
      <summary style={{ cursor: 'pointer', color: '#666' }}>查看证据版本</summary>
      <Typography.Paragraph style={{ overflowWrap: 'anywhere', marginTop: 8 }} copyable={typeof evidence.evidence_hash === 'string'}>
        {typeof evidence.evidence_hash === 'string' ? evidence.evidence_hash : '尚未形成完整证据'}
      </Typography.Paragraph>
    </details>
  </>
}

function DecisionView({ item }: { item: Decision }) {
  const calc = item.calculation
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Tag color={color(item.status)}>{statusLabels[item.status] ?? item.status}</Tag>
    {item.issues.map((x, i) => <Alert key={i} type="warning" showIcon message={x.message} description={`${x.owner}：${x.recovery}（${x.field}）`} />)}
    {calc && <>
      <Row gutter={16}>
        <Col span={6}><Statistic title="采购建议（件）" value={calc.purchase_qty} /></Col>
        <Col span={6}><Statistic title="发货建议（件）" value={calc.shipping_qty} /></Col>
        <Col span={6}><Statistic title="时效缺口（件）" value={calc.time_shortfall} valueStyle={{ color: calc.time_shortfall ? '#cf1322' : undefined }} /></Col>
        <Col span={6}><Statistic title={`采购与运费（${calc.currency}）`} value={calc.total_amount} precision={2} /></Col>
      </Row>
      {calc.warnings.map((x, i) => <Alert key={i} type={i === 0 && calc.time_shortfall ? 'warning' : 'info'} message={x} />)}
      <ol>{calc.steps.map((x, i) => <li key={i}>{x}</li>)}</ol>
      <Trajectory rows={calc.trajectory ?? []} />
    </>}
    <EvidenceView evidence={item.evidence} />
    {item.draft && <Alert type="success" message={`草稿 ${item.draft.draft_no} 已保存，需在「采购与发货草稿」中人工审批。`} />}
  </Space>
}

export default function SupplyAgentWorkbench() {
  const { user } = useAuth()
  const can = (p: string) => user?.role === 'admin' || !!user?.permissions.includes(p)
  const canWrite = can('purchase_agent:write')
  const canDraftRead = can('purchase_agent_drafts:read')
  const canApprove = can('purchase_agent_drafts:write')
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [activeTab, setActiveTab] = useState('launch')
  const [lookups, setLookups] = useState<Lookups>(emptyLookups)
  const [runtime, setRuntime] = useState<{ model_configured: boolean; model?: string | null }>()
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [businessDate, setBusinessDate] = useState(dayjs().format('YYYY-MM-DD'))
  const [prompt, setPrompt] = useState('分析所选商品的补货需求，分别说明采购、发货、补货到达前的缺口和待确认事项。')
  const [allowDrafts, setAllowDrafts] = useState(false)
  const [results, setResults] = useState<Decision[]>([])
  const [reply, setReply] = useState('')
  const [busy, setBusy] = useState(false)
  const [drafts, setDrafts] = useState<SupplyDraft[]>([])
  const [draftPage, setDraftPage] = useState(1)
  const [draftTotal, setDraftTotal] = useState(0)
  const [runs, setRuns] = useState<Run[]>([])
  const [runPage, setRunPage] = useState(1)
  const [runTotal, setRunTotal] = useState(0)
  const [chats, setChats] = useState<Chat[]>([])
  const [editing, setEditing] = useState<Profile | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [detail, setDetail] = useState<SupplyDraft | null>(null)
  const [runDetail, setRunDetail] = useState<Run | null>(null)
  const [chatDetail, setChatDetail] = useState<Chat | null>(null)
  const [latestChat, setLatestChat] = useState<Chat | null>(null)
  const [form] = Form.useForm()
  const formSku = Form.useWatch('sku_id', form)
  const formShop = Form.useWatch('shop_id', form)
  const autoValues = useRef<Record<string, unknown>>({})
  const [autoNotice, setAutoNotice] = useState('')
  const [autoBusy, setAutoBusy] = useState(false)
  useEffect(() => {
    let alive = true
    if (!formOpen || editing || !formSku) return
    for (const [key, value] of Object.entries(autoValues.current)) {
      if (!form.isFieldTouched(key) && form.getFieldValue(key) === value) form.setFieldValue(key, undefined)
    }
    autoValues.current = {}
    setAutoBusy(true); setAutoNotice('')
    request<ReadinessData>(`/purchase-agent/sku-readiness/${formSku}`, { params: { business_date: businessDate } })
      .then(data => {
        if (!alive) return
        const names: Record<string, string> = { supplier_id: '供应商', shop_id: '销量店铺', currency_id: '币种', moq: '起订量', case_pack: '箱规', safety_days: '安全天数', review_days: '复核周期', transport_days: '运输天数', receiving_days: '入库天数' }
        const added: string[] = []
        for (const [key, value] of Object.entries(data.suggested)) {
          if (form.isFieldTouched(key)) continue
          form.setFieldValue(key, value)
          autoValues.current[key] = value
          added.push(`${names[key] ?? key}：${data.origins[key]}`)
        }
        setAutoNotice(added.length ? `已带入 ${added.join('；')}。请核对后保存。` : '此SKU暂无可以唯一确定的参数，请选择店铺、供应商并填写补货规则。')
      })
      .catch(e => { if (alive) setAutoNotice(e instanceof Error ? e.message : '已有资料读取失败，请重新选择SKU') })
      .finally(() => { if (alive) setAutoBusy(false) })
    return () => { alive = false }
  }, [formOpen, formSku, editing])
  useEffect(() => {
    let alive = true
    if (!formOpen || editing || !formSku || !formShop || form.isFieldTouched('currency_id')) return
    request<ReadinessData>(`/purchase-agent/sku-readiness/${formSku}`, { params: { business_date: businessDate, shop_id: formShop } })
      .then(data => { if (alive && !form.isFieldTouched('currency_id')) form.setFieldValue('currency_id', data.suggested.currency_id) })
      .catch(() => { /* SKU读取失败提示由上方统一呈现，币种仍可手动选择。 */ })
    return () => { alive = false }
  }, [formOpen, formSku, formShop, editing])
  const [rejectTarget, setRejectTarget] = useState<SupplyDraft | null>(null)
  const [rejectReason, setRejectReason] = useState('')

  const refreshBase = async () => {
    try {
      const [p, l, r] = await Promise.all([request<{ items: Profile[] }>('/purchase-agent/profiles'), request<Lookups>('/purchase-agent/lookups'), request<{ model_configured: boolean; model?: string }>('/purchase-agent/runtime')])
      setProfiles(p.items); setLookups(l); setRuntime(r)
    } catch (e) { message.error(errorText(e)) }
  }
  const refreshDrafts = async (page = draftPage) => {
    if (!canDraftRead) return
    try { const d = await request<{ items: SupplyDraft[]; total: number }>('/purchase-agent/supply-drafts', { params: { page, page_size: 20 } }); setDrafts(d.items); setDraftTotal(d.total) } catch (e) { message.error(errorText(e)) }
  }
  const refreshRuns = async (page = runPage) => {
    try {
      const [r, c] = await Promise.all([request<{ items: Run[]; total: number }>('/purchase-agent/runs', { params: { page, page_size: 20 } }), request<{ items: Chat[] }>('/purchase-agent/chats')])
      setRuns(r.items); setRunTotal(r.total); setChats(c.items)
    } catch (e) { message.error(errorText(e)) }
  }
  useEffect(() => { void refreshBase() }, [])
  useEffect(() => { void refreshDrafts() }, [draftPage, canDraftRead])
  useEffect(() => { void refreshRuns() }, [runPage])

  const analyze = async (withModel: boolean) => {
    if (!selectedIds.length || !businessDate) { message.warning('请选择补货配置和业务截止日'); return }
    setBusy(true); setReply(''); setResults([]); setLatestChat(null)
    try {
      if (withModel) {
        const c = await request<Chat>('/purchase-agent/chat', { method: 'POST', body: { message: prompt, profile_ids: selectedIds, business_date: businessDate, allow_drafts: allowDrafts } })
        setReply(c.result.error ?? c.result.reply ?? ''); setResults(c.result.items ?? [])
        setLatestChat(c)
        if (c.status === 'FAILED') message.error(c.result.error ?? '模型分析失败')
      } else {
        const res = await request<{ items: Decision[] }>('/purchase-agent/supply-decide', { method: 'POST', body: { profile_ids: selectedIds, business_date: businessDate, create_drafts: allowDrafts } })
        setResults(res.items)
      }
      void refreshDrafts(); void refreshRuns()
    } catch (e) { message.error(errorText(e)) } finally { setBusy(false) }
  }
  const openProfile = (p: Profile | null) => {
    autoValues.current = {}; setAutoNotice(''); setAutoBusy(false)
    setEditing(p); form.resetFields()
    if (p) form.setFieldsValue({ ...p, ...p.config })
    else form.setFields(Object.entries({ name: '', sales_time_basis: 'ordered_at', sales_7_weight: 0.6, review_days: 7, safety_days: 7, compliance_confirmed: false, draft_valid_hours: 24 }).map(([name, value]) => ({ name, value, touched: false })))
    setFormOpen(true)
  }
  const saveProfile = async () => {
    try {
      const v = await form.validateFields()
      const refs = ['name', 'sku_id', 'shop_id', 'warehouse_id', 'destination_id', 'supplier_id']
      const config = Object.fromEntries(Object.entries(v).filter(([k]) => !refs.includes(k)))
      config.budget_limit = String(config.budget_limit); config.freight_unit_cost = String(config.freight_unit_cost)
      config.compliance_reference = config.compliance_reference ?? ''
      config.compliance_valid_until = config.compliance_valid_until || null
      config.season_end = config.season_end || null
      setBusy(true)
      await request(`/purchase-agent/profiles${editing ? '/' + editing.id : ''}`, { method: editing ? 'PUT' : 'POST', body: { ...Object.fromEntries(refs.map(k => [k, v[k]])), config } })
      message.success('补货配置已保存'); setFormOpen(false); await refreshBase()
    } catch (e) { message.error(errorText(e)) } finally { setBusy(false) }
  }
  const approve = async () => {
    if (!detail) return
    setBusy(true)
    try {
      const updated = await request<SupplyDraft>(`/purchase-agent/supply-drafts/${detail.id}/approve`, { method: 'POST', body: { evidence_hash: detail.evidence_hash } })
      setDetail(updated); message.success('复核通过，已生成采购计划和待配货发货草稿'); void refreshDrafts()
    } catch (e) { message.error(errorText(e)) } finally { setBusy(false) }
  }
  const reject = async () => {
    if (!rejectTarget || !rejectReason.trim()) { message.warning('请填写驳回原因'); return }
    setBusy(true)
    try { await request(`/purchase-agent/supply-drafts/${rejectTarget.id}/reject`, { method: 'POST', body: { reason: rejectReason } }); setRejectTarget(null); setDetail(null); void refreshDrafts() } catch (e) { message.error(errorText(e)) } finally { setBusy(false) }
  }
  const label = (items: Lookup[], id: string) => items.find(x => x.id === id)?.name ?? id
  const profileFields = [
    { key: 'sku_id', label: 'SKU', options: options(lookups.skus) }, { key: 'shop_id', label: '销量店铺', options: options(lookups.shops) },
    { key: 'warehouse_id', label: '来源国内仓', options: options(lookups.warehouses.filter(x => x.warehouse_type === 'domestic')) },
    { key: 'destination_id', label: '目的海外仓', options: options(lookups.warehouses.filter(x => x.warehouse_type === 'overseas')) },
    { key: 'supplier_id', label: '采购供应商', options: options(lookups.suppliers) },
  ]
  const numberFields = [
    { key: 'transport_days', label: '运输天数', min: 0, max: 180 }, { key: 'receiving_days', label: '入库至可售天数', min: 0, max: 60 },
    { key: 'review_days', label: '采购复核周期（天）', min: 1, max: 120 }, { key: 'safety_days', label: '安全天数', min: 0, max: 120 },
    { key: 'moq', label: '采购最小起订量（件）', min: 1, max: 1000000 }, { key: 'case_pack', label: '箱规（件/箱）', min: 1, max: 100000 },
    { key: 'draft_valid_hours', label: '草稿有效期（小时）', min: 1, max: 72 },
  ]
  const configuredSkuIds = new Set(profiles.map(p => p.sku_id))
  const replenishmentOptions = [
    ...profiles.map(p => ({
      value: p.id,
      label: `${label(lookups.skus, p.sku_id)} · ${p.name}`,
    })),
    ...lookups.skus.filter(s => !s.code.startsWith('TEACH-') && !configuredSkuIds.has(s.id)).map(s => ({
      value: `sku:${s.id}`,
      label: `${s.code} ${s.name}（点击建立补货配置）`,
    })),
  ]
  return <>
    <Typography.Title level={4}>采购与补货 Agent</Typography.Title>
    <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
      { key: 'launch', label: '上线准备', children: <LaunchReadiness profiles={profiles} skus={lookups.skus} businessDate={businessDate} onShowReadiness={() => setActiveTab('readiness')} /> },
      { key: 'readiness', label: '数据准备', children: <SupplyReadiness skus={lookups.skus} profiles={profiles} businessDate={businessDate} onDate={setBusinessDate} canWrite={canWrite} onConfigure={(skuId, profileId) => {
        const existing = profiles.find(p => p.id === profileId)
        openProfile(existing ?? null)
        if (!existing) form.setFieldsValue({ sku_id: skuId, name: `${lookups.skus.find(s => s.id === skuId)?.code ?? ''} 补货配置` })
      }} /> },
      { key: 'work', label: '供需工作台', children: <Space direction="vertical" style={{ width: '100%' }} size="middle">
        {!runtime?.model_configured && <Alert type="info" showIcon message="模型服务尚未配置，可先使用规则分析。真实模型分析需要管理员配置服务地址、模型名和密钥。" />}
        <Card title="选择补货任务" extra={<Button onClick={() => void refreshBase()}>刷新配置</Button>}>
          <Space wrap>
            <Select mode="multiple" showSearch optionFilterProp="label" style={{ minWidth: 380 }} placeholder="选择 SKU 或补货配置" value={selectedIds} onChange={values => {
              const skuChoice = values.find(v => v.startsWith('sku:'))
              const profileChoices = values.filter(v => !v.startsWith('sku:'))
              setSelectedIds(profileChoices)
              if (skuChoice) {
                const sku = lookups.skus.find(s => s.id === skuChoice.slice(4))
                if (sku) {
                  openProfile(null)
                  form.setFieldsValue({ sku_id: sku.id, name: `${sku.code} 补货配置` })
                }
              }
            }} options={replenishmentOptions} maxCount={10} />
            <label>订单业务截止日 <Input type="date" value={businessDate} onChange={e => setBusinessDate(e.target.value)} style={{ width: 160 }} /></label>
          </Space>
          {lookups.skus.some(s => !s.code.startsWith('TEACH-') && !configuredSkuIds.has(s.id)) && <Alert style={{ marginTop: 12 }} type="info" showIcon message="下拉框也包含尚未配置的真实 SKU。选择后会打开补货配置表单，并预选 SKU。" description="请按真实业务填写销售店铺、国内仓、海外仓、供应商、运输和入库天数、MOQ、箱规、预算及合规信息。有效供应商报价与完整订单时间也会影响分析结果。" />}
          {!profiles.length && <Alert style={{ marginTop: 12 }} type="warning" message="先到「业务配置」建立 SKU、店铺、仓库和供应商的补货规则。" />}
          <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>日销来自此店铺已审核或已发货订单的 7/21 天加权平均；库存使用采集时余额。每个配置有独立预算，批次不共享预算。</Typography.Paragraph>
          <Input.TextArea rows={3} value={prompt} onChange={e => setPrompt(e.target.value)} maxLength={4000} placeholder="例如：分析这些商品，说明需要采购和发货多少，是否会在到货前断货。" />
          <Space wrap style={{ marginTop: 12 }}>
            <Checkbox checked={allowDrafts} onChange={e => setAllowDrafts(e.target.checked)} disabled={!canWrite}>允许保存待人工审批草稿</Checkbox>
            <Button loading={busy} disabled={!canWrite} onClick={() => void analyze(false)}>规则分析</Button>
            <Button type="primary" loading={busy} disabled={!canWrite || !runtime?.model_configured || !prompt.trim()} onClick={() => void analyze(true)}>模型分析{runtime?.model ? `（${runtime.model}）` : ''}</Button>
          </Space>
        </Card>
        {reply && <Card title="模型解释" extra={latestChat && <Button onClick={() => setChatDetail(latestChat)}>运行轨迹</Button>}><Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{reply}</Typography.Paragraph><Typography.Text type="secondary">数量与执行状态以工具结果、草稿记录为准。</Typography.Text></Card>}
        {results.map(x => <Card key={x.run_id} title={profiles.find(p => p.id === x.profile_id)?.name ?? x.profile_id}><DecisionView item={x} /></Card>)}
      </Space> },
      { key: 'business', label: '经营分析', children: <PurchaseBusinessAnalysis profiles={profiles} skus={lookups.skus} currencies={lookups.currencies} canWrite={canWrite} onConfigureSku={skuId => {
        const sku = lookups.skus.find(s => s.id === skuId)
        if (!sku) return
        openProfile(null)
        form.setFieldsValue({ sku_id: sku.id, name: `${sku.code} 补货配置` })
      }} /> },
      { key: 'profiles', label: '业务配置', children: <Card title="SKU 补货配置" extra={canWrite && <Button type="primary" onClick={() => openProfile(null)}>新增配置</Button>}>
        <Alert type="info" style={{ marginBottom: 12 }} message="采购交期取已接受报价；运输、上架、MOQ、箱规、预算与合规由业务负责人确认。销量范围表示该时间段已完整同步，不能用来补造订单。" />
        <Table<Profile> rowKey="id" dataSource={profiles} columns={[
          { title: '配置', dataIndex: 'name' }, { title: 'SKU', render: (_, p) => label(lookups.skus, p.sku_id) }, { title: '店铺', render: (_, p) => label(lookups.shops, p.shop_id) },
          { title: '国内仓 → 海外仓', render: (_, p) => `${label(lookups.warehouses, p.warehouse_id)} → ${label(lookups.warehouses, p.destination_id)}` },
          { title: '合规', render: (_, p) => <Tag color={p.config.compliance_confirmed ? 'green' : 'gold'}>{p.config.compliance_confirmed ? '已确认' : '待确认'}</Tag> },
          { title: '操作', render: (_, p) => <Button disabled={!canWrite} onClick={() => openProfile(p)}>编辑参数</Button> },
        ]} />
      </Card> },
      { key: 'drafts', label: '采购与发货草稿', children: !canDraftRead ? <Alert type="warning" message="需要采购 Agent 草稿查看权限。" /> : <Card title="供需草稿" extra={<Button onClick={() => void refreshDrafts()}>刷新</Button>}>
        <Table<SupplyDraft> rowKey="id" dataSource={drafts} pagination={{ current: draftPage, pageSize: 20, total: draftTotal, onChange: setDraftPage }} columns={[
          { title: '草稿', dataIndex: 'draft_no' }, { title: '配置', dataIndex: 'profile_name' }, { title: '采购量', render: (_, d) => d.calculation.purchase_qty },
          { title: '发货量', render: (_, d) => d.calculation.shipping_qty }, { title: '时效缺口', render: (_, d) => d.calculation.time_shortfall },
          { title: '状态', render: (_, d) => <Tag color={color(d.status)}>{statusLabels[d.status] ?? d.status}</Tag> },
          { title: '操作', render: (_, d) => <Button onClick={async () => { try { setDetail(await request<SupplyDraft>(`/purchase-agent/supply-drafts/${d.id}`)) } catch (e) { message.error(errorText(e)) } }}>查看与审批</Button> },
        ]} />
      </Card> },
      { key: 'runs', label: '运行记录', children: <Space direction="vertical" style={{ width: '100%' }}>
        <Card title="补货运行" extra={<Button onClick={() => void refreshRuns()}>刷新</Button>}>
          <Table<Run> rowKey="id" dataSource={runs} pagination={{ current: runPage, pageSize: 20, total: runTotal, onChange: setRunPage }} columns={[
            { title: '时间', dataIndex: 'created_at', render: dateText }, { title: '业务标识', dataIndex: 'case_id' },
            { title: '状态', render: (_, r) => <Tag color={color(r.status)}>{statusLabels[r.status] ?? r.status}</Tag> },
            { title: '原因', dataIndex: 'error_message' }, { title: '工具记录', render: (_, r) => <Button onClick={async () => { try { setRunDetail(await request<Run>(`/purchase-agent/runs/${r.id}`)) } catch (e) { message.error(errorText(e)) } }}>查看</Button> },
          ]} />
        </Card>
        <Card title="我的模型调用"><Table<Chat> rowKey="id" dataSource={chats} columns={[
          { title: '时间', dataIndex: 'created_at', render: dateText }, { title: '模型', dataIndex: 'model' }, { title: '任务', dataIndex: 'message', ellipsis: true },
          { title: '状态', render: (_, c) => <Tag color={color(c.status)}>{statusLabels[c.status] ?? c.status}</Tag> }, { title: '调用过程', render: (_, c) => <Button onClick={() => setChatDetail(c)}>查看</Button> },
        ]} /></Card>
      </Space> },
    ]} />
    <Modal title={editing ? '编辑补货参数' : '新增补货配置'} open={formOpen} width={960} confirmLoading={busy} okButtonProps={{ disabled: autoBusy }} onCancel={() => setFormOpen(false)} onOk={() => void saveProfile()}>
      {(autoBusy || autoNotice) && <Alert style={{ marginBottom: 16 }} type="info" showIcon message={autoBusy ? '正在读取SKU已有资料…' : autoNotice} />}
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="配置名称" rules={[{ required: true }]}><Input maxLength={120} /></Form.Item>
        <Row gutter={12}>
          {profileFields.map(x => <Col span={8} key={x.key}><Form.Item name={x.key} label={x.label} rules={[{ required: true }]}><Select disabled={!!editing} showSearch optionFilterProp="label" options={x.options} /></Form.Item></Col>)}
          <Col span={8}><Form.Item name="currency_id" label="报价与运费币种" rules={[{ required: true }]}><Select options={options(lookups.currencies)} /></Form.Item></Col>
          {numberFields.map(x => <Col span={8} key={x.key}><Form.Item name={x.key} label={x.label} rules={[{ required: true }]}><InputNumber min={x.min} max={x.max} precision={0} style={{ width: '100%' }} /></Form.Item></Col>)}
          <Col span={8}><Form.Item name="sales_7_weight" label="7天日销权重（其余为21天日销）" rules={[{ required: true }]}><InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={8}><Form.Item name="sales_time_basis" label="订单销量时间依据" rules={[{ required: true }]}><Select options={[{ value: 'ordered_at', label: '真实业务下单时间（上线使用）' }, { value: 'created_at', label: '系统创建时间（教学口径）' }]} /></Form.Item></Col>
          <Col span={8}><Form.Item name="budget_limit" label="此配置采购与运费预算" rules={[{ required: true }]}><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={8}><Form.Item name="freight_unit_cost" label="每件运费（同报价币种）" rules={[{ required: true }]}><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={8}><Form.Item name="sales_history_start" label="完整订单数据开始日" rules={[{ required: true }]}><Input type="date" /></Form.Item></Col>
          <Col span={8}><Form.Item name="sales_complete_through" label="完整订单数据截止日" rules={[{ required: true }]}><Input type="date" /></Form.Item></Col>
          <Col span={8}><Form.Item name="season_end" label="销售季结束日（可选）"><Input type="date" /></Form.Item></Col>
          <Col span={8}><Form.Item name="compliance_reference" label="合规证据编号"><Input maxLength={200} /></Form.Item></Col>
          <Col span={8}><Form.Item name="compliance_valid_until" label="合规有效期"><Input type="date" /></Form.Item></Col>
          <Col span={8}><Form.Item name="compliance_confirmed" valuePropName="checked" label="合规确认"><Checkbox>负责人已核验此供应商/型号</Checkbox></Form.Item></Col>
        </Row>
      </Form>
    </Modal>
    <Drawer title={detail?.draft_no} open={!!detail} onClose={() => setDetail(null)} width={900}>
      {detail && <Space direction="vertical" style={{ width: '100%' }}>
        <Alert type="info" message={`状态：${statusLabels[detail.status] ?? detail.status}；有效期至 ${dateText(detail.expires_at)}`} />
        <DecisionView item={{ profile_id: '', run_id: '', status: detail.status, evidence: detail.snapshot, calculation: detail.calculation, issues: [] }} />
        {detail.status === 'WAITING_APPROVAL' && canApprove && <Space><Button type="primary" loading={busy} onClick={() => void approve()}>复核证据并生成业务草稿</Button><Button danger onClick={() => { setRejectReason(''); setRejectTarget(detail) }}>驳回</Button></Space>}
        {detail.reason && <Typography.Paragraph>驳回原因：{detail.reason}</Typography.Paragraph>}
        {detail.generated_records?.purchase_plan && <Typography.Paragraph>采购计划：{detail.generated_records.purchase_plan.plan_no}　<Link to="/purchase-plans">进入采购计划</Link></Typography.Paragraph>}
        {detail.generated_records?.fba_plans?.map(x => <Typography.Paragraph key={x.plan_no}>发货计划：{x.plan_no}（{x.quantity} 件）</Typography.Paragraph>)}
        {!!detail.generated_records?.fba_plans?.length && <Link to="/fba-plans">进入 FBA 发货计划</Link>}
        <Typography.Text type="secondary">生成的计划仍需按 ERP 既有流程提交、审批、配货和发运。</Typography.Text>
      </Space>}
    </Drawer>
    <Drawer title="工具运行记录" width={860} open={!!runDetail} onClose={() => setRunDetail(null)}>
      {runDetail?.tool_calls?.map(x => <Card key={x.id} title={`${x.tool} · ${x.status} · ${x.elapsed_ms}ms`} style={{ marginBottom: 12 }}><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify({ params: x.params, result: x.result }, null, 2)}</pre></Card>)}
    </Drawer>
    <RunTraceDrawer open={!!chatDetail} onClose={() => setChatDetail(null)} id={chatDetail?.id}
      model={chatDetail?.model} status={chatDetail?.status} elapsedMs={chatDetail?.result.elapsed_ms}
      legacy={!!chatDetail && !chatDetail.result.events}
      events={chatDetail?.result.events ?? (chatDetail?.trace ?? []).map(x => ({ kind: 'tool_end', title: x.tool, status: x.status, elapsed_ms: x.elapsed_ms, details: x.result }))} />
    <Modal title="驳回供需草稿" open={!!rejectTarget} onCancel={() => setRejectTarget(null)} onOk={() => void reject()} confirmLoading={busy}><Input.TextArea value={rejectReason} onChange={e => setRejectReason(e.target.value)} maxLength={500} placeholder="填写需要补充或重新核验的原因" /></Modal>
  </>
}
