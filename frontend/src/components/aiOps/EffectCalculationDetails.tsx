import { Tag, Typography } from 'antd'
import type { EffectMetric } from '../../api/aiOps'
import './EffectCalculationDetails.css'

export default function EffectCalculationDetails({ metrics }: { metrics: EffectMetric[] }) {
  return <div className="effect-calculations">
    {metrics.map((metric) => <section className="effect-calculation" key={metric.metric}>
      <div className="effect-calculation-title">
        <Typography.Text strong>{metric.metric}</Typography.Text>
        <Tag color={metric.rating === 'good' ? 'green' : metric.rating === 'warn' ? 'orange' : 'red'}>{metric.rating === 'good' ? '达标' : '未达标'}</Tag>
      </div>
      <p><span>公式</span>{metric.formula}</p>
      <p><span>代入样例</span>{metric.calculation}</p>
      <p><span>判断</span>{metric.decision}</p>
    </section>)}
    <Typography.Text type="secondary">总评规则：所有指标达标才标记为“达标”；任一指标未达标则标记为“未达标”。以上输入值均为演示样例，尚无真实业务数据血缘。</Typography.Text>
  </div>
}
