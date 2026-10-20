import { useEffect, useState } from 'react'
import { Card, Table, Tag, Spin, message } from 'antd'
import api from '../api'

export default function FbaReconciliationPage() {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/datalab/table/dwd_fba_receipts', { params: { limit: 100 } })
      .then((r) => setRows(r.data.rows || []))
      .catch(() => message.error('加载失败'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />

  return (
    <Card title="FBA 收货对账">
      <Table
        size="small"
        rowKey="id"
        dataSource={rows}
        pagination={{ pageSize: 20 }}
        columns={[
          { title: '收货ID', dataIndex: 'id', width: 80 },
          { title: '发货单ID', dataIndex: 'delivery_id', width: 90 },
          { title: 'Amazon收货单号', dataIndex: 'request_key', width: 200 },
          { title: '收货数量', dataIndex: 'quantity', width: 90 },
          { title: '收货时间', dataIndex: 'created_at', width: 180 },
          { title: '状态', dataIndex: 'request_key', width: 100,
            render: (v: string) => <Tag color={v?.includes('PARTIAL') ? 'orange' : 'green'}>{v?.includes('PARTIAL') ? '部分收货' : '完整收货'}</Tag> },
        ]}
      />
    </Card>
  )
}
