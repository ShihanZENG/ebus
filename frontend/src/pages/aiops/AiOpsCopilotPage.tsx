import { useRef, useState } from 'react'
import { Alert, Button, Card, Collapse, Empty, Input, Space, Spin, Tag, Typography } from 'antd'
import { FileTextOutlined, SendOutlined, UserOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { askCopilot, type AskResult, type CopilotAnalysis, type Reference } from '../../api/aiOps'
import { useAuth } from '../../auth/AuthProvider'

interface ChatItem {
  role: 'user' | 'assistant'
  analysis?: CopilotAnalysis
}

const suggestions = [
  '美国站最近有哪些订单待发货、库存够不够？',
  '哪些 SKU 低于安全库存？',
  '本月有哪些采购单待审批？',
  '欧洲站咖啡品类毛利为什么转负？',
]

/** AI-PG-002 AI 经营 Copilot（AI-M02）。自然语言问题、业务查询、AI 分析，复用经营助手问答接口。 */
export default function AiOpsCopilotPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [items, setItems] = useState<ChatItem[]>([])
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  const ask = async (text: string) => {
    const q = text.trim()
    if (!q || loading) return
    setLoading(true)
    setItems((cur) => [...cur, { role: 'user', analysis: { id: `ask-${Date.now()}`, question: q, reply: '', sources: [], references: [], read_only: true, askedAt: new Date().toLocaleString('zh-CN', { hour12: false }) } }])
    setQuestion('')
    try {
      const res: AskResult = await askCopilot(q)
      const analysis: CopilotAnalysis = {
        id: `ask-${Date.now()}`,
        question: q,
        reply: res.reply,
        sources: res.sources ?? [],
        references: res.references ?? [],
        read_only: res.read_only,
        askedAt: new Date().toLocaleString('zh-CN', { hour12: false }),
      }
      setItems((cur) => [...cur, { role: 'assistant', analysis }])
    } catch (e) {
      setItems((cur) => [...cur, { role: 'assistant', analysis: { id: `err-${Date.now()}`, question: q, reply: `请求失败：${e instanceof Error ? e.message : String(e)}`, sources: [], references: [], read_only: true, askedAt: '' } }])
    } finally {
      setLoading(false)
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div>
        <Typography.Title level={3} style={{ margin: 0 }}>AI 经营 Copilot</Typography.Title>
        <Typography.Text type="secondary">以自然语言提问，Copilot 调用经营助手查询订单、库存、采购等业务数据并给出带来源的答案（只读，不执行写入）。</Typography.Text>
      </div>

      <Alert type="info" showIcon message="当前账号" description={`角色：${user?.role ?? '—'}；可访问范围由后端按权限与店铺/仓库范围过滤，模型文本不替代已验证结论。`} />

      <Card style={{ minHeight: 360 }}>
        {items.length === 0 ? (
          <Empty description="输入问题开始对话，或选择下方建议">
            <Space wrap style={{ marginTop: 12 }}>
              {suggestions.map((s) => <Button key={s} onClick={() => void ask(s)}>{s}</Button>)}
            </Space>
          </Empty>
        ) : (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            {items.map((it, idx) => it.role === 'user' ? (
              <div key={idx} style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                <div style={{ maxWidth: '80%', background: '#1677ff', color: '#fff', padding: '10px 14px', borderRadius: 10 }}>
                  <Space size={6}><UserOutlined />{it.analysis?.question}</Space>
                </div>
              </div>
            ) : (
              <div key={idx} style={{ display: 'flex', gap: 8, justifyContent: 'flex-start' }}>
                <div style={{ maxWidth: '88%', background: '#f5f7fa', padding: '12px 16px', borderRadius: 10, border: '1px solid #eef0f4' }}>
                  <div style={{ whiteSpace: 'pre-wrap' }}>{it.analysis?.reply}</div>
                  {!!it.analysis?.sources?.length && (
                    <div style={{ marginTop: 10 }}><Typography.Text type="secondary">来源：</Typography.Text>
                      <Space wrap size={[4, 4]}>{it.analysis!.sources.map((s) => <Tag key={s} color="blue">{s}</Tag>)}</Space></div>
                  )}
                  {!!it.analysis?.references?.length && (
                    <Collapse size="small" style={{ marginTop: 8 }} items={[{ key: 'refs', label: <Space><FileTextOutlined />参考文献 {it.analysis!.references.length} 条</Space>, children: (
                      <Space direction="vertical" size={6} style={{ width: '100%' }}>
                        {it.analysis!.references.map((r: Reference) => (
                          <Typography.Text key={r.ref_id} type="secondary">{r.path} · {r.section}（{r.start_line}-{r.end_line}）：{r.excerpt}</Typography.Text>
                        ))}
                      </Space>
                    ) }]} />
                  )}
                  {it.analysis && it.analysis.reply && !it.analysis.reply.startsWith('请求失败') && (
                    <Button type="link" style={{ paddingLeft: 0 }} onClick={() => navigate('/ai-copilot-analysis', { state: { analysis: it.analysis } })}>查看分析详情</Button>
                  )}
                </div>
              </div>
            ))}
            {loading && <Spin tip="Copilot 正在分析…" />}
            <div ref={endRef} />
          </Space>
        )}
      </Card>

      <Space.Compact style={{ width: '100%' }}>
        <Input
          placeholder="例如：美国站最近有哪些订单待发货、库存够不够？"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onPressEnter={() => void ask(question)}
          disabled={loading}
        />
        <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={() => void ask(question)}>发送</Button>
      </Space.Compact>
    </Space>
  )
}
