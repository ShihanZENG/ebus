import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Descriptions, Drawer, Form, Input, Modal, Popconfirm, Select, Space, Table, Tabs, Tag, message } from 'antd'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

interface PurchaseItem {
  id: string
  sku_code_snapshot: string
  sku_name_snapshot: string
  quantity_ordered: number
  quantity_received: number
  unit_price: string | number
}
interface PurchaseOrder {
  id: string
  po_no: string
  supplier_id: string
  warehouse_id: string
  status: string
  total_amount: string | number
  expected_arrival_date: string | null
  created_at: string
  remark: string
  items?: PurchaseItem[]
  receipts?: string[]
}
interface ListResult<T> { items: T[]; total: number }
interface NamedRef { id: string; name: string }
type Tab = 'pending' | 'processed' | 'draft'
type Action = 'submit' | 'approve' | 'reject' | 'cancel'

const statuses: Record<string, { text: string; color: string }> = {
  draft: { text: '草稿', color: 'default' },
  submitted: { text: '待审批', color: 'orange' },
  approved: { text: '已通过', color: 'blue' },
  rejected: { text: '已驳回', color: 'red' },
  closed: { text: '已完成', color: 'green' },
  cancelled: { text: '已取消', color: 'default' },
}
const actionNames: Record<Action, string> = { submit: '提交审批', approve: '审批通过', reject: '驳回', cancel: '取消采购单' }
const errorText = (error: unknown) => error instanceof Error ? error.message : '请求失败，请重试'
const dateText = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '—'

export default function PurchaseApprovalsPage() {
  const { user } = useAuth()
  const can = (permission: string) => user?.role === 'admin' || !!user?.permissions.includes(permission)
  const canRead = can('purchase_orders:read')
  const canWrite = can('purchase_orders:write')
  const canReadSuppliers = can('suppliers:read')
  const canReadWarehouses = can('warehouses:read')
  const [tab, setTab] = useState<Tab>('pending')
  const [processedStatus, setProcessedStatus] = useState('approved')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [revision, setRevision] = useState(0)
  const [rows, setRows] = useState<PurchaseOrder[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [names, setNames] = useState<Record<string, string>>({})
  const [detail, setDetail] = useState<PurchaseOrder | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const detailRequest = useRef(0)
  const [busy, setBusy] = useState(false)
  const operationLock = useRef(false)
  const [cancelTarget, setCancelTarget] = useState<PurchaseOrder | null>(null)
  const [cancelForm] = Form.useForm<{ reason: string }>()
  const status = tab === 'pending' ? 'submitted' : tab === 'draft' ? 'draft' : processedStatus

  useEffect(() => {
    let active = true
    if (!canRead) { setRows([]); setTotal(0); return }
    setLoading(true)
    setLoadError('')
    request<ListResult<PurchaseOrder>>('/purchase-orders', { params: { status, page, page_size: pageSize } })
      .then((result) => {
        if (!active) return
        if (page > 1 && !result.items.length && result.total > 0) { setPage(Math.max(1, Math.ceil(result.total / pageSize))); return }
        setRows(result.items); setTotal(result.total)
      })
      .catch((error: unknown) => { if (active) { setRows([]); setTotal(0); setLoadError(errorText(error)) } })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [canRead, status, page, pageSize, revision])

  useEffect(() => {
    let active = true
    const loadNames = async () => {
      const results = await Promise.allSettled([
        canReadSuppliers ? request<ListResult<NamedRef>>('/suppliers', { params: { page_size: 100 } }) : Promise.resolve({ items: [], total: 0 }),
        canReadWarehouses ? request<ListResult<NamedRef>>('/warehouses', { params: { page_size: 100 } }) : Promise.resolve({ items: [], total: 0 }),
      ])
      if (active) setNames(Object.fromEntries(results.flatMap((result) => result.status === 'fulfilled' ? result.value.items.map((item) => [item.id, item.name]) : [])))
    }
    void loadNames()
    return () => { active = false }
  }, [canReadSuppliers, canReadWarehouses])

  const showDetail = async (id: string) => {
    const requestId = ++detailRequest.current
    setDetailLoading(true)
    try {
      const result = await request<PurchaseOrder>(`/purchase-orders/${id}`)
      if (requestId === detailRequest.current) setDetail(result)
    } catch (error) { message.error(errorText(error)) }
    finally { if (requestId === detailRequest.current) setDetailLoading(false) }
  }

  const runAction = async (order: PurchaseOrder, action: Action, reason?: string) => {
    if (!canWrite || operationLock.current) return
    operationLock.current = true
    setBusy(true)
    try {
      await request(`/purchase-orders/${order.id}/${action}`, { method: 'POST', ...(action === 'cancel' ? { body: { reason } } : {}) })
      message.success(`${order.po_no}：${actionNames[action]}成功`)
      if (action === 'cancel') { setCancelTarget(null); cancelForm.resetFields() }
      setRevision((value) => value + 1)
      if (detail?.id === order.id) await showDetail(order.id)
    } catch (error) {
      message.error(errorText(error))
      setRevision((value) => value + 1)
    } finally { operationLock.current = false; setBusy(false) }
  }

  const actions = (order: PurchaseOrder) => <Space wrap>
    {order.status === 'draft' && <Popconfirm title="提交该采购单审批？" onConfirm={() => runAction(order, 'submit')}><Button size="small" disabled={!canWrite || busy}>提交审批</Button></Popconfirm>}
    {order.status === 'submitted' && <>
      <Popconfirm title="确认审批通过？" onConfirm={() => runAction(order, 'approve')}><Button size="small" type="primary" disabled={!canWrite || busy}>通过</Button></Popconfirm>
      <Popconfirm title="确认驳回采购单？" description="当前系统仅记录驳回状态，不保存驳回原因。" onConfirm={() => runAction(order, 'reject')}><Button size="small" danger disabled={!canWrite || busy}>驳回</Button></Popconfirm>
    </>}
    {!['cancelled', 'closed'].includes(order.status) && <Button size="small" danger disabled={!canWrite || busy} onClick={() => { cancelForm.resetFields(); setCancelTarget(order) }}>取消</Button>}
  </Space>

  if (!canRead) return <Alert type="warning" showIcon message="查看采购审批工作台需要采购单读取权限（purchase_orders:read）。" />

  return <Card title="采购审批工作台" extra={<Button loading={loading} onClick={() => setRevision((value) => value + 1)}>刷新</Button>}>
    {!canWrite && <Alert style={{ marginBottom: 12 }} type="info" showIcon message="当前为只读模式；处理采购单需要 purchase_orders:write 权限。" />}
    {loadError && <Alert style={{ marginBottom: 12 }} type="error" showIcon message={loadError} />}
    <Tabs activeKey={tab} onChange={(value) => { setTab(value as Tab); setPage(1) }} items={[
      { key: 'pending', label: '待审批' }, { key: 'processed', label: '已处理' }, { key: 'draft', label: '草稿待提交' },
    ]} />
    {tab === 'processed' && <Space style={{ marginBottom: 16 }}>处理结果<Select value={processedStatus} style={{ width: 160 }} onChange={(value) => { setProcessedStatus(value); setPage(1) }} options={['approved', 'rejected', 'closed', 'cancelled'].map((value) => ({ value, label: statuses[value].text }))} /></Space>}
    <Table<PurchaseOrder> rowKey="id" loading={loading} dataSource={rows} scroll={{ x: 1050 }} pagination={{ current: page, pageSize, total, showSizeChanger: true, showTotal: (count) => `共 ${count} 单`, onChange: (next, size) => { setPage(size !== pageSize ? 1 : next); setPageSize(size) } }} columns={[
      { title: '采购单号', dataIndex: 'po_no', render: (value: string, order) => <Button type="link" onClick={() => void showDetail(order.id)}>{value}</Button> },
      { title: '供应商', dataIndex: 'supplier_id', render: (value: string) => names[value] ?? value },
      { title: '收货仓库', dataIndex: 'warehouse_id', render: (value: string) => names[value] ?? value },
      { title: '采购金额', dataIndex: 'total_amount' },
      { title: '状态', dataIndex: 'status', render: (value: string) => <Tag color={statuses[value]?.color}>{statuses[value]?.text ?? value}</Tag> },
      { title: '创建时间', dataIndex: 'created_at', render: dateText },
      { title: '操作', render: (_, order) => actions(order) },
    ]} />
    <Drawer open={!!detail || detailLoading} title={`采购详情${detail ? ` · ${detail.po_no}` : ''}`} width={820} onClose={() => { detailRequest.current++; setDetail(null); setDetailLoading(false) }}>
      {detailLoading ? <p>正在读取采购详情…</p> : detail && <>
        <Descriptions bordered column={2} size="small" items={[
          { key: 'supplier', label: '供应商', children: names[detail.supplier_id] ?? detail.supplier_id },
          { key: 'warehouse', label: '收货仓库', children: names[detail.warehouse_id] ?? detail.warehouse_id },
          { key: 'status', label: '状态', children: statuses[detail.status]?.text ?? detail.status },
          { key: 'total', label: '采购金额', children: detail.total_amount },
          { key: 'arrival', label: '预计到货', children: dateText(detail.expected_arrival_date) },
          { key: 'remark', label: '备注 / 取消原因', children: detail.remark || '—' },
        ]} />
        {detail.status === 'rejected' && <Alert style={{ marginTop: 12 }} type="info" showIcon message="此单已驳回。当前采购审批接口不保存驳回原因，无法展示具体原因。" />}
        <h3>采购明细</h3>
        <Table<PurchaseItem> rowKey="id" size="small" pagination={false} dataSource={detail.items ?? []} columns={[
          { title: 'SKU', dataIndex: 'sku_code_snapshot' }, { title: '品名', dataIndex: 'sku_name_snapshot' },
          { title: '订购量', dataIndex: 'quantity_ordered' }, { title: '单价', dataIndex: 'unit_price' }, { title: '已收合格量', dataIndex: 'quantity_received' },
        ]} />
        <p>关联收货单：{detail.receipts?.join('、') || '暂无'}</p>
        {actions(detail)}
      </>}
    </Drawer>
    <Modal open={!!cancelTarget} title={`取消采购单 · ${cancelTarget?.po_no ?? ''}`} confirmLoading={busy} okButtonProps={{ disabled: !canWrite, danger: true }} onCancel={() => { if (!busy) setCancelTarget(null) }} onOk={async () => {
      try { const values = await cancelForm.validateFields(); if (cancelTarget) await runAction(cancelTarget, 'cancel', values.reason.trim()) } catch { /* 表单字段显示验证错误。 */ }
    }}>
      <Form form={cancelForm} layout="vertical"><Form.Item name="reason" label="取消原因" rules={[{ required: true, whitespace: true, message: '请填写取消原因' }, { max: 500 }]}><Input.TextArea rows={3} maxLength={500} /></Form.Item></Form>
    </Modal>
  </Card>
}
