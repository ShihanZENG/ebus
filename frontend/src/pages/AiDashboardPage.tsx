import { useMemo, useState } from 'react'
import { Alert, Button, Drawer, Segmented, Select, Tag } from 'antd'
import { ArrowRightOutlined, ArrowUpOutlined, ArrowDownOutlined, BulbOutlined, CheckOutlined, DotChartOutlined, ExpandAltOutlined, LineChartOutlined, RadarChartOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import AiDashboardLiveSnapshot from './AiDashboardLiveSnapshot'
import { insights, makeScenario, metricNames, metricValue, scopeNames, type Insight, type Metric, type Scope } from './aiCockpitDemo'
import './aiCockpit.css'

const metricKeys: Metric[] = ['sales', 'profit', 'ads', 'orders', 'turnover', 'inventory']
const levelNames = { high: '高优先级', medium: '需关注', opportunity: '增长机会' }
const todos = [
  { title: '待审批方案', count: 2, detail: '样例补货与广告调整方案等待负责人复核。', next: '确认数据依据、预算约束和变更版本后再审批。' },
  { title: '失败任务', count: 1, detail: '样例广告诊断任务因报表缺失而中止。', next: '补齐归因报表后重新发起只读分析。' },
  { title: '需人工介入', count: 1, detail: '样例供应商交期尚未核实。', next: '请采购负责人确认到货承诺，再判断补货可行性。' },
]

export default function AiDashboardPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  // 默认展示真实经营快照；虚构概念演示需显式切换，且全程带「设计演示」标识。
  const [mode, setMode] = useState<'live' | 'demo'>('live')
  const [scope, setScope] = useState<Scope>('all')
  const [days, setDays] = useState<7 | 30>(30)
  const [metric, setMetric] = useState<Metric>('sales')
  const [riskFilter, setRiskFilter] = useState('all')
  const [selected, setSelected] = useState<{ insight: Insight; action: boolean } | null>(null)
  const [queued, setQueued] = useState<string[]>([])
  const [tableOpen, setTableOpen] = useState(false)
  const [hovered, setHovered] = useState<number | null>(null)
  const [grain, setGrain] = useState<'day' | 'week' | 'month'>('day')
  const [showTarget, setShowTarget] = useState(false)
  const [todoIndex, setTodoIndex] = useState<number | null>(null)
  const scenario = useMemo(() => makeScenario(scope, days), [scope, days])
  const scopedInsights = insights.filter((item) => scope === 'all' || item.scope === scope)
  const visibleInsights = scopedInsights.filter((item) => riskFilter === 'all' || item.level === riskFilter)
  const highCount = scopedInsights.filter((item) => item.level === 'high').length
  const salesGrowth = (scenario.current.sales / scenario.previous.sales - 1) * 100
  const marginChange = scenario.margin - scenario.previousMargin
  const canAsk = user?.role === 'admin' || user?.permissions.includes('assistant:read')

  const startAnalysis = (insight: Insight) => navigate('/ai-assistant', { state: { cockpitDemo: { insightId: insight.id, scope, days } } })
  const dailyRows = scenario.rows.map((row) => {
    const previous = metric === 'sales' ? row.previousSales : metric === 'profit' ? row.previousProfit : metric === 'orders' ? row.previousOrders : metric === 'ads' ? row.previousAds : metric === 'inventory' ? row.previousInventory : metric === 'turnover' ? row.previousTurnover : row.previousOrders / row.previousVisits * 100
    return { date: row.date, value: metric === 'conversion' ? row.orders / row.visits * 100 : row[metric], previous }
  })
  const dailyTargets: Record<Metric, number> = { sales: scope === 'all' ? 25000 : scope === 'us' ? 15000 : 10000, profit: scope === 'all' ? 5500 : scope === 'us' ? 3300 : 2200, ads: scope === 'all' ? 2500 : scope === 'us' ? 1700 : 800, orders: scope === 'all' ? 400 : scope === 'us' ? 240 : 160, inventory: scope === 'all' ? 3 : 2, turnover: 42, conversion: 4 }
  const buckets = new Map<string, typeof dailyRows>()
  dailyRows.forEach((row, index) => {
    const key = grain === 'day' ? row.date : grain === 'week' ? `第 ${Math.floor(index / 7) + 1} 周` : `${row.date.split('/')[0]} 月`
    buckets.set(key, [...(buckets.get(key) ?? []), row])
  })
  const isSnapshotMetric = (key: Metric) => key === 'inventory' || key === 'turnover' || key === 'conversion'
  const snapshotMetric = isSnapshotMetric(metric)
  const chartRows = [...buckets.entries()].map(([date, rows]) => ({ date, value: snapshotMetric ? rows[rows.length - 1].value : rows.reduce((sum, row) => sum + row.value, 0), previous: snapshotMetric ? rows[rows.length - 1].previous : rows.reduce((sum, row) => sum + row.previous, 0), target: dailyTargets[metric] * (snapshotMetric ? 1 : rows.length) }))
  const maxValue = Math.max(...chartRows.flatMap((row) => [row.value, row.previous, showTarget ? row.target : 0])) * 1.12
  const x = (i: number) => chartRows.length === 1 ? 380 : 68 + i / (chartRows.length - 1) * 624
  const y = (value: number) => 218 - value / maxValue * 180
  const line = chartRows.map((row, i) => `${x(i)},${y(row.value)}`).join(' ')
  const previousLine = chartRows.map((row, i) => `${x(i)},${y(row.previous)}`).join(' ')
  const targetLine = chartRows.map((row, i) => `${x(i)},${y(row.target)}`).join(' ')
  const chartIndex = Math.min(hovered ?? chartRows.length - 1, chartRows.length - 1)
  const chartRow = chartRows[chartIndex]

  return <div className="ai-cockpit">
    <header className="cockpit-heading">
      <div><div className="cockpit-eyebrow"><RadarChartOutlined /> COMMERCEOS · 经营决策中心</div><h1>AI 经营驾驶舱</h1><p>{mode === 'live' ? '实时经营快照与风险识别，基于本地 ERP 业务记录。' : '看清经营变化，把洞察变成下一步行动（设计演示）。'}</p></div>
      <Segmented
        value={mode}
        onChange={(value) => setMode(value as 'live' | 'demo')}
        options={[
          { label: '实时经营快照', value: 'live' },
          { label: '概念演示（虚构样例）', value: 'demo' },
        ]}
      />
    </header>

    {mode === 'live' ? (
      <>
        <Alert
          type="info"
          showIcon
          message="当前为实时经营快照"
          description="数据来自本地业务记录，按授权店铺与仓库范围统计，不代表电商平台实时同步。切换到「概念演示」可查看设计演示概念稿（指标为虚构样例）。"
        />
        <AiDashboardLiveSnapshot />
      </>
    ) : (
      <>
        <div className="cockpit-toolbar">
          <div className="cockpit-demo"><span />设计演示 <small>所有指标、分析与方案均为虚构样例 · USD</small></div>
          <div className="cockpit-filters"><Select aria-label="选择演示店铺" value={scope} onChange={(value: Scope) => { setScope(value); setHovered(null) }} options={Object.entries(scopeNames).map(([value, label]) => ({ value, label }))} />
            <div className="cockpit-segment" aria-label="演示统计周期">{([7, 30] as const).map((value) => <button key={value} aria-pressed={days === value} onClick={() => { setDays(value); setHovered(null) }}>{value} 天</button>)}</div>
          </div>
        </div>

        <div className="cockpit-section-heading"><div><span className="cockpit-section-number">01</span><h2>经营表现</h2><span>当前周期与前一周期对比</span></div><small>{scenario.rows[0].date} — 10/21 · 样例</small></div>
        <section className="cockpit-metrics" aria-label="经营指标，选择后查看趋势">
          {metricKeys.map((key) => {
            const delta = (scenario.current[key] / scenario.previous[key] - 1) * 100
            const lowerIsBetter = key === 'inventory' || key === 'turnover' || key === 'ads'
            return <button className={`cockpit-metric ${metric === key ? 'active' : ''}`} key={key} aria-pressed={metric === key} onClick={() => { setMetric(key); setHovered(null) }}><span className="cockpit-metric-label">{metricNames[key]}<LineChartOutlined /></span><strong>{metricValue(key, scenario.current[key])}</strong><span className={(lowerIsBetter ? delta <= 0 : delta >= 0) ? 'cockpit-positive' : 'cockpit-negative'}>{delta >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />} {Math.abs(delta).toFixed(2)}% <small>{isSnapshotMetric(key) ? '期末对比' : '较前期'}</small></span></button>
          })}
        </section>

        <section className="cockpit-brief" aria-labelledby="brief-title">
          <div className="cockpit-brief-main"><div className="cockpit-eyebrow"><ThunderboltOutlined /> AI 经营简报 <span>样例分析</span></div>
            <h2 id="brief-title">AI 经营洞察：销售增长是否带来了利润改善？</h2>
            <p>{scopeNames[scope]}在样例周期内销售额增长 <strong>{salesGrowth.toFixed(1)}%</strong>，贡献利润率为 <strong>{scenario.margin.toFixed(1)}%</strong>，较前一周期下降 <strong>{Math.abs(marginChange).toFixed(1)} 个百分点</strong>。{scope === 'de' ? '建议优先检查退货原因，同时评估高转化商品的增长机会。' : '建议先核查主力商品的断货窗口与低效广告支出，再决定增长投入。'}</p>
            <div className="cockpit-brief-links"><button onClick={() => setSelected({ insight: scopedInsights[0], action: false })}>查看判断依据 <ArrowRightOutlined /></button><span>样例截至 2026.10.21 · 对比前一等长周期</span></div>
          </div>
          <div className="cockpit-focus"><span className="cockpit-focus-label">本次决策重点</span><strong>{String(scopedInsights.length).padStart(2, '0')}<small> 项洞察</small></strong><div><span className="cockpit-dot red" />{highCount} 项需优先处理</div><div><span className="cockpit-dot green" />{scopedInsights.filter((item) => item.level === 'opportunity').length} 项增长机会</div><button onClick={() => document.getElementById('cockpit-actions')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>查看行动建议 <ArrowRightOutlined /></button></div>
        </section>

        <div className="cockpit-performance">
          <section className="cockpit-panel cockpit-chart"><div className="cockpit-panel-heading"><div><h3>{metricNames[metric]}趋势</h3><span className="cockpit-muted">{scopeNames[scope]} · {days} 天样例</span></div><button className="cockpit-icon-button" aria-label="查看趋势数据表" onClick={() => setTableOpen(true)}><ExpandAltOutlined /></button></div>
            <div className="cockpit-trend-controls"><div className="cockpit-segment">{([['day', '日'], ['week', '周'], ['month', '月']] as const).map(([value, label]) => <button key={value} aria-pressed={grain === value} onClick={() => { setGrain(value); setHovered(null) }}>{label}</button>)}</div><button className="cockpit-text-button" aria-pressed={showTarget} onClick={() => setShowTarget((value) => !value)}>{showTarget ? '隐藏样例目标' : '对比样例目标'}</button></div>
            <div className="cockpit-chart-legend"><span><i />当前周期</span><span><i className="previous" />前一周期（按日对齐）</span></div>
            <div className="cockpit-chart-readout" aria-live="polite"><span>{chartRow.date}</span><strong>{metricValue(metric, chartRow.value)}</strong><span>前期 {metricValue(metric, chartRow.previous)}</span>{showTarget && <span className="cockpit-target">目标 {metricValue(metric, chartRow.target)}</span>}</div>
            <svg viewBox="0 0 720 250" role="img" aria-label={`${metricNames[metric]}样例趋势，详细数值可通过右上角按钮打开数据表`} onMouseLeave={() => setHovered(null)}>
              <defs><linearGradient id="cockpit-trend-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#6c61dd" stopOpacity=".22" /><stop offset="100%" stopColor="#6c61dd" stopOpacity="0" /></linearGradient></defs>
              {[0, 1, 2, 3, 4].map((step) => <g key={step}><line x1="68" x2="692" y1={38 + step * 45} y2={38 + step * 45} stroke="#edf0f5" /><text x="56" y={42 + step * 45} textAnchor="end" fill="#8991a5" fontSize="11">{metric === 'conversion' ? `${(maxValue * (1 - step / 4)).toFixed(1)}%` : Math.round(maxValue * (1 - step / 4)).toLocaleString()}</text></g>)}
              <polygon points={`68,218 ${line} 692,218`} fill="url(#cockpit-trend-fill)" /><polyline points={previousLine} fill="none" stroke="#c4c8da" strokeWidth="2" strokeDasharray="5 5" /><polyline points={line} fill="none" stroke="#7163df" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />
              {showTarget && <polyline points={targetLine} fill="none" stroke="#21a69c" strokeWidth="2" strokeDasharray="3 4" />}
              {chartRows.map((row, i) => <g key={row.date}>{(i === 0 || i === chartRows.length - 1 || i % Math.ceil(chartRows.length / 5) === 0) && <text x={x(i)} y="242" textAnchor="middle" fill="#8991a5" fontSize="11">{row.date}</text>}<rect x={x(i) - 624 / chartRows.length / 2} y="25" width={624 / chartRows.length} height="195" fill="transparent" onMouseEnter={() => setHovered(i)} onClick={() => setHovered(i)} /></g>)}
              <circle cx={x(chartIndex)} cy={y(chartRow.value)} r="5" fill="#7163df" stroke="white" strokeWidth="2" />
            </svg>
            <small className="cockpit-muted">周按所选周期每 7 天分组，月按自然月分组；仅汇总范围内日期。库存与周转取组末值，金额与订单按组累加。目标为独立样例计划值。</small>
          </section>
          <section className="cockpit-panel cockpit-todos"><div className="cockpit-panel-heading"><h3><BulbOutlined /> 风险与待办</h3><span className="cockpit-soft-tag">工作区样例</span></div><div className="cockpit-todo-grid">{todos.map((item, index) => <button key={item.title} onClick={() => setTodoIndex(index)}><strong>{item.count}</strong><span>{item.title}</span></button>)}<button onClick={() => setSelected({ insight: scopedInsights[0], action: false })}><strong>{scopedInsights.filter((item) => item.level !== 'opportunity').length}</strong><span>未处理风险</span></button></div><h4>需要关注</h4>{scopedInsights.filter((item) => item.level !== 'opportunity').map((item) => <button className={`cockpit-todo-risk ${item.level}`} key={item.id} onClick={() => setSelected({ insight: item, action: false })}><span>{item.title}</span><small>{levelNames[item.level]}</small></button>)}<small className="cockpit-muted">审批、失败和人工介入待办为工作区级样例；风险随店铺范围切换。</small></section>
        </div>

        <div className="cockpit-section-heading"><div><span className="cockpit-section-number">02</span><h2>风险与机会</h2><span>从影响追溯到原因</span></div><div className="cockpit-segment">{[['all', '全部'], ['high', '高优先级'], ['opportunity', '机会']].map(([value, label]) => <button key={value} aria-pressed={riskFilter === value} onClick={() => setRiskFilter(value)}>{label}</button>)}</div></div>
        <section className="cockpit-insights" aria-label="风险与机会列表">
          {visibleInsights.map((item) => <button className={`cockpit-insight ${item.level}`} key={item.id} onClick={() => setSelected({ insight: item, action: false })}><div className="cockpit-insight-meta"><span>{levelNames[item.level]}</span><small>{scopeNames[item.scope]}</small></div><h3>{item.title}</h3><span className="cockpit-entity">{item.entity}</span><p>{item.impact}</p><div className="cockpit-insight-footer"><span><DotChartOutlined /> {item.evidence.length} 项依据</span><span>查看分析 <ArrowRightOutlined /></span></div></button>)}
          {!visibleInsights.length && <div className="cockpit-empty">当前店铺的样例中没有这一类洞察，可切换筛选查看其他事项。</div>}
        </section>

        <div className="cockpit-section-heading" id="cockpit-actions"><div><span className="cockpit-section-number">03</span><h2>下一步行动</h2><span>先明确方案，再审批执行</span></div><small>{queued.filter((id) => scopedInsights.some((item) => item.id === id)).length} 项已加入演示计划</small></div>
        <section className="cockpit-panel cockpit-actions">{scopedInsights.map((item, index) => <div className="cockpit-action" key={item.id}><span className="cockpit-action-number">{String(index + 1).padStart(2, '0')}</span><div className="cockpit-action-body"><h3>{item.action}</h3><p>问题：{item.title}</p><p>{item.outcome}</p><span>{levelNames[item.level]} <i>·</i> {item.owner} <i>·</i> {queued.includes(item.id) ? '已加入演示计划，未提交审批' : '方案待确认'}</span></div><div className="cockpit-action-buttons"><Button icon={queued.includes(item.id) ? <CheckOutlined /> : <ArrowRightOutlined />} onClick={() => setSelected({ insight: item, action: true })}>{queued.includes(item.id) ? '查看计划' : '查看方案'}</Button><Button disabled={!canAsk} type="primary" onClick={() => startAnalysis(item)}>进入 AI 分析</Button></div></div>)}<div className="cockpit-action-note">分析入口携带当前对象、店铺、周期与样例证据。演示计划只保存在当前页面，不提交审批或更改业务数据。{queued.length > 0 && <button onClick={() => setQueued([])}>清空演示计划</button>}</div></section>

        <footer className="cockpit-footer"><div><ThunderboltOutlined /><span><strong>继续深入分析</strong><small>进入 AI 决策工作台，使用当前账号可访问的真实业务数据发起问题。</small></span></div><Button type="primary" disabled={!canAsk} onClick={() => navigate('/ai-assistant')}>{canAsk ? '打开 AI 决策工作台' : '需要 AI 助手访问权限'} <ArrowRightOutlined /></Button></footer>

        <Drawer title={selected?.action ? '行动方案预览' : '洞察详情'} open={!!selected} onClose={() => setSelected(null)} width="min(560px, 100vw)" className="cockpit-drawer">
          {selected && <><Tag color="purple">设计演示 · 虚构样例</Tag><h2>{selected.action ? selected.insight.action : selected.insight.title}</h2><p className="cockpit-muted">{scopeNames[selected.insight.scope]} / {selected.insight.entity}</p><h3>预期业务影响</h3><p>{selected.insight.impact}</p><h3>待验证假设</h3><p>{selected.insight.cause}</p><h3>判断依据</h3><Tag>样例观测 · 尚未核验真实数据</Tag><div className="cockpit-evidence">{selected.insight.evidence.map((item) => <div key={item.label}><span>{item.label}</span><strong>{item.value}</strong><small>{item.source}</small></div>)}</div><h3>建议行动</h3><ol className="cockpit-steps">{selected.insight.steps.map((step) => <li key={step}>{step}</li>)}</ol><div className="cockpit-outcome"><strong>{selected.insight.outcome}</strong><p>{selected.insight.constraint}</p><small>负责人角色：{selected.insight.owner} · 预期效果待验证</small></div><Button type="primary" block disabled={!canAsk} onClick={() => startAnalysis(selected.insight)}>进入 AI 分析</Button><Button block style={{ marginTop: 10 }} disabled={queued.includes(selected.insight.id)} onClick={() => setQueued((current) => [...current, selected.insight.id])}>{queued.includes(selected.insight.id) ? '已加入演示计划' : '加入演示计划'}</Button><p className="cockpit-muted">此流程仅使用演示上下文，不发起实际审批或执行。</p></>}
        </Drawer>
        <Drawer title="待办详情 · 工作区样例" open={todoIndex !== null} onClose={() => setTodoIndex(null)} width="min(480px, 100vw)">{todoIndex !== null && <><Tag color="purple">设计演示</Tag><h2>{todos[todoIndex].title}</h2><p>{todos[todoIndex].detail}</p><h3>下一步</h3><p>{todos[todoIndex].next}</p><p className="cockpit-muted">此处未接入真实任务或审批记录。</p></>}</Drawer>
        <Drawer title={`${metricNames[metric]} · 样例趋势明细`} open={tableOpen} onClose={() => setTableOpen(false)} width="min(600px, 100vw)"><p>虚构样例，前期数值按日序与当前周期对齐。</p><table className="cockpit-data-table"><thead><tr><th scope="col">日期</th><th scope="col">当前周期</th><th scope="col">前一周期</th></tr></thead><tbody>{chartRows.map((row) => <tr key={row.date}><th scope="row">{row.date}</th><td>{metricValue(metric, row.value)}</td><td>{metricValue(metric, row.previous)}</td></tr>)}</tbody></table></Drawer>
      </>
    )}
  </div>
}
