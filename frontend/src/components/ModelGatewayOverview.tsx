import { Alert, Card, Descriptions, Space } from 'antd'
import type { LimModelMetrics } from '../api/lim'

export default function ModelGatewayOverview({ metrics }: { metrics: LimModelMetrics | null }) {
  if (!metrics) return null
  const { governance, call_count, success_rate, known_total_tokens, unknown_usage_count } = metrics
  const { limits } = governance
  return <Card title={`近 ${metrics.days} 天模型调用与治理`}>
    <Space direction="vertical" style={{ width: '100%' }}>
      <Alert showIcon type={governance.mode === 'redis' ? 'info' : 'warning'}
        message={governance.mode === 'redis' ? '已配置 Redis 共享治理' : '当前为单进程内存治理，重启会重置额度；多实例部署请配置 Redis。'} />
      <Descriptions column={3} items={[
        { key: 'calls', label: '可见调用', children: call_count },
        { key: 'success', label: '成功率', children: success_rate === null ? '暂无调用' : `${(success_rate * 100).toFixed(1)}%` },
        { key: 'tokens', label: '已知 Token', children: known_total_tokens ?? '暂无已知用量' },
        { key: 'unknown', label: '用量不完整的调用', children: unknown_usage_count },
        { key: 'latency', label: '平均耗时', children: metrics.mean_latency_ms === null ? '暂无记录' : `${Math.round(metrics.mean_latency_ms)} ms` },
        { key: 'rate', label: '每用户每分钟', children: `${limits.requests_per_minute} 次` },
        { key: 'concurrency', label: '每用户同时调用', children: `${limits.concurrency} 次` },
        { key: 'quota', label: '每日 Token 预算', children: limits.daily_tokens.toLocaleString() },
        { key: 'attempts', label: '最多尝试', children: `${limits.max_attempts} 次` },
      ]} />
      <Alert type="info" message="预算按 UTC 日期重置，先保守预留再按已知用量结算；失败或用量未知的尝试保留预留额。已知 Token 不包含供应商未返回的用量，费用与缓存尚未启用。" />
    </Space>
  </Card>
}
