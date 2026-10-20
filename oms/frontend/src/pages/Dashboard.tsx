import { useEffect, useState } from 'react'
import { Row, Col, Card, Statistic, Table, Tag, Space, Select, DatePicker, Empty } from 'antd'
import { ShoppingCartOutlined, CheckCircleOutlined, CarOutlined, CloseCircleOutlined, FileDoneOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { Dayjs } from 'dayjs'
import api from '../api'

const STATUS_COLOR: Record<string, string> = {
  draft: 'orange', approved: 'blue', shipping_requested: 'cyan',
  fulfilled: 'green', cancelled: 'red', after_sale: 'purple',
}
const STATUS_LABEL: Record<string, string> = {
  draft: '待审核', approved: '已审核', shipping_requested: '待发货',
  fulfilled: '已发货', cancelled: '已取消', after_sale: '售后中',
}

export default function Dashboard() {
  const [data, setData] = useState<any>(null)
  const [shops, setShops] = useState<any[]>([])
  const [shopId, setShopId] = useState<string | undefined>()
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const navigate = useNavigate()

  const load = () => {
    const params: any = {}
    if (shopId) params.shop_id = shopId
    if (range?.[0]) params.date_from = range[0].format('YYYY-MM-DD')
    if (range?.[1]) params.date_to = range[1].add(1, 'day').format('YYYY-MM-DD')
    api.get('/orders/summary', { params }).then((r) => setData(r.data)).catch(() => {})
  }

  useEffect(() => { load() }, [shopId, range])
  useEffect(() => {
    api.get('/shops?page_size=100').then((r) => setShops(r.data.items)).catch(() => {})
  }, [])

  const statusCounts = data?.status_counts ?? {}
  const total = data?.total_orders ?? 0

  const cards = [
    { title: '订单总数', value: total, icon: <ShoppingCartOutlined />, color: '#1677ff' },
    { title: '待审核', value: statusCounts.draft ?? 0, icon: <CheckCircleOutlined />, color: '#fa8c16', path: '/orders?status=draft' },
    { title: '待发货', value: statusCounts.shipping_requested ?? 0, icon: <CarOutlined />, color: '#13c2c2', path: '/orders?status=shipping_requested' },
    { title: '已发货', value: statusCounts.fulfilled ?? 0, icon: <FileDoneOutlined />, color: '#52c41a', path: '/orders?status=fulfilled' },
    { title: '已取消', value: statusCounts.cancelled ?? 0, icon: <CloseCircleOutlined />, color: '#ff4d4f', path: '/orders?status=cancelled' },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16, flexWrap: 'wrap' }}>
        <Select allowClear placeholder="筛选店铺" style={{ width: 220 }} value={shopId}
          onChange={(v) => setShopId(v)}
          options={shops.map((s) => ({ value: s.id, label: `${s.name}（${s.code}）` }))} />
        <DatePicker.RangePicker value={range} onChange={(v) => setRange(v)} />
      </Space>

      <Row gutter={16}>
        {cards.map((c) => (
          <Col span={4} key={c.title} xs={12} sm={8} md={4}>
            <Card hoverable={!!c.path} onClick={() => c.path && navigate(c.path)}
              style={{ borderRadius: 8, cursor: c.path ? 'pointer' : 'default' }}>
              <Statistic title={c.title} value={c.value} prefix={<span style={{ color: c.color, marginRight: 4 }}>{c.icon}</span>} />
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={10}>
          <Card title="币种金额汇总" size="small">
            {(data?.currency_totals ?? []).length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> :
              <Table rowKey="currency_id" pagination={false} size="small" dataSource={data?.currency_totals ?? []}
                columns={[
                  { title: '币种', dataIndex: 'currency_id' },
                  { title: '订单金额合计', dataIndex: 'amount', align: 'right' },
                ]} />}
          </Card>
        </Col>
        <Col span={14}>
          <Card title="最近订单" size="small">
            <Table rowKey="id" size="small" pagination={false} dataSource={data?.recent_orders ?? []}
              onRow={(r: any) => ({ onClick: () => navigate(`/orders?id=${r.id}`), style: { cursor: 'pointer' } })}
              columns={[
                { title: '来源单号', dataIndex: 'source_order_no' },
                { title: '客户', dataIndex: 'customer_name', ellipsis: true },
                { title: '金额', dataIndex: 'grand_total', align: 'right' },
                { title: '状态', dataIndex: 'status', render: (v) => <Tag color={STATUS_COLOR[v]}>{STATUS_LABEL[v]}</Tag> },
              ]} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
