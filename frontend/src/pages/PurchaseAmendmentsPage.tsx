import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Descriptions, Drawer, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

interface PoItem {
  id: string
  sku_id: string
  sku_code_snapshot: string
  sku_name_snapshot: string
  quantity_ordered: number
  quantity_received: number
  unit_price: string | number
}
interface PurchaseOrder {
  id: string
  po_no: string
  status: string
  supplier_id: string
  warehouse_id: string
  total_amount: string | number
  expected_arrival_date: string | null
  remark: string
  items: PoItem[]
}
interface ProposalItem { po_item_id: string; sku_id: string; quantity_ordered: number; unit_price: string }
interface Snapshot {
  purchase_order_id: string
  po_no: string
  supplier_id: string
  warehouse_id: string
  status: string
  total_amount: string
  expected_arrival_date: string | null
  remark: string
  items: (ProposalItem & { sku_code_snapshot: string; sku_name_snapshot: string; quantity_received: number })[]
}
interface Amendment {
  id: string
  amendment_no: string
  purchase_order_id: string
  po_no: string
  reason: string
  original_snapshot: Snapshot
  proposed_snapshot: { expected_arrival_date: string | null; remark: string; items: ProposalItem[] }
  status: 'submitted' | 'approved' | 'rejected'
  decision_note: string
  decided_at: string | null
  created_at: string
}
interface ListResult<T> { items: T[]; total: number; page: number; page_size: number }
interface DraftLine { po_item_id: string; sku_id: string; sku_code_snapshot: string; sku_name_snapshot: string; quantity_ordered: number; unit_price: number }
interface CreateValues { purchase_order_id: string; reason: string; expected_arrival_date: string; remark: string }
interface DecisionValues { decision_note: string }

const errorText = (error: unknown) => error instanceof Error ? error.message : '请求失败，请重试'
const dateText = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '—'
const money = (value: number | string) => Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const statuses = { submitted: { text: '待审批', color: 'orange' }, approved: { text: '已通过', color: 'green' }, rejected: { text: '已驳回', color: 'red' } }

export default function PurchaseAmendmentsPage() {
  const { user } = useAuth()
  const can = (permission: string) => user?.role === 'admin' || !!user?.permissions.includes(permission)
  const canRead = can('purchase_amendments:read')
  const canWrite = can('purchase_amendments:write')
  const canReadOrders = can('purchase_orders:read')
  const [rows, setRows] = useState<Amendment[]>([])
  const [orders, setOrders] = useState<PurchaseOrder[]>([])
  const [loading, setLoading] = useState(false)
  const [revision, setRevision] = useState(0)
  const [statusFilter, setStatusFilter] = useState<string>()
  const [selected, setSelected] = useState<Amendment | null>(null)
  const [orderDetail, setOrderDetail] = useState<PurchaseOrder | null>(null)
  const [draftLines, setDraftLines] = useState<DraftLine[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [createBusy, setCreateBusy] = useState(false)
  const [decisionBusy, setDecisionBusy] = useState(false)
  const [decisionTarget, setDecisionTarget] = useState<{ row: Amendment; action: 'approve' | 'reject' } | null>(null)
  const [form] = Form.useForm<CreateValues>()
  const [decisionForm] = Form.useForm<DecisionValues>()

  const refresh = useCallback(async () => {
    if (!canRead) { setRows([]); return }
    setLoading(true)
    try {
      const result = await request<ListResult<Amendment>>('/purchase-amendments', { params: { status: statusFilter, page: 1, page_size: 100 } })
      setRows(result.items)
    } catch (error) { message.error(errorText(error)) }
    finally { setLoading(false) }
  }, [canRead, statusFilter])

  useEffect(() => { void refresh() }, [refresh, revision])
  useEffect(() => {
    if (!createOpen || !canReadOrders) return
    request<ListResult<PurchaseOrder>>('/purchase-orders', { params: { status: 'approved', page: 1, page_size: 100 } })
      .then((result) => setOrders(result.items))
      .catch((error: unknown) => message.error(errorText(error)))
  }, [createOpen, canReadOrders])

  const orderOptions = useMemo(() => orders
    .filter((po) => po.status === 'approved' && (po.items ?? []).every((item) => item.quantity_received === 0))
    .map((po) => ({ label: `${po.po_no} · ${money(po.total_amount)}`, value: po.id })), [orders])

  const loadSelectedOrder = async (id?: string) => {
    setOrderDetail(null)
    setDraftLines([])
    if (!id) return
    try {
      const po = await request<PurchaseOrder>(`/purchase-orders/${id}`)
      if (po.status !== 'approved' || po.items.some((item) => item.quantity_received > 0)) {
        message.warning('该采购单已有收货或状态已变化，请刷新后重新选择')
        form.setFieldValue('purchase_order_id', undefined)
        return
      }
      setOrderDetail(po)
      setDraftLines(po.items.map((item) => ({
        po_item_id: item.id, sku_id: item.sku_id, sku_code_snapshot: item.sku_code_snapshot,
        sku_name_snapshot: item.sku_name_snapshot, quantity_ordered: item.quantity_ordered,
        unit_price: Number(item.unit_price),
      })))
    } catch (error) { message.error(errorText(error)) }
  }

  const openCreate = () => {
    form.resetFields()
    setOrderDetail(null)
    setDraftLines([])
    setCreateOpen(true)
  }

  const create = async (values: CreateValues) => {
    if (!orderDetail || draftLines.length !== orderDetail.items.length) return
    setCreateBusy(true)
    try {
      await request('/purchase-amendments', { method: 'POST', body: {
        purchase_order_id: values.purchase_order_id,
        reason: values.reason.trim(),
        expected_arrival_date: values.expected_arrival_date ? new Date(values.expected_arrival_date).toISOString() : null,
        remark: values.remark,
        items: draftLines.map(({ po_item_id, sku_id, quantity_ordered, unit_price }) => ({ po_item_id, sku_id, quantity_ordered, unit_price })),
      } })
      message.success('采购变更申请已提交')
      setCreateOpen(false)
      setRevision((x) => x + 1)
    } catch (error) { message.error(errorText(error)) }
    finally { setCreateBusy(false) }
  }

  const decide = async (values: DecisionValues) => {
    if (!decisionTarget) return
    setDecisionBusy(true)
    try {
      await request(`/purchase-amendments/${decisionTarget.row.id}/${decisionTarget.action}`, {
        method: 'POST', body: { decision_note: values.decision_note?.trim() ?? '' },
      })
      message.success(decisionTarget.action === 'approve' ? '变更已批准，采购单已同步更新' : '已驳回变更申请')
      setDecisionTarget(null)
      setSelected(null)
      decisionForm.resetFields()
      setRevision((x) => x + 1)
    } catch (error) { message.error(errorText(error)) }
    finally { setDecisionBusy(false) }
  }

  const openDetail = async (row: Amendment) => {
    try { setSelected(await request<Amendment>(`/purchase-amendments/${row.id}`)) }
    catch (error) { message.error(errorText(error)) }
  }

  const columns: ColumnsType<Amendment> = [
    { title: '变更单号', dataIndex: 'amendment_no', width: 210 },
    { title: '采购单号', dataIndex: 'po_no', width: 180 },
    { title: '申请原因', dataIndex: 'reason', ellipsis: true },
    { title: '申请时间', dataIndex: 'created_at', width: 180, render: dateText },
    { title: '状态', dataIndex: 'status', width: 100, render: (value: keyof typeof statuses) => <Tag color={statuses[value]?.color}>{statuses[value]?.text ?? value}</Tag> },
    { title: '处理意见', dataIndex: 'decision_note', width: 200, ellipsis: true, render: (value) => value || '—' },
    { title: '操作', key: 'actions', fixed: 'right', width: 210, render: (_, row) => <Space>
      <Button type="link" onClick={() => void openDetail(row)}>详情</Button>
      {canWrite && row.status === 'submitted' && <>
        <Button type="link" onClick={() => { decisionForm.resetFields(); setDecisionTarget({ row, action: 'approve' }) }}>通过</Button>
        <Button type="link" danger onClick={() => { decisionForm.resetFields(); setDecisionTarget({ row, action: 'reject' }) }}>驳回</Button>
      </>}
    </Space> },
  ]

  const comparisonColumns: ColumnsType<{ key: string; name: string; original: string; proposed: string }> = [
    { title: '字段', dataIndex: 'name', width: 130 },
    { title: '变更前', dataIndex: 'original' },
    { title: '变更后', dataIndex: 'proposed' },
  ]
  const comparisonRows = selected ? (() => {
    const before = selected.original_snapshot
    const after = selected.proposed_snapshot
    const rows = [
      { key: 'total', name: '采购总金额', original: money(before.total_amount), proposed: money(after.items.reduce((sum, item) => sum + Number(item.quantity_ordered) * Number(item.unit_price), 0)) },
      { key: 'arrival', name: '预计到货日', original: dateText(before.expected_arrival_date), proposed: dateText(after.expected_arrival_date) },
      { key: 'remark', name: '采购备注', original: before.remark || '—', proposed: after.remark || '—' },
    ]
    const beforeItems = new Map(before.items.map((item) => [item.po_item_id, item]))
    after.items.forEach((item) => {
      const old = beforeItems.get(item.po_item_id)
      if (!old) return
      const name = `${old.sku_code_snapshot} ${old.sku_name_snapshot}`
      rows.push({ key: `${item.po_item_id}-qty`, name: `${name} 数量`, original: String(old.quantity_ordered), proposed: String(item.quantity_ordered) })
      rows.push({ key: `${item.po_item_id}-price`, name: `${name} 单价`, original: money(old.unit_price), proposed: money(item.unit_price) })
    })
    return rows
  })() : []

  return <Card title="采购变更" extra={<Space>
    <Select allowClear placeholder="全部状态" style={{ width: 130 }} value={statusFilter} onChange={(value) => setStatusFilter(value)} options={Object.entries(statuses).map(([value, item]) => ({ value, label: item.text }))} />
    <Button onClick={() => setRevision((x) => x + 1)}>刷新</Button>
    {canWrite && <Button type="primary" onClick={openCreate}>新建变更申请</Button>}
  </Space>}>
    {!canRead && <Alert type="warning" showIcon message="当前账号没有采购变更查看权限" />}
    {canRead && <Table rowKey="id" loading={loading} columns={columns} dataSource={rows} scroll={{ x: 1250 }} pagination={{ pageSize: 20, showTotal: (total) => `共 ${total} 条` }} />}

    <Modal title="新建采购变更申请" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => form.submit()} confirmLoading={createBusy} width={900} destroyOnClose>
      <Form form={form} layout="vertical" onFinish={(values) => void create(values)}>
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message="仅可申请尚未收货的已审批采购单；SKU、供应商和收货仓库保持不变。变更审批通过后会直接更新采购单并保留审计记录。" />
        <Form.Item name="purchase_order_id" label="采购单" rules={[{ required: true, message: '请选择采购单' }]}>
          <Select showSearch optionFilterProp="label" placeholder="选择可变更的已审批采购单" options={orderOptions} onChange={(value) => void loadSelectedOrder(value)} />
        </Form.Item>
        {orderDetail && <Descriptions size="small" bordered column={3} style={{ marginBottom: 16 }}>
          <Descriptions.Item label="采购单号">{orderDetail.po_no}</Descriptions.Item>
          <Descriptions.Item label="当前金额">{money(orderDetail.total_amount)}</Descriptions.Item>
          <Descriptions.Item label="SKU 行数">{orderDetail.items.length}</Descriptions.Item>
        </Descriptions>}
        <Form.Item name="reason" label="变更原因" rules={[{ required: true, whitespace: true, message: '请填写变更原因' }, { max: 500 }]}>
          <Input.TextArea rows={2} maxLength={500} showCount />
        </Form.Item>
        <Space size="middle" style={{ display: 'flex' }} align="start">
          <Form.Item name="expected_arrival_date" label="预计到货时间" style={{ flex: 1 }}>
            <Input type="datetime-local" />
          </Form.Item>
          <Form.Item name="remark" label="采购备注" style={{ flex: 2 }}>
            <Input maxLength={500} />
          </Form.Item>
        </Space>
        {draftLines.length > 0 && <Table<DraftLine>
          rowKey="po_item_id" size="small" pagination={false} dataSource={draftLines}
          columns={[
            { title: 'SKU', key: 'sku', render: (_, row) => <>{row.sku_code_snapshot}<br /><small>{row.sku_name_snapshot}</small></> },
            { title: '变更数量', dataIndex: 'quantity_ordered', width: 150, render: (value, _row, index) => <InputNumber min={1} max={1_000_000} precision={0} value={value} onChange={(next) => setDraftLines((list) => list.map((line, i) => i === index ? { ...line, quantity_ordered: Number(next ?? 1) } : line))} /> },
            { title: '变更单价', dataIndex: 'unit_price', width: 160, render: (value, _row, index) => <InputNumber min={0} precision={2} value={value} onChange={(next) => setDraftLines((list) => list.map((line, i) => i === index ? { ...line, unit_price: Number(next ?? 0) } : line))} /> },
            { title: '变更后小计', key: 'subtotal', width: 140, render: (_, row) => money(row.quantity_ordered * row.unit_price) },
          ]}
        />}
      </Form>
    </Modal>

    <Drawer title={selected ? `采购变更详情 · ${selected.amendment_no}` : '采购变更详情'} open={!!selected} width={760} onClose={() => setSelected(null)}>
      {selected && <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="采购单号">{selected.po_no}</Descriptions.Item>
          <Descriptions.Item label="状态"><Tag color={statuses[selected.status]?.color}>{statuses[selected.status]?.text}</Tag></Descriptions.Item>
          <Descriptions.Item label="申请原因" span={2}>{selected.reason}</Descriptions.Item>
          <Descriptions.Item label="提交时间">{dateText(selected.created_at)}</Descriptions.Item>
          <Descriptions.Item label="处理时间">{dateText(selected.decided_at)}</Descriptions.Item>
          <Descriptions.Item label="处理意见" span={2}>{selected.decision_note || '—'}</Descriptions.Item>
        </Descriptions>
        <Table rowKey="key" size="small" pagination={false} columns={comparisonColumns} dataSource={comparisonRows} />
        {canWrite && selected.status === 'submitted' && <Space>
          <Button type="primary" onClick={() => { decisionForm.resetFields(); setDecisionTarget({ row: selected, action: 'approve' }) }}>通过</Button>
          <Button danger onClick={() => { decisionForm.resetFields(); setDecisionTarget({ row: selected, action: 'reject' }) }}>驳回</Button>
        </Space>}
      </Space>}
    </Drawer>

    <Modal title={decisionTarget?.action === 'approve' ? '批准采购变更' : '驳回采购变更'} open={!!decisionTarget} onCancel={() => setDecisionTarget(null)} onOk={() => decisionForm.submit()} confirmLoading={decisionBusy}>
      <Form form={decisionForm} layout="vertical" onFinish={(values) => void decide(values)}>
        {decisionTarget?.action === 'approve' && <Alert type="warning" showIcon style={{ marginBottom: 16 }} message="批准后将原子更新采购单金额、明细、预计到货时间和备注，采购单保持已审批状态。若采购单或收货状态已变化，审批会失败。" />}
        <Form.Item name="decision_note" label="处理意见" rules={[{ max: 500 }]}>
          <Input.TextArea rows={3} maxLength={500} showCount placeholder="填写审批意见或驳回原因" />
        </Form.Item>
      </Form>
    </Modal>
  </Card>
}
