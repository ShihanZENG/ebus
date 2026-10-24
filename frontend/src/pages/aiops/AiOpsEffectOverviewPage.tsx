import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Col, Row, Space, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { fetchEffects, type EffectRecord } from '../../api/aiOps'
import DemoNote from '../../components/aiOps/DemoNote'

const ratingMeta: Record<EffectRecord['rating'], { color: string; label: string }> = { good: { color: 'green', label: '达标' }, warn: { color: 'orange', label: '基本达标' }, bad: { color: 'red', label: '未达标' } }

/** AI-PG-017 效果评估总览（AI-M09 效果评估中心）。已执行策略的结果及偏差分析。演示数据。 */
export default function AiOpsEffectOverviewPage() {
  const navigate = useNavigate()
  const [rows, setRows] = useState<EffectRecord[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => { setLoading(true); setRows(await fetchEffects()); setLoading(false) }, [])
  useEffect(() => { void load() }, [load])

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Typography.Title level={3} style={{ margin: 0 }}>效果评估总览</Typography.Title>
      <DemoNote scope="效果评估" />
      <Row gutter={[16, 16]}>
        {rows.map((r) => (
          <Col key={r.id} xs={24} md={12}>
            <Card
              title={<Space><Typography.Text strong>{r.title}</Typography.Text><Tag color={ratingMeta[r.rating].color}>{ratingMeta[r.rating].label}</Tag></Space>}
              extra={<Button type="link" onClick={() => navigate(`/ai-effect/${r.id}`)}>复盘详情</Button>}
              loading={loading}
            >
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Typography.Text type="secondary">关联策略：{r.strategyId}</Typography.Text>
                <Typography.Text type="secondary">复盘时间：{r.reviewedAt}</Typography.Text>
                {r.metrics.map((m) => (
                  <Typography.Text key={m.metric}>· {m.metric}：计划 {m.plan} / 实际 <Typography.Text strong>{m.actual}</Typography.Text>（{m.deviation}）</Typography.Text>
                ))}
              </Space>
            </Card>
          </Col>
        ))}
      </Row>
    </Space>
  )
}
