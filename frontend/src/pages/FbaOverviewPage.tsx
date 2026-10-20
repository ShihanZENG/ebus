import { useEffect, useMemo, useState } from 'react'
import { Card, Col, Row, Statistic, Table, Tag, Spin, message } from 'antd'
import api from '../api'

export default function FbaOverviewPage() {
  const [deliveries, setDeliveries] = useState<any[]>([])
  const [inventory, setInventory] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.get('/datalab/table/dwd_fba_delivery_orders', { params: { limit: 100 } }),
      api.get('/datalab/table/dwd_inventory', { params: { limit: 100 } }),
    ]).then(([d, inv]) => {
      setDeliveries(d.data.rows || [])
      setInventory(inv.data.rows || [])
    }).catch(() => message.error('FBA数据加载失败'))
      .finally(() => setLoading(false))
  }, [])

  const stats = useMemo(() => {
    const totalBoxes = deliveries.reduce((s, r) => s + Number(r.box_count || 0), 0)
    const totalFreight = deliveries.reduce((s, r) => s + Number(r.freight_cny || 0), 0)
    const shipped = deliveries.filter((r) => r.shipped_at).length
    const totalSku = inventory.length
    const totalQty = inventory.reduce((s, r) => s + Number(r.quantity || 0), 0)
    return { totalBoxes, totalFreight, shipped, totalSku, totalQty, total: deliveries.length }
  }, [deliveries, inventory])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />

  return (
    <>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}><Card><Statistic title="发货单总数" value={stats.total} /></Card></Col>
        <Col span={4}><Card><Statistic title="已发货" value={stats.shipped} valueStyle={{ color: '#3f8600' }} /></Card></Col>
        <Col span={4}><Card><Statistic title="总箱数" value={stats.totalBoxes} suffix="箱" /></Card></Col>
        <Col span={4}><Card><Statistic title="总运费" value={`¥${stats.totalFreight.toFixed(0)}`} /></Card></Col>
        <Col span={4}><Card><Statistic title="FBA SKU数" value={stats.totalSku} /></Card></Col>
        <Col span={4}><Card><Statistic title="FBA库存总量" value={stats.totalQty} suffix="件" valueStyle={{ color: '#1677ff' }} /></Card></Col>
      </Row>

      <Card title="最近发货单">
        <Table
          size="small"
          rowKey="id"
          dataSource={deliveries.slice(0, 10)}
          pagination={false}
          columns={[
            { title: '发货单号', dataIndex: 'delivery_order_no', width: 180 },
            { title: '目的地', dataIndex: 'destination', width: 140 },
            { title: '承运商', dataIndex: 'carrier', width: 120 },
            { title: '箱数', dataIndex: 'box_count', width: 70 },
            { title: '运费', dataIndex: 'freight_cny', render: (v: number) => `¥${Number(v).toFixed(0)}` },
            { title: '状态', dataIndex: 'status_text', width: 100, render: (v: string) => <Tag color="blue">{v || '—'}</Tag> },
            { title: '发货时间', dataIndex: 'shipped_at', width: 150 },
          ]}
        />
      </Card>
    </>
  )
}
