import { useEffect, useState } from 'react'
import { Card, Table, Tabs, Spin, message, Row, Col, Statistic, Tag } from 'antd'
import api from '../api'

export default function Dashboard() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    load()
  }, [])

  const load = async () => {
    try {
      const res = await api.get('/datalab/overview')
      setData(res.data)
    } catch {
      message.error('数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />

  const salesRows = data?.sales_daily?.rows || []
  const invRows = data?.inventory_health?.rows || []
  const poRows = data?.purchase_open?.rows || []
  const repRows = data?.replenishment?.rows || []
  const dqRows = data?.data_quality?.rows || []

  // 汇总销售数据
  const totalOrders = salesRows.reduce((s: number, r: any) => s + (r.order_count || 0), 0)
  const totalAmount = salesRows.reduce((s: number, r: any) => s + (r.net_receipts || 0), 0)
  const totalRefund = salesRows.reduce((s: number, r: any) => s + (r.refund_amount || 0), 0)

  return (
    <>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card><Statistic title="订单数(近30天)" value={totalOrders} /></Card></Col>
        <Col span={6}><Card><Statistic title="净销售额(USD)" value={totalAmount.toFixed(2)} precision={2} prefix="$" /></Card></Col>
        <Col span={6}><Card><Statistic title="退款金额(USD)" value={totalRefund.toFixed(2)} precision={2} prefix="$" valueStyle={{ color: '#cf1322' }} /></Card></Col>
        <Col span={6}><Card><Statistic title="待处理采购单" value={poRows.length} /></Card></Col>
      </Row>

      <Tabs items={[
        {
          key: 'sales', label: '销售日报',
          children: (
            <Table rowKey={(_, i) => i ?? 0} dataSource={salesRows} pagination={{ pageSize: 15 }} size="small">
              <Table.Column dataIndex="business_date" title="日期" />
              <Table.Column dataIndex="store_name" title="店铺" />
              <Table.Column dataIndex="platform" title="平台" />
              <Table.Column dataIndex="order_count" title="订单数" />
              <Table.Column dataIndex="order_amount" title="订单金额" render={(v: number) => `$${v?.toFixed(2)}`} />
              <Table.Column dataIndex="net_receipts" title="净收款" render={(v: number) => `$${v?.toFixed(2)}`} />
              <Table.Column dataIndex="refund_amount" title="退款" render={(v: number) => `$${v?.toFixed(2)}`} />
            </Table>
          ),
        },
        {
          key: 'inventory', label: '库存健康',
          children: (
            <Table rowKey={(_, i) => i ?? 0} dataSource={invRows} pagination={{ pageSize: 15 }} size="small">
              <Table.Column dataIndex="sku" title="SKU" />
              <Table.Column dataIndex="name" title="名称" />
              <Table.Column dataIndex="quantity" title="在库" />
              <Table.Column dataIndex="available" title="可售" />
              <Table.Column dataIndex="reserved" title="预留" />
              <Table.Column dataIndex="sales_30d" title="30天销量" />
              <Table.Column dataIndex="coverage_days" title="可售天数"
                render={(v: number) => v == null ? '-' : v.toFixed(1)} />
              <Table.Column dataIndex="risk" title="风险"
                render={(v: string) => {
                  const map: Record<string, string> = {
                    normal: 'green', overstock: 'blue', low_stock: 'orange',
                    no_demand: 'default', out_of_stock: 'red',
                  }
                  return <Tag color={map[v] || 'default'}>{v}</Tag>
                }} />
            </Table>
          ),
        },
        {
          key: 'purchase', label: '待采购',
          children: (
            <Table rowKey="id" dataSource={poRows} pagination={false} size="small">
              <Table.Column dataIndex="order_sn" title="采购单号" />
              <Table.Column dataIndex="supplier_name" title="供应商" />
              <Table.Column dataIndex="status_text" title="状态" />
              <Table.Column dataIndex="amount" title="金额" render={(v: number) => `¥${v}`} />
              <Table.Column dataIndex="pending_qty" title="待收数量" />
              <Table.Column dataIndex="arrival_risk" title="到货风险"
                render={(v: string) => v === 'unknown_eta' ? <Tag color="orange">未知ETA</Tag> : <Tag>{v}</Tag>} />
            </Table>
          ),
        },
        {
          key: 'replenishment', label: '补货审核',
          children: (
            <Table rowKey="id" dataSource={repRows} pagination={{ pageSize: 15 }} size="small">
              <Table.Column dataIndex="sku" title="SKU" />
              <Table.Column dataIndex="store_name" title="店铺" />
              <Table.Column dataIndex="urgency" title="紧急度"
                render={(v: string) => <Tag color={v === 'P1' ? 'red' : v === 'P2' ? 'orange' : 'default'}>{v}</Tag>} />
              <Table.Column dataIndex="daily_sales" title="日均销量" />
              <Table.Column dataIndex="local_available" title="本地可售" />
              <Table.Column dataIndex="fba_available" title="FBA可售" />
              <Table.Column dataIndex="suggested_qty" title="建议补货" />
              <Table.Column dataIndex="decision" title="决策" />
            </Table>
          ),
        },
        {
          key: 'quality', label: '数据质量',
          children: (
            <Table rowKey="entity" dataSource={dqRows} pagination={false} size="small">
              <Table.Column dataIndex="entity" title="数据实体" />
              <Table.Column dataIndex="total_rows" title="总行数" />
              <Table.Column dataIndex="incomplete_rows" title="不完整行数"
                render={(v: number) => v === 0 ? <Tag color="green">完整</Tag> : <Tag color="red">{v}</Tag>} />
            </Table>
          ),
        },
      ]} />
    </>
  )
}
