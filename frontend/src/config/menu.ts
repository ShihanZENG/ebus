import type { ReactNode } from 'react'

export interface NavNode {
  /** 叶子节点 key 即路由路径（不含前导斜杠）；规划项可标记 disabled。分组以 g- 开头。 */
  key: string
  label: string
  icon?: ReactNode
  disabled?: boolean
  children?: NavNode[]
}

/** ERP 业务导航。叶子 key 对应路由；g- 开头的节点仅用于分组。 */
const ERP_NAV: NavNode[] = [
  { key: 'dashboard', label: '首页' },
  { key: 'oms-reconciliation-prep', label: 'ERP ↔ OMS 对账准备' },
  {
    key: 'g-catalog',
    label: '商品中心',
    children: [
      { key: 'products', label: '商品' },
      { key: 'skus', label: 'SKU' },
      { key: 'listings', label: 'Listing 映射' },
    ],
  },
  {
    key: 'g-scm',
    label: '采购',
    children: [
      { key: 'purchase-plans', label: '采购计划' },
      { key: 'replenishment', label: '补货建议' },
      { key: 'purchase-orders', label: '采购单' },
      { key: 'purchase-amendments', label: '采购变更' },
      { key: 'purchase-approvals', label: '审批工作台' },
      { key: 'receiving', label: '收货单' },
      { key: 'suppliers', label: '供应商' },
      { key: 'purchase-supplier-quotation', label: '供应商报价' },
      { key: 'supply-infos', label: '当前供货价' },
    ],
  },
  {
    key: 'g-wms',
    label: '仓库物流',
    children: [
      { key: 'inventory', label: '库存余额' },
      { key: 'inbound', label: '入库单' },
      { key: 'shipments', label: '出库单' },
      { key: 'inventory-txns', label: '库存流水' },
      { key: 'warehouses', label: '仓库档案' },
    ],
  },
  {
    key: 'g-fba',
    label: 'FBA',
    children: [
      {
        key: 'g-fba-shipping',
        label: '发货流程',
        children: [
          { key: 'fba-plans', label: 'FBA 发货计划' },
          { key: 'fba-shipments', label: 'FBA 货件' },
          { key: 'fba-shipping-orders', label: 'FBA 发货单' },
          { key: 'fba-overseas-plans', label: '海外发货计划' },
        ],
      },
      {
        key: 'g-fba-inventory',
        label: '库存与费用',
        children: [
          { key: 'fba-overview', label: 'FBA 总览' },
          { key: 'fba-inventory', label: 'FBA 库存' },
          { key: 'fba-reconciliation', label: 'FBA 对账' },
          { key: 'fba-label-printing', label: '标签打印' },
        ],
      },
    ],
  },
  {
    key: 'g-ads',
    label: '广告',
    children: [{ key: 'ad-campaigns', label: '广告管理' }],
  },
  {
    key: 'g-service',
    label: '客服',
    children: [
      { key: 'customer-tickets', label: '客服工单' },
      { key: 'after-sales', label: '售后' },
    ],
  },
  {
    key: 'g-finance',
    label: '财务',
    children: [{ key: 'finance-settlements', label: '结算管理' }],
  },
  {
    key: 'g-statistics',
    label: '统计',
    children: [{ key: 'statistics', label: '经营统计' }],
  },
  {
    key: 'g-bi',
    label: 'BI',
    children: [{ key: 'datalab', label: '经营看板' }],
  },
  {
    key: 'g-tools',
    label: '工具',
    children: [{ key: 'agent-generations', label: '经营与客服生成' }, { key: 'dictionaries', label: '币种与单位' }],
  },
  {
    key: 'g-system',
    label: '设置',
    children: [
      { key: 'shops', label: '店铺资料' },
      { key: 'users', label: '账号与角色' },
      { key: 'audit-logs', label: '操作日志' },
    ],
  },
  {
    key: 'g-sales',
    label: '销售',
    children: [
      { key: 'orders', label: '销售订单' },
      { key: 'order-import', label: '订单导入' },
      { key: 'customers', label: '客户档案' },
    ],
  },
]

/**
 * AI 智能经营系统导航（2026-10-24 按「17→7 导航精简方案」收敛）。
 * 旧入口 → 新入口映射（需求编号全部保留，仅菜单去编号）：
 *   ai-dashboard(PG-001) → 经营驾驶舱；ai-copilot(PG-002) → AI Copilot
 *   g-ai-risk(PG-004/005/006) + 经营任务历史(PG-019) + Agent 任务追踪(PG-007/008 业务侧) → 风险与任务中心
 *   g-ai-strategy(PG-009/010) + g-ai-sim(PG-011/012) + 策略模板(PG-020) → 策略决策中心（组 key g-ai-strategy）
 *   g-ai-approval(PG-013/014) + g-ai-execution(PG-015/016) → 审批与执行中心
 *     （ai-approval-center 策略审批；ai-execution-center 策略执行与监控，执行状态/异常/记录/审计保留）
 *   g-ai-effect(PG-017/018) → 效果复盘中心
 *   g-ai-capability 7 个业务场景 → 业务智能应用
 *   g-ai-agent 技术编排（Prompt 配置/工具注册/模型调用追踪）→ LIM 智能中间层
 */
const AI_NAV: NavNode[] = [
  { key: 'ai-dashboard', label: '经营驾驶舱' },
  { key: 'ai-copilot', label: 'AI Copilot' },
  {
    key: 'g-ai-risk-task',
    label: '风险与任务中心',
    children: [
      { key: 'ai-risk-center', label: '风险事件与规则' },
      { key: 'ai-task-history', label: '经营任务历史' },
      { key: 'ai-agent-workbench', label: 'Agent 任务追踪' },
    ],
  },
  {
    key: 'g-ai-strategy',
    label: '策略决策中心',
    children: [
      { key: 'ai-strategy-center', label: '策略工作台（任务/生成/仿真/方案对比）' },
      { key: 'ai-strategy-templates', label: '策略模板' },
    ],
  },
  {
    key: 'g-ai-approval-execution',
    label: '审批与执行中心',
    children: [
      { key: 'ai-approval-center', label: '策略审批' },
      { key: 'ai-execution-center', label: '策略执行与监控' },
    ],
  },
  {
    key: 'g-ai-effect',
    label: '效果复盘中心',
    children: [
      { key: 'ai-effect-overview', label: '效果评估与复盘' },
    ],
  },
  {
    key: 'g-ai-capability',
    label: '业务智能应用',
    children: [
      { key: 'ai-capability', label: '应用中心' },
      { key: 'product-agent', label: '商品与 Listing AI' },
      { key: 'operations-agent', label: '销售订单 AI' },
      { key: 'lim-replenishment', label: '库存补货 AI' },
      { key: 'purchase-agent', label: '采购供应链 AI' },
      { key: 'ad-growth', label: '广告增长 AI' },
      { key: 'profit-finance', label: '财务利润 AI' },
      { key: 'customer-agent', label: '客服售后 AI' },
    ],
  },
]

const LIM_NAV: NavNode[] = [
  { key: 'lim-console', label: '01 平台总览' },
  { key: 'lim-workbench', label: '多智能体 LIM 工作台' },
  { key: 'lim-model-gateway', label: '02 模型网关' },
  { key: 'lim-agent-runtime', label: '03 智能体运行时' },
  { key: 'lim-tool-registry', label: '04 工具注册中心' },
  { key: 'lim-knowledge', label: '05 知识检索与来源治理' },
  { key: 'lim-skills', label: '06 记忆与技能治理' },
  {
    key: 'g-lim-operations',
    label: '运行治理',
    children: [
      { key: 'lim-workflow', label: '07 工作流编排' },
      { key: 'lim-runs', label: '08 运行追踪' },
      { key: 'lim-eval', label: '09 评测与回归' },
      { key: 'lim-alerts', label: '10 运行告警' },
    ],
  },
  { key: 'lim-safety', label: '11 安全与治理' },
  { key: 'lim-diagnosis', label: '12 多智能体联合诊断' },
]

const STOREFRONT_NAV: NavNode[] = [
  { key: 'storefront', label: '站点运营后台' },
]

export interface SystemNavigation {
  id: 'erp' | 'ai' | 'lim' | 'storefront'
  name: string
  mark: string
  homePage: string
  nav: NavNode[]
}

export const SYSTEM_NAV: SystemNavigation[] = [
  { id: 'erp', name: 'ERP 业务系统', mark: 'E', homePage: 'dashboard', nav: ERP_NAV },
  { id: 'ai', name: 'AI 智能经营系统', mark: 'A', homePage: 'ai-dashboard', nav: AI_NAV },
  { id: 'lim', name: 'LIM 智能中间层', mark: 'L', homePage: 'lim-console', nav: LIM_NAV },
  { id: 'storefront', name: 'Storefront 独立站', mark: 'S', homePage: 'storefront', nav: STOREFRONT_NAV },
]

const SYSTEM_ONLY_ROUTES: Record<SystemNavigation['id'], Set<string>> = {
  erp: new Set(),
  ai: new Set(['ai/tasks', 'ai-dashboard', 'ai-copilot', 'ai-copilot-analysis', 'ai-risk-center', 'ai-strategy-center', 'ai-approval-center', 'ai-execution-center', 'ai-agent-workbench', 'ai-agent-collab', 'ai-effect-overview', 'ai-effect', 'ai-task-history', 'ai-strategy-templates', 'ai-capability', 'product-agent', 'operations-agent', 'lim-replenishment', 'purchase-agent', 'ad-growth', 'profit-finance', 'customer-agent']),
  lim: new Set(['lim-console', 'lim-workbench', 'lim-agent-runtime', 'lim-tool-registry', 'lim-workflow', 'lim-runs', 'lim-alerts', 'lim-eval', 'lim-knowledge', 'lim-skills', 'lim-model-gateway', 'lim-diagnosis']),
  storefront: new Set(['storefront']),
}

export function findSystemNavigation(path: string): SystemNavigation {
  const route = path.replace(/^\/+|\/+$/g, '')
  return SYSTEM_NAV.find((system) =>
    [...SYSTEM_ONLY_ROUTES[system.id]].some((key) => route === key || route.startsWith(key + '/')),
  ) ?? SYSTEM_NAV[0]
}

/** 详情路由（带 :id 或子路径）到其所属分组 + 代表性叶子的映射，用于侧栏分组高亮与页签标签。 */
export const DETAIL_ROUTE_GROUP: Record<string, { group: string; leaf: string | null }> = {
  'ai-agent-collab': { group: 'g-ai-risk-task', leaf: 'ai-agent-workbench' },
  'ai-effect': { group: 'g-ai-effect', leaf: 'ai-effect-overview' },
}

/**
 * 计算某路径在所属系统导航中的「叶子 + 分组」状态，兼容详情路由。
 * - 返回 group = 离该路由最近的祖先分组 key（用于侧栏分组高亮）。
 * - 返回 leaf = 精确匹配的叶子 key；详情路由经映射后可能回指某个真实叶子（如 ai-copilot-analysis → ai-copilot、ai/tasks → ai-strategy-center）。
 */
export function resolveNavState(pathname: string, systemId: string): { leaf: string | null; group: string | null } {
  const route = pathname.replace(/^\/+|\/+$/g, '')
  if (!route) return { leaf: null, group: null }
  const head = route.split('/')[0]
  if (systemId === 'ai') {
    if (route.startsWith('ai/tasks')) return { leaf: 'ai-strategy-center', group: 'g-ai-strategy' }
    if (head === 'ai-copilot-analysis') return { leaf: 'ai-copilot', group: null }
    if (DETAIL_ROUTE_GROUP[head]) return { leaf: DETAIL_ROUTE_GROUP[head].leaf, group: DETAIL_ROUTE_GROUP[head].group }
  }
  const sys = SYSTEM_NAV.find((s) => s.id === systemId)
  if (!sys) return { leaf: null, group: null }
  const walk = (nodes: NavNode[], ancestor: string | null): { leaf: string | null; group: string | null } => {
    for (const n of nodes) {
      if (n.key === route) return { leaf: n.key, group: ancestor }
      if (n.children) {
        const r = walk(n.children, n.key)
        if (r.leaf || r.group) return r
      }
    }
    return { leaf: null, group: null }
  }
  return walk(sys.nav, null)
}

/** Backward-compatible ERP navigation for permission and API metadata consumers. */
export const NAV = ERP_NAV

/** 按路由 key 找到「分组 → 叶子」的路径，用于面包屑与页面标题。 */
export function findNavPath(key: string, nodes: NavNode[] = NAV): string[] {
  const walk = (nodes: NavNode[], path: string[]): string[] => {
    for (const node of nodes) {
      const next = [...path, node.label]
      if (node.key === key) return next
      if (node.children) {
        const found = walk(node.children, next)
        if (found.length) return found
      }
    }
    return []
  }
  return walk(nodes, [])
}

export function findNavGroup(key: string): NavNode | undefined {
  return NAV.find((node) => node.key === key || node.children?.some((child) =>
    child.key === key || child.children?.some((leaf) => leaf.key === key),
  ))
}

/** 页面所需的后端权限；users 管理页仅管理员可见。 */
export const NAV_PERMISSION: Record<string, string> = {
  'ai-risk-center': 'purchase_agent:read',
  'ai-strategy-center': 'purchase_agent:read',
  'ai-approval-center': 'purchase_agent:read',
  'ai-execution-center': 'purchase_agent:read',
  'ai-copilot': 'assistant:read',
  'ai-copilot-analysis': 'assistant:read',
  'ai-agent-workbench': 'assistant:read',
  'ai-agent-collab': 'assistant:read',
  'ai-effect-overview': 'assistant:read',
  'ai-effect': 'assistant:read',
  'ai-strategy-templates': 'assistant:read',
  'ai-capability': 'assistant:read',
  'ai-dashboard': 'dashboard:read',
  'ai-assistant': 'assistant:read',
  'ai-task-history': 'assistant:read',
  'lim-console': 'assistant:read',
  'lim-workbench': 'assistant:read',
  'lim-agent-runtime': 'assistant:read',
  'lim-tool-registry': 'assistant:read',
  'lim-workflow': 'assistant:read',
  'lim-runs': 'assistant:read',
  'lim-alerts': 'assistant:read',
  'lim-eval': 'assistant:read',
  'lim-knowledge': 'assistant:read',
  'lim-skills': 'assistant:read',
  'lim-model-gateway': 'assistant:read',
  'lim-safety': 'assistant:read',
  'lim-diagnosis': 'assistant:read',
  'lim-replenishment': 'purchase_agent:read',
  'oms-reconciliation-prep': 'orders:read',
  'product-agent': 'assistant:read',
  'operations-agent': 'assistant:read',
  'ad-growth': 'advertising_agent:write',
  'profit-finance': 'finance_agent:write',
  'customer-agent': 'customer_tickets:read',
  products: 'products:read',
  skus: 'skus:read',
  listings: 'listings:read',
  storefront: 'storefront:read',
  orders: 'orders:read',
  customers: 'customers:read',
  'order-import': 'orders:read',
  'after-sales': 'after_sales:read',
  'customer-tickets': 'customer_tickets:read',
  inventory: 'inventory:read',
  inbound: 'inbound_orders:read',
  shipments: 'shipments:read',
  'inventory-txns': 'inventory:read',
  'fba-plans': 'fba_plans:read',
  'fba-shipments': 'fba_plans:read',
  'fba-shipping-orders': 'fba_plans:read',
  'fba-overseas-plans': 'fba_plans:read',
  'fba-overview': 'fba_plans:read',
  'fba-inventory': 'fba_plans:read',
  'fba-reconciliation': 'fba_plans:read',
  'fba-label-printing': 'fba_plans:read',
  'purchase-orders': 'purchase_orders:read',
  'purchase-plans': 'purchase_plans:read',
  'purchase-amendments': 'purchase_amendments:read',
  'purchase-approvals': 'purchase_orders:read',
  receiving: 'purchase_orders:read',
  'purchase-supplier-quotation': 'supplier_quotes:read',
  'purchase-agent': 'purchase_agent:read',
  replenishment: 'replenishment:read',
  'supply-infos': 'supplier_skus:read',
  shops: 'shops:read',
  warehouses: 'warehouses:read',
  suppliers: 'suppliers:read',
  dictionaries: 'dictionaries:read',
  'audit-logs': 'audit:read',
  datalab: 'dashboard:read',
  statistics: 'dashboard:read',
  'ad-campaigns': 'dashboard:read',
  'finance-settlements': 'dashboard:read',
}

/** 各页面对应的后端接口，用于排查数据来源。 */
export const MODULE_API: Record<string, string> = {
  'ai-dashboard': '聚合：/api/v1/orders/summary + /inventory/summary + /purchase-orders/summary + /replenishment-suggestions/summary（真实业务接口）',
  'ai-assistant': 'POST /api/v1/assistant/ask',
  'ai-task-history': '/api/v1/assistant/tasks（真实接口）',
  'lim-console': '/api/v1/lim/*',
  'lim-safety': 'GET /api/v1/lim/safety/overview',
  'lim-diagnosis': 'POST /api/v1/lim/diagnoses（LangGraph 多智能体联合诊断；复用 business_evidence_tools 只读证据工具，supervisor→并行 workers→synthesis）',
  'lim-replenishment': '/api/v1/purchase-agent/profiles + /api/v1/lim/runs + /traces',
  'oms-reconciliation-prep': '/api/v1/reconciliation-prep/erp-orders + browser-local OMS JSON comparison',
  'product-agent': 'POST /api/v1/agents/product/ask',
  'operations-agent': 'POST /api/v1/agents/operations/ask',
  'customer-agent': 'POST /api/v1/agents/customer/draft/{ticket_id}',
  'ad-growth': 'POST /api/v1/agent-generations/ads + GET /api/v1/generation-reviews?kind=ads',
  'profit-finance': 'POST /api/v1/agent-generations/profit + POST /api/v1/profit-reconciliations/fee-discrepancies + GET /api/v1/generation-reviews?kind=profit',
  dashboard: '聚合：/orders + /inventory + /purchase-orders + /replenishment-suggestions',
  products: '/api/v1/products',
  skus: '/api/v1/skus',
  listings: '/api/v1/listings',
  storefront: '/api/v1/storefront/products',
  orders: '/api/v1/orders',
  'order-import': 'POST /api/v1/orders/import',
  'after-sales': '/api/v1/orders/{id}/after-sales',
  'customer-tickets': '/api/v1/customer-tickets',
  inventory: '/api/v1/inventory',
  inbound: '/api/v1/inbound-orders',
  shipments: '/api/v1/shipments',
  'inventory-txns': '/api/v1/inventory/transactions',
  'fba-plans': '/api/v1/fba-plans',
  'purchase-orders': '/api/v1/purchase-orders',
  'purchase-plans': '/api/v1/purchase-plans',
  'purchase-amendments': '/api/v1/purchase-amendments',
  'purchase-approvals': '/api/v1/purchase-orders?status=submitted',
  receiving: '/api/v1/purchase-orders/{id}/receipts',
  'purchase-supplier-quotation': '/api/v1/supplier-quotes',
  'purchase-agent': '/api/v1/purchase-agent/decide',
  'agent-generations': '/api/v1/agent-generations',
  replenishment: '/api/v1/replenishment-suggestions',
  'supply-infos': '/api/v1/supply-infos',
  shops: '/api/v1/shops',
  warehouses: '/api/v1/warehouses',
  suppliers: '/api/v1/suppliers',
  dictionaries: '/api/v1/dictionaries',
  users: '/api/v1/users',
  'audit-logs': '/api/v1/audit-logs',
  datalab: '/api/v1/datalab/overview',
  'ai-copilot': 'POST /api/v1/assistant/ask（真实，只读）',
  'ai-copilot-analysis': '复用 /assistant/ask 返回；结构化图表/工具结果属规划中能力',
  'ai-risk-center': 'GET /api/v1/decision-center/risks + /tasks（真实后端）',
  'ai-strategy-center': 'GET /api/v1/decision-center/tasks + 仿真版本（真实后端）',
  'ai-approval-center': 'POST /api/v1/decision-center/tasks/{id}/submit|approve|reject（真实后端）',
  'ai-execution-center': 'POST /api/v1/decision-center/tasks/{id}/execute|confirm + 任务/执行记录（真实后端）',
  'ai-agent-workbench': '前端构造演示数据（设计演示·虚构样例）',
  'ai-agent-collab': '前端构造演示数据（设计演示·虚构样例）',
  'ai-effect-overview': '前端构造演示数据（设计演示·虚构样例）',
  'ai-effect': '前端构造演示数据（设计演示·虚构样例）',
  'ai-strategy-templates': '前端构造演示数据（设计演示·虚构样例）',
  'ai-capability': '枢纽页：跳转 7 个业务场景 AI（各自真实接口）',
}
