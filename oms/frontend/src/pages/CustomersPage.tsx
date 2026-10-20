import { useEffect, useState } from 'react'
import { Table, Card, Tag, Button, Space, Input, Drawer, Descriptions, Select, message, Typography, Empty } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../api'

const LEVEL = { normal: { color: 'default', label: '普通' }, vip: { color: 'gold', label: 'VIP' }, blacklist: { color: 'red', label: '黑名单' } }

export default function CustomersPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState<any>({})
  const [detail, setDetail] = useState<any>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [tagInput, setTagInput] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const p: any = { page, page_size: 20 }
      if (filters.q) p.q = filters.q
      if (filters.level) p.level = filters.level
      if (filters.tag) p.tag = filters.tag
      const r = await api.get('/customers', { params: p })
      setRows(r.data.items); setTotal(r.data.total)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page, filters])

  const openDetail = async (id: string) => {
    setDetailId(id)
    const r = await api.get(`/customers/${id}`)
    setDetail(r.data)
    setTagInput('')
  }

  const updateLevel = async (level: string) => {
    await api.patch(`/customers/${detail.id}`, { level })
    message.success('客户分级已更新')
    openDetail(detail.id); load()
  }

  const addTag = async () => {
    if (!tagInput.trim()) return
    const tags = [...(detail.tags ?? []), tagInput.trim()]
    await api.patch(`/customers/${detail.id}`, { tags })
    message.success('标签已添加')
    setTagInput('')
    openDetail(detail.id)
  }

  const removeTag = async (tag: string) => {
    await api.patch(`/customers/${detail.id}`, { tags: (detail.tags ?? []).filter((t: string) => t !== tag) })
    message.success('标签已移除')
    openDetail(detail.id)
  }

  return (
    <div>
      <Card>
        <Space style={{ marginBottom: 12 }}>
          <Input.Search allowClear placeholder="搜索客户号/姓名/联系方式" style={{ width: 260 }}
            onSearch={(v) => { setFilters((f: any) => ({ ...f, q: v || undefined })); setPage(1) }} />
          <Select allowClear placeholder="客户分级" style={{ width: 130 }} value={filters.level}
            onChange={(v) => { setFilters((f: any) => ({ ...f, level: v })); setPage(1) }}
            options={Object.entries(LEVEL).map(([v, s]) => ({ value: v, label: s.label }))} />
          <Input allowClear placeholder="按标签筛选" style={{ width: 130 }}
            onPressEnter={(e: any) => { setFilters((f: any) => ({ ...f, tag: e.target.value || undefined })); setPage(1) }} />
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        </Space>
        <Table rowKey="id" loading={loading} dataSource={rows}
          onRow={(r) => ({ onClick: () => openDetail(r.id), style: { cursor: 'pointer' } })}
          columns={[
            { title: '客户号', dataIndex: 'customer_no', width: 130 },
            { title: '姓名', dataIndex: 'name', width: 120 },
            { title: '联系方式', dataIndex: 'contact', width: 160, ellipsis: true },
            { title: '国家', dataIndex: 'country', width: 80 },
            { title: '分级', dataIndex: 'level', width: 90, render: (v: string) => <Tag color={LEVEL[v as keyof typeof LEVEL]?.color}>{LEVEL[v as keyof typeof LEVEL]?.label ?? v}</Tag> },
            { title: '标签', dataIndex: 'tags', width: 180, render: (v: string[]) => (v ?? []).map((t) => <Tag key={t}>{t}</Tag>) },
            { title: '订单数', dataIndex: 'order_count', width: 80, align: 'right' },
            { title: '来源渠道', dataIndex: 'source_channel', width: 100 },
          ]}
          pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />
      </Card>

      <Drawer width={640} open={!!detailId} onClose={() => setDetailId(null)} title={`客户详情 ${detail?.name ?? ''}`}>
        {!detail ? <Empty /> : (
          <div>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="客户号">{detail.customer_no}</Descriptions.Item>
              <Descriptions.Item label="姓名">{detail.name}</Descriptions.Item>
              <Descriptions.Item label="邮箱">{detail.email || '-'}</Descriptions.Item>
              <Descriptions.Item label="国家">{detail.country}</Descriptions.Item>
              <Descriptions.Item label="来源渠道">{detail.source_channel}</Descriptions.Item>
              <Descriptions.Item label="备注" span={2}>{detail.note || '-'}</Descriptions.Item>
            </Descriptions>

            <div style={{ marginTop: 16 }}>
              <Typography.Text strong>客户分级：</Typography.Text>
              <Space>
                {Object.entries(LEVEL).map(([v, s]) => (
                  <Button key={v} size="small" type={detail.level === v ? 'primary' : 'default'} onClick={() => updateLevel(v)}>{s.label}</Button>
                ))}
              </Space>
            </div>

            <div style={{ marginTop: 16 }}>
              <Typography.Text strong>标签：</Typography.Text>
              <Space style={{ marginLeft: 8, flexWrap: 'wrap' }}>
                {(detail.tags ?? []).map((t: string) => <Tag key={t} closable onClose={() => removeTag(t)}>{t}</Tag>)}
              </Space>
              <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                <Input placeholder="添加标签，如 vip / 高退货率" value={tagInput} onChange={(e) => setTagInput(e.target.value)} onPressEnter={addTag} style={{ width: 260 }} />
                <Button onClick={addTag}>添加</Button>
              </div>
            </div>

            {detail.total_spent?.length > 0 && <div style={{ marginTop: 16 }}>
              <Typography.Text strong>累计消费：</Typography.Text>
              {detail.total_spent.map((t: any) => <Tag key={t.currency_id} color="blue" style={{ marginLeft: 8 }}>{t.currency_id} {t.amount}</Tag>)}
            </div>}

            <div style={{ marginTop: 16 }}>
              <Typography.Title level={5}>最近订单</Typography.Title>
              <Table rowKey="id" size="small" pagination={false} dataSource={detail.orders ?? []}
                columns={[
                  { title: '来源单号', dataIndex: 'source_order_no' },
                  { title: '金额', dataIndex: 'grand_total', align: 'right' },
                  { title: '状态', dataIndex: 'status' },
                  { title: '时间', dataIndex: 'created_at', render: (v: string) => dayjs(v).format('YYYY-MM-DD') },
                ]} />
            </div>

            {detail.tickets?.length > 0 && <div style={{ marginTop: 16 }}>
              <Typography.Title level={5}>关联客服工单</Typography.Title>
              <Table rowKey="id" size="small" pagination={false} dataSource={detail.tickets}
                columns={[
                  { title: '工单号', dataIndex: 'ticket_no' },
                  { title: '主题', dataIndex: 'subject' },
                  { title: '状态', dataIndex: 'status' },
                ]} />
            </div>}
          </div>
        )}
      </Drawer>
    </div>
  )
}
