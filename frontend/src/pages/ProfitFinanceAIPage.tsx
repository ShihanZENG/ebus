import { useEffect, useState } from 'react'
import { Alert, Button, Card, Checkbox, Descriptions, Input, InputNumber, Modal, Select, Space, Table, Tag, Tabs, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

interface Shop { id: string; name: string; code: string }
interface ProfitLine { key: string; source_event_id: string; category: string; amount: number; settlement_deducted: boolean }
interface ProfitFacts {
  currency: string
  period_start: string
  period_end: string
  net_sales: string
  contribution: string
  contribution_rate_pct: string | null
  after_known_costs: string
  expected_settlement: string
  reported_settlement: string | null
  settlement_delta: string | null
  settlement_status: string
  limitations: string[]
}
interface GenerationResult { id: string; kind: string; review_status: string; source_reference: string; evidence_hash?: string; result: { facts?: ProfitFacts; draft?: string } }
interface ReviewItem { id: string; kind: string; source_reference: string; review_status: 'pending' | 'approved' | 'rejected'; created_at: string; result: { facts?: ProfitFacts } }
interface FeeResult {
  status: string
  currency: string
  confirmed_overcharge: boolean
  expected_charge: string | null
  net_actual_charge: string | null
  discrepancy: string | null
  reason: string
  missing_evidence?: string[]
}

const today = new Date().toISOString().slice(0, 10)
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()))
const CATEGORIES = ['sale', 'refund', 'cogs', 'platform_fee', 'advertising', 'logistics', 'tax', 'settlement_other']
const statusColor: Record<string, string> = {
  CONFIRMED_OVERCHARGE: 'red', MATCHED: 'green', UNDERCHARGE: 'orange',
  EVIDENCE_INCOMPLETE: 'orange', RATE_NOT_APPLICABLE: 'orange', ADJUSTMENT_PENDING: 'orange',
}

function blankLine(): ProfitLine {
  return { key: uid(), source_event_id: '', category: 'sale', amount: 0, settlement_deducted: false }
}

export default function ProfitFinanceAIPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const can = (p: string) => isAdmin || !!user?.permissions.includes(p)
  const [shops, setShops] = useState<Shop[]>([])
  const [shopId, setShopId] = useState('')
  const [source, setSource] = useState('')
  const [start, setStart] = useState(today)
  const [end, setEnd] = useState(today)
  const [currency, setCurrency] = useState('USD')
  const [lines, setLines] = useState<ProfitLine[]>([blankLine()])
  const [reported, setReported] = useState('')
  const [busy, setBusy] = useState(false)
  const [output, setOutput] = useState<GenerationResult | null>(null)

  // 费用差异复核表单
  const [feeSource, setFeeSource] = useState('')
  const [feeCurrency, setFeeCurrency] = useState('USD')
  const [fee, setFee] = useState({
    statement_line_id: '', fee_code: '', transaction_type: '',
    transaction_date: today, settlement_period_start: today, settlement_period_end: today,
    rate_source_reference: '', rate_effective_from: today, rate_effective_until: '',
    billing_base: 0, applicable_rate_pct: 0, fixed_fee: 0, actual_charge: 0,
  })
  const [adjustmentsReviewed, setAdjustmentsReviewed] = useState(false)
  const [feeBusy, setFeeBusy] = useState(false)
  const [feeOutput, setFeeOutput] = useState<FeeResult | null>(null)

  const [reviews, setReviews] = useState<ReviewItem[]>([])
  const [reviewsBusy, setReviewsBusy] = useState(false)
  const [decision, setDecision] = useState<{ item: ReviewItem; status: 'approved' | 'rejected' } | null>(null)
  const [reviewNote, setReviewNote] = useState('')

  useEffect(() => {
    if (can('shops:read')) {
      request<{ items: Shop[] }>('/shops', { params: { page: 1, page_size: 100 } })
        .then((data) => setShops(data.items)).catch(() => setShops([]))
    }
  }, [user])

  const loadReviews = async () => {
    if (!can('finance_agent:read')) return
    setReviewsBusy(true)
    try {
      const items: ReviewItem[] = []
      for (const kind of ['profit', 'fee_reconciliation']) {
        const data = await request<{ items: ReviewItem[] }>('/generation-reviews', {
          params: { kind, review_status: 'pending', page: 1, page_size: 50 },
        })
        items.push(...data.items)
      }
      setReviews(items)
    } catch { setReviews([]) } finally { setReviewsBusy(false) }
  }
  useEffect(() => { void loadReviews() }, [user])

  const updateLine = (key: string, patch: Partial<ProfitLine>) =>
    setLines((cur) => cur.map((l) => (l.key === key ? { ...l, ...patch } : l)))

  const submitProfit = async () => {
    if (!shopId || !source) { message.error('请填写店铺与真实来源'); return }
    if (lines.some((l) => !l.source_event_id)) { message.error('每行需填写来源事件 ID'); return }
    setBusy(true); setOutput(null)
    try {
      const body = {
        shop_id: shopId, source_reference: source, period_start: start, period_end: end, currency,
        lines: lines.map(({ key, ...l }) => l),
        reported_settlement: reported === '' ? null : reported,
      }
      const result = await request<GenerationResult>('/agent-generations/profit', { method: 'POST', body })
      setOutput(result)
      message.success('利润复算草稿已生成并留存证据，待人工审核')
      if (isAdmin) void loadReviews()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '生成失败')
    } finally { setBusy(false) }
  }

  const submitFee = async () => {
    if (!shopId || !feeSource) { message.error('请填写店铺与真实来源'); return }
    setFeeBusy(true); setFeeOutput(null)
    try {
      const body = {
        shop_id: shopId, source_reference: feeSource, currency: feeCurrency,
        statement_line_id: fee.statement_line_id || null,
        fee_code: fee.fee_code || null,
        transaction_type: fee.transaction_type || null,
        transaction_date: fee.transaction_date,
        settlement_period_start: fee.settlement_period_start,
        settlement_period_end: fee.settlement_period_end,
        rate_source_reference: fee.rate_source_reference || null,
        rate_effective_from: fee.rate_effective_from,
        rate_effective_until: fee.rate_effective_until || null,
        billing_base: fee.billing_base,
        applicable_rate_pct: fee.applicable_rate_pct,
        fixed_fee: fee.fixed_fee,
        actual_charge: fee.actual_charge,
        adjustments_reviewed: adjustmentsReviewed,
        adjustments: [],
      }
      const result = await request<{ result: FeeResult }>('/profit-reconciliations/fee-discrepancies', { method: 'POST', body })
      setFeeOutput(result.result)
      message.success('费用差异复核已留存证据，待人工审核')
      if (isAdmin) void loadReviews()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '复核失败')
    } finally { setFeeBusy(false) }
  }

  const decide = async (item: ReviewItem, status: 'approved' | 'rejected') => {
    if (status === 'rejected' && !reviewNote.trim()) { message.error('驳回必须填写原因'); return }
    setReviewsBusy(true)
    try {
      await request(`/generation-reviews/${item.id}/decision`, { method: 'POST', body: { status, note: reviewNote.trim() } })
      message.success(status === 'approved' ? '已审核通过' : '已驳回')
      setDecision(null); setReviewNote('')
      await loadReviews()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '审核失败')
    } finally { setReviewsBusy(false) }
  }

  const reviewColumns: ColumnsType<ReviewItem> = [
    { title: '类型', dataIndex: 'kind', width: 160, render: (v: string) => v === 'fee_reconciliation' ? '费用复核' : '利润复算' },
    { title: '来源', dataIndex: 'source_reference', ellipsis: true },
    { title: '生成时间', dataIndex: 'created_at', width: 180, render: (v: string) => new Date(v).toLocaleString() },
    { title: '状态', dataIndex: 'review_status', width: 100, render: (v: string) => <Tag color={v === 'pending' ? 'orange' : v === 'approved' ? 'green' : 'red'}>{v}</Tag> },
    { title: '操作', width: 160, render: (_: unknown, item: ReviewItem) => <Space>
      <Button type="link" disabled={item.review_status !== 'pending'} onClick={() => setDecision({ item, status: 'approved' })}>通过</Button>
      <Button type="link" danger disabled={item.review_status !== 'pending'} onClick={() => setDecision({ item, status: 'rejected' })}>驳回</Button>
    </Space> },
  ]

  const facts = output?.result.facts

  return <><Tabs defaultActiveKey="profit" items={[
    {
      key: 'profit',
      label: '利润复算',
      children: <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Alert type="info" showIcon message="真实账单输入、服务端计算、模型草稿、人工审核"
          description="销售、采购成本、平台费必须各有来源行；缺项不能当作零。不同口径的结果不会合并成「最终净利润」。" />
        <Card>
          <Space wrap style={{ marginBottom: 12 }}>
            <Select showSearch optionFilterProp="label" placeholder="选择店铺" value={shopId || undefined} onChange={setShopId}
              style={{ width: 240 }} options={shops.map((s) => ({ value: s.id, label: `${s.name} (${s.code})` }))} />
            {!shops.length && <Input value={shopId} onChange={(e) => setShopId(e.target.value)} placeholder="店铺 ID（36 位）" style={{ width: 360 }} />}
            <Input value={source} onChange={(e) => setSource(e.target.value)} placeholder="真实来源：平台账单号或报表文件名" style={{ width: 280 }} />
            <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
            <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
            <Input value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} maxLength={3} placeholder="币种" style={{ width: 80 }} />
          </Space>
          <Table<ProfitLine> rowKey="key" dataSource={lines} pagination={false} size="small"
            columns={[
              { title: '来源事件 ID', dataIndex: 'source_event_id', render: (v: string, r) => <Input value={v} onChange={(e) => updateLine(r.key, { source_event_id: e.target.value })} /> },
              { title: '类别', dataIndex: 'category', width: 160, render: (v: string, r) => <Select value={v} onChange={(val) => updateLine(r.key, { category: val })} options={CATEGORIES.map((c) => ({ value: c, label: c }))} /> },
              { title: '金额', dataIndex: 'amount', render: (v: number, r) => <InputNumber min={0} precision={2} value={v} onChange={(val) => updateLine(r.key, { amount: val ?? 0 })} /> },
              { title: '已从结算扣除', dataIndex: 'settlement_deducted', width: 130, render: (v: boolean, r) => <Checkbox checked={v} onChange={(e) => updateLine(r.key, { settlement_deducted: e.target.checked })} /> },
              { title: '', width: 60, render: (_: unknown, r) => <Button danger type="link" onClick={() => setLines((cur) => cur.filter((x) => x.key !== r.key))}>删除</Button> },
            ]} />
          <Space wrap style={{ marginTop: 12 }}>
            <Button onClick={() => setLines((cur) => [...cur, blankLine()])}>添加一行</Button>
            <Input value={reported} onChange={(e) => setReported(e.target.value)} placeholder="平台报告应结金额（可留空）" style={{ width: 240 }} />
          </Space>
          <div style={{ marginTop: 16 }}>
            <Button type="primary" loading={busy} disabled={!can('finance_agent:write')} onClick={() => void submitProfit()}>生成利润复算草稿</Button>
            {!can('finance_agent:write') && <Typography.Text type="secondary" style={{ marginLeft: 12 }}>需要 finance_agent:write 权限</Typography.Text>}
          </div>
        </Card>
        {output && <Card title={`复算结果（${output.review_status === 'pending' ? '待审核' : output.review_status}）`}>
          <Space wrap style={{ marginBottom: 8 }}>
            <Tag>来源：{output.source_reference}</Tag>
            <Tag color="blue">证据哈希 {output.evidence_hash ? `${String(output.evidence_hash).slice(0, 10)}…` : '—'}</Tag>
          </Space>
          {facts && <>
            <Descriptions bordered column={2} size="small">
              <Descriptions.Item label="净销售">{facts.net_sales}</Descriptions.Item>
              <Descriptions.Item label="贡献利润">{facts.contribution}</Descriptions.Item>
              <Descriptions.Item label="贡献率%">{facts.contribution_rate_pct ?? '—'}</Descriptions.Item>
              <Descriptions.Item label="已知费用后">{facts.after_known_costs}</Descriptions.Item>
              <Descriptions.Item label="平台应结额">{facts.expected_settlement}</Descriptions.Item>
              <Descriptions.Item label="报告应结额">{facts.reported_settlement ?? '—'}</Descriptions.Item>
              <Descriptions.Item label="结算差额">{facts.settlement_delta ?? '—'}</Descriptions.Item>
              <Descriptions.Item label="结算状态"><Tag color={facts.settlement_status === 'MATCHED' ? 'green' : facts.settlement_status === 'REVIEW_REQUIRED' ? 'orange' : 'default'}>{facts.settlement_status}</Tag></Descriptions.Item>
            </Descriptions>
            <Alert type="warning" showIcon style={{ marginTop: 12 }} message="口径说明"
              description={<ul style={{ margin: 0, paddingLeft: 18 }}>{facts.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>} />
            <Typography.Paragraph style={{ marginTop: 12 }}><Typography.Text strong>模型说明（待审核）：</Typography.Text>{output.result.draft}</Typography.Paragraph>
          </>}
        </Card>}
      </Space>,
    },
    {
      key: 'fee',
      label: '费用差异复核',
      children: <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Alert type="info" showIcon message="单笔平台费用证据复算"
          description="只有账单行、费用代码、交易类型与日期、适用费率及生效期、计费基数、实扣额与调整记录完整时，才可能给出 CONFIRMED_OVERCHARGE。缺证据返回人工复核，不把缺失当作零。" />
        <Card>
          <Space wrap style={{ marginBottom: 12 }}>
            {!shops.length && <Input value={shopId} onChange={(e) => setShopId(e.target.value)} placeholder="店铺 ID（36 位）" style={{ width: 360 }} />}
            <Select showSearch optionFilterProp="label" placeholder="选择店铺" value={shopId || undefined} onChange={setShopId} style={{ width: 240 }} options={shops.map((s) => ({ value: s.id, label: `${s.name} (${s.code})` }))} />
            <Input value={feeSource} onChange={(e) => setFeeSource(e.target.value)} placeholder="真实来源：平台账单号" style={{ width: 240 }} />
            <Input value={feeCurrency} onChange={(e) => setFeeCurrency(e.target.value.toUpperCase())} maxLength={3} placeholder="币种" style={{ width: 80 }} />
          </Space>
          <Space wrap>
            <Input value={fee.statement_line_id} onChange={(e) => setFee((f) => ({ ...f, statement_line_id: e.target.value }))} placeholder="账单行 ID" style={{ width: 150 }} />
            <Input value={fee.fee_code} onChange={(e) => setFee((f) => ({ ...f, fee_code: e.target.value }))} placeholder="费用代码" style={{ width: 130 }} />
            <Input value={fee.transaction_type} onChange={(e) => setFee((f) => ({ ...f, transaction_type: e.target.value }))} placeholder="交易类型" style={{ width: 130 }} />
            <Input type="date" value={fee.transaction_date} onChange={(e) => setFee((f) => ({ ...f, transaction_date: e.target.value }))} />
          </Space>
          <Typography.Paragraph type="secondary" style={{ margin: '12px 0 4px' }}>结算期间</Typography.Paragraph>
          <Space wrap>
            <Input type="date" value={fee.settlement_period_start} onChange={(e) => setFee((f) => ({ ...f, settlement_period_start: e.target.value }))} />
            <Input type="date" value={fee.settlement_period_end} onChange={(e) => setFee((f) => ({ ...f, settlement_period_end: e.target.value }))} />
          </Space>
          <Typography.Paragraph type="secondary" style={{ margin: '12px 0 4px' }}>适用费率</Typography.Paragraph>
          <Space wrap>
            <Input value={fee.rate_source_reference} onChange={(e) => setFee((f) => ({ ...f, rate_source_reference: e.target.value }))} placeholder="费率来源" style={{ width: 200 }} />
            <Input type="date" value={fee.rate_effective_from} onChange={(e) => setFee((f) => ({ ...f, rate_effective_from: e.target.value }))} placeholder="费率生效日" />
            <Input type="date" value={fee.rate_effective_until} onChange={(e) => setFee((f) => ({ ...f, rate_effective_until: e.target.value }))} placeholder="费率失效日（可选）" />
          </Space>
          <Typography.Paragraph type="secondary" style={{ margin: '12px 0 4px' }}>计费与实扣</Typography.Paragraph>
          <Space wrap>
            <InputNumber min={0} precision={2} value={fee.billing_base} onChange={(val) => setFee((f) => ({ ...f, billing_base: val ?? 0 }))} addonBefore="计费基数" style={{ width: 200 }} />
            <InputNumber min={0} precision={4} value={fee.applicable_rate_pct} onChange={(val) => setFee((f) => ({ ...f, applicable_rate_pct: val ?? 0 }))} addonBefore="费率%" style={{ width: 180 }} />
            <InputNumber min={0} precision={2} value={fee.fixed_fee} onChange={(val) => setFee((f) => ({ ...f, fixed_fee: val ?? 0 }))} addonBefore="固定费" style={{ width: 180 }} />
            <InputNumber min={0} precision={2} value={fee.actual_charge} onChange={(val) => setFee((f) => ({ ...f, actual_charge: val ?? 0 }))} addonBefore="实扣额" style={{ width: 200 }} />
          </Space>
          <div style={{ marginTop: 12 }}><Checkbox checked={adjustmentsReviewed} onChange={(e) => setAdjustmentsReviewed(e.target.checked)}>已核对调整/冲回记录（未核对将判定证据不完整）</Checkbox></div>
          <div style={{ marginTop: 16 }}>
            <Button type="primary" loading={feeBusy} disabled={!can('finance_agent:write')} onClick={() => void submitFee()}>复核平台费用</Button>
          </div>
        </Card>
        {feeOutput && <Card title="复核结果">
          <Space wrap style={{ marginBottom: 8 }}>
            <Tag color={statusColor[feeOutput.status] ?? 'default'}>{feeOutput.status}</Tag>
            <Tag color={feeOutput.confirmed_overcharge ? 'red' : 'default'}>{feeOutput.confirmed_overcharge ? '疑似多扣' : '未确认多扣'}</Tag>
          </Space>
          <Descriptions bordered column={2} size="small">
            <Descriptions.Item label="复算应扣">{feeOutput.expected_charge ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="净实扣">{feeOutput.net_actual_charge ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="差额">{feeOutput.discrepancy ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="币种">{feeOutput.currency}</Descriptions.Item>
          </Descriptions>
          <Alert type="info" showIcon style={{ marginTop: 12 }} message={feeOutput.reason} />
          {!!feeOutput.missing_evidence?.length && <Alert type="warning" showIcon style={{ marginTop: 8 }}
            message={`缺失证据：${feeOutput.missing_evidence.join('、')}`} />}
        </Card>}
      </Space>,
    },
    {
      key: 'review',
      label: '审核队列',
      children: <Card title="待审核利润与费用记录" extra={<Button onClick={() => void loadReviews()} loading={reviewsBusy}>刷新</Button>}>
        <Table<ReviewItem> rowKey="id" dataSource={reviews} loading={reviewsBusy} pagination={false}
          expandable={{ expandedRowRender: (item) => item.result.facts ? <Descriptions bordered column={2} size="small">
            <Descriptions.Item label="净销售">{item.result.facts.net_sales}</Descriptions.Item>
            <Descriptions.Item label="贡献利润">{item.result.facts.contribution}</Descriptions.Item>
            <Descriptions.Item label="平台应结额">{item.result.facts.expected_settlement}</Descriptions.Item>
            <Descriptions.Item label="结算状态">{item.result.facts.settlement_status}</Descriptions.Item>
          </Descriptions> : null }}
          columns={reviewColumns} />
        {!can('finance_agent:read') && <Typography.Text type="secondary">需要 finance_agent:read 权限查看审核队列</Typography.Text>}
        {!isAdmin && can('finance_agent:read') && <Typography.Text type="secondary"> 仅管理员可执行审核决定</Typography.Text>}
      </Card>,
    },
  ]} />
    <Modal open={!!decision} title={decision?.status === 'approved' ? '审核通过' : '驳回生成结果'}
      okText={decision?.status === 'approved' ? '确认通过' : '确认驳回'} confirmLoading={reviewsBusy}
      onOk={() => decision && void decide(decision.item, decision.status)} onCancel={() => { setDecision(null); setReviewNote('') }}>
      <Typography.Paragraph type="secondary">来源：{decision?.item.source_reference}</Typography.Paragraph>
      <Input.TextArea rows={4} value={reviewNote} onChange={(e) => setReviewNote(e.target.value)}
        placeholder={decision?.status === 'rejected' ? '填写驳回原因（必填）' : '填写审核备注（可选）'} />
    </Modal>
  </>
}
