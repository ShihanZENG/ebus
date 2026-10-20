import { useEffect, useState } from 'react'
import { Table, Card, Tag, Space, Select, DatePicker, Button, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../api'

export default function AuditLogsPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState<any>({})

  const load = async () => {
    setLoading(true)
    try {
      const p: any = { page, page_size: 20 }
      if (filters.resource) p.resource = filters.resource
      if (filters.date_from) p.date_from = filters.date_from
      if (filters.date_to) p.date_to = filters.date_to
      const r = await api.get('/audit-logs', { params: p })
      setRows(r.data.items); setTotal(r.data.total)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page, filters])
  return (
    <Card>
      <Space style={{ marginBottom: 12, flexWrap: 'wrap' }}>
        <Select allowClear placeholder="资源类型" style={{ width: 180 }} value={filters.resource}
          onChange={(v) => { setFilters((f: any) => ({ ...f, resource: v })); setPage(1) }}
          options={['orders', 'payment_records', 'after_sales', 'refunds', 'customer_tickets', 'customers',
            'inventory', 'shipments', 'listings', 'shops', 'products', 'skus', 'users', 'roles', 'dictionaries', 'auth'].map((r) => ({ value: r, label: r }))} />
        <DatePicker.RangePicker onChange={(v) => {
          setFilters((f: any) => ({ ...f,
            date_from: v?.[0]?.format('YYYY-MM-DD'), date_to: v?.[1] ? v[1].add(1, 'day').format('YYYY-MM-DD') : undefined }))
          setPage(1)
        }} />
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Table rowKey="id" loading={loading} dataSource={rows} scroll={{ x: 900 }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 160, render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss') },
          { title: '操作人', dataIndex: 'actor_id', width: 100, render: (v: string) => <Tag>{v.slice(0, 8)}</Tag> },
          { title: '资源', dataIndex: 'resource', width: 130, render: (v: string) => <Tag color="blue">{v}</Tag> },
          { title: '动作', dataIndex: 'action', width: 120, render: (v: string) => <Tag color="purple">{v}</Tag> },
          { title: '记录ID', dataIndex: 'record_id', width: 110, render: (v: string) => <Typography.Text code>{v.slice(0, 8)}</Typography.Text> },
          { title: '变更前', dataIndex: 'before', ellipsis: true, render: (v: any) => v ? JSON.stringify(v) : '-' },
          { title: '变更后', dataIndex: 'after', ellipsis: true, render: (v: any) => v ? JSON.stringify(v) : '-' },
        ]}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />
    </Card>
  )
}
