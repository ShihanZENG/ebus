import { useEffect, useState } from 'react'
import { Card, Table, Spin, message, Statistic, Row, Col } from 'antd'
import api from '../api'

export default function FbaInventoryPage() {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/datalab/table/dwd_inventory', { params: { limit: 100 } })
      .then((r) => setRows(r.data.rows || []))
      .catch(() => message.error('加载失败'))
      .finally(() => setLoading(false))
  }, [])

  const totalQty = rows.reduce((s, r) => s + Number(r.quantity || 0), 0)
  const totalAvail = rows.reduce((s, r) => s + Number(r.available || 0), 0)
  const totalReserved = rows.reduce((s, r) => s + Number(r.reserved || 0), 0)

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />

  return (
    <>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}><Card><Statistic title="在库总量" value={totalQty} suffix="件" /></Card></Col>
        <Col span={8}><Card><Statistic title="可售" value={totalAvail} suffix="件" valueStyle={{ color: '#3f8600' }} /></Card></Col>
        <Col span={8}><Card><Statistic title="预留" value={totalReserved} suffix="件" valueStyle={{ color: '#cf1322' }} /></Card></Col>
      </Row>
      <Card title="FBA 库存明细">
        <Table
          size="small"
          rowKey="id"
          dataSource={rows}
          pagination={{ pageSize: 20 }}
          columns={[
            { title: 'SKU', dataIndex: 'sku', width: 140 },
            { title: '仓库', dataIndex: 'warehouse_name', width: 160 },
            { title: '批次号', dataIndex: 'batch_no', width: 140 },
            { title: '在库', dataIndex: 'quantity', width: 70 },
            { title: '可售', dataIndex: 'available', width: 70 },
            { title: '预留', dataIndex: 'reserved', width: 70 },
            { title: 'FNSKU', dataIndex: 'fnsku', width: 140 },
          ]}
        />
      </Card>
    </>
  )
}
