import { useEffect, useMemo, useState } from 'react'
import { Card, Statistic, Row, Col, Table, Tag, Spin, message } from 'antd'
import api from '../api'

export default function FinanceSettlementsPage() {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/datalab/table/dws_finance_day', { params: { limit: 100 } })
      .then((r) => setRows(r.data.rows || []))
      .catch(() => message.error('财务数据加载失败'))
      .finally(() => setLoading(false))
  }, [])

  const totals = useMemo(() => {
    const cny = rows.filter((r) => r.currency === 'CNY').reduce((s, r) => s + Number(r.amount || 0), 0)
    const usd = rows.filter((r) => r.currency === 'USD').reduce((s, r) => s + Number(r.amount || 0), 0)
    return { cny, usd, count: rows.length }
  }, [rows])

  const typeColors: Record<string, string> = {
    '采购付款': 'blue', '销售收入': 'green', '退款': 'red', '平台费用': 'orange',
  }

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />

  return (
    <>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card><Statistic title="财务记录数" value={totals.count} /></Card></Col>
        <Col span={6}><Card><Statistic title="人民币总额" value={totals.cny.toFixed(2)} prefix="¥" /></Card></Col>
        <Col span={6}><Card><Statistic title="美元总额" value={totals.usd.toFixed(2)} prefix="$" /></Card></Col>
        <Col span={6}><Card><Statistic title="数据来源" value="DataLab" valueStyle={{ fontSize: 18 }} /></Card></Col>
      </Row>

      <Card title="每日财务汇总">
        <Table
          size="small"
          rowKey={(_, i) => i ?? 0}
          dataSource={rows.slice().reverse()}
          pagination={{ pageSize: 20 }}
          columns={[
            { title: '日期', dataIndex: 'business_date', width: 110 },
            { title: '类型', dataIndex: 'type', width: 120,
              render: (v: string) => <Tag color={typeColors[v] || 'default'}>{v}</Tag> },
            { title: '状态', dataIndex: 'status_text', width: 90 },
            { title: '币种', dataIndex: 'currency', width: 70 },
            { title: '笔数', dataIndex: 'entry_count', width: 80 },
            { title: '金额', dataIndex: 'amount', width: 130,
              render: (v: number, r: any) => `${r.currency === 'CNY' ? '¥' : '$'}${Number(v).toFixed(2)}` },
          ]}
        />
      </Card>
    </>
  )
}
