import { useEffect, useState } from 'react'
import { Card, Table, Button, Spin, message, Tag } from 'antd'
import { PrinterOutlined } from '@ant-design/icons'
import api from '../api'

export default function FbaLabelPrintingPage() {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/datalab/table/dwd_listing_fba_dimensions', { params: { limit: 100 } })
      .then((r) => setRows(r.data.rows || []))
      .catch(() => message.error('加载失败'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />

  return (
    <Card
      title="FBA 标签打印清单"
      extra={<Button type="primary" icon={<PrinterOutlined />} onClick={() => message.info('打印功能开发中')}>批量打印</Button>}
    >
      <Table
        size="small"
        rowKey="_record_key"
        dataSource={rows}
        pagination={{ pageSize: 20 }}
        columns={[
          { title: '卖家SKU', dataIndex: 'seller_sku', width: 140 },
          { title: '产品名称', dataIndex: 'spu_name', width: 160 },
          { title: 'FNSKU', dataIndex: 'fnsku', width: 160, render: (v: string) => <Tag color="blue">{v}</Tag> },
          { title: 'ASIN', dataIndex: 'asin', width: 140 },
          { title: '父ASIN', dataIndex: 'parent_asin', width: 140 },
          { title: 'SPU', dataIndex: 'spu', width: 120 },
          { title: '分类', dataIndex: 'attributes', width: 200,
            render: (v: string) => { try { return JSON.parse(v)[0] || '—' } catch { return v || '—' } } },
          { title: '更新时间', dataIndex: 'updated_at', width: 150 },
          { title: '操作', key: 'action', width: 80,
            render: () => <Button type="link" size="small" icon={<PrinterOutlined />} onClick={() => message.info('打印功能开发中')}>打印</Button> },
        ]}
      />
    </Card>
  )
}
