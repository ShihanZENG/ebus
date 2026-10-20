import { useEffect, useState } from 'react'
import { Table, Card, Tag, Button, Space, Select, Modal, Form, Input, InputNumber, message, Row, Col, Statistic } from 'antd'
import { CheckOutlined, CloseOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../api'

const TYPE_LABEL = { refund: '退款', return: '退货' }
const STATUS = {
  pending: { color: 'orange', label: '待处理' },
  completed: { color: 'green', label: '已完成' },
  rejected: { color: 'red', label: '已拒绝' },
}

export default function AfterSalesPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<string | undefined>()
  const [stats, setStats] = useState<any>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [orders, setOrders] = useState<any[]>([])
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const p: any = { page, page_size: 20 }
      if (status) p.status = status
      const r = await api.get('/after-sales', { params: p })
      setRows(r.data.items); setTotal(r.data.total)
      const s = await api.get('/after-sales/stats')
      setStats(s.data)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page, status])
  useEffect(() => {
    api.get('/orders?status=shipping_requested&page_size=100').then((r) => setOrders(r.data.items))
  }, [])

  const resolve = (id: string, to: 'completed' | 'rejected') => {
    Modal.confirm({
      title: to === 'completed' ? '确认完成售后？' : '确认拒绝售后？',
      content: to === 'completed' ? '完成后退款可继续流转' : '拒绝后该售后申请关闭',
      onOk: async () => {
        await api.post(`/after-sales/${id}/resolve`, { status: to })
        message.success('已处理')
        load()
      },
    })
  }

  const create = async () => {
    const v = await form.validateFields()
    await api.post(`/orders/${v.order_id}/after-sales`, {
      type: v.type, reason: v.reason, quantity: v.quantity ?? 0, amount: v.amount ?? 0, remark: v.remark ?? '',
    })
    message.success('售后申请已创建')
    setCreateOpen(false); form.resetFields(); load()
  }

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small"><Statistic title="售后申请总数" value={stats?.by_type?.reduce((s: number, t: any) => s + t.count, 0) ?? 0} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="退款申请" value={stats?.by_type?.find((t: any) => t.type === 'refund')?.count ?? 0} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="退货申请" value={stats?.by_type?.find((t: any) => t.type === 'return')?.count ?? 0} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="待处理" value={stats?.by_status?.find((t: any) => t.status === 'pending')?.count ?? 0} /></Card></Col>
      </Row>

      <Card>
        <Space style={{ marginBottom: 12 }}>
          <Select allowClear placeholder="售后状态" style={{ width: 140 }} value={status}
            onChange={(v) => { setStatus(v); setPage(1) }}
            options={Object.entries(STATUS).map(([v, s]) => ({ value: v, label: s.label }))} />
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建售后申请</Button>
        </Space>
        <Table rowKey="id" loading={loading} dataSource={rows}
          columns={[
            { title: '订单号', dataIndex: 'order_no', width: 150 },
            { title: '客户', dataIndex: 'customer', width: 130 },
            { title: '类型', dataIndex: 'type', width: 90, render: (v: string) => <Tag color={v === 'refund' ? 'blue' : 'cyan'}>{TYPE_LABEL[v as keyof typeof TYPE_LABEL]}</Tag> },
            { title: '原因', dataIndex: 'reason', ellipsis: true },
            { title: '数量', dataIndex: 'quantity', width: 70, align: 'right' },
            { title: '金额', dataIndex: 'amount', width: 90, align: 'right' },
            { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <Tag color={STATUS[v as keyof typeof STATUS].color}>{STATUS[v as keyof typeof STATUS].label}</Tag> },
            { title: '创建时间', dataIndex: 'created_at', width: 150, render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm') },
            { title: '操作', key: 'op', width: 160, render: (_: any, r: any) => r.status === 'pending' && (
              <Space>
                <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => resolve(r.id, 'completed')}>完成</Button>
                <Button size="small" danger icon={<CloseOutlined />} onClick={() => resolve(r.id, 'rejected')}>拒绝</Button>
              </Space>
            )},
          ]}
          pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />
      </Card>

      <Modal open={createOpen} title="新建售后申请" onCancel={() => setCreateOpen(false)} onOk={create}>
        <Form form={form} layout="vertical" initialValues={{ type: 'refund', quantity: 1, amount: 0 }}>
          <Form.Item name="order_id" label="关联订单" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label"
              options={orders.map((o: any) => ({ value: o.id, label: `${o.source_order_no}（${o.customer_name}）` }))} />
          </Form.Item>
          <Form.Item name="type" label="类型" rules={[{ required: true }]}>
            <Select options={[{ value: 'refund', label: '退款' }, { value: 'return', label: '退货' }]} />
          </Form.Item>
          <Form.Item name="reason" label="原因" rules={[{ required: true }]}>
            <Input.TextArea rows={3} placeholder="如：商品质量问题 / 客户不想要了 / 发错货" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="quantity" label="退货数量"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="amount" label="退款金额"><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Form.Item name="remark" label="备注"><Input /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
