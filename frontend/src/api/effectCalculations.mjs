const one = (value) => Math.round(value * 10) / 10
const signed = (value) => `${value >= 0 ? '+' : ''}${value}`
const dollars = (value) => `${value < 0 ? '-' : '+'}$${Math.abs(value).toLocaleString('en-US')}`

export function calculateEffectMetric(kind, input) {
  if (kind === 'margin') {
    if (!(input.revenue > 0)) throw new Error('revenue must be positive')
    const actual = one(input.profit / input.revenue * 100)
    const gap = one(actual - input.target)
    return {
      metric: '加权毛利', plan: `≥ ${input.target}%`, actual: `${actual}%`, deviation: `${signed(gap)}pp`, rating: gap >= 0 ? 'good' : 'bad',
      formula: '加权毛利率 = 毛利额 ÷ 销售额 × 100%；偏差 = 实际毛利率 − 目标毛利率',
      calculation: `$${input.profit.toLocaleString('en-US')} ÷ $${input.revenue.toLocaleString('en-US')} × 100% = ${actual}%；${actual}% − ${input.target}% = ${signed(gap)}pp`,
      decision: gap >= 0 ? '实际毛利率达到目标。' : '实际毛利率低于目标。',
    }
  }
  if (kind === 'profit') {
    const increase = input.current - input.baseline
    const gap = increase - input.target
    return {
      metric: '利润贡献', plan: dollars(input.target), actual: dollars(increase), deviation: dollars(gap), rating: gap >= 0 ? 'good' : 'bad',
      formula: '增量利润贡献 = 复盘期利润 − 对照基线利润；偏差 = 增量利润贡献 − 计划增量',
      calculation: `${dollars(input.current)} − (${dollars(input.baseline)}) = ${dollars(increase)}；${dollars(increase)} − ${dollars(input.target)} = ${dollars(gap)}`,
      decision: gap >= 0 ? '增量利润贡献达到计划。' : '增量利润贡献低于计划。',
    }
  }
  if (kind === 'conversion') {
    if (!(input.baseline > 0)) throw new Error('baseline conversion must be positive')
    const change = one((input.current / input.baseline - 1) * 100)
    const room = one(change + input.maxDrop)
    return {
      metric: '转化率', plan: `降幅 ≤ ${input.maxDrop}%`, actual: `${signed(change)}%`, deviation: room >= 0 ? `优于上限 ${room}pp` : `超出上限 ${Math.abs(room)}pp`, rating: room >= 0 ? 'good' : 'bad',
      formula: '相对变化率 = (复盘期转化率 ÷ 基线转化率 − 1) × 100%；允许降幅为相对变化率下限',
      calculation: `(${input.current}% ÷ ${input.baseline}% − 1) × 100% = ${signed(change)}%；与 -${input.maxDrop}% 下限相差 ${signed(room)}pp`,
      decision: room >= 0 ? '转化率降幅在允许范围内。' : '转化率降幅超出允许范围。',
    }
  }
  if (kind === 'outboundHours') {
    if (!(input.orderCount > 0)) throw new Error('orderCount must be positive')
    const actual = one(input.totalHours / input.orderCount)
    const gap = one(actual - input.target)
    return {
      metric: '平均出库时长', plan: `≤ ${input.target}h`, actual: `${actual}h`, deviation: `${signed(gap)}h`, rating: gap <= 0 ? 'good' : 'bad',
      formula: '平均出库时长 = 样本订单出库耗时合计 ÷ 样本订单数；偏差 = 实际均值 − 目标上限',
      calculation: `${input.totalHours}h ÷ ${input.orderCount} 单 = ${actual}h；${actual}h − ${input.target}h = ${signed(gap)}h`,
      decision: gap <= 0 ? '平均出库时长达到目标。' : '平均出库时长超过目标上限。',
    }
  }
  if (kind === 'affectedOrders') {
    const gap = input.affected - input.target
    return {
      metric: '受影响订单', plan: `≤ ${input.target}`, actual: String(input.affected), deviation: signed(gap), rating: gap <= 0 ? 'good' : 'bad',
      formula: '受影响订单数 = 样本中出库耗时超过 24h 的订单去重计数；偏差 = 实际单数 − 目标上限',
      calculation: `${input.affected} 单 − ${input.target} 单 = ${signed(gap)} 单`,
      decision: gap <= 0 ? '受影响订单数达到目标。' : '受影响订单数超过目标上限。',
    }
  }
  throw new Error(`Unknown effect metric: ${kind}`)
}

export function summarizeEffectRating(metrics) {
  if (metrics.some((metric) => metric.rating !== 'good')) return 'bad'
  return 'good'
}
