import { useEffect, useState } from 'react'
import { Table, Card, Tag, Space, Select, Button } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../api'

const STATUS = {
  success: { color: 'green', label: '成功' },
  failed: { color: 'red', label: '失败' },
  partial: { color: 'orange', label: '部分成功' },
}

export default function SyncLogsPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [shops, setShops] = useState<any[]>([])
  const [shopId, setShopId] = useState<string | undefined>()

  const load = async () => {
    setLoading(true)
    try {
      const p: any = { page, page_size: 20 }
      if (shopId) p.shop_id = shopId
      const r = await api.get('/channel-sync-logs', { params: p })
      setRows(r.data.items); setTotal(r.data.total)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page, shopId])
  useEffect(() => { api.get('/shops?page_size=100').then((r) => setShops(r.data.items)) }, [])

  return (
    <Card>
      <Space style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="店铺" style={{ width: 200 }} value={shopId}
          onChange={(v) => { setShopId(v); setPage(1) }}
          options={shops.map((s) => ({ value: s.id, label: s.name }))} />
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Table rowKey="id" loading={loading} dataSource={rows}
        columns={[
          { title: '店铺', dataIndex: 'shop_name', width: 150, ellipsis: true },
          { title: '渠道', dataIndex: 'source_channel', width: 100, render: (v: string) => <Tag>{v}</Tag> },
          { title: '同步方式', dataIndex: 'sync_type', width: 100, render: (v: string) => v === 'api' ? '接口拉取' : '文件导入' },
          { title: '状态', dataIndex: 'status', width: 100, render: (v: string) => <Tag color={STATUS[v as keyof typeof STATUS]?.color}>{STATUS[v as keyof typeof STATUS]?.label ?? v}</Tag> },
          { title: '总行数', dataIndex: 'total_rows', width: 80, align: 'right' },
          { title: '新增', dataIndex: 'created_count', width: 80, align: 'right' },
          { title: '跳过', dataIndex: 'skipped_count', width: 80, align: 'right' },
          { title: '失败', dataIndex: 'error_count', width: 80, align: 'right' },
          { title: '消息', dataIndex: 'message', ellipsis: true },
          { title: '时间', dataIndex: 'created_at', width: 150, render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm') },
        ]}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />
    </Card>
  )
}
