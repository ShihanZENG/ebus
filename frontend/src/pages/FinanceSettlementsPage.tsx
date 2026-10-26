import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Statistic, Row, Col, Table, Tag, Spin, message } from 'antd'
import api from '../api'
import DataProvenance, { type DataMeta } from '../components/DataProvenance'
import FinanceFeeReconciliationPanel from './FinanceFeeReconciliationPanel'

export default function FinanceSettlementsPage() {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [dataMeta, setDataMeta] = useState<DataMeta | null>(null)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const response = await api.get<{ rows?: any[]; data_meta: DataMeta }>('/datalab/table/dws_finance_day', { params: { limit: 100 } })
      setRows(response.data.rows || [])
      setDataMeta(response.data.data_meta)
    } catch (cause) {
      const description = cause instanceof Error ? cause.message : '财务 DataLab 数据加载失败'
      setError(description)
      setDataMeta({ source: 'datalab', source_mode: 'warehouse_snapshot', data_status: 'unavailable',
        upstream_updated_at: null, upstream_freshness: 'not_provided', sample_status: 'unclassified' })
      message.error('财务数据加载失败')
    } finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [])

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

      <DataProvenance title="DataLab 财务快照" meta={dataMeta} />
      {error && <Alert style={{ marginBottom: 16 }} type="error" showIcon message="财务快照暂不可用" description={error} action={<Button size="small" onClick={() => void load()}>重试</Button>} />}
      {!error && <Alert style={{ marginBottom: 16 }} type="info" showIcon message="有限行快照" description="本页最多读取 100 行后在页面汇总；行数可能不完整，不能作为全量财务汇总或逐笔凭据。DataLab 未提供上游更新时间，本次查询时间不代表数据刷新时间。" />}

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
      <FinanceFeeReconciliationPanel />
    </>
  )
}
