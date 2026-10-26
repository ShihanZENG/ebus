import { useCallback, useEffect, useState } from 'react'
import {
  Alert, Button, Card, Col, Form, Input, Row, Select, Space, Table, Tag, Typography, message,
} from 'antd'
import api from '../api'
import { useAuth } from '../auth/AuthProvider'

interface Shop {
  id: string
  name: string
  code: string
}

interface FeeResult {
  currency: string
  statement_line_id?: string | null
  fee_code?: string | null
  transaction_type?: string | null
  transaction_date?: string | null
  status: string
  confirmed_overcharge: boolean
  review_required: boolean
  expected_charge: string | null
  actual_charge?: string | null
  posted_adjustments?: string | null
  net_actual_charge: string | null
  discrepancy: string | null
  missing_evidence: string[]
  reason: string
}

interface FeeEvidence {
  rate_source_reference?: string | null
  rate_effective_from?: string | null
  rate_effective_until?: string | null
  billing_base?: string | null
  applicable_rate_pct?: string | null
}

interface FeeRecord {
  id: string
  shop_id: string
  source_reference: string
  evidence_hash: string
  created_at: string
  review_required: boolean
  review_status: 'pending' | 'approved' | 'rejected'
  review_note?: string | null
  evidence?: FeeEvidence | null
  result: FeeResult
}

interface FeeHistory {
  items: FeeRecord[]
  total: number
  page: number
  page_size: number
}

const feeStatus: Record<string, { label: string; color: string }> = {
  EVIDENCE_INCOMPLETE: { label: '待补证', color: 'orange' },
  RATE_NOT_APPLICABLE: { label: '费率未覆盖交易日', color: 'red' },
  ADJUSTMENT_PENDING: { label: '调整待入账', color: 'orange' },
  CONFIRMED_OVERCHARGE: { label: '复算发现多扣', color: 'red' },
  UNDERCHARGE: { label: '少扣，需复核', color: 'volcano' },
  MATCHED: { label: '复算一致', color: 'green' },
}

const missingEvidenceLabels: Record<string, string> = {
  statement_line_id: '账单行号',
  fee_code: '费用代码',
  transaction_type: '交易类型',
  transaction_date: '交易日期',
  settlement_period_start: '结算期开始',
  settlement_period_end: '结算期结束',
  rate_source_reference: '费率来源',
  rate_effective_from: '费率生效日',
  billing_base: '计费基数',
  applicable_rate_pct: '适用费率',
  actual_charge: '实扣金额',
  adjustments_reviewed: '调整项核对',
}

function money(value: string | null | undefined, currency: string) {
  return value === null || value === undefined ? '—' : `${currency} ${value}`
}

function localDateTime(value: string) {
  const date = new Date(value.endsWith('Z') ? value : `${value}Z`)
  return Number.isNaN(date.getTime()) ? '时间格式无效' : date.toLocaleString('zh-CN', { hour12: false })
}

function blankToNull(value: unknown) {
  if (value === undefined || value === null || String(value).trim() === '') return null
  return String(value).trim()
}

export default function FinanceFeeReconciliationPanel() {
  const { user } = useAuth()
  const can = (permission: string) => user?.role === 'admin' || Boolean(user?.permissions.includes(permission))
  const canRead = can('finance_agent:read')
  const canWrite = can('finance_agent:write')
  const canReadShops = can('shops:read')
  const [form] = Form.useForm()
  const [shops, setShops] = useState<Shop[]>([])
  const [records, setRecords] = useState<FeeRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [sourceDraft, setSourceDraft] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [currencyDraft, setCurrencyDraft] = useState('')
  const [currencyFilter, setCurrencyFilter] = useState<string>()
  const [shopFilter, setShopFilter] = useState<string>()
  const [latestResult, setLatestResult] = useState<FeeRecord | null>(null)

  useEffect(() => {
    if (!canReadShops) return
    api.get<{ items: Shop[] }>('/shops', { params: { page: 1, page_size: 100 } })
      .then((response) => setShops(response.data.items))
      .catch(() => setShops([]))
  }, [canReadShops])

  const loadHistory = useCallback(async (nextPage = 1) => {
    if (!canRead) return
    setLoading(true)
    setHistoryError('')
    try {
      const response = await api.get<FeeHistory>('/profit-reconciliations/fee-discrepancies', {
        params: {
          page: nextPage,
          page_size: 20,
          ...(shopFilter ? { shop_id: shopFilter } : {}),
          ...(currencyFilter ? { currency: currencyFilter } : {}),
          ...(sourceFilter ? { source_reference: sourceFilter } : {}),
        },
      })
      setRecords(response.data.items)
      setTotal(response.data.total)
      setPage(response.data.page)
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : '费用复算历史加载失败')
    } finally {
      setLoading(false)
    }
  }, [canRead, currencyFilter, shopFilter, sourceFilter])

  useEffect(() => { void loadHistory(1) }, [loadHistory])

  const submit = async (values: Record<string, any>) => {
    if (!canWrite) return
    setSubmitting(true)
    try {
      const payload = {
        shop_id: values.shop_id,
        source_reference: values.source_reference,
        currency: String(values.currency || '').trim().toUpperCase(),
        statement_line_id: blankToNull(values.statement_line_id),
        fee_code: blankToNull(values.fee_code),
        transaction_type: blankToNull(values.transaction_type),
        transaction_date: blankToNull(values.transaction_date),
        settlement_period_start: blankToNull(values.settlement_period_start),
        settlement_period_end: blankToNull(values.settlement_period_end),
        rate_source_reference: blankToNull(values.rate_source_reference),
        rate_effective_from: blankToNull(values.rate_effective_from),
        rate_effective_until: blankToNull(values.rate_effective_until),
        billing_base: blankToNull(values.billing_base),
        applicable_rate_pct: blankToNull(values.applicable_rate_pct),
        fixed_fee: blankToNull(values.fixed_fee) ?? '0.00',
        actual_charge: blankToNull(values.actual_charge),
        adjustments_reviewed: values.adjustments_reviewed ?? null,
        adjustments: values.adjustments ?? [],
      }
      const response = await api.post<FeeRecord>('/profit-reconciliations/fee-discrepancies', payload)
      setLatestResult(response.data)
      if (response.data.result.status === 'EVIDENCE_INCOMPLETE') {
        message.warning('记录已保存为待补证，未确认多扣')
      } else {
        message.success('复算记录已保存，仍需人工审核')
      }
      await loadHistory(1)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '费用复算失败')
    } finally {
      setSubmitting(false)
    }
  }

  if (!canRead && !canWrite) return null

  const columns = [
    { title: '记录号', dataIndex: 'id', width: 120, render: (value: string) => <Typography.Text copyable={{ text: value }}>{value.slice(0, 8)}…</Typography.Text> },
    { title: '记录时间', dataIndex: 'created_at', width: 165, render: (value: string) => localDateTime(value) },
    { title: '店铺', dataIndex: 'shop_id', width: 120, render: (value: string) => shops.find((shop) => shop.id === value)?.name || value.slice(0, 8) },
    { title: '凭据来源', dataIndex: 'source_reference', width: 200 },
    { title: '币种', dataIndex: ['result', 'currency'], width: 75 },
    { title: '费用代码', dataIndex: ['result', 'fee_code'], width: 120, render: (value?: string | null) => value || '—' },
    { title: '账单行', dataIndex: ['result', 'statement_line_id'], width: 110, render: (value?: string | null) => value || '—' },
    { title: '费率来源', dataIndex: ['evidence', 'rate_source_reference'], width: 180, render: (value?: string | null) => value || '—' },
    { title: '计费基数 / 费率', width: 165, render: (_: unknown, row: FeeRecord) =>
      `${money(row.evidence?.billing_base, row.result.currency)} / ${row.evidence?.applicable_rate_pct ?? '—'}%` },
    { title: '费率有效期', width: 180, render: (_: unknown, row: FeeRecord) =>
      `${row.evidence?.rate_effective_from ?? '—'} 至 ${row.evidence?.rate_effective_until ?? '无失效日'}` },
    { title: '复算状态', dataIndex: ['result', 'status'], width: 150, render: (value: string) => {
      const status = feeStatus[value] ?? { label: value, color: 'default' }
      return <Tag color={status.color}>{status.label}</Tag>
    } },
    { title: '应收费用', dataIndex: ['result', 'expected_charge'], width: 120, render: (value: string | null, row: FeeRecord) => money(value, row.result.currency) },
    { title: '实扣金额', dataIndex: ['result', 'actual_charge'], width: 120, render: (value: string | null, row: FeeRecord) => money(value, row.result.currency) },
    { title: '已入账调整', dataIndex: ['result', 'posted_adjustments'], width: 120, render: (value: string | null, row: FeeRecord) => money(value, row.result.currency) },
    { title: '净实扣', dataIndex: ['result', 'net_actual_charge'], width: 120, render: (value: string | null, row: FeeRecord) => money(value, row.result.currency) },
    { title: '净差异', dataIndex: ['result', 'discrepancy'], width: 120, render: (value: string | null, row: FeeRecord) => money(value, row.result.currency) },
    { title: '缺失证据', dataIndex: ['result', 'missing_evidence'], width: 220, render: (values: string[]) => values?.length
      ? values.map((value) => missingEvidenceLabels[value] ?? value).join('、') : '—' },
    { title: '审核状态', dataIndex: 'review_status', width: 100, render: (value: FeeRecord['review_status']) => {
      const labels = { pending: ['待人工审核', 'orange'], approved: ['已审核', 'green'], rejected: ['已驳回', 'red'] } as const
      const [label, color] = labels[value]
      return <Tag color={color}>{label}</Tag>
    } },
  ]

  return <Space direction="vertical" size="middle" style={{ display: 'flex', marginTop: 20 }}>
    <Card title="本地平台费用复算">
      <Alert style={{ marginBottom: 16 }} type="info" showIcon
        message="逐笔按凭据来源和币种复算；不同币种不合并。多扣结果仍须人工审核。"
        description="只使用本次录入的账单行、适用费率和调整项。缺少证据时记录为“待补证”，不会自动确认多扣或有效。" />
      {canWrite ? <Form form={form} layout="vertical" onFinish={(values) => void submit(values)} initialValues={{ fixed_fee: '0.00', adjustments: [] }}>
        <Row gutter={16}>
          <Col xs={24} md={8}><Form.Item name="shop_id" label="ERP 店铺" rules={[{ required: true, message: '请选择或填写店铺' }]}>
            {shops.length ? <Select showSearch optionFilterProp="label" placeholder="选择授权店铺"
              options={shops.map((shop) => ({ value: shop.id, label: `${shop.name}（${shop.code}）` }))} />
              : <Input placeholder="填写授权店铺 ID" />}
          </Form.Item></Col>
          <Col xs={24} md={10}><Form.Item name="source_reference" label="凭据来源" rules={[{ required: true, min: 3, message: '填写账单号、文件名或其他可追溯来源' }]}>
            <Input maxLength={500} placeholder="平台账单号、文件名或账单来源标识" />
          </Form.Item></Col>
          <Col xs={24} md={6}><Form.Item name="currency" label="币种" rules={[{ required: true, len: 3, message: '填写 3 位币种代码' }]}>
            <Input maxLength={3} placeholder="USD" />
          </Form.Item></Col>
        </Row>
        <Row gutter={16}>
          <Col xs={24} md={8}><Form.Item name="statement_line_id" label="账单行号"><Input placeholder="例如 line-1001" /></Form.Item></Col>
          <Col xs={24} md={8}><Form.Item name="fee_code" label="费用代码"><Input placeholder="例如 REFERRAL_FEE" /></Form.Item></Col>
          <Col xs={24} md={8}><Form.Item name="transaction_type" label="交易类型"><Input placeholder="例如 SALE" /></Form.Item></Col>
          <Col xs={24} md={8}><Form.Item name="transaction_date" label="交易日期"><Input type="date" /></Form.Item></Col>
          <Col xs={24} md={8}><Form.Item name="settlement_period_start" label="结算期开始"><Input type="date" /></Form.Item></Col>
          <Col xs={24} md={8}><Form.Item name="settlement_period_end" label="结算期结束"><Input type="date" /></Form.Item></Col>
          <Col xs={24} md={8}><Form.Item name="rate_source_reference" label="费率凭据来源"><Input placeholder="费率表、合同或平台规则版本" /></Form.Item></Col>
          <Col xs={24} md={8}><Form.Item name="rate_effective_from" label="费率生效日"><Input type="date" /></Form.Item></Col>
          <Col xs={24} md={8}><Form.Item name="rate_effective_until" label="费率失效日（可选）"><Input type="date" /></Form.Item></Col>
          <Col xs={24} md={6}><Form.Item name="billing_base" label="计费基数"><Input inputMode="decimal" placeholder="不含币种符号" /></Form.Item></Col>
          <Col xs={24} md={6}><Form.Item name="applicable_rate_pct" label="适用费率（%）"><Input inputMode="decimal" placeholder="例如 15.000000" /></Form.Item></Col>
          <Col xs={24} md={6}><Form.Item name="fixed_fee" label="固定费用"><Input inputMode="decimal" /></Form.Item></Col>
          <Col xs={24} md={6}><Form.Item name="actual_charge" label="账单实扣"><Input inputMode="decimal" placeholder="不含币种符号" /></Form.Item></Col>
        </Row>
        <Form.Item name="adjustments_reviewed" label="调整项是否已核对">
          <Select allowClear placeholder="未核对时留空，将标记待补证"
            options={[{ value: true, label: '已核对调整项' }, { value: false, label: '尚未核对' }]} />
        </Form.Item>
        <Form.List name="adjustments">
          {(fields, { add, remove }) => <Space direction="vertical" style={{ width: '100%' }}>
            <Typography.Text strong>结算调整 / 冲回</Typography.Text>
            {fields.map((field) => <Row key={field.key} gutter={8} align="middle">
              <Col xs={24} md={7}><Form.Item name={[field.name, 'adjustment_id']} rules={[{ required: true, message: '填写调整编号' }]}><Input placeholder="调整编号" /></Form.Item></Col>
              <Col xs={12} md={5}><Form.Item name={[field.name, 'adjustment_type']} rules={[{ required: true }]}><Select placeholder="类型" options={[{ value: 'credit', label: '贷项' }, { value: 'reversal', label: '冲回' }]} /></Form.Item></Col>
              <Col xs={12} md={5}><Form.Item name={[field.name, 'status']} rules={[{ required: true }]}><Select placeholder="状态" options={[{ value: 'posted', label: '已入账' }, { value: 'pending', label: '待入账' }]} /></Form.Item></Col>
              <Col xs={18} md={5}><Form.Item name={[field.name, 'amount']} rules={[{ required: true }]}><Input inputMode="decimal" placeholder="金额" /></Form.Item></Col>
              <Col xs={6} md={2}><Button danger onClick={() => remove(field.name)}>移除</Button></Col>
            </Row>)}
            <Button onClick={() => add({ adjustment_type: 'credit', status: 'pending' })}>添加调整项</Button>
          </Space>}
        </Form.List>
        <Button type="primary" htmlType="submit" loading={submitting} style={{ marginTop: 16 }}>保存并复算</Button>
      </Form> : <Alert type="warning" showIcon message="当前账号为只读模式" description="查看复算历史需要 finance_agent:read；提交费用复算需要 finance_agent:write。" />}
      {latestResult && <Card size="small" title="本次复算结果" style={{ marginTop: 16 }}>
        <Space wrap>
          <Tag color={feeStatus[latestResult.result.status]?.color ?? 'default'}>{feeStatus[latestResult.result.status]?.label ?? latestResult.result.status}</Tag>
          <Tag>{latestResult.result.currency}</Tag>
          <Typography.Text>来源：{latestResult.source_reference}</Typography.Text>
          <Typography.Text>费率来源：{latestResult.evidence?.rate_source_reference || '待补'}</Typography.Text>
          <Typography.Text>计费基数：{money(latestResult.evidence?.billing_base, latestResult.result.currency)}</Typography.Text>
          <Typography.Text>适用费率：{latestResult.evidence?.applicable_rate_pct ?? '—'}%</Typography.Text>
          <Typography.Text>应收：{money(latestResult.result.expected_charge, latestResult.result.currency)}</Typography.Text>
          <Typography.Text>实扣：{money(latestResult.result.actual_charge, latestResult.result.currency)}</Typography.Text>
          <Typography.Text>净实扣：{money(latestResult.result.net_actual_charge, latestResult.result.currency)}</Typography.Text>
          <Typography.Text>差异：{money(latestResult.result.discrepancy, latestResult.result.currency)}</Typography.Text>
          <Tag color="orange">待人工审核</Tag>
        </Space>
        <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}>{latestResult.result.reason}</Typography.Paragraph>
      </Card>}
    </Card>

    {canRead && <Card title="费用复算历史" extra={<Space wrap>
      {shops.length > 0 && <Select allowClear placeholder="全部可访问店铺" style={{ width: 200 }} value={shopFilter}
        onChange={(value) => { setShopFilter(value); setPage(1) }} options={shops.map((shop) => ({ value: shop.id, label: shop.name }))} />}
      <Input.Search allowClear maxLength={3} placeholder="按币种筛选" style={{ width: 130 }} value={currencyDraft}
        onChange={(event) => {
          setCurrencyDraft(event.target.value)
          if (!event.target.value) { setCurrencyFilter(undefined); setPage(1) }
        }}
        onSearch={(value) => { const next = value.trim().toUpperCase(); setCurrencyDraft(next); setCurrencyFilter(next || undefined); setPage(1) }} />
      <Input.Search placeholder="筛选凭据来源" allowClear style={{ width: 220 }} value={sourceDraft}
        onChange={(event) => setSourceDraft(event.target.value)} onSearch={(value) => { setSourceFilter(value.trim()); setPage(1) }} />
      <Button onClick={() => void loadHistory(page)} loading={loading}>刷新</Button>
    </Space>}>
      {historyError && <Alert type="error" showIcon message="费用复算历史加载失败" description={historyError} style={{ marginBottom: 12 }} />}
      <Table<FeeRecord> rowKey="id" size="small" dataSource={records} loading={loading} scroll={{ x: 2150 }}
        pagination={{ current: page, pageSize: 20, total, showSizeChanger: false, onChange: (nextPage) => void loadHistory(nextPage), showTotal: (count) => `共 ${count} 条` }}
        locale={{ emptyText: '暂无费用复算记录' }} columns={columns} />
    </Card>}
  </Space>
}
