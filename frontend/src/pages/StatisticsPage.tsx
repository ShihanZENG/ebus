import { useEffect, useMemo, useState } from 'react'
import { Card, Col, Row, Statistic, Table, Select, Spin, message } from 'antd'
import api from '../api'

export default function StatisticsPage() {
  const [storeDay, setStoreDay] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [store, setStore] = useState<string>('全部')

  useEffect(() => { load() }, [])

  const load = async () => {
    try {
      const [sales] = await Promise.all([
        api.get('/datalab/table/dws_sales_store_day', { params: { limit: 100 } }),
      ])
      setStoreDay(sales.data.rows || [])
    } catch {
      message.error('数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  const filtered = useMemo(() =>
    store === '全部' ? storeDay : storeDay.filter((r) => r.store_name === store),
  [storeDay, store])

  const stores = useMemo(() =>
    ['全部', ...Array.from(new Set(storeDay.map((r) => r.store_name)))],
  [storeDay])

  const totals = useMemo(() => {
    const orders = filtered.reduce((s, r) => s + (r.order_count || 0), 0)
    const amount = filtered.reduce((s, r) => s + Number(r.order_amount || 0), 0)
    const refund = filtered.reduce((s, r) => s + Number(r.refund_amount || 0), 0)
    return { orders, amount, refund, net: amount - refund }
  }, [filtered])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />

  return (
    <>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card><Statistic title="总订单数" value={totals.orders} /></Card></Col>
        <Col span={6}><Card><Statistic title="总销售额" value={totals.amount.toFixed(2)} prefix="$" /></Card></Col>
        <Col span={6}><Card><Statistic title="退款金额" value={totals.refund.toFixed(2)} prefix="$" valueStyle={{ color: '#cf1322' }} /></Card></Col>
        <Col span={6}><Card><Statistic title="净销售额" value={totals.net.toFixed(2)} prefix="$" valueStyle={{ color: '#3f8600' }} /></Card></Col>
      </Row>

      <Card
        title="每日销售明细"
        extra={<Select value={store} onChange={setStore} style={{ width: 200 }} options={stores.map((s) => ({ label: s, value: s }))} />}
      >
        <Table
          size="small"
          rowKey={(_, i) => i ?? 0}
          dataSource={filtered.slice().reverse()}
          pagination={{ pageSize: 20 }}
          columns={[
            { title: '日期', dataIndex: 'business_date', width: 110 },
            { title: '店铺', dataIndex: 'store_name', width: 180 },
            { title: '平台', dataIndex: 'platform', width: 100 },
            { title: '订单数', dataIndex: 'order_count', width: 90 },
            { title: '订单金额', dataIndex: 'order_amount', render: (v: number) => `$${Number(v).toFixed(2)}` },
            { title: '已付金额', dataIndex: 'paid_amount', render: (v: number) => `$${Number(v).toFixed(2)}` },
            { title: '退款', dataIndex: 'refund_amount', render: (v: number) => `$${Number(v).toFixed(2)}` },
          ]}
        />
      </Card>
    </>
  )
}
