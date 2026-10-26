import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Col, List, Row, Space, Statistic, Tag, Typography } from 'antd'
import { ApiOutlined, TeamOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { fetchAgents, fetchCollabTasks, type AgentRole, type AgentStatus, type CollabTask } from '../../api/aiOps'
import DemoNote from '../../components/aiOps/DemoNote'

const agentStatus: Record<AgentStatus, { color: string; label: string }> = { online: { color: 'green', label: '在线' }, busy: { color: 'orange', label: '忙碌' }, offline: { color: 'default', label: '离线' } }
const collabStatus: Record<CollabTask['status'], { color: string; label: string }> = { running: { color: 'blue', label: '进行中' }, completed: { color: 'green', label: '已完成' }, failed: { color: 'red', label: '失败' } }

/** AI-PG-007 经营 Agent 工作台（AI-M04 经营 Agent 协作）。Agent 角色、协作任务、执行状态。演示数据。 */
export default function AiOpsAgentWorkbenchPage() {
  const navigate = useNavigate()
  const [agents, setAgents] = useState<AgentRole[]>([])
  const [tasks, setTasks] = useState<CollabTask[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    const [a, t] = await Promise.all([fetchAgents(), fetchCollabTasks()])
    setAgents(a); setTasks(t); setLoading(false)
  }, [])
  useEffect(() => { void load() }, [load])

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Typography.Title level={3} style={{ margin: 0 }}>经营 Agent 工作台</Typography.Title>
      <DemoNote scope="Agent 角色与协作任务" />

      <Card title={<Space><ApiOutlined />Agent 角色</Space>} loading={loading}>
        <Row gutter={[16, 16]}>
          {agents.map((a) => (
            <Col key={a.id} xs={24} md={12} xl={8}>
              <Card size="small">
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Typography.Text strong>{a.name}</Typography.Text>
                  <Tag color={agentStatus[a.status].color}>{agentStatus[a.status].label}</Tag>
                </Space>
                <Typography.Paragraph type="secondary" style={{ margin: '8px 0' }}>{a.description}</Typography.Paragraph>
                <Space wrap size={4}>{(a.tools).map((t) => <Tag key={t}>{t}</Tag>)}</Space>
                <Row gutter={8} style={{ marginTop: 10 }}>
                  <Col span={12}><Statistic title="已处理任务" value={a.tasksHandled} /></Col>
                  <Col span={12}><Statistic title="平均时延" value={a.avgLatencyMs} suffix="ms" /></Col>
                </Row>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      <Card title={<Space><TeamOutlined />多 Agent 协作任务</Space>} loading={loading}>
        <List
          dataSource={tasks}
          renderItem={(t) => (
            <List.Item actions={[<Button key="v" type="link" onClick={() => navigate(`/ai-agent-collab/${t.id}`)}>查看协作详情</Button>]}>
              <List.Item.Meta
                title={<Space><Typography.Text strong>{t.title}</Typography.Text><Tag color={collabStatus[t.status].color}>{collabStatus[t.status].label}</Tag></Space>}
                description={`协调：<span>${t.coordinator}</span>　参与：${t.participants.join('、')}　进度 ${t.progress}%`}
              />
            </List.Item>
          )}
        />
      </Card>
    </Space>
  )
}
