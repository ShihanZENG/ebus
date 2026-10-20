import { useEffect, useState } from 'react'
import { Table, Card, Tag, Space, Select, Button, Modal, Form, InputNumber, Input, message, Typography } from 'antd'
import { ReloadOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../api'

export default function InboundPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [warehouses, setWarehouses] = useState<any[]>([])
  const [suppliers, setSuppliers] = useState<any[]>([])
  const [skus, setSkus] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const [items, setItems] = useState<any[]>([])

  const load = async () => {
    setLoading(true)
    try {
      const r = await api.get('/inbound-orders', { params: { page, page_size: 20 } })
      setRows(r.data.items); setTotal(r.data.total)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page])
  useEffect(() => {
    api.get('/warehouses?page_size=100').then((r) => setWarehouses(r.data.items))
    api.get('/suppliers?page_size=100').then((r) => setSuppliers(r.data.items))
    api.get('/skus?page_size=100').then((r) => setSkus(r.data.items))
  }, [])

  const create = async () => {
    const v = await form.validateFields()
    if (!items.length) { message.warning('请添加入库明细'); return }
    await api.post('/inbound-orders', { ...v, items: items.map((i) => ({ sku_id: i.sku_id, quantity: i.quantity })) })
    message.success('入库单已创建，库存已增加')
    setOpen(false); form.resetFields(); setItems([]); load()
  }

  return (
    <Card>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setItems([]); setOpen(true) }}>创建入库单</Button>
      </Space>
      <Table rowKey="id" loading={loading} dataSource={rows}
        columns={[
          { title: '入库单号', dataIndex: 'id', width: 200, render: (v: string) => <Typography.Text code>{v.slice(0, 8)}</Typography.Text> },
          { title: '仓库', dataIndex: 'warehouse_id', width: 120, render: (v: string) => warehouses.find((w) => w.id === v)?.name ?? v },
          { title: '供应商', dataIndex: 'supplier_id', width: 120, render: (v: string) => v ? suppliers.find((s) => s.id === v)?.name ?? v : '-' },
          { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <Tag color={v === 'confirmed' ? 'green' : 'orange'}>{v === 'confirmed' ? '已入库' : v}</Tag> },
          { title: '备注', dataIndex: 'remark', ellipsis: true },
          { title: '创建时间', dataIndex: 'created_at', width: 150, render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm') },
        ]}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />

      <Modal open={open} title="创建入库单" onCancel={() => setOpen(false)} onOk={create} width={640}>
        <Form form={form} layout="vertical">
          <Form.Item name="warehouse_id" label="入库仓库" rules={[{ required: true }]}>
            <Select options={warehouses.map((w) => ({ value: w.id, label: w.name }))} /></Form.Item>
          <Form.Item name="supplier_id" label="供应商">
            <Select allowClear options={suppliers.map((s) => ({ value: s.id, label: s.name }))} /></Form.Item>
          <Form.Item name="remark" label="备注"><Input /></Form.Item>
        </Form>
        <Typography.Text strong>入库明细</Typography.Text>
        {items.map((it, idx) => (
          <Space key={idx} style={{ display: 'flex', marginTop: 8 }}>
            <Select style={{ width: 220 }} placeholder="SKU" value={it.sku_id} options={skus.map((s) => ({ value: s.id, label: `${s.code} ${s.name}` }))}
              onChange={(v) => { const n = [...items]; n[idx] = { ...n[idx], sku_id: v }; setItems(n) }} />
            <InputNumber min={1} placeholder="数量" value={it.quantity} style={{ width: 120 }}
              onChange={(v) => { const n = [...items]; n[idx] = { ...n[idx], quantity: v ?? 1 }; setItems(n) }} />
            <Button type="text" danger onClick={() => setItems(items.filter((_, i) => i !== idx))}>删除</Button>
          </Space>
        ))}
        <Button type="dashed" block style={{ marginTop: 8 }} onClick={() => setItems([...items, { quantity: 1 }])}>添加明细</Button>
      </Modal>
    </Card>
  )
}
