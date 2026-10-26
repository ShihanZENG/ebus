import { Alert, Space, Tag, Typography } from 'antd'

export interface DataMeta {
  source: string
  source_mode: string
  data_status: 'available' | 'missing' | 'unavailable' | string
  record_count?: number
  last_record_updated_at?: string | null
  last_record_update_semantics?: string
  upstream_updated_at?: string | null
  upstream_freshness?: string
  queried_at?: string | null
  source_name?: string | null
  sample_status?: string
  simulated_record_count?: number
  unclassified_legacy_payment_count?: number
  payment_record_counts?: Record<string, number>
}

function timeText(value?: string | null) {
  if (!value) return '未提供'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间格式无效' : date.toLocaleString('zh-CN', { hour12: false })
}

const sourceLabels: Record<string, string> = {
  erp_local: 'ERP 本地业务记录（非平台实时同步）',
  ads_report_import: '广告报表文件导入',
  datalab: 'DataLab 仓库快照',
}

const statusLabels: Record<string, { label: string; color: string; type: 'info' | 'warning' | 'error' }> = {
  available: { label: '有数据', color: 'green', type: 'info' },
  missing: { label: '缺失', color: 'orange', type: 'warning' },
  unavailable: { label: '暂不可用', color: 'red', type: 'error' },
}

export default function DataProvenance({ meta, title }: { meta?: DataMeta | null; title?: string }) {
  if (!meta) return null
  const status = statusLabels[meta.data_status] ?? statusLabels.unavailable
  const lastUpdate = meta.last_record_updated_at
    ? `${meta.source_mode === 'file_import' ? '最近导入时间' : '最近记录更新时间'}：${timeText(meta.last_record_updated_at)}`
    : meta.source_mode === 'warehouse_snapshot'
      ? '上游最近更新时间：未提供'
      : `最近记录更新：${timeText(meta.last_record_updated_at)}`

  return (
    <Alert
      role="status"
      showIcon
      type={status.type}
      message={`${title ? `${title} · ` : ''}${sourceLabels[meta.source] ?? meta.source} · ${status.label}`}
      description={(
        <Space wrap size={[8, 4]}>
          <Typography.Text type="secondary">{lastUpdate}</Typography.Text>
          {meta.last_record_update_semantics && <Typography.Text type="secondary">口径：{meta.last_record_update_semantics}</Typography.Text>}
          {meta.upstream_freshness === 'not_provided' && meta.queried_at &&
            <Typography.Text type="secondary">本次查询：{timeText(meta.queried_at)}</Typography.Text>}
          {meta.source_name && <Typography.Text type="secondary">来源文件：{meta.source_name}</Typography.Text>}
          {meta.sample_status === 'unclassified' && <Tag>样例/生产属性未标记</Tag>}
          {(meta.simulated_record_count ?? 0) > 0 &&
            <Tag color="purple">模拟记录 {meta.simulated_record_count} 条，未计入上述收款指标</Tag>}
          {(meta.unclassified_legacy_payment_count ?? 0) > 0 &&
            <Tag color="default">历史来源未分类 {meta.unclassified_legacy_payment_count} 条</Tag>}
        </Space>
      )}
      style={{ marginBottom: 12 }}
    />
  )
}
