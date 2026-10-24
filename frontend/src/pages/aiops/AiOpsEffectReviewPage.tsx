import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Row, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { fetchEffect, type EffectMetric, type EffectRecord } from '../../api/aiOps'
import DemoNote from '../../components/aiOps/DemoNote'

const ratingMeta: Record<EffectRecord['rating'], { color: string; label: string }> = { good: { color: 'green', label: '达标' }, warn: { color: 'orange', label: '基本达标' }, bad: { color: 'red', label: '未达标' } }

/** AI-PG-018 策略复盘详情（AI-M09）。仿真结果与实际指标对比、评价。演示数据。 */
export default function AiOpsEffectReviewPage() {
  const navigate = useNavigate()
  const { id } = useParams()
  const [rec, setRec] = useState<EffectRecord | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => { setLoading(true); setRec(await fetchEffect(id ?? '')); setLoading(false) }, [id])
  useEffect(() => { void load() }, [load])

  if (loading) return <Typography.Text>加载中…</Typography.Text>
  if (!rec) return <Alert type="error" message="未找到该复盘记录（演示数据）" />

  const columns: ColumnsType<EffectMetric> = [
    { title: '指标', dataIndex: 'metric' },
    { title: '计划（仿真）', dataIndex: 'plan' },
    { title: '实际', dataIndex: 'actual', render: (v: string) => <Typography.Text strong>{v}</Typography.Text> },
    { title: '偏差', dataIndex: 'deviation', render: (v: string) => <Tag color={rec.rating === 'good' ? 'green' : rec.rating === 'warn' ? 'orange' : 'red'}>{v}</Tag> },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>策略复盘详情</Typography.Title>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/ai-effect-overview')}>返回总览</Button>
      </div>
      <DemoNote scope="效果评估" />

      <Card>
        <Row gutter={16} align="middle">
          <Col flex="auto">
            <Typography.Title level={5} style={{ margin: 0 }}>{rec.title}</Typography.Title>
            <Space wrap style={{ marginTop: 6 }}>
              <Tag>关联策略 {rec.strategyId}</Tag>
              <Tag color={ratingMeta[rec.rating].color}>{ratingMeta[rec.rating].label}</Tag>
              <Tag>复盘 {rec.reviewedAt}</Tag>
            </Space>
          </Col>
        </Row>
      </Card>

      <Card title="仿真结果与实际指标对比">
        <Table rowKey="metric" pagination={false} columns={columns} dataSource={rec.metrics} />
      </Card>

      <Card title="评价">
        <Alert type={rec.rating === 'good' ? 'success' : rec.rating === 'warn' ? 'warning' : 'error'} message={rec.comment} />
      </Card>
    </Space>
  )
}
