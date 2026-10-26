import { useCallback, useEffect, useState } from 'react'
import {
  Table, Card, Tag, Button, Space, Input, Select, DatePicker, Drawer, Descriptions,
  Form, Modal, InputNumber, message, Divider, Typography, Statistic, Row, Col,
  Empty,
} from 'antd'
import {
  PlusOutlined, SearchOutlined, CheckOutlined, CarOutlined, CloseOutlined,
  ImportOutlined, EditOutlined, EyeOutlined, ReloadOutlined,
  DownloadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../api'
import OrderLifecycle from './OrderLifecycle'
import { useSearchParams } from 'react-router-dom'

const STATUS: Record<string, { color: string; label: string }> = {
  draft: { color: 'orange', label: '待审核' },
  approved: { color: 'blue', label: '已审核' },
  shipping_requested: { color: 'cyan', label: '待发货' },
  fulfilled: { color: 'green', label: '已发货' },
  cancelled: { color: 'red', label: '已取消' },
  after_sale: { color: 'purple', label: '售后中' },
}

export default function OrdersPage() {
  const [params] = useSearchParams()
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [shops, setShops] = useState<any[]>([])
  const [warehouses, setWarehouses] = useState<any[]>([])
  const [skus, setSkus] = useState<any[]>([])
  const [currencies, setCurrencies] = useState<any[]>([])
  const [filters, setFilters] = useState<any>({ status: params.get('status') ?? undefined })
  const [selected, setSelected] = useState<React.Key[]>([])

  const [detailId, setDetailId] = useState<string | null>(null)
  const [detail, setDetail] = useState<any>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const [createOpen, setCreateOpen] = useState(false)
  const [editOrder, setEditOrder] = useState<any>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [batchWarehouse, setBatchWarehouse] = useState<string | undefined>()

  const exportReconciliation = async () => {
    if (!filters.date_from || !filters.date_to) { message.warning('请先选择订单日期范围'); return }
    try {
      const params: any = { date_from: filters.date_from, date_to: dayjs(filters.date_to).subtract(1, 'day').format('YYYY-MM-DD'), limit: 10000 }
      if (filters.shop_id) params.shop_id = filters.shop_id
      const { data } = await api.get('/orders/export', { params })
      if (data.truncated) { message.warning('导出超过 10000 条，请缩小日期范围'); return }
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
      const a = document.createElement('a'); a.href = url; a.download = 'oms-orders.json'; a.click(); URL.revokeObjectURL(url)
    } catch { /* axios interceptor reports the API error */ }
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const p: any = { page, page_size: pageSize }
      if (filters.status) p.status = filters.status
      if (filters.shop_id) p.shop_id = filters.shop_id
      if (filters.q) p.q = filters.q
      if (filters.date_from) p.date_from = filters.date_from
      if (filters.date_to) p.date_to = filters.date_to
      const r = await api.get('/orders', { params: p })
      setRows(r.data.items)
      setTotal(r.data.total)
    } finally { setLoading(false) }
  }, [page, pageSize, filters])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    api.get('/shops?page_size=100').then((r) => setShops(r.data.items))
    api.get('/warehouses?page_size=100').then((r) => setWarehouses(r.data.items))
    api.get('/skus?page_size=100').then((r) => setSkus(r.data.items))
    api.get('/dictionaries?kind=currency').then((r) => setCurrencies(r.data.items))
  }, [])

  // 从 URL 参数打开详情
  useEffect(() => {
    const id = params.get('id')
    if (id) openDetail(id)
  }, [params])

  const openDetail = async (id: string) => {
    setDetailId(id)
    setDetailLoading(true)
    try {
      const r = await api.get(`/orders/${id}`)
      setDetail(r.data)
    } finally { setDetailLoading(false) }
  }

  const approve = async (id: string) => {
    const wh = warehouses[0]?.id
    if (!wh) { message.warning('请先在系统设置中创建仓库'); return }
    Modal.confirm({
      title: '确认审核订单？',
      content: `履约仓库：${warehouses.find((w) => w.id === wh)?.name ?? wh}`,
      onOk: async () => {
        await api.post(`/orders/${id}/approve`, { warehouse_id: wh })
        message.success('已审核')
        load()
      },
    })
  }

  const requestShipment = (id: string) => {
    Modal.confirm({
      title: '提交发货申请？',
      content: '将检查并预留库存，订单进入待仓库发货状态',
      onOk: async () => {
        await api.post(`/orders/${id}/shipment-request`, {})
        message.success('已提交发货申请')
        load()
      },
    })
  }

  const cancel = (id: string) => {
    let reason = ''
    Modal.confirm({
      title: '取消订单',
      content: <Input.TextArea placeholder="请填写取消原因" onChange={(e) => (reason = e.target.value)} rows={3} />,
      okText: '确认取消', okButtonProps: { danger: true },
      onOk: async () => {
        if (!reason.trim()) { message.warning('请填写取消原因'); throw new Error('empty') }
        await api.post(`/orders/${id}/cancel`, { reason })
        message.success('订单已取消')
        load()
      },
    })
  }

  const batchApprove = async () => {
    if (!selected.length) { message.warning('请先勾选订单'); return }
    if (!batchWarehouse) { message.warning('请选择履约仓库'); return }
    const r = await api.post('/orders/batch-approve', { order_ids: selected, warehouse_id: batchWarehouse })
    message.success(`批量审核完成：成功 ${r.data.ok_count}，失败 ${r.data.fail_count}`)
    setSelected([])
    load()
  }

  const batchCancel = () => {
    if (!selected.length) { message.warning('请先勾选订单'); return }
    let reason = ''
    Modal.confirm({
      title: `批量取消 ${selected.length} 笔订单`,
      content: <Input.TextArea placeholder="请填写取消原因" onChange={(e) => (reason = e.target.value)} rows={3} />,
      okText: '确认批量取消', okButtonProps: { danger: true },
      onOk: async () => {
        if (!reason.trim()) { message.warning('请填写原因'); throw new Error('empty') }
        const r = await api.post('/orders/batch-cancel', { order_ids: selected, reason })
        message.success(`批量取消完成：成功 ${r.data.ok_count}，失败 ${r.data.fail_count}`)
        setSelected([])
        load()
      },
    })
  }

  const columns = [
    { title: '来源单号', dataIndex: 'source_order_no', width: 150 },
    { title: '客户', dataIndex: 'customer_name', width: 130, ellipsis: true },
    { title: '店铺', dataIndex: 'shop_name', width: 140, ellipsis: true },
    { title: '金额', dataIndex: 'grand_total', width: 100, align: 'right' as const,
      render: (v: number, r: any) => `${v} ${r.currency_id}` },
    { title: '状态', dataIndex: 'status', width: 100,
      render: (v: string) => <Tag color={STATUS[v].color}>{STATUS[v].label}</Tag> },
    { title: '创建时间', dataIndex: 'created_at', width: 160,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm') },
    { title: '操作', key: 'op', width: 300, fixed: 'right' as const,
      render: (_: any, r: any) => (
        <Space size={4}>
          <Button size="small" icon={<EyeOutlined />} onClick={() => openDetail(r.id)}>详情</Button>
          {r.status === 'draft' && <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => approve(r.id)}>审核</Button>}
          {r.status === 'approved' && <Button size="small" icon={<CarOutlined />} onClick={() => requestShipment(r.id)}>发货</Button>}
          {['draft', 'approved'].includes(r.status) &&
            <Button size="small" icon={<EditOutlined />} onClick={() => { setEditOrder(r); setCreateOpen(true) }}>编辑</Button>}
          {['draft', 'approved', 'shipping_requested'].includes(r.status) &&
            <Button size="small" danger icon={<CloseOutlined />} onClick={() => cancel(r.id)}>取消</Button>}
        </Space>
      )},
  ]

  return (
    <div>
      <Card>
        <Space style={{ marginBottom: 12, flexWrap: 'wrap' }}>
          <Select allowClear placeholder="订单状态" style={{ width: 130 }} value={filters.status}
            onChange={(v) => { setFilters((f: any) => ({ ...f, status: v })); setPage(1) }}
            options={Object.entries(STATUS).map(([v, s]) => ({ value: v, label: s.label }))} />
          <Select allowClear placeholder="店铺" style={{ width: 200 }} value={filters.shop_id}
            onChange={(v) => { setFilters((f: any) => ({ ...f, shop_id: v })); setPage(1) }}
            options={shops.map((s) => ({ value: s.id, label: s.name }))} />
          <Input.Search allowClear placeholder="搜索单号/客户" style={{ width: 220 }} prefix={<SearchOutlined />}
            onSearch={(v) => { setFilters((f: any) => ({ ...f, q: v || undefined })); setPage(1) }} />
          <DatePicker.RangePicker onChange={(v) => {
            setFilters((f: any) => ({ ...f,
              date_from: v?.[0]?.format('YYYY-MM-DD'), date_to: v?.[1] ? v[1].add(1, 'day').format('YYYY-MM-DD') : undefined }))
            setPage(1)
          }} />
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        </Space>

        <Space style={{ marginBottom: 12 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditOrder(null); setCreateOpen(true) }}>手动创建订单</Button>
          <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>批量导入订单</Button>
          <Button icon={<DownloadOutlined />} onClick={exportReconciliation}>导出对账 JSON</Button>
          <Select allowClear placeholder="批量审核-履约仓库" style={{ width: 180 }} value={batchWarehouse}
            onChange={setBatchWarehouse} options={warehouses.map((w) => ({ value: w.id, label: w.name }))} />
          <Button icon={<CheckOutlined />} onClick={batchApprove}>批量审核</Button>
          <Button danger icon={<CloseOutlined />} onClick={batchCancel}>批量取消</Button>
        </Space>

        <Table rowKey="id" loading={loading} dataSource={rows} columns={columns}
          rowSelection={{ selectedRowKeys: selected, onChange: setSelected }}
          scroll={{ x: 1200 }}
          pagination={{ current: page, pageSize, total, showSizeChanger: true,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) } }} />
      </Card>

      <Drawer width={640} open={!!detailId} onClose={() => setDetailId(null)} title={`订单详情 ${detail?.source_order_no ?? ''}`}>
        {detailLoading || !detail ? <Empty /> : (
          <div>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={6}><Statistic title="订单金额" value={detail.grand_total} suffix={detail.currency_id} /></Col>
              <Col span={6}><Statistic title="优惠" value={detail.discount_amount} /></Col>
              <Col span={6}><Statistic title="应付" value={detail.grand_total - detail.discount_amount} suffix={detail.currency_id} /></Col>
              <Col span={6}><Statistic title="状态" valueRender={() => <Tag color={STATUS[detail.status]?.color}>{STATUS[detail.status]?.label}</Tag>} /></Col>
            </Row>
            <Descriptions bordered size="small" column={2} title="基本信息">
              <Descriptions.Item label="来源单号">{detail.source_order_no}</Descriptions.Item>
              <Descriptions.Item label="来源渠道">{detail.source_channel}</Descriptions.Item>
              <Descriptions.Item label="店铺ID">{detail.shop_id}</Descriptions.Item>
              <Descriptions.Item label="客户">{detail.customer_name}</Descriptions.Item>
              <Descriptions.Item label="取消原因">{detail.cancel_reason || '-'}</Descriptions.Item>
              <Descriptions.Item label="备注">{detail.remark || '-'}</Descriptions.Item>
            </Descriptions>
            <Descriptions bordered size="small" column={1} title="收货信息" style={{ marginTop: 12 }}>
              <Descriptions.Item label="收件人">{detail.shipping_name} {detail.shipping_phone}</Descriptions.Item>
              <Descriptions.Item label="地址">{detail.shipping_address}, {detail.shipping_city}, {detail.shipping_state} {detail.shipping_zip}, {detail.shipping_country}</Descriptions.Item>
            </Descriptions>
            <OrderLifecycle orderId={detail.id} />
            <Divider>商品明细</Divider>
            <Table rowKey="id" size="small" pagination={false} dataSource={detail.items}
              columns={[
                { title: 'SKU', dataIndex: 'sku_code_snapshot' },
                { title: '名称', dataIndex: 'sku_name_snapshot' },
                { title: '数量', dataIndex: 'quantity', align: 'right' },
                { title: '单价', dataIndex: 'unit_price', align: 'right' },
                { title: '优惠', dataIndex: 'discount_amount', align: 'right' },
                { title: '小计', dataIndex: 'line_total', align: 'right' },
              ]} />
            {detail.payments?.length > 0 && <>
              <Divider>收款记录</Divider>
              <Table rowKey="id" size="small" pagination={false} dataSource={detail.payments}
                columns={[
                  { title: '金额', dataIndex: 'amount', align: 'right', render: (v: number) => `${v} ${detail.currency_id}` },
                  { title: '方式', dataIndex: 'method' },
                  { title: '来源', dataIndex: 'source' },
                  { title: '时间', dataIndex: 'paid_at', render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm') },
                  { title: '备注', dataIndex: 'remark' },
                ]} />
            </>}
            {detail.after_sales?.length > 0 && <>
              <Divider>售后记录</Divider>
              <Table rowKey="id" size="small" pagination={false} dataSource={detail.after_sales}
                columns={[
                  { title: '类型', dataIndex: 'type', render: (v: string) => v === 'refund' ? '退款' : '退货' },
                  { title: '原因', dataIndex: 'reason' },
                  { title: '数量', dataIndex: 'quantity', align: 'right' },
                  { title: '金额', dataIndex: 'amount', align: 'right' },
                  { title: '状态', dataIndex: 'status', render: (v: string) => <Tag color={v === 'completed' ? 'green' : v === 'rejected' ? 'red' : 'orange'}>{v}</Tag> },
                ]} />
            </>}
            {detail.refunds?.length > 0 && <>
              <Divider>退款记录</Divider>
              <Table rowKey="id" size="small" pagination={false} dataSource={detail.refunds}
                columns={[
                  { title: '退款单号', dataIndex: 'refund_no' },
                  { title: '金额', dataIndex: 'amount', align: 'right' },
                  { title: '状态', dataIndex: 'status' },
                  { title: '渠道', dataIndex: 'channel' },
                  { title: '流水号', dataIndex: 'channel_txn_no' },
                ]} />
            </>}
          </div>
        )}
      </Drawer>

      <OrderFormModal
        open={createOpen} onClose={() => setCreateOpen(false)}
        shops={shops} skus={skus} currencies={currencies} warehouses={warehouses}
        editing={editOrder} onSaved={() => { setCreateOpen(false); load() }} />

      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} shops={shops} currencies={currencies}
        onSaved={() => { setImportOpen(false); load() }} />
    </div>
  )
}

// ---------------- 创建/编辑订单 ----------------

function OrderFormModal({ open, onClose, shops, skus, currencies, warehouses, editing, onSaved }: any) {
  const [form] = Form.useForm()
  const [items, setItems] = useState<any[]>([])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    form.resetFields()
    if (editing) {
      form.setFieldsValue({
        ...editing,
        customer_name: editing.customer_name, customer_contact: editing.customer_contact,
        shipping_name: editing.shipping_name, shipping_phone: editing.shipping_phone,
        shipping_address: editing.shipping_address, shipping_city: editing.shipping_city,
        shipping_state: editing.shipping_state, shipping_country: editing.shipping_country,
        shipping_zip: editing.shipping_zip, remark: editing.remark, warehouse_id: editing.warehouse_id,
        shop_id: editing.shop_id, currency_id: editing.currency_id,
        source_order_no: editing.source_order_no, source_channel: editing.source_channel,
      })
      setItems((editing.items ?? []).map((it: any) => ({ ...it })))
    } else {
      setItems([])
    }
  }, [open, editing])

  const addItem = () => setItems((v) => [...v, { sku_id: undefined, quantity: 1, unit_price: 0, discount_amount: 0 }])

  const save = async () => {
    const values = await form.validateFields()
    if (!items.length || items.some((i) => !i.sku_id || !i.quantity)) {
      message.warning('请完整填写商品明细'); return
    }
    setSaving(true)
    try {
      const payload = {
        ...values,
        items: items.map((i) => ({ sku_id: i.sku_id, quantity: i.quantity, unit_price: i.unit_price, discount_amount: i.discount_amount ?? 0 })),
      }
      if (editing) {
        await api.patch(`/orders/${editing.id}`, { ...payload, reason: payload.reason ?? '编辑订单' })
        message.success('订单已更新')
      } else {
        await api.post('/orders', payload)
        message.success('订单已创建')
      }
      onSaved()
    } catch (e: any) {
      message.error(e.message)
    } finally { setSaving(false) }
  }

  const defaultUnit = currencies.find((c: any) => c.code === 'USD')?.id

  return (
    <Modal open={open} title={editing ? `编辑订单 ${editing.source_order_no}` : '手动创建订单'}
      onCancel={onClose} width={760} onOk={save} confirmLoading={saving} okText="保存">
      <Form form={form} layout="vertical" initialValues={{ source_channel: 'manual', shipping_country: 'US', currency_id: defaultUnit }}>
        <Row gutter={12}>
          <Col span={12}><Form.Item name="shop_id" label="店铺" rules={[{ required: true }]}>
            <Select placeholder="选择店铺" options={shops.map((s: any) => ({ value: s.id, label: s.name }))} /></Form.Item></Col>
          <Col span={12}><Form.Item name="source_channel" label="来源渠道" rules={[{ required: true }]}>
            <Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="source_order_no" label="来源单号" rules={[{ required: true }]}>
            <Input disabled={!!editing} placeholder={editing ? '来源单号不可修改' : '如 AMZ-2026-10001'} /></Form.Item></Col>
          <Col span={12}><Form.Item name="currency_id" label="币种" rules={[{ required: true }]}>
            <Select options={currencies.map((c: any) => ({ value: c.id, label: `${c.code} ${c.name}` }))} /></Form.Item></Col>
          <Col span={12}><Form.Item name="warehouse_id" label="履约仓库">
            <Select allowClear placeholder="待审核时指定" options={warehouses.map((w: any) => ({ value: w.id, label: w.name }))} /></Form.Item></Col>
          <Col span={12}><Form.Item name="customer_name" label="客户姓名"><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="customer_contact" label="客户联系方式"><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="shipping_name" label="收件人"><Input /></Form.Item></Col>
          <Col span={6}><Form.Item name="shipping_phone" label="电话"><Input /></Form.Item></Col>
          <Col span={6}><Form.Item name="shipping_country" label="国家"><Input /></Form.Item></Col>
          <Col span={6}><Form.Item name="shipping_state" label="州/省"><Input /></Form.Item></Col>
          <Col span={6}><Form.Item name="shipping_city" label="城市"><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="shipping_address" label="地址"><Input /></Form.Item></Col>
          <Col span={6}><Form.Item name="shipping_zip" label="邮编"><Input /></Form.Item></Col>
          <Col span={6}><Form.Item name="remark" label="备注"><Input /></Form.Item></Col>
        </Row>
        <Divider>商品明细</Divider>
        {items.map((item, idx) => {
          const sku = skus.find((s: any) => s.id === item.sku_id)
          return (
            <Space key={idx} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
              <Select style={{ width: 200 }} placeholder="SKU" value={item.sku_id}
                onChange={(v) => {
                  const s = skus.find((x: any) => x.id === v)
                  const next = [...items]; next[idx] = { ...next[idx], sku_id: v, unit_price: s?.price ?? 0 }
                  setItems(next)
                }}
                options={skus.map((s: any) => ({ value: s.id, label: `${s.code} ${s.name}` }))} />
              <InputNumber min={1} placeholder="数量" value={item.quantity} style={{ width: 100 }}
                onChange={(v) => { const n = [...items]; n[idx] = { ...n[idx], quantity: v ?? 1 }; setItems(n) }} />
              <InputNumber min={0} precision={2} placeholder="单价" value={item.unit_price} style={{ width: 120 }}
                onChange={(v) => { const n = [...items]; n[idx] = { ...n[idx], unit_price: v ?? 0 }; setItems(n) }} />
              <InputNumber min={0} precision={2} placeholder="优惠" value={item.discount_amount} style={{ width: 100 }}
                onChange={(v) => { const n = [...items]; n[idx] = { ...n[idx], discount_amount: v ?? 0 }; setItems(n) }} />
              <Typography.Text type="secondary">{sku ? `${sku.name}` : ''}</Typography.Text>
              <Button type="text" danger onClick={() => setItems(items.filter((_, i) => i !== idx))}>删除</Button>
            </Space>
          )
        })}
        <Button type="dashed" block icon={<PlusOutlined />} onClick={addItem}>添加商品</Button>
      </Form>
    </Modal>
  )
}

// ---------------- 导入订单 ----------------

function ImportModal({ open, onClose, shops, currencies, onSaved }: any) {
  const [form] = Form.useForm()
  const [rows, setRows] = useState<any[]>([])
  const [result, setResult] = useState<any>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => { if (open) { setRows([]); setResult(null); form.resetFields() } }, [open])

  const importText = async (text: string) => {
    const lines = text.split('\n').map((l) => l.trim()).filter(Boolean)
    const parsed = lines.slice(1).map((line) => {
      const cols = line.split(/[\t,]/)
      return {
        source_order_no: cols[0]?.trim(), sku_code: cols[1]?.trim(),
        quantity: Number(cols[2]), unit_price: Number(cols[3]),
        discount_amount: Number(cols[4] ?? 0), customer_name: cols[5]?.trim() ?? '',
      }
    }).filter((r) => r.source_order_no && r.sku_code)
    setRows(parsed)
  }

  const submit = async () => {
    const values = await form.validateFields()
    if (!rows.length) { message.warning('没有可导入的行'); return }
    setSaving(true)
    try {
      const r = await api.post('/orders/import', {
        shop_id: values.shop_id, source_channel: values.source_channel ?? 'manual',
        currency_id: values.currency_id, rows,
      })
      setResult(r.data)
      message.success(`导入完成：新增 ${r.data.created_count}，跳过 ${r.data.skipped_count}，失败 ${r.data.error_count}`)
      if (r.data.error_count === 0) onSaved()
    } catch (e: any) { message.error(e.message) }
    finally { setSaving(false) }
  }

  return (
    <Modal open={open} title="批量导入订单" onCancel={onClose} width={760} onOk={submit} confirmLoading={saving}
      okText="执行导入" okButtonProps={{ disabled: !rows.length }}>
      <Form form={form} layout="vertical" initialValues={{ source_channel: 'manual' }}>
        <Row gutter={12}>
          <Col span={8}><Form.Item name="shop_id" label="导入店铺" rules={[{ required: true }]}>
            <Select options={shops.map((s: any) => ({ value: s.id, label: s.name }))} /></Form.Item></Col>
          <Col span={8}><Form.Item name="source_channel" label="来源渠道" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="currency_id" label="币种" rules={[{ required: true }]}>
            <Select options={currencies.map((c: any) => ({ value: c.id, label: c.code }))} /></Form.Item></Col>
        </Row>
        <Typography.Paragraph type="secondary">
          粘贴 CSV/TSV 文本，首行为表头，后续每行：来源单号, SKU编码, 数量, 单价, 优惠(可空), 客户名(可空)
        </Typography.Paragraph>
        <Input.TextArea rows={6} placeholder={'source_order_no\tsku_code\tquantity\tunit_price\tdiscount_amount\tcustomer_name\nAMZ-1\tCUP-BK\t2\t18.50\t0\tJohn'}
          onChange={(e) => importText(e.target.value)} />
        {rows.length > 0 && <Typography.Text>已解析 <b>{rows.length}</b> 行</Typography.Text>}
        {result && (
          <div style={{ marginTop: 12 }}>
            <Typography.Text type="success">新增 {result.created_count} / 跳过 {result.skipped_count} / 失败 {result.error_count}</Typography.Text>
            {result.errors?.map((e: any, i: number) => <div key={i}><Typography.Text type="danger">行 {e.rows.join(',')}：{e.message}</Typography.Text></div>)}
          </div>
        )}
      </Form>
    </Modal>
  )
}
