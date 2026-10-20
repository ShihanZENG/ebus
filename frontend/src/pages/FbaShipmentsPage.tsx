import { useEffect, useState } from 'react'
import { Card, Table, Spin, message } from 'antd'
import api from '../api'

export default function FbaShipmentsPage() {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/datalab/table/dwd_fba_local_shipments', { params: { limit: 100 } })
      .then((r) => setRows(r.data.rows || []))
      .catch(() => message.error('加载失败'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />

  return (
    <Card title="FBA 货件追踪">
      <Table
        size="small"
        rowKey="_record_key"
        dataSource={rows}
        pagination={{ pageSize: 20 }}
        columns={[
          { title: '记录ID', dataIndex: '_record_key', width: 80 },
          { title: '发货单ID', dataIndex: 'delivery_id', width: 100 },
          { title: '货件记录ID', dataIndex: 'shipment_record_id', width: 120 },
        ]}
      />
    </Card>
  )
}
