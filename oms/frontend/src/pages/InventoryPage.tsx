import { useEffect, useState } from 'react'
import { Table, Card, Tag, Space, Select, Button, Modal, Form, InputNumber, Input, message } from 'antd'
import { ReloadOutlined, PlusOutlined } from '@ant-design/icons'
import api from '../api'

export default function InventoryPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [warehouses, setWarehouses] = useState<any[]>([])
  const [skus, setSkus] = useState<any[]>([])
  const [whId, setWhId] = useState<string | undefined>()
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const p: any = { page, page_size: 20 }
      if (whId) p.warehouse_id = whId
      const r = await api.get('/inventory', { params: p })
      setRows(r.data.items); setTotal(r.data.total)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page, whId])
  useEffect(() => {
    api.get('/warehouses?page_size=100').then((r) => setWarehouses(r.data.items))
    api.get('/skus?page_size=100').then((r) => setSkus(r.data.items))
  }, [])

  const adjust = async () => {
    const v = await form.validateFields()
    if (!whId) { message.warning('请先选择仓库'); return }
    await api.post(`/warehouses/${whId}/inventory/adjust`, v)
    message.success('库存已调整'); setOpen(false); form.resetFields(); load()
  }

  return (
    <Card>
      <Space style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="仓库" style={{ width: 200 }} value={whId}
          onChange={(v) => { setWhId(v); setPage(1) }}
          options={warehouses.map((w) => ({ value: w.id, label: w.name }))} />
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setOpen(true) }}>库存调整/盘点</Button>
      </Space>
      <Table rowKey="id" loading={loading} dataSource={rows}
        columns={[
          { title: '仓库', dataIndex: 'warehouse_id', width: 100, render: (v: string) => warehouses.find((w) => w.id === v)?.name ?? v },
          { title: 'SKU', dataIndex: 'sku_code', width: 120 },
          { title: '在库数量', dataIndex: 'on_hand_qty', width: 100, align: 'right' },
          { title: '预留数量', dataIndex: 'reserved_qty', width: 100, align: 'right' },
          { title: '可售数量', dataIndex: 'available_qty', width: 100, align: 'right', render: (v: number) => <Tag color={v <= 0 ? 'red' : 'green'}>{v}</Tag> },
        ]}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />

      <Modal open={open} title="库存调整/盘点" onCancel={() => setOpen(false)} onOk={adjust}>
        <Form form={form} layout="vertical">
          <Form.Item name="sku_id" label="SKU" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label" options={skus.map((s) => ({ value: s.id, label: `${s.code} ${s.name}` }))} /></Form.Item>
          <Form.Item name="on_hand_qty" label="盘点后在库数量" rules={[{ required: true }]}>
            <InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="reason" label="调整原因" rules={[{ required: true }]}><Input /></Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
