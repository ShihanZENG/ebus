// Fictional design fixtures. Never submit these IDs, amounts, or proposals to business APIs.
export type Scope = 'all' | 'us' | 'de'
export type Metric = 'sales' | 'profit' | 'orders' | 'conversion' | 'ads' | 'inventory' | 'turnover'
export const scopeNames: Record<Scope, string> = { all: '全部店铺', us: 'Amazon · 美国店', de: 'Amazon · 德国店' }
export const metricNames: Record<Metric, string> = { sales: '销售额', profit: '贡献利润', orders: '订单量', conversion: '转化率', ads: '广告花费', inventory: '缺货风险 SKU', turnover: '库存周转天数' }
export interface Insight {
  id: string
  scope: 'us' | 'de'
  level: 'high' | 'medium' | 'opportunity'
  title: string
  entity: string
  impact: string
  cause: string
  evidence: { label: string; value: string; source: string }[]
  action: string
  outcome: string
  owner: string
  steps: string[]
  constraint: string
}
export const insights: Insight[] = [
  { id: 'stock', scope: 'us', level: 'high', title: '主力商品可能在补货到达前断货', entity: '便携咖啡机 · CF-01', impact: '若维持当前销量，预计存在 5 天供货缺口。', cause: '近 7 天需求上升，现有可售库存覆盖时间短于预计补货周期。', evidence: [{ label: '库存可售天数', value: '8 天', source: '样例库存与日均销量' }, { label: '补货预计到达', value: '13 天后', source: '样例采购在途计划' }, { label: '近 7 天日均销量', value: '46 件', source: '样例商品销售记录' }], action: '优先评估 CF-01 紧急补货', outcome: '目标：缩短约 5 天供货缺口', owner: '采购负责人', steps: ['核对可用库存和采购在途数量', '比较加急物流与跨仓调拨成本', '提交补货方案，由采购负责人审批'], constraint: '需核实供应商承诺交期、物流成本和可调拨库存。' },
  { id: 'ads', scope: 'us', level: 'high', title: '广告支出增长快于销售贡献', entity: '品牌词拓展 · 广告组 A', impact: '广告成本正在压缩主力商品的贡献利润。', cause: '部分搜索词点击成本抬升，新增流量未带来相应的订单增长。', evidence: [{ label: '广告投入产出比', value: '2.4 → 1.8', source: '样例广告归因报表' }, { label: '单次点击成本', value: '+18.6%', source: '样例广告费用记录' }, { label: '广告转化率', value: '−0.8 个百分点', source: '样例投放转化数据' }], action: '复核低效搜索词与广告预算', outcome: '目标：在保留核心流量的同时控制支出', owner: '增长负责人', steps: ['核对广告归因窗口和搜索词表现', '模拟降低低效词出价的影响', '经运营审批后调整预算并跟踪转化'], constraint: '预算调整可能影响曝光，需保留对照组观察。' },
  { id: 'returns', scope: 'de', level: 'medium', title: '同一规格的退货原因集中出现', entity: '保温杯 · TM-02', impact: '规格理解偏差可能继续增加售后成本。', cause: '近期退货反馈集中在容量预期，商品图片和文案可能表达不够清楚。', evidence: [{ label: '近 7 天退货申请', value: '12 笔', source: '样例售后工单' }, { label: '涉及容量描述', value: '8 笔', source: '样例退货原因分类' }, { label: '当前详情页', value: '缺少尺寸对照', source: '样例 Listing 审阅' }], action: '补充商品容量说明与对照图', outcome: '目标：减少规格误解导致的退货', owner: '商品负责人', steps: ['抽查售后工单并核实产品规格', '起草容量说明和尺寸对照内容', '人工审核发布后跟踪退货原因变化'], constraint: '文案和图片应与真实商品规格一致。' },
  { id: 'growth', scope: 'de', level: 'opportunity', title: '高转化商品仍有增长空间', entity: '旅行收纳套装 · TR-03', impact: '库存充足、转化稳定，可评估增量流量机会。', cause: '自然访问转化表现良好，当前曝光规模仍较小。', evidence: [{ label: '商品转化率', value: '5.8%', source: '样例商品访问数据' }, { label: '库存覆盖', value: '42 天', source: '样例库存预测' }, { label: '贡献利润率', value: '24.1%', source: '样例成本拆解' }], action: '设计小规模增长实验', outcome: '目标：验证新增曝光能否带来增量利润', owner: '运营负责人', steps: ['确定实验预算和利润底线', '设置小范围流量实验及对照组', '按利润与转化变化决定是否扩大'], constraint: '效果为待验证假设，先设置预算上限。' },
]

export function makeScenario(scope: Scope, days: 7 | 30) {
  const rows = Array.from({ length: days }, (_, index) => {
    const day = 30 - days + index
    const date = new Date(Date.UTC(2026, 8, 22 + day))
    const variation = [0.90, 0.96, 1.02, 0.95, 1.08, 1.14, 1.03][day % 7]
    const stores = (['us', 'de'] as const).filter((store) => scope === 'all' || store === scope)
    let sales = 0, profit = 0, orders = 0, visits = 0, previousSales = 0, previousProfit = 0, previousOrders = 0, previousVisits = 0, ads = 0, previousAds = 0, inventory = 0, previousInventory = 0, turnover = 0, previousTurnover = 0
    stores.forEach((store) => {
      const base = store === 'us' ? 11200 : 7600
      const revenue = Math.round(base * variation * (1 + day * 0.009))
      const previous = Math.round(base * variation * (1 + day * 0.003))
      const count = Math.round(revenue / (store === 'us' ? 69 : 58))
      const beforeCount = Math.round(previous / (store === 'us' ? 68 : 57))
      sales += revenue
      profit += Math.round(revenue * (store === 'us' ? 0.205 - day * 0.001 : 0.218))
      orders += count
      visits += Math.round(count / (store === 'us' ? 0.031 : 0.038))
      previousSales += previous
      previousProfit += Math.round(previous * 0.219)
      previousOrders += beforeCount
      previousVisits += Math.round(beforeCount / 0.032)
      ads += Math.round(revenue * (store === 'us' ? 0.12 + day * 0.001 : 0.09))
      previousAds += Math.round(previous * 0.10)
      inventory += store === 'us' ? 3 + Math.floor(day / 8) : 1
      previousInventory += store === 'us' ? 3 : 1
      turnover += store === 'us' ? 48 - day * 0.2 : 40
      previousTurnover += store === 'us' ? 49 : 43
    })
    return { date: `${date.getUTCMonth() + 1}/${date.getUTCDate()}`, sales, profit, orders, visits, previousSales, previousProfit, previousOrders, previousVisits, ads, previousAds, inventory, previousInventory, turnover: turnover / stores.length, previousTurnover: previousTurnover / stores.length }
  })
  const sum = (key: keyof typeof rows[number]) => rows.reduce((total, row) => total + Number(row[key]), 0)
  const last = rows[rows.length - 1]
  const current = { sales: sum('sales'), profit: sum('profit'), orders: sum('orders'), conversion: sum('orders') / sum('visits') * 100, ads: sum('ads'), inventory: last.inventory, turnover: last.turnover }
  const previous = { sales: sum('previousSales'), profit: sum('previousProfit'), orders: sum('previousOrders'), conversion: sum('previousOrders') / sum('previousVisits') * 100, ads: sum('previousAds'), inventory: last.previousInventory, turnover: last.previousTurnover }
  return { rows, current, previous, margin: current.profit / current.sales * 100, previousMargin: previous.profit / previous.sales * 100 }
}

export function metricValue(metric: Metric, value: number) {
  if (metric === 'conversion') return `${value.toFixed(2)}%`
  if (metric === 'turnover') return `${value.toFixed(1)} 天`
  if (metric === 'inventory') return `${Math.round(value)} 个`
  if (metric === 'orders') return Math.round(value).toLocaleString('zh-CN')
  return `$${Math.round(value).toLocaleString('zh-CN')}`
}
