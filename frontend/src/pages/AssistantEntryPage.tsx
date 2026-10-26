import { useState } from 'react'
import { Alert, Button, Input, Tag } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import AssistantPage from './AssistantPage'
import { insights, scopeNames, type Scope } from './aiCockpitDemo'
import './aiCockpit.css'

type DemoContext = { insightId: string; scope: Scope; days: 7 | 30 }
function demoContext(state: unknown): DemoContext | null {
  if (!state || typeof state !== 'object' || !('cockpitDemo' in state)) return null
  const value = state.cockpitDemo
  if (!value || typeof value !== 'object' || !('insightId' in value) || !('scope' in value) || !('days' in value)) return null
  if (typeof value.insightId !== 'string' || !insights.some((item) => item.id === value.insightId)) return null
  if (value.scope !== 'all' && value.scope !== 'us' && value.scope !== 'de') return null
  if (value.days !== 7 && value.days !== 30) return null
  return { insightId: value.insightId, scope: value.scope, days: value.days }
}

function DemoTaskPreview({ context }: { context: DemoContext }) {
  const navigate = useNavigate()
  const insight = insights.find((item) => item.id === context.insightId)!
  const [goal, setGoal] = useState(`分析${insight.entity}：${insight.title}。${insight.action}，${insight.constraint}暂时不要执行业务变更。`)
  const [confirmed, setConfirmed] = useState(false)
  return <div className="ai-cockpit cockpit-task-preview">
    <header className="cockpit-heading"><div><div className="cockpit-eyebrow">驾驶舱 → AI 决策工作台</div><h1>AI 决策工作台</h1><p>{insight.action}</p></div><Tag color="purple">设计演示 · 任务草稿</Tag></header>
    <Alert type="info" showIcon message="已带入驾驶舱的演示上下文" description="对象、店铺、周期和证据均为样例。这里演示任务理解与计划确认，不调用模型、提交审批或操作业务数据。" />
    <div className="cockpit-task-columns">
      <section className="cockpit-panel"><h3>任务上下文</h3><dl><dt>对象</dt><dd>{insight.entity}</dd><dt>业务范围</dt><dd>{scopeNames[context.scope]}</dd><dt>统计周期</dt><dd>2026.{context.days === 7 ? '10.15' : '09.22'} — 10.21</dd><dt>约束</dt><dd>{insight.constraint}</dd></dl><h3>执行计划 · 待运行</h3><ol className="cockpit-steps"><li>核对数据来源与时间范围</li><li>协调专业 Agent 进行分析</li><li>验证约束并比较行动方案</li><li>形成有证据的报告供人工确认</li></ol></section>
      <section className="cockpit-panel"><h3>经营目标</h3><Input.TextArea aria-label="演示任务目标" value={goal} onChange={(event) => { setGoal(event.target.value); setConfirmed(false) }} rows={7} maxLength={2000} /><p className="cockpit-muted">确认前可修改问题与约束。这里的目标仅保存在当前演示页面。</p><Button type="primary" disabled={!goal.trim() || confirmed} onClick={() => setConfirmed(true)}>{confirmed ? '演示计划已确认' : '确认演示计划'}</Button><div className="cockpit-outcome"><strong>{confirmed ? '计划已确认，等待真实能力接入' : '任务理解摘要'}</strong><p>围绕{insight.entity}核验异常、比较改善方案，并检查预算、库存或政策约束。</p><p>预期交付：数据依据、影响评估、方案对比及人工确认入口。</p><small>尚未运行 Agent；无模型输出或实际业务执行结果。</small></div><Button onClick={() => navigate('/ai-assistant', { replace: true, state: null })}>退出演示，打开真实工作台</Button></section>
      <section className="cockpit-panel"><h3>已带入的证据</h3><Tag color="purple">虚构样例</Tag><div className="cockpit-evidence">{insight.evidence.map((item) => <div key={item.label}><span>{item.label}</span><strong>{item.value}</strong><small>{item.source}</small></div>)}</div><h3>待验证假设</h3><p className="cockpit-muted">{insight.cause}</p><h3>影响与审批</h3><p className="cockpit-muted">{insight.impact}</p><Tag>审批未发起</Tag></section>
    </div>
  </div>
}

export default function AssistantEntryPage() {
  const location = useLocation()
  const context = demoContext(location.state)
  return context ? <DemoTaskPreview key={`${location.key}-${context.insightId}`} context={context} /> : <AssistantPage />
}
