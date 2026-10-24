import { Alert, Button, Card, Collapse, Descriptions, Empty, Space, Tag, Typography } from 'antd'
import { ArrowLeftOutlined, FileTextOutlined } from '@ant-design/icons'
import { useLocation, useNavigate } from 'react-router-dom'
import { type CopilotAnalysis, type Reference } from '../../api/aiOps'
import DemoNote from '../../components/aiOps/DemoNote'

/** AI-PG-003 Copilot 分析详情（AI-M02）。展示证据来源、数据表、图表与工具结果。 */
export default function AiOpsCopilotAnalysisPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const analysis = (location.state as { analysis?: CopilotAnalysis } | null)?.analysis

  if (!analysis) {
    return (
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Typography.Title level={3}>Copilot 分析详情</Typography.Title>
        <Empty description="暂无分析记录，请先在 AI 经营 Copilot 中发起提问">
          <Button type="primary" onClick={() => navigate('/ai-copilot')}>前往 Copilot</Button>
        </Empty>
      </Space>
    )
  }

  const isError = analysis.reply.startsWith('请求失败')

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>Copilot 分析详情</Typography.Title>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/ai-copilot')}>返回对话</Button>
      </div>

      <Card title="分析概要">
        <Descriptions column={1} size="small">
          <Descriptions.Item label="问题">{analysis.question}</Descriptions.Item>
          <Descriptions.Item label="提问时间">{analysis.askedAt || '—'}</Descriptions.Item>
          <Descriptions.Item label="读写属性"><Tag color={analysis.read_only ? 'green' : 'orange'}>{analysis.read_only ? '只读' : '含写草稿'}</Tag></Descriptions.Item>
        </Descriptions>
        <Typography.Paragraph style={{ marginTop: 12, whiteSpace: 'pre-wrap' }}>{analysis.reply}</Typography.Paragraph>
      </Card>

      {!isError && (
        <Card title="证据来源">
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <div><Typography.Text type="secondary">来源系统：</Typography.Text>{analysis.sources.length ? analysis.sources.map((s) => <Tag key={s} color="blue">{s}</Tag>) : <Typography.Text type="secondary">未标注</Typography.Text>}</div>
            {analysis.references.length > 0 && (
              <Collapse size="small" items={[{ key: 'refs', label: <Space><FileTextOutlined />参考文献 {analysis.references.length} 条</Space>, children: (
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  {analysis.references.map((r: Reference) => (
                    <Typography.Text key={r.ref_id} type="secondary">{r.path} · {r.section}（{r.start_line}-{r.end_line}）：{r.excerpt}</Typography.Text>
                  ))}
                </Space>
              ) }]} />
            )}
          </Space>
        </Card>
      )}

      <Card title="数据表 · 图表 · 工具结果">
        <DemoNote scope="结构化证据可视化" compact />
        <Alert type="info" showIcon message="能力说明" description="当前经营助手接口仅返回文本结论、来源与文献引用；结构化的数据表、图表与工具调用结果视图属于规划中的增强能力，待后端补足以工具轨迹返回后接入。下方为占位示意，不构成真实数据。" />
        <Empty style={{ marginTop: 16 }} description="结构化数据表 / 图表 / 工具结果（规划中）" />
      </Card>
    </Space>
  )
}
