import { useEffect, useState } from 'react'
import { Alert, Descriptions, Table, Timeline, Button, Space } from 'antd'
import api from '../api'

const labels: Record<string, string> = { Created: '已创建', Confirmed: '已确认', Cancelled: '已取消', Paid: '已付款', Unpaid: '未付款', PartiallyPaid: '部分付款', Refunded: '已退款', PartiallyRefunded: '部分退款', Picking: '拣货中', Shipped: '已发货', Unallocated: '未分配', Restricted: '无查看权限', Unknown: '待核实' }
export default function OrderLifecycle({ orderId }: { orderId: string }) {
  const [data, setData] = useState<any>()
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    setData(undefined); setError('')
    api.get(`/orders/${orderId}/lifecycle`).then(r => { if (active) setData(r.data) })
      .catch(() => { if (active) setError('订单状态与事件加载失败，请重试') })
    return () => { active = false }
  }, [orderId, revision])
  return <Space direction="vertical" style={{ width: '100%', marginTop: 16 }}>
    <Button onClick={() => setRevision(x => x + 1)}>刷新生命周期</Button>
    {error && <Alert type="error" message={error} />}
    {data && <>
      <Descriptions bordered column={1} size="small" title="订单、支付与履约状态">
        <Descriptions.Item label="订单状态">{labels[data.order_status] ?? data.order_status}</Descriptions.Item>
        <Descriptions.Item label="支付状态">{labels[data.payment_status] ?? data.payment_status}</Descriptions.Item>
        <Descriptions.Item label="履约状态">{labels[data.fulfillment_status] ?? data.fulfillment_status}</Descriptions.Item>
      </Descriptions>
      <Alert type="info" message={data.limitations} />
      <h4>订单事件时间线</h4>
      <Timeline items={data.events.map((e: any) => ({ key: e.id, children: <><b>{e.action}</b> · {e.from_status || '—'} → {e.to_status || '—'}<div>{e.source} · {e.occurred_at} UTC</div></> }))} />
      <h4>库存预留与变更记录</h4>
      <Table rowKey="id" size="small" dataSource={data.inventory_records} pagination={{ pageSize: 5 }} scroll={{ x: 480 }} columns={[
        { title: '类型', dataIndex: 'type' }, { title: 'SKU', dataIndex: 'sku_id', ellipsis: true },
        { title: '预留变化', dataIndex: 'reserved_delta' }, { title: '在库变化', dataIndex: 'on_hand_delta' },
      ]} />
    </>}
  </Space>
}
