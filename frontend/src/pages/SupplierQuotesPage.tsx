import { useCallback, useEffect, useMemo, useState } from 'react'
import dayjs, { type Dayjs } from 'dayjs'
import {
  Alert, Button, Card, DatePicker, Descriptions, Drawer, Form, Input, InputNumber,
  Modal, Select, Space, Table, Tag, Typography, message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

type QuoteStatus = 'pending' | 'accepted' | 'rejected'
interface Quote {
  id: string; quote_no: string; supplier_id: string; supplier_code: string; supplier_name: string
  sku_id: string; sku_code: string; sku_name: string; unit_price: number | string
  lead_time_days: number; quoted_at: string; valid_until: string | null; remark: string
  status: QuoteStatus; decision_note: string; decided_at: string | null
}
interface ListResult { items: Quote[]; total: number; page: number; page_size: number }
interface Lookup { id: string; code: string; name: string; is_active?: boolean }
interface FormValues {
  supplier_id: string; sku_id: string; unit_price: number; lead_time_days: number
  quoted_at: Dayjs; valid_until?: Dayjs; remark?: string
}

const STATUS: Record<QuoteStatus, { label: string; color: string }> = {
  pending: { label: '待处理', color: 'orange' },
  accepted: { label: '已接受', color: 'green' },
  rejected: { label: '已驳回', color: 'red' },
}
const formatDate = (value?: string | null) => value ? new Date(value).toLocaleDateString('zh-CN') : '—'
const formatDateTime = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'

/** 报价记录独立保存历史；供应商 SKU 供货信息只表示当前生效价格。 */
export default function SupplierQuotesPage() {
  const { user } = useAuth()
  const canRead = user?.role === 'admin' || Boolean(user?.permissions.includes('supplier_quotes:read'))
  const canWrite = user?.role === 'admin' || Boolean(user?.permissions.includes('supplier_quotes:write'))
  const canCreateQuote = canWrite && (user?.role === 'admin' || Boolean(user?.permissions.includes('suppliers:read') && user?.permissions.includes('skus:read')))
  const [rows, setRows] = useState<Quote[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [status, setStatus] = useState<QuoteStatus | undefined>()
  const [loading, setLoading] = useState(false)
  const [suppliers, setSuppliers] = useState<Lookup[]>([])
  const [skus, setSkus] = useState<Lookup[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [detail, setDetail] = useState<Quote | null>(null)
  const [decision, setDecision] = useState<{ quote: Quote; outcome: 'accept' | 'reject' } | null>(null)
  const [processing, setProcessing] = useState(false)
  const [form] = Form.useForm<FormValues>()
  const [decisionForm] = Form.useForm<{ decision_note: string }>()

  const supplierOptions = useMemo(() => suppliers.filter(x => x.is_active !== false).map(x => ({ value: x.id, label: `${x.code} ${x.name}` })), [suppliers])
  const skuOptions = useMemo(() => skus.filter(x => x.is_active !== false).map(x => ({ value: x.id, label: `${x.code} ${x.name}` })), [skus])

  const loadLookups = useCallback(async () => {
    try {
      const [supplierResult, skuResult] = await Promise.all([
        request<{ items: Lookup[] }>('/suppliers', { params: { page: 1, page_size: 100 } }),
        request<{ items: Lookup[] }>('/skus', { params: { page: 1, page_size: 100 } }),
      ])
      setSuppliers(supplierResult.items)
      setSkus(skuResult.items)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '供应商或 SKU 资料加载失败')
    }
  }, [])

  const load = useCallback(async () => {
    if (!canRead) return
    setLoading(true)
    try {
      const result = await request<ListResult>('/supplier-quotes', { params: { page, page_size: pageSize, status } })
      setRows(result.items)
      setTotal(result.total)
    } catch (err) {
      setRows([])
      setTotal(0)
      message.error(err instanceof Error ? err.message : '报价记录加载失败')
    } finally {
      setLoading(false)
    }
  }, [canRead, page, pageSize, status])

  useEffect(() => { void load() }, [load])
  useEffect(() => { if (canCreateQuote) void loadLookups() }, [canCreateQuote, loadLookups])

  const createQuote = async () => {
    let values: FormValues
    try { values = await form.validateFields() } catch { return }
    setCreating(true)
    try {
      await request<Quote>('/supplier-quotes', {
        method: 'POST',
        body: {
          supplier_id: values.supplier_id,
          sku_id: values.sku_id,
          unit_price: values.unit_price,
          lead_time_days: values.lead_time_days,
          quoted_at: values.quoted_at.format('YYYY-MM-DD') + 'T00:00:00',
          valid_until: values.valid_until?.format('YYYY-MM-DD') ?? null,
          remark: values.remark ?? '',
        },
      })
      message.success('报价已登记，历史记录已保存')
      setCreateOpen(false)
      form.resetFields()
      setPage(1)
      if (page === 1) await load()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '创建报价失败')
    } finally { setCreating(false) }
  }

  const openDecision = (quote: Quote, outcome: 'accept' | 'reject') => {
    decisionForm.resetFields()
    setDecision({ quote, outcome })
  }

  const submitDecision = async () => {
    if (!decision) return
    let values: { decision_note: string }
    try { values = await decisionForm.validateFields() } catch { return }
    setProcessing(true)
    try {
      const endpoint = decision.outcome === 'accept' ? 'accept' : 'reject'
      const updated = await request<Quote>(`/supplier-quotes/${decision.quote.id}/${endpoint}`, {
        method: 'POST', body: { decision_note: values.decision_note ?? '' },
      })
      message.success(decision.outcome === 'accept' ? '报价已接受，当前供货价已更新' : '报价已驳回')
      setDecision(null)
      setDetail(updated)
      await load()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '处理报价失败')
    } finally { setProcessing(false) }
  }

  const showDetail = async (row: Quote) => {
    try { setDetail(await request<Quote>(`/supplier-quotes/${row.id}`)) }
    catch (err) { message.error(err instanceof Error ? err.message : '读取报价详情失败') }
  }

  const columns: ColumnsType<Quote> = [
    { title: '报价单号', dataIndex: 'quote_no', width: 180, fixed: 'left' },
    { title: '供应商', dataIndex: 'supplier_name', width: 160, render: (_, row) => `${row.supplier_code} ${row.supplier_name}` },
    { title: 'SKU', dataIndex: 'sku_code', width: 200, render: (_, row) => `${row.sku_code} ${row.sku_name}` },
    { title: '报价单价', dataIndex: 'unit_price', width: 120, render: v => Number(v).toFixed(2) },
    { title: '交期（天）', dataIndex: 'lead_time_days', width: 100 },
    { title: '报价日期', dataIndex: 'quoted_at', width: 120, render: formatDate },
    { title: '有效期至', dataIndex: 'valid_until', width: 120, render: formatDate },
    { title: '状态', dataIndex: 'status', width: 100, render: v => <Tag color={STATUS[v as QuoteStatus]?.color}>{STATUS[v as QuoteStatus]?.label ?? v}</Tag> },
    { title: '处理意见', dataIndex: 'decision_note', width: 180, ellipsis: true, render: v => v || '—' },
    {
      title: '操作', key: 'actions', width: 180, fixed: 'right',
      render: (_, row) => <Space size={2}>
        <Button type="link" size="small" onClick={() => void showDetail(row)}>详情</Button>
        {canWrite && row.status === 'pending' && <>
          <Button type="link" size="small" onClick={() => openDecision(row, 'accept')}>接受</Button>
          <Button type="link" size="small" danger onClick={() => openDecision(row, 'reject')}>驳回</Button>
        </>}
      </Space>,
    },
  ]

  if (!canRead) return <Alert type="error" showIcon message="没有供应商报价读取权限" />

  return <Card
    title={<Space direction="vertical" size={0}>
      <span style={{ fontSize: 16, fontWeight: 600 }}>供应商报价</span>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>每次报价单独留存。接受报价后，才会更新该供应商与 SKU 的当前供货价和交期。</Typography.Text>
    </Space>}
    extra={<Space wrap>
      <Select allowClear placeholder="全部状态" style={{ width: 130 }} value={status} onChange={value => { setStatus(value); setPage(1) }} options={Object.entries(STATUS).map(([value, item]) => ({ value, label: item.label }))} />
      <Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button>
      {canWrite && <Button type="primary" icon={<PlusOutlined />} disabled={!canCreateQuote} onClick={() => { form.resetFields(); form.setFieldsValue({ quoted_at: dayjs(), lead_time_days: 7 }); setCreateOpen(true) }}>登记报价</Button>}
    </Space>}
  >
    {canWrite && !canCreateQuote && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="登记报价还需要供应商与 SKU 的读取权限。" />}
    <Table<Quote> rowKey="id" size="small" loading={loading} columns={columns} dataSource={rows} scroll={{ x: 1450 }} pagination={{
      current: page, pageSize, total, showSizeChanger: true, showTotal: n => `共 ${n} 条`,
      onChange: (p, ps) => { setPage(p); setPageSize(ps) },
    }} />

    <Modal title="登记供应商报价" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => void createQuote()} confirmLoading={creating} destroyOnClose>
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item name="supplier_id" label="供应商" rules={[{ required: true, message: '请选择供应商' }]}><Select showSearch optionFilterProp="label" options={supplierOptions} placeholder="选择启用中的供应商" /></Form.Item>
        <Form.Item name="sku_id" label="SKU" rules={[{ required: true, message: '请选择 SKU' }]}><Select showSearch optionFilterProp="label" options={skuOptions} placeholder="选择启用中的 SKU" /></Form.Item>
        <Space style={{ display: 'flex' }} align="start">
          <Form.Item name="unit_price" label="报价单价" rules={[{ required: true, message: '请填写报价单价' }]}><InputNumber min={0.01} precision={2} style={{ width: 170 }} /></Form.Item>
          <Form.Item name="lead_time_days" label="交期（天）" rules={[{ required: true, message: '请填写交期' }]}><InputNumber min={0} max={3650} precision={0} style={{ width: 140 }} /></Form.Item>
        </Space>
        <Space style={{ display: 'flex' }} align="start">
          <Form.Item name="quoted_at" label="报价日期" rules={[{ required: true, message: '请选择报价日期' }]}><DatePicker /></Form.Item>
          <Form.Item name="valid_until" label="有效期至"><DatePicker /></Form.Item>
        </Space>
        <Form.Item name="remark" label="备注"><Input.TextArea rows={3} maxLength={1000} showCount /></Form.Item>
      </Form>
    </Modal>

    <Modal title={`${decision?.outcome === 'accept' ? '接受' : '驳回'}报价 · ${decision?.quote.quote_no ?? ''}`} open={Boolean(decision)} onCancel={() => setDecision(null)} onOk={() => void submitDecision()} confirmLoading={processing} destroyOnClose>
      <Typography.Paragraph>供应商：{decision?.quote.supplier_name}　SKU：{decision?.quote.sku_code}</Typography.Paragraph>
      {decision?.outcome === 'accept' && <Alert type="info" showIcon style={{ marginBottom: 16 }} message="接受后将原子更新当前供货价和交期，并保留此报价记录。" />}
      <Form form={decisionForm} layout="vertical"><Form.Item name="decision_note" label="处理意见"><Input.TextArea rows={3} maxLength={1000} showCount /></Form.Item></Form>
    </Modal>

    <Drawer open={Boolean(detail)} title={`报价详情${detail ? ` · ${detail.quote_no}` : ''}`} width={620} onClose={() => setDetail(null)}>
      {detail && <>
        <Descriptions bordered size="small" column={1}>
          <Descriptions.Item label="状态"><Tag color={STATUS[detail.status]?.color}>{STATUS[detail.status]?.label ?? detail.status}</Tag></Descriptions.Item>
          <Descriptions.Item label="供应商">{detail.supplier_code} {detail.supplier_name}</Descriptions.Item>
          <Descriptions.Item label="SKU">{detail.sku_code} {detail.sku_name}</Descriptions.Item>
          <Descriptions.Item label="报价单价">{Number(detail.unit_price).toFixed(2)}</Descriptions.Item>
          <Descriptions.Item label="交期">{detail.lead_time_days} 天</Descriptions.Item>
          <Descriptions.Item label="报价日期">{formatDateTime(detail.quoted_at)}</Descriptions.Item>
          <Descriptions.Item label="有效期至">{formatDate(detail.valid_until)}</Descriptions.Item>
          <Descriptions.Item label="报价备注">{detail.remark || '—'}</Descriptions.Item>
          <Descriptions.Item label="处理意见">{detail.decision_note || '—'}</Descriptions.Item>
          <Descriptions.Item label="处理时间">{formatDateTime(detail.decided_at)}</Descriptions.Item>
        </Descriptions>
        {canWrite && detail.status === 'pending' && <Space style={{ marginTop: 16 }}>
          <Button type="primary" onClick={() => openDecision(detail, 'accept')}>接受报价</Button>
          <Button danger onClick={() => openDecision(detail, 'reject')}>驳回报价</Button>
        </Space>}
      </>}
    </Drawer>
  </Card>
}
