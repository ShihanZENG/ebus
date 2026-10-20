import { useEffect, useState } from 'react'
import { Table, Card, Space, Select, Button, Input, Modal, Form, InputNumber, message } from 'antd'
import { ReloadOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../api'

export default function PaymentsPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [orders, setOrders] = useState<any[]>([])
  const [currencies, setCurrencies] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      // 收款记录通过订单详情聚合展示；此处取最近订单的收款流水
      const orderRes = await api.get('/orders', { params: { page, page_size: 20 } })
      const items: any[] = []
      for (const o of orderRes.data.items) {
        try {
          const d = await api.get(`/orders/${o.id}`)
          for (const pay of d.data.payments ?? []) {
            items.push({ ...pay, source_order_no: o.source_order_no, customer_name: o.customer_name })
          }
        } catch { /* 忽略 */ }
      }
      setRows(items); setTotal(items.length)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page])
  useEffect(() => {
    api.get('/orders?page_size=100').then((r) => setOrders(r.data.items))
    api.get('/dictionaries?kind=currency').then((r) => setCurrencies(r.data.items))
  }, [])

  const create = async () => {
    const v = await form.validateFields()
    await api.post(`/orders/${v.order_id}/payments`, {
      amount: v.amount, currency_id: v.currency_id, method: v.method ?? 'manual',
      source: v.source ?? 'manual', remark: v.remark ?? '',
    })
    message.success('收款登记成功')
    setOpen(false); form.resetFields(); load()
  }

  return (
    <Card>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setOpen(true) }}>登记收款</Button>
      </Space>
      <Table rowKey="id" loading={loading} dataSource={rows}
        columns={[
          { title: '订单号', dataIndex: 'source_order_no', width: 150 },
          { title: '客户', dataIndex: 'customer_name', width: 120 },
          { title: '金额', dataIndex: 'amount', width: 100, align: 'right' },
          { title: '币种', dataIndex: 'currency_id', width: 70 },
          { title: '方式', dataIndex: 'method', width: 100 },
          { title: '来源', dataIndex: 'source', width: 100 },
          { title: '收款时间', dataIndex: 'paid_at', width: 160, render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm') },
          { title: '备注', dataIndex: 'remark', ellipsis: true },
        ]}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />

      <Modal open={open} title="登记收款" onCancel={() => setOpen(false)} onOk={create}>
        <Form form={form} layout="vertical">
          <Form.Item name="order_id" label="订单" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label" options={orders.map((o) => ({ value: o.id, label: `${o.source_order_no}（${o.customer_name}）` }))} /></Form.Item>
          <Form.Item name="amount" label="收款金额" rules={[{ required: true }]}>
            <InputNumber min={0.01} precision={2} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="currency_id" label="币种" rules={[{ required: true }]}>
            <Select options={currencies.map((c) => ({ value: c.id, label: c.code }))} /></Form.Item>
          <Form.Item name="method" label="支付方式" initialValue="manual">
            <Select options={[{ value: 'paypal', label: 'PayPal' }, { value: 'card', label: '信用卡' }, { value: 'platform', label: '平台扣款' }, { value: 'manual', label: '手工登记' }]} /></Form.Item>
          <Form.Item name="source" label="来源" initialValue="manual">
            <Select options={[{ value: 'amazon', label: '亚马逊' }, { value: 'shopee', label: 'Shopee' }, { value: 'manual', label: '手工' }]} /></Form.Item>
          <Form.Item name="remark" label="备注"><Input /></Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
