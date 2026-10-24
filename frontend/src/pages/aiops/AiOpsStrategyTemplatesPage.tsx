import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Col, Row, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { fetchTemplates, type StrategyTemplate } from '../../api/aiOps'
import DemoNote from '../../components/aiOps/DemoNote'

/** AI-PG-020 经营策略模板（AI-M10）。常用业务场景和参数模板。演示数据。 */
export default function AiOpsStrategyTemplatesPage() {
  const navigate = useNavigate()
  const [rows, setRows] = useState<StrategyTemplate[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => { setLoading(true); setRows(await fetchTemplates()); setLoading(false) }, [])
  useEffect(() => { void load() }, [load])

  const columns: ColumnsType<StrategyTemplate> = [
    { title: '模板名称', dataIndex: 'name', render: (t: string) => <Typography.Text strong>{t}</Typography.Text> },
    { title: '适用场景', dataIndex: 'scenario' },
    { title: '说明', dataIndex: 'description', ellipsis: true },
    { title: '默认参数', dataIndex: 'params', render: (p: StrategyTemplate['params']) => <Space wrap>{p.map((x) => <Tag key={x.key}>{x.key}: {x.value}</Tag>)}</Space> },
    { title: '使用次数', dataIndex: 'usageCount', render: (n: number) => `${n} 次` },
    { title: '操作', render: (_, _r) => <Button type="link" onClick={() => navigate('/ai-strategy-tasks')}>基于此创建</Button> },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Typography.Title level={3} style={{ margin: 0 }}>经营策略模板</Typography.Title>
      <DemoNote scope="策略模板" />
      <Card>
        <Table rowKey="id" loading={loading} columns={columns} dataSource={rows} pagination={false} />
      </Card>
      <Row gutter={[16, 16]}>
        {rows.map((t) => (
          <Col key={t.id} xs={24} md={12} xl={6}>
            <Card size="small" title={t.name}>
              <Typography.Paragraph type="secondary" style={{ margin: 0 }}>{t.description}</Typography.Paragraph>
            </Card>
          </Col>
        ))}
      </Row>
    </Space>
  )
}
