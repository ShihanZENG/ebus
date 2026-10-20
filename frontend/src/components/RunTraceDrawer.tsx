import { Alert, Collapse, Drawer, Empty, Space, Tag, Timeline, Typography } from 'antd'

export interface TraceEvent {
  kind: string
  title: string
  status: string
  timestamp?: string
  elapsed_ms?: number | null
  details?: Record<string, unknown>
}

export default function RunTraceDrawer({ open, onClose, id, model, status, elapsedMs, events, legacy = false }: {
  open: boolean; onClose: () => void; id?: string; model?: string; status?: string
  elapsedMs?: number; events: TraceEvent[]; legacy?: boolean
}) {
  return <Drawer title="运行轨迹" open={open} onClose={onClose} width={560} styles={{ wrapper: { maxWidth: '100vw' } }}>
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Typography.Text copyable={!!id} style={{ overflowWrap: 'anywhere' }}>{id}</Typography.Text>
      <Space wrap>
        <Tag color={status === 'FAILED' ? 'red' : status === 'COMPLETED' ? 'green' : 'blue'}>{status === 'FAILED' ? '执行失败' : status === 'COMPLETED' ? '已完成' : status}</Tag>
        {model && <Tag>{model}</Tag>}
        <Typography.Text type="secondary">总耗时：{elapsedMs == null ? '未记录' : `${elapsedMs} ms`}</Typography.Text>
      </Space>
      <Alert type={status === 'FAILED' ? 'warning' : 'info'} showIcon message={status === 'FAILED' ? '失败前的工具结果仅供排查；本次新草稿未保存。' : '展示实际执行事件；请求结束后可查看。'} />
      {legacy && <Typography.Text type="secondary">此历史记录仅保存了工具调用，没有模型轮次和事件时间。</Typography.Text>}
      {!events.length ? <Empty description="暂无运行事件" /> : <Timeline style={{ marginTop: 12 }} items={events.map((event, index) => ({
        color: event.status === 'error' ? 'red' : event.kind === 'complete' ? 'green' : 'blue',
        children: <Space direction="vertical" size={6} style={{ width: '100%' }}>
          <Typography.Text strong>{event.title}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {event.timestamp ? new Date(event.timestamp).toLocaleString('zh-CN') : '时间未记录'}
            {event.elapsed_ms != null && ` · ${event.elapsed_ms} ms`}
          </Typography.Text>
          {!!Object.keys(event.details ?? {}).length && <Collapse size="small" style={{ width: '100%' }} items={[{
            key: String(index), label: '查看详情', children: <pre style={{ margin: 0, padding: 12, background: '#111827', color: '#e5e7eb', borderRadius: 6, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 320, overflow: 'auto' }}>{JSON.stringify(event.details, null, 2)}</pre>,
          }]} />}
        </Space>,
      }))} />}
    </Space>
  </Drawer>
}
