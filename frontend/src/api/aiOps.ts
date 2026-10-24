/**
 * AI 智能经营系统（4.4）前端数据 / 接口层。
 *
 * 设计原则（来自项目硬约定）：
 * 1. 真实优先 —— 后端已具备的接口直接调用，数据真实：
 *    - 经营快照汇总（订单 / 库存 / 采购 / 补货）：/orders/summary 等 4 接口；
 *    - AI 经营 Copilot 问答：/assistant/ask；经营任务历史：/assistant/tasks；
 *    - 风险中心 / 策略生成 / 仿真 / 审批 / 执行：真实后端 /api/v1/decision-center/*，
 *      由前端既有 DecisionCenterPage 统一承载（不在此文件构造演示数据）。
 * 2. 演示数据必须标来源 —— 仅 AI-M04 经营 Agent 协作、AI-M09 效果评估、AI-M10 策略模板
 *    属于本期尚未在后端落地的业务概念，本文件以「设计演示 · 虚构样例」形式给出前端构造数据，
 *    页面会用 DemoNote 横幅明确隔离，绝不伪装成真实接口数据。
 */
import { request } from './client'

// ---------------------------------------------------------------------------
// 通用类型
// ---------------------------------------------------------------------------
export type DataStatus = 'available' | 'missing' | 'unavailable'
export interface DataMeta {
  source: string
  source_mode: string
  data_status: DataStatus
  record_count?: number
  last_record_updated_at?: string | null
}

// ---------------------------------------------------------------------------
// 真实数据：经营快照汇总（与 AiDashboardLiveSnapshot 同口径）
// ---------------------------------------------------------------------------
export interface OrderSummary {
  total: number
  by_status: Record<string, number>
  by_currency: { code: string; amount: string }[]
  data_meta: DataMeta
}
export interface InventorySummary {
  available_qty: number
  low_stock_count: number
  low_stock_threshold: number
  data_meta: DataMeta
}
export interface PurchaseSummary {
  total: number
  by_status: Record<string, number>
  data_meta: DataMeta
}
export interface ReplenishmentSummary {
  pending_count: number
  pending_sku_count: number
  data_meta: DataMeta
}
export interface CockpitData {
  orders: OrderSummary | null
  inventory: InventorySummary | null
  purchases: PurchaseSummary | null
  replenishment: ReplenishmentSummary | null
}

/** 拉取四类经营汇总；任一失败不影响其余展示。需由调用方按权限过滤。 */
export async function fetchCockpit(
  can: (p: string) => boolean,
): Promise<{ data: CockpitData; error: boolean }> {
  const [orders, inventory, purchases, replenishment] = await Promise.allSettled([
    can('orders:read') ? request<OrderSummary>('/orders/summary') : Promise.resolve(null),
    can('inventory:read') ? request<InventorySummary>('/inventory/summary') : Promise.resolve(null),
    can('purchase_orders:read') ? request<PurchaseSummary>('/purchase-orders/summary') : Promise.resolve(null),
    can('replenishment:read') ? request<ReplenishmentSummary>('/replenishment-suggestions/summary') : Promise.resolve(null),
  ])
  const unwrap = <T,>(r: PromiseSettledResult<T | null>): T | null => (r.status === 'fulfilled' ? r.value : null)
  return {
    data: {
      orders: unwrap(orders),
      inventory: unwrap(inventory),
      purchases: unwrap(purchases),
      replenishment: unwrap(replenishment),
    },
    error: [orders, inventory, purchases, replenishment].some((r) => r.status === 'rejected'),
  }
}

// ---------------------------------------------------------------------------
// 真实数据：AI 经营 Copilot（复用经营助手问答接口）
// ---------------------------------------------------------------------------
export type Reference = { ref_id: string; path: string; section: string; start_line: number; end_line: number; excerpt: string }
export interface AskResult {
  reply: string
  sources: string[]
  references?: Reference[]
  read_only: boolean
}
export interface CopilotAnalysis {
  id: string
  question: string
  reply: string
  sources: string[]
  references: Reference[]
  read_only: boolean
  askedAt: string
}

export function askCopilot(message: string): Promise<AskResult> {
  return request<AskResult>('/assistant/ask', { method: 'POST', body: { message } })
}

// ---------------------------------------------------------------------------
// 真实数据：经营任务历史（复用助手任务接口）
// ---------------------------------------------------------------------------
export type AssistantTaskStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'
export interface AssistantTask {
  run_id: string
  goal: string
  status: AssistantTaskStatus
  created_at: string
  finished_at?: string | null
  trace_id?: string | null
  error_code?: string | null
}
export interface TaskPage {
  items: AssistantTask[]
  total: number
}
export function fetchAssistantTasks(page = 1, pageSize = 20): Promise<TaskPage> {
  return request<TaskPage>('/assistant/tasks', { params: { page, page_size: pageSize } })
}

// ===========================================================================
// 以下为「设计演示 · 虚构样例」数据（后端对应能力尚未落地）
// 每个对象均携带 source: 'demo'，页面用 DemoNote 横幅隔离。
// ===========================================================================
export const DEMO_SOURCE = 'demo'

// ---------------------------------------------------------------------------
// AI-M04 经营 Agent 协作
// ---------------------------------------------------------------------------
export type AgentStatus = 'online' | 'busy' | 'offline'
export interface AgentRole {
  id: string
  name: string
  domain: string
  description: string
  status: AgentStatus
  tasksHandled: number
  avgLatencyMs: number
  tools: string[]
  source: 'demo'
}
export interface CollabStep {
  agentId: string
  agentName: string
  action: string
  status: 'done' | 'running' | 'pending'
  output: string
}
export interface CollabTask {
  id: string
  title: string
  coordinator: string
  participants: string[]
  status: 'running' | 'completed' | 'failed'
  progress: number
  steps: CollabStep[]
  createdAt: string
  source: 'demo'
}

const demoAgents: AgentRole[] = [
  { id: 'AG-OPS', name: '运营 Agent', domain: '销售订单 / 库存 / 采购', description: '只读查询订单、库存、采购与补货，解释异常并生成核对结论。', status: 'online', tasksHandled: 1284, avgLatencyMs: 820, tools: ['orders', 'inventory', 'purchase-orders', 'replenishment'], source: 'demo' },
  { id: 'AG-SUPPLY', name: '供应链 Agent', domain: '补货 / 采购 / 发货', description: '基于销量与在途生成补货与采购草稿，提交人工审批。', status: 'busy', tasksHandled: 642, avgLatencyMs: 1510, tools: ['scm.decide', 'purchase-draft', 'fba-plan'], source: 'demo' },
  { id: 'AG-FIN', name: '财务 Agent', domain: '利润 / 对账 / 结算', description: '复算利润与费用差异，生成可审计的财务草稿。', status: 'online', tasksHandled: 318, avgLatencyMs: 1120, tools: ['profit-reconciliations', 'fee-discrepancies'], source: 'demo' },
  { id: 'AG-ADS', name: '广告 Agent', domain: '广告增长 / 预算', description: '评估 ACOS/ROAS，生成预算与文案建议草稿。', status: 'online', tasksHandled: 205, avgLatencyMs: 980, tools: ['ads-report', 'ads-draft'], source: 'demo' },
  { id: 'AG-SERVICE', name: '客服 Agent', domain: '工单 / 售后', description: '基于已审核规则拟定回复草稿，人工发送。', status: 'offline', tasksHandled: 156, avgLatencyMs: 640, tools: ['customer-tickets', 'reply-draft'], source: 'demo' },
]

const demoCollabTasks: CollabTask[] = [
  {
    id: 'COL-2026-0077', title: '美国站断货应急：补货 + 促销降速联合作业', coordinator: '运营 Agent',
    participants: ['运营 Agent', '供应链 Agent', '广告 Agent'], status: 'running', progress: 60,
    createdAt: '2026-10-23 09:20',
    steps: [
      { agentId: 'AG-OPS', agentName: '运营 Agent', action: '识别缺货 SKU 与影响范围', status: 'done', output: 'SKU-US-NAVA-001 预计 1.6 天触底，影响 47 笔待发货。' },
      { agentId: 'AG-SUPPLY', agentName: '供应链 Agent', action: '生成加急补货草稿', status: 'done', output: '补货 600 件 / 加急渠道，ETA 6 天，已提交审批。' },
      { agentId: 'AG-ADS', agentName: '广告 Agent', action: '生成降速投放建议', status: 'running', output: '正在评估 Top 20 关键词降速 30% 的销量影响…' },
      { agentId: 'AG-OPS', agentName: '运营 Agent', action: '汇总处置方案', status: 'pending', output: '待前序步骤完成后汇总。' },
    ],
    source: 'demo',
  },
  {
    id: 'COL-2026-0075', title: '欧洲站毛利修复：调价 + 投放优化', coordinator: '财务 Agent',
    participants: ['财务 Agent', '广告 Agent', '运营 Agent'], status: 'completed', progress: 100,
    createdAt: '2026-10-21 15:00',
    steps: [
      { agentId: 'AG-FIN', agentName: '财务 Agent', action: '定位负毛利 SKU', status: 'done', output: 'SKU-EU-COFFEE-02 加权毛利 -3.1%。' },
      { agentId: 'AG-ADS', agentName: '广告 Agent', action: '暂停低效词', status: 'done', output: '暂停 14 个 ACOS>50% 词。' },
      { agentId: 'AG-OPS', agentName: '运营 Agent', action: '生成调价建议', status: 'done', output: '建议提价 6%，恢复至正毛利。' },
    ],
    source: 'demo',
  },
]

export function fetchAgents(): Promise<AgentRole[]> {
  return Promise.resolve(structuredClone(demoAgents))
}
export function fetchCollabTasks(): Promise<CollabTask[]> {
  return Promise.resolve(structuredClone(demoCollabTasks))
}

// ---------------------------------------------------------------------------
// AI-M09 效果评估中心
// ---------------------------------------------------------------------------
export interface EffectMetric {
  metric: string
  plan: string
  actual: string
  deviation: string
  rating: 'good' | 'warn' | 'bad'
}
export interface EffectRecord {
  id: string
  strategyId: string
  title: string
  rating: 'good' | 'warn' | 'bad'
  reviewedAt: string
  metrics: EffectMetric[]
  comment: string
  source: 'demo'
}

const demoEffects: EffectRecord[] = [
  {
    id: 'EFF-2026-0501', strategyId: 'STR-2026-0385', title: '欧洲站咖啡毛利修复复盘',
    rating: 'good', reviewedAt: '2026-10-23 08:00',
    metrics: [
      { metric: '加权毛利', plan: '≥ 5%', actual: '5.4%', deviation: '+0.4pp', rating: 'good' },
      { metric: '利润贡献', plan: '+$5,200', actual: '+$5,480', deviation: '+$280', rating: 'good' },
      { metric: '转化率', plan: '降幅 ≤ 5%', actual: '-3.2%', deviation: '优于预期', rating: 'good' },
    ],
    comment: '提价与暂停低效词组合生效，转化损失可控，建议固化为止损基线。',
    source: 'demo',
  },
  {
    id: 'EFF-2026-0498', strategyId: 'STR-2026-0372', title: '美东仓出库时效优化复盘',
    rating: 'warn', reviewedAt: '2026-10-22 09:00',
    metrics: [
      { metric: '平均出库时长', plan: '≤ 24h', actual: '29h', deviation: '+5h', rating: 'warn' },
      { metric: '受影响订单', plan: '≤ 100', actual: '148', deviation: '+48', rating: 'warn' },
    ],
    comment: '波次优化见效但未达标，需补充峰值产能或延长作业窗口。',
    source: 'demo',
  },
]

export function fetchEffects(): Promise<EffectRecord[]> {
  return Promise.resolve(structuredClone(demoEffects))
}
export function fetchEffect(id: string): Promise<EffectRecord | null> {
  return Promise.resolve(demoEffects.find((e) => e.id === id) ? structuredClone(demoEffects.find((e) => e.id === id)!) : null)
}

// ---------------------------------------------------------------------------
// AI-M10 经营策略模板
// ---------------------------------------------------------------------------
export interface StrategyTemplate {
  id: string
  name: string
  scenario: string
  description: string
  params: { key: string; value: string }[]
  usageCount: number
  source: 'demo'
}

const demoTemplates: StrategyTemplate[] = [
  { id: 'TPL-001', name: '断货应急标准模板', scenario: '单 SKU 可用库存覆盖天数 < 3 天', description: '自动生成加急补货 + 促销降速候选方案并仿真。', params: [{ key: '覆盖天数阈值', value: '3 天' }, { key: '加急渠道', value: '空运' }, { key: '降速幅度', value: '15%' }], usageCount: 23, source: 'demo' },
  { id: 'TPL-002', name: '负毛利修复模板', scenario: '加权贡献毛利 < 0', description: '组合调价与广告优化，约束提价幅度。', params: [{ key: '提价上限', value: '8%' }, { key: 'ACOS 目标', value: '≤ 35%' }], usageCount: 15, source: 'demo' },
  { id: 'TPL-003', name: '广告预算再分配模板', scenario: '总预算不变需提升 ROAS', description: '跨活动再分配预算并仿真 ROAS 变化。', params: [{ key: '总预算', value: '沿用现有' }, { key: 'ROAS 目标', value: '+15%' }], usageCount: 9, source: 'demo' },
  { id: 'TPL-004', name: '旺季备货模板', scenario: '大促前 60 天', description: '基于历史销量与安全库存生成备货计划草稿。', params: [{ key: '提前期', value: '60 天' }, { key: '安全库存', value: '1.5×' }], usageCount: 31, source: 'demo' },
]

export function fetchTemplates(): Promise<StrategyTemplate[]> {
  return Promise.resolve(structuredClone(demoTemplates))
}
