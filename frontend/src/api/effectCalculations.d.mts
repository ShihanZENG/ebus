export type EffectRating = 'good' | 'warn' | 'bad'
export interface CalculatedEffectMetric {
  metric: string
  plan: string
  actual: string
  deviation: string
  rating: EffectRating
  formula: string
  calculation: string
  decision: string
}
export function calculateEffectMetric(kind: 'margin' | 'profit' | 'conversion' | 'outboundHours' | 'affectedOrders', input: Record<string, number>): CalculatedEffectMetric
export function summarizeEffectRating(metrics: Pick<CalculatedEffectMetric, 'rating'>[]): EffectRating
