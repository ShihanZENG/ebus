import { useEffect, useState } from 'react'
import { Alert, Button, Card, Input, Modal, Select, Space, Table, Tag, Tabs, Typography, message } from 'antd'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

type Kind = 'profit' | 'ads' | 'customer' | 'rules'
interface GenerationResult { id: string; kind: string; evidence_hash: string; source_reference: string; review_required: boolean; result: Record<string, unknown> }
interface ReviewItem extends GenerationResult { shop_id: string; review_status: 'pending' | 'approved' | 'rejected'; created_at: string; review_note?: string | null }
interface Shop { id: string; name: string; code: string }
interface Ticket { id: string; ticket_no: string; subject: string }

const today = new Date().toISOString().slice(0, 10)
const help: Record<Kind, string> = {
  profit: '利润行 JSON：每行包含 source_event_id、category、amount；平台实际从结算中扣除的费用另标 settlement_deducted=true。',
  ads: '广告行 JSON：每行包含 source_row_id、campaign_id、attribution_window_days、impressions、clicks、spend、attributed_orders、attributed_sales。',
  customer: '从真实工单生成回复草稿。仅使用管理员发布且匹配店铺市场、类目和生效日的规则。',
  rules: '管理员维护规则。applicable_roles 留空仅适用于有权客服角色；若要让登录的独立站顾客看到此规则，须明确加入 storefront_customer，并确认正文可对外公开。',
}

export default function AgentGenerationsPage() {
  const { user } = useAuth()
  const can = (permission: string) => user?.role === 'admin' || !!user?.permissions.includes(permission)
  const [kind, setKind] = useState<Kind>('profit')
  const [shops, setShops] = useState<Shop[]>([])
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [shopId, setShopId] = useState('')
  const [source, setSource] = useState('')
  const [start, setStart] = useState(today)
  const [end, setEnd] = useState(today)
  const [currency, setCurrency] = useState('USD')
  const [rowsJson, setRowsJson] = useState('')
  const [reported, setReported] = useState('')
  const [ticketId, setTicketId] = useState('')
  const [category, setCategory] = useState('')
  const [asOf, setAsOf] = useState(today)
  const [ruleJson, setRuleJson] = useState('')
  const [busy, setBusy] = useState(false)
  const [output, setOutput] = useState<unknown>(null)
  const [reviews, setReviews] = useState<ReviewItem[]>([])
  const [reviewsBusy, setReviewsBusy] = useState(false)
  const [decision, setDecision] = useState<{ item: ReviewItem; status: 'approved' | 'rejected' } | null>(null)
  const [reviewNote, setReviewNote] = useState('')

  const loadReviews = async () => {
    if (user?.role !== 'admin') return
    setReviewsBusy(true)
    try {
      const data = await request<{ items: ReviewItem[] }>('/generation-reviews', {
        params: { review_status: 'pending', page: 1, page_size: 50 },
      })
      setReviews(data.items)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '待审核记录加载失败')
    } finally { setReviewsBusy(false) }
  }

  useEffect(() => {
    if (can('shops:read')) {
      request<{ items: Shop[] }>('/shops', { params: { page: 1, page_size: 100 } })
        .then((data) => setShops(data.items)).catch(() => setShops([]))
    }
    if (can('customer_tickets:read')) {
      request<{ items: Ticket[] }>('/customer-tickets', { params: { page: 1, page_size: 100 } })
        .then((data) => setTickets(data.items)).catch(() => setTickets([]))
    }
    if (user?.role === 'admin') void loadReviews()
  }, [user])

  const submitDecision = async () => {
    if (!decision) return
    if (decision.status === 'rejected' && !reviewNote.trim()) {
      message.error('驳回时必须填写原因')
      return
    }
    setReviewsBusy(true)
    try {
      await request(`/generation-reviews/${decision.item.id}/decision`, {
        method: 'POST', body: { status: decision.status, note: reviewNote.trim() },
      })
      message.success(decision.status === 'approved' ? '已审核通过' : '已驳回')
      setDecision(null)
      setReviewNote('')
      await loadReviews()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '审核失败')
      setReviewsBusy(false)
    }
  }

  const submit = async () => {
    setBusy(true)
    setOutput(null)
    try {
      let result: unknown
      if (kind === 'rules') {
        result = await request('/agent-generations/rules', { method: 'POST', body: JSON.parse(ruleJson) })
      } else if (kind === 'customer') {
        if (!ticketId || !category) throw new Error('请选择工单并填写类目')
        result = await request<GenerationResult>(`/agent-generations/customer/${ticketId}`,
          { method: 'POST', body: { category, as_of: asOf } })
      } else {
        if (!shopId || !source || !rowsJson) throw new Error('请填写店铺、来源与明细')
        const rows = JSON.parse(rowsJson)
        if (!Array.isArray(rows)) throw new Error('明细须为 JSON 数组')
        const body = { shop_id: shopId, source_reference: source, period_start: start,
          period_end: end, currency, ...(kind === 'profit' ? { lines: rows,
            reported_settlement: reported === '' ? null : reported } : { rows }) }
        result = await request<GenerationResult>(`/agent-generations/${kind}`, { method: 'POST', body })
      }
      setOutput(result)
      message.success(kind === 'rules' ? '规则已保存' : '待审核草稿已生成并留存证据')
      if (kind !== 'rules' && user?.role === 'admin') void loadReviews()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '生成失败')
    } finally { setBusy(false) }
  }

  const allowed = kind === 'rules' ? user?.role === 'admin'
    : kind === 'customer' ? can('customer_tickets:read')
      : kind === 'ads' ? can('advertising_agent:write') : can('finance_agent:write')
  return <Space direction="vertical" size="large" style={{ width: '100%' }}>
    <Typography.Title level={3}>经营与客服生成</Typography.Title>
    <Alert type="info" showIcon message="真实输入、服务端计算、模型草稿、人工审核"
      description="利润与广告数字由后端计算，模型只解释结果。客服草稿只引用已发布规则。任何生成结果都不会自动退款、发消息或改预算。" />
    <Card>
      <Tabs activeKey={kind} onChange={(value) => { setKind(value as Kind); setOutput(null) }} items={[
        { key: 'profit', label: '利润与对账' }, { key: 'ads', label: '广告与经营' },
        { key: 'customer', label: '客服草稿' }, ...(user?.role === 'admin' ? [{ key: 'rules', label: '发布规则' }] : []),
      ]} />
      <Typography.Paragraph type="secondary">{help[kind]}</Typography.Paragraph>
      {kind === 'profit' || kind === 'ads' ? <Space direction="vertical" style={{ width: '100%' }}>
        <Select showSearch optionFilterProp="label" placeholder="选择店铺" value={shopId || undefined}
          onChange={setShopId} options={shops.map((s) => ({ value: s.id, label: `${s.name} (${s.code})` }))} />
        {!shops.length && <Input value={shopId} onChange={(e) => setShopId(e.target.value)} placeholder="店铺 ID" />}
        <Input value={source} onChange={(e) => setSource(e.target.value)} placeholder="真实来源，例如平台账单号或广告报表文件名" />
        <Space wrap>
          <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          <Input value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} maxLength={3} placeholder="币种" />
        </Space>
        <Input.TextArea rows={10} value={rowsJson} onChange={(e) => setRowsJson(e.target.value)}
          placeholder={kind === 'profit' ? '[{"source_event_id":"账单行1","category":"sale","amount":"100.00"}]'
            : '[{"source_row_id":"报表行1","campaign_id":"活动1","attribution_window_days":7,"impressions":100,"clicks":10,"spend":"5.00","attributed_orders":1,"attributed_sales":"50.00"}]'} />
        {kind === 'profit' && <Input value={reported} onChange={(e) => setReported(e.target.value)} placeholder="平台报告应结金额（可留空）" />}
      </Space> : kind === 'customer' ? <Space direction="vertical" style={{ width: '100%' }}>
        <Select showSearch optionFilterProp="label" placeholder="选择工单" value={ticketId || undefined}
          onChange={setTicketId} options={tickets.map((t) => ({ value: t.id, label: `${t.ticket_no} ${t.subject}` }))} />
        {!tickets.length && <Input value={ticketId} onChange={(e) => setTicketId(e.target.value)} placeholder="工单 ID" />}
        <Input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="规则类目，例如 apparel 或 3c" />
        <Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
      </Space> : <Input.TextArea rows={10} value={ruleJson} onChange={(e) => setRuleJson(e.target.value)}
        placeholder='{"rule_code":"...","version":"v1","status":"published","market":"...","category":"apparel","applicable_roles":["customer_service_agent"],"effective_from":"2026-10-01","source_reference":"...","content":"..."}' />}
      <div style={{ marginTop: 16 }}><Button type="primary" loading={busy} disabled={!allowed} onClick={() => void submit()}>
        {kind === 'rules' ? '保存规则' : '生成待审核草稿'}
      </Button></div>
    </Card>
    {output !== null && <Card title="生成结果与证据"><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
      {JSON.stringify(output, null, 2)}
    </pre></Card>}
    {user?.role === 'admin' && <Card title="待审核生成结果" extra={<Button onClick={() => void loadReviews()} loading={reviewsBusy}>刷新</Button>}>
      <Table rowKey="id" dataSource={reviews} loading={reviewsBusy} pagination={false}
        expandable={{
          expandedRowRender: (item: ReviewItem) => <div>
            <Typography.Text strong>完整生成结果（草稿、规则引用及限制说明）</Typography.Text>
            <pre style={{ marginTop: 8, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 480, overflow: 'auto' }}>
              {JSON.stringify(item.result ?? {}, null, 2)}
            </pre>
          </div>,
          rowExpandable: (item: ReviewItem) => item.result !== undefined && item.result !== null,
          columnTitle: '查看结果',
        }}
        columns={[
        { title: '类型', dataIndex: 'kind', width: 150 },
        { title: '来源', dataIndex: 'source_reference', ellipsis: true },
        { title: '生成时间', dataIndex: 'created_at', width: 190, render: (value: string) => new Date(value).toLocaleString() },
        { title: '状态', dataIndex: 'review_status', width: 100, render: () => <Tag color="orange">待审核</Tag> },
        { title: '操作', width: 150, render: (_: unknown, item: ReviewItem) => <Space>
          <Button type="link" onClick={() => { setReviewNote(''); setDecision({ item, status: 'approved' }) }}>通过</Button>
          <Button type="link" danger onClick={() => { setReviewNote(''); setDecision({ item, status: 'rejected' }) }}>驳回</Button>
        </Space> },
      ]} />
    </Card>}
    <Modal open={!!decision} title={decision?.status === 'approved' ? '审核通过' : '驳回生成结果'}
      okText={decision?.status === 'approved' ? '确认通过' : '确认驳回'} confirmLoading={reviewsBusy}
      onOk={() => void submitDecision()} onCancel={() => { setDecision(null); setReviewNote('') }}>
      <Typography.Paragraph type="secondary">来源：{decision?.item.source_reference}</Typography.Paragraph>
      <Input.TextArea rows={4} value={reviewNote} onChange={(event) => setReviewNote(event.target.value)}
        placeholder={decision?.status === 'rejected' ? '填写驳回原因（必填）' : '填写审核备注（可选）'} />
    </Modal>
  </Space>
}
