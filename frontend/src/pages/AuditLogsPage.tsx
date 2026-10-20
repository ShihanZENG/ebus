import { useCallback, useEffect, useState } from 'react'
import { Card, Popover, Select, Space, Table, Tag, Typography, Button, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { request } from '../api/client'

interface AuditLog {
  id: string
  actor_id: string
  resource: string
  record_id: string
  action: string
  before: unknown
  after: unknown
  created_at: string
}

interface ListResult {
  items: AuditLog[]
  total: number
}

const ACTION_COLOR: Record<string, string> = {
  create: 'green',
  update: 'blue',
  approve: 'cyan',
  submit: 'cyan',
  reject: 'red',
  cancel: 'default',
  login: 'purple',
  logout: 'purple',
}

function JsonCell({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <Typography.Text type="secondary">—</Typography.Text>
  const text = JSON.stringify(value, null, 2)
  return (
    <Popover content={<pre style={{ maxWidth: 460, maxHeight: 320, overflow: 'auto', margin: 0 }}>{text}</pre>}>
      <Button type="link" size="small">
        查看
      </Button>
    </Popover>
  )
}

/** 操作日志：所有写操作的留痕，支持按资源类型筛选并查看变更前后快照。 */
export default function AuditLogsPage() {
  const [rows, setRows] = useState<AuditLog[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [resource, setResource] = useState<string>()
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await request<ListResult>('/audit-logs', {
        params: { page, page_size: pageSize, resource },
      })
      setRows(res.items)
      setTotal(res.total)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, resource])

  useEffect(() => {
    void load()
  }, [load])

  const columns: ColumnsType<AuditLog> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => new Date(v).toLocaleString('zh-CN', { hour12: false }),
    },
    { title: '资源', dataIndex: 'resource', width: 150 },
    {
      title: '动作',
      dataIndex: 'action',
      width: 110,
      render: (v: string) => <Tag color={ACTION_COLOR[v] ?? 'default'}>{v}</Tag>,
    },
    {
      title: '记录',
      dataIndex: 'record_id',
      width: 220,
      render: (v: string) => (
        <Typography.Text copyable={{ text: v }} style={{ fontSize: 12 }}>
          {v.slice(0, 12)}…
        </Typography.Text>
      ),
    },
    { title: '变更前', dataIndex: 'before', width: 90, render: (v: unknown) => <JsonCell value={v} /> },
    { title: '变更后', dataIndex: 'after', width: 90, render: (v: unknown) => <JsonCell value={v} /> },
  ]

  return (
    <Card
      title={
        <Space direction="vertical" size={0}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>操作日志</span>
          <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
            记录所有新增、修改、审核与登录行为，可回溯每条数据的变更前后值
          </Typography.Text>
        </Space>
      }
      extra={
        <Space>
          <Select
            allowClear
            style={{ width: 200 }}
            placeholder="按资源筛选"
            value={resource}
            onChange={(v) => {
              setResource(v)
              setPage(1)
            }}
            options={[
              { label: '订单', value: 'orders' },
              { label: '采购单', value: 'purchase_orders' },
              { label: '库存', value: 'inventory' },
              { label: '商品', value: 'products' },
              { label: 'SKU', value: 'skus' },
              { label: '店铺', value: 'shops' },
              { label: '仓库', value: 'warehouses' },
              { label: '供应商', value: 'suppliers' },
              { label: '登录', value: 'auth' },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            刷新
          </Button>
        </Space>
      }
    >
      <Table<AuditLog>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={rows}
        columns={columns}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p)
            setPageSize(ps)
          },
        }}
      />
    </Card>
  )
}
