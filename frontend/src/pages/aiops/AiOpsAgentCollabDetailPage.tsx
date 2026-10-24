import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Progress, Row, Space, Steps, Tag, Typography } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { fetchCollabTasks, type CollabTask } from '../../api/aiOps'
import DemoNote from '../../components/aiOps/DemoNote'

const stepStatus: Record<CollabTask['steps'][number]['status'], 'finish' | 'process' | 'wait'> = { done: 'finish', running: 'process', pending: 'wait' }

/** AI-PG-008 Agent 协作详情（AI-M04）。多 Agent 任务分解、执行及结果。演示数据。 */
export default function AiOpsAgentCollabDetailPage() {
  const navigate = useNavigate()
  const { id } = useParams()
  const [task, setTask] = useState<CollabTask | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    const all = await fetchCollabTasks()
    setTask(all.find((t) => t.id === id) ?? null)
    setLoading(false)
  }, [id])
  useEffect(() => { void load() }, [load])

  if (loading) return <Typography.Text>加载中…</Typography.Text>
  if (!task) return <Alert type="error" message="未找到该协作任务（演示数据）" />

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>Agent 协作详情</Typography.Title>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/ai-agent-workbench')}>返回工作台</Button>
      </div>
      <DemoNote scope="协作任务" />

      <Card>
        <Row gutter={16} align="middle">
          <Col flex="auto"><Typography.Title level={5} style={{ margin: 0 }}>{task.title}</Typography.Title>
            <Space wrap style={{ marginTop: 6 }}>
              <Tag>协调：{task.coordinator}</Tag>
              <Tag>参与：{task.participants.join('、')}</Tag>
              <Tag>创建：{task.createdAt}</Tag>
            </Space></Col>
          <Col><Progress type="circle" percent={task.progress} size={64} /></Col>
        </Row>
      </Card>

      <Card title="任务分解与执行">
        <Steps
          direction="vertical"
          current={task.steps.filter((s) => s.status !== 'pending').length}
          items={task.steps.map((s) => ({
            title: <Space><Tag color="blue">{s.agentName}</Tag>{s.action}</Space>,
            status: stepStatus[s.status],
            description: s.output,
          }))}
        />
      </Card>
    </Space>
  )
}
