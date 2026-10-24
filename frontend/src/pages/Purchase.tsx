import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Alert, Button, Descriptions, Drawer, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, Tabs, Tag, message } from 'antd'
import api from '../api'
import { useAuth } from '../auth/AuthProvider'

interface PurchaseOrder {
  id: string
  po_no: string
  supplier_id: string
  warehouse_id: string
  total_amount: string | number
  status: string
  expected_arrival_date?: string | null
  remark?: string
}

interface PurchaseOrderItem {
  id: string
  sku_id: string
  unit_price: string | number
  sku_code_snapshot: string
  sku_name_snapshot: string
  quantity_ordered: number
  quantity_received: number
}

interface PurchaseOrderDetail extends PurchaseOrder {
  items: PurchaseOrderItem[]
}

interface ReceiptItem { id: string; po_item_id: string; sku_id: string; quantity_accepted: number; quantity_rejected: number }
interface Receipt { id: string; receipt_no: string; received_at: string; remark: string; items: ReceiptItem[] }
interface PoForm { supplier_id: string; warehouse_id: string; expected_arrival_date?: string; remark?: string; items: { sku_id: string; quantity_ordered: number; unit_price: number | string }[] }

function localDateTime(value?: string | null) {
  if (!value) return undefined
  const date = new Date(value)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

interface Suggestion {
  id: string
  sku_id: string
  warehouse_id: string
  suggested_qty: number
  safety_stock: number
  lead_time_days: number
  avg_daily_sales: number | string
  status: string
  reason?: string | null
  formula_inputs: {
    avg_daily_sales?: number
    lead_time_days?: number
    safety_stock?: number
    effective_stock?: number
    effective_in_transit?: number
    reorder_point?: number
  } | null
}

interface Ref {
  id: string
  code?: string
  name: string
}

interface ListResult<T> {
  items: T[]
  total: number
}

/** 采购单状态与后端 scm.py 保持一致：draft → submitted → approved → closed。 */
const poStatus: Record<string, { color: string; text: string }> = {
  draft: { color: 'default', text: '草稿' },
  submitted: { color: 'orange', text: '待审批' },
  approved: { color: 'blue', text: '已审批' },
  rejected: { color: 'red', text: '已驳回' },
  closed: { color: 'green', text: '已完成' },
  cancelled: { color: 'red', text: '已取消' },
}

/** 补货建议状态取自 scm.py：转单后写入的是 turned_into_po，不是 converted。 */
const sugStatus: Record<string, string> = {
  pending: '待处理',
  approved: '已批准',
  turned_into_po: '已转采购单',
  rejected: '已驳回',
}

function receiptNo(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  const rand = Math.random().toString(36).slice(2, 6).toUpperCase()
  return `RCV-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${rand}`
}

export default function Purchase() {
  const location = useLocation()
  const navigate = useNavigate()
  const { user } = useAuth()
  const canRead = (permission: string) => user?.role === 'admin' || !!user?.permissions.includes(permission)
  const canReadPurchaseOrders = canRead('purchase_orders:read')
  const canWritePurchaseOrders = canRead('purchase_orders:write')
  const canReadReplenishment = canRead('replenishment:read')
  const canWriteReplenishment = canRead('replenishment:write')
  const canReadSuppliers = canRead('suppliers:read')
  const canReadSkus = canRead('skus:read')
  const canReadWarehouses = canRead('warehouses:read')
  const [pos, setPos] = useState<PurchaseOrder[]>([])
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [suppliers, setSuppliers] = useState<Ref[]>([])
  const [skus, setSkus] = useState<Ref[]>([])
  const [whs, setWhs] = useState<Ref[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [calcOpen, setCalcOpen] = useState(false)
  const [calcResult, setCalcResult] = useState<Suggestion | null>(null)
  const [form] = Form.useForm()

  // 收货弹窗
  const [receiptOpen, setReceiptOpen] = useState(false)
  const [receiptPo, setReceiptPo] = useState<PurchaseOrderDetail | null>(null)
  const [receiptSubmitting, setReceiptSubmitting] = useState(false)
  const [receiptForm] = Form.useForm()
  // 取消弹窗（后端 OrderCancel 要求 reason，1~500 字）
  const [cancelOpen, setCancelOpen] = useState(false)
  const [cancelTarget, setCancelTarget] = useState<PurchaseOrder | null>(null)
  const [cancelForm] = Form.useForm()
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectTarget, setRejectTarget] = useState<PurchaseOrder | null>(null)
  const [rejecting, setRejecting] = useState(false)
  const [rejectForm] = Form.useForm()
  // 补货建议调整弹窗
  const [adjustOpen, setAdjustOpen] = useState(false)
  const [adjustTarget, setAdjustTarget] = useState<Suggestion | null>(null)
  const [adjustForm] = Form.useForm()
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<PurchaseOrderDetail | null>(null)
  const [saving, setSaving] = useState(false)
  const [poForm] = Form.useForm<PoForm>()
  const [detail, setDetail] = useState<PurchaseOrderDetail | null>(null)
  const [receipts, setReceipts] = useState<Receipt[]>([])
  const [receiptRejected, setReceiptRejected] = useState<Record<string, number>>({})

  const showDetail = async (id: string) => {
    const [order, records] = await Promise.all([
      api.get<PurchaseOrderDetail>(`/purchase-orders/${id}`),
      api.get<ListResult<Receipt>>(`/purchase-orders/${id}/receipts`),
    ])
    setDetail(order.data)
    setReceipts(records.data.items)
  }

  const openEditor = async (id?: string) => {
    const order = id ? (await api.get<PurchaseOrderDetail>(`/purchase-orders/${id}`)).data : null
    if (order && order.status !== 'draft') { message.warning('当前采购单已不是草稿，请刷新后重试'); return }
    setEditing(order)
    poForm.resetFields()
    poForm.setFieldsValue(order ? {
      supplier_id: order.supplier_id, warehouse_id: order.warehouse_id,
      expected_arrival_date: localDateTime(order.expected_arrival_date), remark: order.remark,
      items: order.items.map((item) => ({ sku_id: item.sku_id, quantity_ordered: item.quantity_ordered, unit_price: item.unit_price })),
    } : { items: [{ quantity_ordered: 1, unit_price: 0 }] })
    setEditorOpen(true)
  }

  const savePo = async () => {
    const values = await poForm.validateFields()
    if (new Set(values.items.map((item) => item.sku_id)).size !== values.items.length) {
      message.warning('采购明细不能重复选择同一个 SKU'); return
    }
    setSaving(true)
    try {
      const payload = {
        remark: values.remark ?? '', items: values.items,
        ...(values.expected_arrival_date ? { expected_arrival_date: new Date(values.expected_arrival_date).toISOString() } : {}),
      }
      const result = editing
        ? await api.patch<PurchaseOrderDetail>(`/purchase-orders/${editing.id}`, payload)
        : await api.post<PurchaseOrderDetail>('/purchase-orders', { ...payload, supplier_id: values.supplier_id, warehouse_id: values.warehouse_id })
      message.success(editing ? '采购草稿已保存' : '采购草稿已创建')
      setEditorOpen(false)
      await load()
      await showDetail(result.data.id)
    } finally { setSaving(false) }
  }

  const load = async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const [p, s, sup, sk, w] = await Promise.allSettled([
        canReadPurchaseOrders ? api.get<ListResult<PurchaseOrder>>('/purchase-orders', { params: { page_size: 50 } }) : Promise.resolve(null),
        canReadReplenishment ? api.get<ListResult<Suggestion>>('/replenishment-suggestions', { params: { page_size: 50 } }) : Promise.resolve(null),
        canReadSuppliers ? api.get<ListResult<Ref>>('/suppliers', { params: { page_size: 100 } }) : Promise.resolve(null),
        canReadSkus ? api.get<ListResult<Ref>>('/skus', { params: { page_size: 100 } }) : Promise.resolve(null),
        canReadWarehouses ? api.get<ListResult<Ref>>('/warehouses', { params: { page_size: 100 } }) : Promise.resolve(null),
      ])
      if (p.status === 'fulfilled' && p.value) setPos(p.value.data.items)
      if (s.status === 'fulfilled' && s.value) setSuggestions(s.value.data.items)
      if (sup.status === 'fulfilled' && sup.value) setSuppliers(sup.value.data.items)
      if (sk.status === 'fulfilled' && sk.value) setSkus(sk.value.data.items)
      if (w.status === 'fulfilled' && w.value) setWhs(w.value.data.items)
      if ([p, s, sup, sk, w].some((result) => result.status === 'rejected')) setLoadError('部分采购资料加载失败，请刷新后重试')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load().catch(() => {})
  }, [])

  const submit = async (id: string) => {
    await api.post(`/purchase-orders/${id}/submit`)
    message.success('已提交审批')
    void load().catch(() => {})
  }

  const approve = async (id: string) => {
    await api.post(`/purchase-orders/${id}/approve`)
    message.success('已审批')
    void load().catch(() => {})
  }

  /** 驳回：必须填写原因，并由后端保存在采购单备注及审计快照中。 */
  const submitReject = async () => {
    const values = await rejectForm.validateFields()
    setRejecting(true)
    try {
      await api.post(`/purchase-orders/${rejectTarget!.id}/reject`, { reason: values.reason.trim() })
    } finally { setRejecting(false) }
    message.success('已驳回')
    setRejectOpen(false)
    rejectForm.resetFields()
    setRejectTarget(null)
    void load().catch(() => {})
  }

  /** 关闭：POST /purchase-orders/{id}/close，后端要求所有明细已收齐。 */
  const close = async (id: string) => {
    await api.post(`/purchase-orders/${id}/close`)
    message.success('已关闭')
    void load().catch(() => {})
  }

  /** 取消：POST /purchase-orders/{id}/cancel，body { reason }。 */
  const submitCancel = async () => {
    const v = await cancelForm.validateFields()
    await api.post(`/purchase-orders/${cancelTarget!.id}/cancel`, { reason: v.reason })
    message.success('已取消')
    setCancelOpen(false)
    cancelForm.resetFields()
    setCancelTarget(null)
    void load().catch(() => {})
  }

  const openReceipt = async (id: string) => {
    const [res, records] = await Promise.all([
      api.get<PurchaseOrderDetail>(`/purchase-orders/${id}`),
      api.get<ListResult<Receipt>>(`/purchase-orders/${id}/receipts`),
    ])
    const rejected: Record<string, number> = {}
    records.data.items.forEach((record) => record.items.forEach((item) => { rejected[item.po_item_id] = (rejected[item.po_item_id] ?? 0) + item.quantity_rejected }))
    setReceiptRejected(rejected)
    setReceiptPo(res.data)
    receiptForm.resetFields()
    receiptForm.setFieldsValue({ receipt_no: receiptNo(), remark: '' })
    for (const it of res.data.items ?? []) {
      receiptForm.setFieldValue(`acc_${it.id}`, 0)
      receiptForm.setFieldValue(`rej_${it.id}`, 0)
    }
    setReceiptOpen(true)
  }

  /** 收货：POST /purchase-orders/{id}/receipts，body { receipt_no, remark, items:[{po_item_id, quantity_accepted, quantity_rejected}] }。 */
  const submitReceipt = async () => {
    const v = await receiptForm.validateFields()
    const items = (receiptPo?.items ?? []).map((it) => ({
      po_item_id: it.id,
      quantity_accepted: Number(v[`acc_${it.id}`] ?? 0),
      quantity_rejected: Number(v[`rej_${it.id}`] ?? 0),
    })).filter((item) => item.quantity_accepted > 0 || item.quantity_rejected > 0)
    if (!items.some((x) => x.quantity_accepted > 0 || x.quantity_rejected > 0)) {
      message.warning('请至少填写一条明细的收货数量')
      return
    }
    setReceiptSubmitting(true)
    try {
      await api.post(`/purchase-orders/${receiptPo!.id}/receipts`, {
        receipt_no: v.receipt_no,
        remark: v.remark ?? '',
        items,
      })
      message.success('收货成功')
      setReceiptOpen(false)
      if (detail?.id === receiptPo!.id) await showDetail(receiptPo!.id)
      void load().catch(() => {})
    } finally {
      setReceiptSubmitting(false)
    }
  }

  const convert = async (id: string) => {
    await api.post(`/replenishment-suggestions/${id}/convert`)
    message.success('已生成采购草稿单')
    void load().catch(() => {})
  }

  /** 调整：PATCH /replenishment-suggestions/{id}，body { suggested_qty, reason }。 */
  const openAdjust = (r: Suggestion) => {
    setAdjustTarget(r)
    adjustForm.setFieldsValue({ suggested_qty: r.suggested_qty, reason: r.reason ?? '' })
    setAdjustOpen(true)
  }

  const submitAdjust = async () => {
    const v = await adjustForm.validateFields()
    await api.patch(`/replenishment-suggestions/${adjustTarget!.id}`, {
      suggested_qty: v.suggested_qty,
      reason: v.reason ?? '',
    })
    message.success('已调整')
    setAdjustOpen(false)
    void load().catch(() => {})
  }

  /** 后端 compute 接收数组，返回 { items: [...] }，取第一条展示。 */
  const calc = async () => {
    const v = await form.validateFields()
    const res = await api.post<ListResult<Suggestion>>('/replenishment-suggestions/compute', [
      {
        sku_id: v.sku_id,
        warehouse_id: v.warehouse_id,
        supplier_id: v.supplier_id,
        avg_daily_sales: v.avg_daily_sales,
        safety_stock: v.safety_stock,
        lead_time_days: v.lead_time_days,
      },
    ])
    setCalcResult(res.data.items[0] ?? null)
    message.success('计算完成')
    void load().catch(() => {})
  }

  const nameOf = (list: Ref[], id: string) => list.find((x) => x.id === id)?.name ?? id

  /** 合格数与不合格数合计不得超过未收量，且均不能为负。 */
  const qtyRule = (item: PurchaseOrderItem, self: 'acc' | 'rej') => {
    const remaining = item.quantity_ordered - item.quantity_received - (receiptRejected[item.id] ?? 0)
    const other = self === 'acc' ? `rej_${item.id}` : `acc_${item.id}`
    return [
      { required: true, message: '请填写数量' },
      {
        validator: (_: unknown, value: number | undefined) => {
          const cur = Number(value ?? 0)
          if (!Number.isInteger(cur) || cur < 0) return Promise.reject(new Error('数量须为非负整数'))
          const sum = cur + Number(receiptForm.getFieldValue(other) ?? 0)
          if (sum > remaining) return Promise.reject(new Error(`合计不能超过未收量 ${remaining}`))
          return Promise.resolve()
        },
      },
    ]
  }

  return (
    <>
      {loadError && <Alert role="alert" type="error" showIcon message="采购资料加载失败" description={loadError} action={<Button size="small" loading={loading} onClick={() => void load()}>重试</Button>} style={{ marginBottom: 16 }} />}
      {loading && <span role="status" aria-live="polite" className="visually-hidden">正在加载采购资料</span>}
      <Tabs
        activeKey={location.pathname === '/replenishment' ? 'suggest' : 'po'}
        onChange={(key) => navigate(key === 'suggest' ? '/replenishment' : '/purchase-orders')}
        items={[
          {
            key: 'po',
            label: '采购单',
            children: (
              <>
              <Space style={{ marginBottom: 16 }}>
                <Button type="primary" disabled={!canWritePurchaseOrders || !canReadSuppliers || !canReadWarehouses || !canReadSkus} onClick={() => void openEditor().catch(() => {})}>新建采购单</Button>
                <Button onClick={() => void load().catch(() => {})}>刷新</Button>
              </Space>
              <Table<PurchaseOrder>
                rowKey="id"
                loading={loading}
                dataSource={pos}
                pagination={false}
                columns={[
                  { title: '采购单号', dataIndex: 'po_no', width: 190, render: (value: string, row) => <Button type="link" onClick={() => void showDetail(row.id).catch(() => {})}>{value}</Button> },
                  {
                    title: '供应商',
                    dataIndex: 'supplier_id',
                    render: (id: string) => nameOf(suppliers, id),
                  },
                  {
                    title: '金额',
                    dataIndex: 'total_amount',
                    width: 120,
                    render: (v: string | number) => v,
                  },
                  {
                    title: '状态',
                    dataIndex: 'status',
                    width: 110,
                    render: (v: string) => (
                      <Tag color={poStatus[v]?.color}>{poStatus[v]?.text || v}</Tag>
                    ),
                  },
                  {
                    title: '操作',
                    width: 300,
                    render: (_, r) => (
                      <Space wrap>
                        <Button size="small" onClick={() => void showDetail(r.id).catch(() => {})}>详情 / 收货记录</Button>
                        {r.status === 'draft' && <Button size="small" disabled={!canWritePurchaseOrders || !canReadSkus} onClick={() => void openEditor(r.id).catch(() => {})}>编辑草稿</Button>}
                        {r.status === 'draft' && (
                          <Popconfirm title="提交该采购单进入审批？" onConfirm={() => void submit(r.id).catch(() => {})}>
                            <Button size="small" type="primary" disabled={!canWritePurchaseOrders}>
                              提交审批
                            </Button>
                          </Popconfirm>
                        )}
                        {r.status === 'submitted' && (
                          <>
                            <Popconfirm title="确认审批通过该采购单？" onConfirm={() => void approve(r.id).catch(() => {})}>
                              <Button size="small" type="primary" disabled={!canWritePurchaseOrders}>
                                审批
                              </Button>
                            </Popconfirm>
                            <Button size="small" danger disabled={!canWritePurchaseOrders} onClick={() => {
                              rejectForm.resetFields()
                              setRejectTarget(r)
                              setRejectOpen(true)
                            }}>驳回</Button>
                          </>
                        )}
                        {r.status === 'approved' && (
                          <>
                            <Button
                              size="small"
                              type="primary"
                              disabled={!canWritePurchaseOrders}
                              onClick={() => void openReceipt(r.id).catch(() => {})}
                            >
                              收货
                            </Button>
                            <Popconfirm
                              title="确认关闭该采购单？"
                              description="需所有明细均已收齐，否则后端会拒绝。"
                              onConfirm={() => void close(r.id).catch(() => {})}
                            >
                              <Button size="small" disabled={!canWritePurchaseOrders}>
                                关闭
                              </Button>
                            </Popconfirm>
                          </>
                        )}
                        {!['closed', 'cancelled'].includes(r.status) && (
                          <Button
                            size="small"
                            danger
                            disabled={!canWritePurchaseOrders}
                            onClick={() => {
                              setCancelTarget(r)
                              cancelForm.resetFields()
                              setCancelOpen(true)
                            }}
                          >
                            取消
                          </Button>
                        )}
                      </Space>
                    ),
                  },
                ]}
              />
              </>
            ),
          },
          {
            key: 'suggest',
            label: '补货建议',
            children: (
              <>
                <Space style={{ marginBottom: 16 }}>
                  <Button type="primary" disabled={!canWriteReplenishment || !canReadSkus || !canReadWarehouses} onClick={() => setCalcOpen(true)}>
                    计算补货建议
                  </Button>
                </Space>
                <Table<Suggestion>
                  rowKey="id"
                  loading={loading}
                  dataSource={suggestions}
                  pagination={false}
                  columns={[
                    {
                      title: 'SKU',
                      dataIndex: 'sku_id',
                      render: (id: string) => nameOf(skus, id),
                    },
                    { title: '建议数量', dataIndex: 'suggested_qty', width: 100 },
                    { title: '仓库', dataIndex: 'warehouse_id', render: (id: string) => nameOf(whs, id) },
                    { title: '调整原因', dataIndex: 'reason', render: (value?: string) => value || '—' },
                    { title: '安全库存', dataIndex: 'safety_stock', width: 100 },
                    { title: '交期(天)', dataIndex: 'lead_time_days', width: 100 },
                    {
                      title: '状态',
                      dataIndex: 'status',
                      width: 120,
                      render: (v: string) => <Tag>{sugStatus[v] || v}</Tag>,
                    },
                    {
                      title: '操作',
                      width: 180,
                      render: (_, r) => (
                        <Space wrap>
                          {r.status !== 'turned_into_po' && (
                            <Button size="small" disabled={!canWriteReplenishment} onClick={() => openAdjust(r)}>
                              调整
                            </Button>
                          )}
                          {r.status !== 'turned_into_po' && r.status !== 'rejected' && (
                            <Button size="small" type="primary" disabled={!canWriteReplenishment} onClick={() => void convert(r.id).catch(() => {})}>
                              转采购单
                            </Button>
                          )}
                        </Space>
                      ),
                    },
                  ]}
                />
              </>
            ),
          },
        ].filter((item) => item.key === 'po' ? canReadPurchaseOrders : canReadReplenishment)}
      />

      <Modal open={editorOpen} title={editing ? `编辑采购草稿 · ${editing.po_no}` : '新建采购单'} width={900} confirmLoading={saving} onCancel={() => setEditorOpen(false)} onOk={() => void savePo().catch(() => {})} okText="保存草稿">
        <Form form={poForm} layout="vertical">
          <Space align="start" style={{ display: 'flex' }}>
            <Form.Item name="supplier_id" label="供应商" rules={[{ required: true }]} style={{ width: 260 }}><Select disabled={!!editing} showSearch optionFilterProp="label" options={suppliers.map((item) => ({ value: item.id, label: item.name }))} /></Form.Item>
            <Form.Item name="warehouse_id" label="收货仓库" rules={[{ required: true }]} style={{ width: 260 }}><Select disabled={!!editing} showSearch optionFilterProp="label" options={whs.map((item) => ({ value: item.id, label: item.name }))} /></Form.Item>
            <Form.Item name="expected_arrival_date" label="预计到货（本地时间）" rules={[{ validator: (_, value) => editing?.expected_arrival_date && !value ? Promise.reject(new Error('已有预计到货时间须保留或修改')) : Promise.resolve() }]}><Input type="datetime-local" /></Form.Item>
          </Space>
          <Form.Item name="remark" label="备注"><Input.TextArea maxLength={500} rows={2} /></Form.Item>
          <Form.List name="items" rules={[{ validator: (_, items: PoForm['items']) => !items?.length || items.length > 200 ? Promise.reject(new Error('请填写 1～200 条采购明细')) : Promise.resolve() }]}>
            {(fields, { add, remove }, { errors }) => <>
              {fields.map(({ key, name, ...rest }) => <Space key={key} align="start" style={{ display: 'flex' }}>
                <Form.Item {...rest} name={[name, 'sku_id']} label="SKU" rules={[{ required: true, message: '请选择 SKU' }]}><Select style={{ width: 300 }} showSearch optionFilterProp="label" options={skus.map((item) => ({ value: item.id, label: `${item.code ?? ''} ${item.name}` }))} /></Form.Item>
                <Form.Item {...rest} name={[name, 'quantity_ordered']} label="订购数量" rules={[{ required: true }, { type: 'integer', min: 1, max: 1000000 }]}><InputNumber min={1} max={1000000} precision={0} /></Form.Item>
                <Form.Item {...rest} name={[name, 'unit_price']} label="采购单价" rules={[{ required: true }]}><InputNumber min={0} max={9999999999.99} precision={2} /></Form.Item>
                <Button danger style={{ marginTop: 30 }} onClick={() => remove(name)}>移除</Button>
              </Space>)}
              <Form.ErrorList errors={errors} />
              <Button onClick={() => add({ quantity_ordered: 1, unit_price: 0 })} disabled={fields.length >= 200}>添加采购明细</Button>
            </>}
          </Form.List>
        </Form>
      </Modal>

      <Drawer open={!!detail} title={`采购详情 · ${detail?.po_no ?? ''}`} width="min(950px, 100vw)" onClose={() => setDetail(null)}>
        {detail && <>
          <Descriptions bordered column={2} size="small" items={[
            { key: 'supplier', label: '供应商', children: nameOf(suppliers, detail.supplier_id) },
            { key: 'warehouse', label: '仓库', children: nameOf(whs, detail.warehouse_id) },
            { key: 'status', label: '状态', children: poStatus[detail.status]?.text ?? detail.status },
            { key: 'total', label: '采购总额', children: detail.total_amount },
            { key: 'arrival', label: '预计到货', children: detail.expected_arrival_date ? new Date(detail.expected_arrival_date).toLocaleString('zh-CN') : '—' },
            { key: 'remark', label: '备注', children: detail.remark || '—' },
          ]} />
          <h3>采购明细</h3>
          <Table rowKey="id" size="small" pagination={false} dataSource={detail.items} columns={[
            { title: 'SKU', dataIndex: 'sku_code_snapshot' }, { title: '品名', dataIndex: 'sku_name_snapshot' },
            { title: '单价', dataIndex: 'unit_price' }, { title: '订购数量', dataIndex: 'quantity_ordered' },
            { title: '累计合格数', dataIndex: 'quantity_received' },
            { title: '累计不合格数', render: (_, item) => receipts.flatMap((record) => record.items).filter((line) => line.po_item_id === item.id).reduce((total, line) => total + line.quantity_rejected, 0) },
          ]} />
          <h3>收货记录</h3>
          <Table<Receipt> rowKey="id" size="small" pagination={false} dataSource={receipts} columns={[
            { title: '收货单号', dataIndex: 'receipt_no' },
            { title: '收货时间', dataIndex: 'received_at', render: (value: string) => new Date(value).toLocaleString('zh-CN') },
            { title: '备注', dataIndex: 'remark' },
          ]} expandable={{ expandedRowRender: (record) => <Table rowKey="id" size="small" pagination={false} dataSource={record.items} columns={[
            { title: 'SKU', dataIndex: 'sku_id', render: (id: string) => detail.items.find((item) => item.sku_id === id)?.sku_code_snapshot ?? nameOf(skus, id) },
            { title: '合格数量', dataIndex: 'quantity_accepted' }, { title: '不合格数量', dataIndex: 'quantity_rejected' },
          ]} /> }} />
          <Alert style={{ marginTop: 16 }} type="info" showIcon message="收货合格数增加库存；不合格数仅记录，并占用已处理的订购数量。全部合格收齐后采购单自动关闭。" />
        </>}
      </Drawer>

      {/* 收货 */}
      <Modal
        open={receiptOpen}
        title={receiptPo ? `采购收货 - ${receiptPo.po_no}` : '采购收货'}
        onCancel={() => setReceiptOpen(false)}
        onOk={() => void submitReceipt().catch(() => {})}
        okText="确认收货"
        confirmLoading={receiptSubmitting}
        width={720}
        destroyOnClose
      >
        <Alert style={{ marginBottom: 12 }} type="info" showIcon message="合格数入库，不合格数仅记录。未收量已扣除历次合格与不合格数量。" />
        <Form form={receiptForm} layout="vertical">
          <Space size={16} style={{ display: 'flex' }}>
            <Form.Item
              name="receipt_no"
              label="收货单号"
              style={{ flex: 1 }}
              rules={[{ required: true, message: '请填写收货单号' }]}
            >
              <Input placeholder="如 RCV-20260101-0001" maxLength={64} />
            </Form.Item>
            <Form.Item name="remark" label="备注" style={{ flex: 1 }}>
              <Input placeholder="选填" maxLength={500} />
            </Form.Item>
          </Space>
          <Form.Item shouldUpdate style={{ marginBottom: 0 }}>
            {() => (
              <Table<PurchaseOrderItem>
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={receiptPo?.items ?? []}
                locale={{ emptyText: '该采购单没有明细' }}
                columns={[
                  {
                    title: 'SKU',
                    dataIndex: 'sku_code_snapshot',
                    render: (code: string, it) => `${code} ${it.sku_name_snapshot}`.trim(),
                  },
                  { title: '订购量', dataIndex: 'quantity_ordered', width: 80 },
                  { title: '已收合格', dataIndex: 'quantity_received', width: 80 },
                  { title: '已收不合格', width: 90, render: (_, it) => receiptRejected[it.id] ?? 0 },
                  {
                    title: '未收量',
                    width: 80,
                    render: (_, it) => <b>{Math.max(0, it.quantity_ordered - it.quantity_received - (receiptRejected[it.id] ?? 0))}</b>,
                  },
                  {
                    title: '本次合格数',
                    width: 130,
                    render: (_, it) => (
                      <Form.Item
                        name={`acc_${it.id}`}
                        style={{ marginBottom: 0 }}
                        rules={qtyRule(it, 'acc')}
                        dependencies={[`rej_${it.id}`]}
                      >
                        <InputNumber min={0} precision={0} max={Math.max(0, it.quantity_ordered - it.quantity_received - (receiptRejected[it.id] ?? 0))} style={{ width: '100%' }} />
                      </Form.Item>
                    ),
                  },
                  {
                    title: '不合格数',
                    width: 130,
                    render: (_, it) => (
                      <Form.Item
                        name={`rej_${it.id}`}
                        style={{ marginBottom: 0 }}
                        rules={qtyRule(it, 'rej')}
                        dependencies={[`acc_${it.id}`]}
                      >
                        <InputNumber min={0} precision={0} max={Math.max(0, it.quantity_ordered - it.quantity_received - (receiptRejected[it.id] ?? 0))} style={{ width: '100%' }} />
                      </Form.Item>
                    ),
                  },
                ]}
              />
            )}
          </Form.Item>
        </Form>
      </Modal>

      {/* 驳回采购单 */}
      <Modal
        open={rejectOpen}
        title={rejectTarget ? `驳回采购单 - ${rejectTarget.po_no}` : '驳回采购单'}
        onCancel={() => setRejectOpen(false)}
        onOk={() => void submitReject().catch(() => {})}
        confirmLoading={rejecting}
        okText="确认驳回"
        okButtonProps={{ danger: true }}
        destroyOnClose
      >
        <Form form={rejectForm} layout="vertical">
          <Form.Item
            name="reason"
            label="驳回原因"
            rules={[
              { required: true, message: '请填写驳回原因' },
              { max: 480, message: '不能超过 480 字' },
              { validator: (_, value) => value?.trim() ? Promise.resolve() : Promise.reject(new Error('驳回原因不能为空')) },
            ]}
          >
            <Input.TextArea rows={3} maxLength={480} placeholder="请说明驳回原因" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 取消采购单 */}
      <Modal
        open={cancelOpen}
        title={cancelTarget ? `取消采购单 - ${cancelTarget.po_no}` : '取消采购单'}
        onCancel={() => setCancelOpen(false)}
        onOk={() => void submitCancel().catch(() => {})}
        okText="确认取消"
        okButtonProps={{ danger: true }}
        destroyOnClose
      >
        <Form form={cancelForm} layout="vertical">
          <Form.Item
            name="reason"
            label="取消原因"
            rules={[
              { required: true, message: '请填写取消原因' },
              { max: 500, message: '不能超过 500 字' },
            ]}
          >
            <Input.TextArea rows={3} maxLength={500} placeholder="后端要求 1~500 字" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 调整补货建议 */}
      <Modal
        open={adjustOpen}
        title="调整补货建议"
        onCancel={() => setAdjustOpen(false)}
        onOk={() => void submitAdjust().catch(() => {})}
        destroyOnClose
      >
        <Form form={adjustForm} layout="vertical">
          <Form.Item
            name="suggested_qty"
            label="建议数量"
            rules={[{ required: true, message: '请填写建议数量' }, { type: 'integer', min: 0, max: 10000000 }]}
          >
            <InputNumber min={0} max={10000000} precision={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="reason" label="调整原因">
            <Input.TextArea rows={3} maxLength={500} placeholder="选填" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={calcOpen}
        title="补货计算"
        onCancel={() => setCalcOpen(false)}
        onOk={() => void calc().catch(() => {})}
        width={560}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="sku_id" label="SKU" rules={[{ required: true, message: '请选择 SKU' }]}>
            <Select options={skus.map((s) => ({ label: `${s.code ?? ''} ${s.name}`.trim(), value: s.id }))} />
          </Form.Item>
          <Form.Item name="warehouse_id" label="仓库" rules={[{ required: true, message: '请选择仓库' }]}>
            <Select options={whs.map((w) => ({ label: w.name, value: w.id }))} />
          </Form.Item>
          <Form.Item name="supplier_id" label="供应商（可选）">
            <Select allowClear options={suppliers.map((s) => ({ label: s.name, value: s.id }))} />
          </Form.Item>
          <Form.Item name="avg_daily_sales" label="日均销量" initialValue={1}>
            <InputNumber min={0} step={0.5} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="lead_time_days" label="交期(天)" initialValue={7}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="safety_stock" label="安全库存" initialValue={0}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Form>

        {calcResult && (
          <div style={{ marginTop: 16, padding: 12, background: '#f0f5ff', borderRadius: 6 }}>
            <div>
              有效库存：{calcResult.formula_inputs?.effective_stock ?? 0}　在途：
              {calcResult.formula_inputs?.effective_in_transit ?? 0}　再订货点：
              {calcResult.formula_inputs?.reorder_point ?? 0}
            </div>
            <div style={{ marginTop: 4 }}>
              建议补货：
              <b style={{ fontSize: 18, color: '#2b5cff' }}>{calcResult.suggested_qty}</b> 件
            </div>
            <div style={{ color: '#595959', fontSize: 12, marginTop: 4 }}>
              公式：round(日均销量 × 交期) + 安全库存 − 有效库存 − 在途
            </div>
          </div>
        )}
      </Modal>
    </>
  )
}
