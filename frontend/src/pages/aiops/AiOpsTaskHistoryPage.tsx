import { Space, Typography } from 'antd'
import AssistantTasksPanel from '../AssistantTasksPanel'

/**
 * AI-PG-019 经营任务历史（AI-M10 经营任务与策略历史）。
 * 复用现有助手任务面板（真实接口 /assistant/tasks），数据为真实运行记录。
 */
export default function AiOpsTaskHistoryPage() {
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div>
        <Typography.Title level={3} style={{ margin: 0 }}>经营任务历史</Typography.Title>
        <Typography.Text type="secondary">经营助手的追踪任务与运行记录（真实接口数据，进程重启后暂无自动恢复，页面已标注）。</Typography.Text>
      </div>
      <AssistantTasksPanel />
    </Space>
  )
}
