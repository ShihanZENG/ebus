import { useEffect, useState } from 'react'
import { Card, Table, Tag, Spin, message } from 'antd'
import api from '../api'

export default function FbaShippingOrdersPage() {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/datalab/table/dwd_fba_delivery_orders', { params: { limit: 100 } })
      .then((r) => setRows(r.data.rows || []))
      .catch(() => message.error('加载失败'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />

  return (
    <Card title="FBA 发货单">
      <Table
        size="small"
        rowKey="id"
        dataSource={rows}
        pagination={{ pageSize: 20 }}
        columns={[
          { title: '发货单号', dataIndex: 'delivery_order_no', width: 180 },
          { title: '店铺', dataIndex: 'store_name', width: 160 },
          { title: '目的地', dataIndex: 'destination', width: 130 },
          { title: '承运商', dataIndex: 'carrier', width: 110 },
          { title: '追踪号', dataIndex: 'tracking_no', width: 140 },
          { title: '箱数', dataIndex: 'box_count', width: 60 },
          { title: '毛重(kg)', dataIndex: 'gross_weight_kg', width: 90 },
          { title: '体积(CBM)', dataIndex: 'chargeable_cbm', width: 90 },
          { title: '运费(¥)', dataIndex: 'freight_cny', width: 90, render: (v: number) => Number(v || 0).toFixed(0) },
          { title: '状态', dataIndex: 'status_text', width: 90, render: (v: string) => <Tag color="blue">{v || '—'}</Tag> },
          { title: '发货时间', dataIndex: 'shipped_at', width: 150 },
          { title: '收货时间', dataIndex: 'received_at', width: 150 },
        ]}
      />
    </Card>
  )
}
