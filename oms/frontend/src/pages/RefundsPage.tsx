import { useEffect, useState } from 'react'
import { Table, Card, Tag, Space, Select, Button, Modal, Form, InputNumber, Input, message } from 'antd'
import { ReloadOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../api'

const STATUS = {
  pending: { color: 'orange', label: '待审批' },
  approved: { color: 'blue', label: '已批准' },
  executed: { color: 'green', label: '已执行' },
  rejected: { color: 'red', label: '已拒绝' },
}

export default function RefundsPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<string | undefined>()
  const [afterSales, setAfterSales] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const p: any = { page, page_size: 20 }
      if (status) p.status = status
      const r = await api.get('/refunds', { params: p })
      setRows(r.data.items); setTotal(r.data.total)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page, status])
  useEffect(() => {
    api.get('/after-sales?status=completed&page_size=100').then((r) => setAfterSales(r.data.items))
  }, [])

  const transition = (id: string, next: string, channelTxn = '') => {
    Modal.confirm({
      title: `确认退款状态变更为「${STATUS[next as keyof typeof STATUS]?.label}」？`,
      onOk: async () => {
        await api.post(`/refunds/${id}/status`, { status: next, channel_txn_no: channelTxn })
        message.success('已更新'); load()
      },
    })
  }

  const create = async () => {
    const v = await form.validateFields()
    await api.post('/refunds', v)
    message.success('退款记录已创建')
    setOpen(false); form.resetFields(); load()
  }

  return (
    <Card>
      <Space style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="退款状态" style={{ width: 140 }} value={status}
          onChange={(v) => { setStatus(v); setPage(1) }}
          options={Object.entries(STATUS).map(([v, s]) => ({ value: v, label: s.label }))} />
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setOpen(true) }}>发起退款</Button>
      </Space>
      <Table rowKey="id" loading={loading} dataSource={rows}
        columns={[
          { title: '退款单号', dataIndex: 'refund_no', width: 160 },
          { title: '订单号', dataIndex: 'order_no', width: 150 },
          { title: '客户', dataIndex: 'customer', width: 120 },
          { title: '金额', dataIndex: 'amount', width: 90, align: 'right' },
          { title: '币种', dataIndex: 'currency_id', width: 70 },
          { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <Tag color={STATUS[v as keyof typeof STATUS]?.color}>{STATUS[v as keyof typeof STATUS]?.label ?? v}</Tag> },
          { title: '渠道', dataIndex: 'channel', width: 100 },
          { title: '流水号', dataIndex: 'channel_txn_no', width: 130 },
          { title: '原因', dataIndex: 'reason', ellipsis: true },
          { title: '创建时间', dataIndex: 'created_at', width: 150, render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm') },
          { title: '操作', key: 'op', width: 200, render: (_: any, r: any) => (
            <Space>
              {r.status === 'pending' && <Button size="small" type="primary" onClick={() => transition(r.id, 'approved')}>批准</Button>}
              {r.status === 'pending' && <Button size="small" danger onClick={() => transition(r.id, 'rejected')}>拒绝</Button>}
              {r.status === 'approved' && <Button size="small" onClick={() => {
                let txn = ''
                Modal.confirm({
                  title: '执行退款',
                  content: <Input placeholder="渠道交易流水号" onChange={(e) => (txn = e.target.value)} />,
                  onOk: async () => { await api.post(`/refunds/${r.id}/status`, { status: 'executed', channel_txn_no: txn }); message.success('退款已执行'); load() },
                })
              }}>执行退款</Button>}
            </Space>
          )},
        ]}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />

      <Modal open={open} title="发起退款" onCancel={() => setOpen(false)} onOk={create}>
        <Form form={form} layout="vertical">
          <Form.Item name="after_sale_id" label="关联售后申请" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label" options={afterSales.map((a) => ({ value: a.id, label: `${a.order_no}（${a.reason}）` }))} /></Form.Item>
          <Form.Item name="amount" label="退款金额" rules={[{ required: true }]}>
            <InputNumber min={0.01} precision={2} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="reason" label="原因" rules={[{ required: true }]}><Input.TextArea rows={3} /></Form.Item>
          <Form.Item name="channel" label="退款渠道" initialValue="manual">
            <Select options={[{ value: 'paypal', label: 'PayPal' }, { value: 'stripe', label: 'Stripe' }, { value: 'platform', label: '平台原路退回' }, { value: 'manual', label: '线下处理' }]} /></Form.Item>
          <Form.Item name="channel_txn_no" label="渠道交易流水号"><Input /></Form.Item>
          <Form.Item name="remark" label="备注"><Input /></Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
