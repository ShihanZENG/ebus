import { useCallback, useEffect, useState } from 'react'
import { Alert, Card, Table, Button, Empty, Spin, Tag } from 'antd'
import { PrinterOutlined } from '@ant-design/icons'
import { request } from '../api/client'

export default function FbaLabelPrintingPage() {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    request<{ rows?: any[] }>('/datalab/table/dwd_listing_fba_dimensions', { params: { limit: 100 } })
      .then((r) => setRows(r.rows || []))
      .catch((reason) => { setRows([]); setError(reason instanceof Error ? reason.message : 'FBA 标签资料加载失败，请重试') })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <Card
      title="FBA 标签打印清单"
      extra={<Button type="primary" icon={<PrinterOutlined />} disabled aria-label="批量打印（功能尚未配置）" title="条码制式与标签规格尚未配置">批量打印</Button>}
    >
      <Alert type="info" showIcon message="当前显示标签资料清单；条码打印需配置条码制式和标签规格。" style={{ marginBottom: 16 }} />
      {error && <Alert role="alert" type="error" showIcon message="标签资料加载失败" description={error} action={<Button size="small" loading={loading} onClick={load}>重试</Button>} style={{ marginBottom: 16 }} />}
      {loading && <div role="status" aria-live="polite" style={{ padding: 24 }}><Spin /><span className="visually-hidden">正在加载 FBA 标签资料</span></div>}
      {!loading && !error && rows.length === 0 && <Empty description="没有可显示的 FBA 标签资料" />}
      {!loading && (error || rows.length === 0) ? null : <Table
        size="small"
        rowKey="_record_key"
        dataSource={rows}
        loading={loading}
        scroll={{ x: 1000 }}
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
            render: () => <Button type="link" size="small" icon={<PrinterOutlined />} disabled aria-label="打印标签（功能尚未配置）" title="条码制式与标签规格尚未配置">打印</Button> },
        ]}
      />}
    </Card>
  )
}
