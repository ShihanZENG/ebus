import { useEffect, useMemo, useState } from 'react'
import { Card, Table, Tag, Spin, message, Statistic, Row, Col } from 'antd'
import api from '../api'

export default function FbaOverseasPlansPage() {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/datalab/table/dwd_fba_delivery_orders', { params: { limit: 100 } })
      .then((r) => setRows(r.data.rows || []))
      .catch(() => message.error('加载失败'))
      .finally(() => setLoading(false))
  }, [])

  const stats = useMemo(() => {
    const total = rows.length
    const shipped = rows.filter((r) => r.shipped_at).length
    const received = rows.filter((r) => r.received_at).length
    const inTransit = shipped - received
    return { total, shipped, received, inTransit }
  }, [rows])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />

  return (
    <>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card><Statistic title="总发货单" value={stats.total} /></Card></Col>
        <Col span={6}><Card><Statistic title="已发货" value={stats.shipped} valueStyle={{ color: '#1677ff' }} /></Card></Col>
        <Col span={6}><Card><Statistic title="在途" value={stats.inTransit} valueStyle={{ color: '#faad14' }} /></Card></Col>
        <Col span={6}><Card><Statistic title="已收货" value={stats.received} valueStyle={{ color: '#3f8600' }} /></Card></Col>
      </Row>

      <Card title="海外仓发货计划">
        <Table
          size="small"
          rowKey="id"
          dataSource={rows}
          pagination={{ pageSize: 20 }}
          columns={[
            { title: '发货单号', dataIndex: 'delivery_order_no', width: 180 },
            { title: '目的地', dataIndex: 'destination', width: 140 },
            { title: '仓库', dataIndex: 'warehouse_name', width: 140 },
            { title: '承运商', dataIndex: 'carrier', width: 120 },
            { title: '追踪号', dataIndex: 'tracking_no', width: 140 },
            { title: '箱数', dataIndex: 'box_count', width: 60 },
            { title: '运费(¥)', dataIndex: 'freight_cny', width: 90, render: (v: number) => Number(v || 0).toFixed(0) },
            { title: '状态', dataIndex: 'status_text', width: 90,
              render: (v: string, r: any) => {
                if (r.received_at) return <Tag color="green">已收货</Tag>
                if (r.shipped_at) return <Tag color="orange">在途</Tag>
                return <Tag color="default">{v || '待发货'}</Tag>
              } },
            { title: '发货时间', dataIndex: 'shipped_at', width: 150 },
          ]}
        />
      </Card>
    </>
  )
}
