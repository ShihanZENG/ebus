import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Col, Collapse, Row, Space, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { fetchEffects, type EffectRecord } from '../../api/aiOps'
import DemoNote from '../../components/aiOps/DemoNote'
import EffectCalculationDetails from '../../components/aiOps/EffectCalculationDetails'
import './AiOpsEffectOverviewPage.css'

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
              className="effect-overview-card"
              title={<Space wrap><Typography.Text strong>{r.title}</Typography.Text><Tag color={ratingMeta[r.rating].color}>{ratingMeta[r.rating].label}</Tag></Space>}
              extra={<Button type="link" onClick={() => navigate(`/ai-effect/${r.id}`)}>复盘详情</Button>}
              loading={loading}
            >
              <div className="effect-overview-meta">
                <span>关联策略 <Typography.Text strong>{r.strategyId}</Typography.Text></span>
                <span>复盘时间 <Typography.Text strong>{r.reviewedAt}</Typography.Text></span>
              </div>
              <div className="effect-overview-metrics" role="table" aria-label={`${r.title}指标对比`}>
                <div className="effect-overview-metric effect-overview-metric-head" role="row">
                  <span role="columnheader">指标</span><span role="columnheader">计划</span><span role="columnheader">实际</span><span role="columnheader">偏差</span>
                </div>
                {r.metrics.map((m) => (
                  <div className="effect-overview-metric" role="row" key={m.metric}>
                    <span className="effect-overview-name" role="cell">{m.metric}</span>
                    <span className="effect-overview-value" role="cell" data-label="计划">{m.plan}</span>
                    <Typography.Text strong className="effect-overview-value" role="cell" data-label="实际">{m.actual}</Typography.Text>
                    <span className="effect-overview-value" role="cell" data-label="偏差"><Tag color={ratingMeta[m.rating].color}>{m.deviation}</Tag></span>
                  </div>
                ))}
              </div>
              <Collapse ghost size="small" style={{ marginTop: 8 }} items={[{
                key: 'calculation', label: '查看计算公式与判断依据',
                children: <EffectCalculationDetails metrics={r.metrics} />,
              }]} />
            </Card>
          </Col>
        ))}
      </Row>
    </Space>
  )
}
