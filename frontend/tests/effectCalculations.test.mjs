import test from 'node:test'
import assert from 'node:assert/strict'
import { calculateEffectMetric, summarizeEffectRating } from '../src/api/effectCalculations.mjs'

test('gross margin uses profit divided by revenue and compares percentage points', () => {
  const result = calculateEffectMetric('margin', { revenue: 100000, profit: 5400, target: 5 })
  assert.equal(result.actual, '5.4%')
  assert.equal(result.deviation, '+0.4pp')
  assert.equal(result.rating, 'good')
})

test('incremental profit subtracts baseline and compares the planned increase', () => {
  const result = calculateEffectMetric('profit', { baseline: -80, current: 5400, target: 5200 })
  assert.equal(result.actual, '+$5,480')
  assert.equal(result.deviation, '+$280')
  assert.equal(result.rating, 'good')
})

test('conversion change is relative to the baseline conversion rate', () => {
  const result = calculateEffectMetric('conversion', { baseline: 5, current: 4.84, maxDrop: 5 })
  assert.equal(result.actual, '-3.2%')
  assert.equal(result.deviation, '优于上限 1.8pp')
  assert.equal(result.rating, 'good')
})

test('warehouse targets fail when actual hours and orders exceed their limits', () => {
  const hours = calculateEffectMetric('outboundHours', { totalHours: 5800, orderCount: 200, target: 24 })
  const orders = calculateEffectMetric('affectedOrders', { affected: 148, target: 100 })
  assert.deepEqual([hours.actual, hours.deviation, hours.rating], ['29h', '+5h', 'bad'])
  assert.deepEqual([orders.actual, orders.deviation, orders.rating], ['148', '+48', 'bad'])
  assert.equal(summarizeEffectRating([hours, orders]), 'bad')
})

test('missing denominator is not turned into a false zero or success', () => {
  assert.throws(() => calculateEffectMetric('margin', { revenue: 0, profit: 5400, target: 5 }), /revenue/)
})

test('overall conclusion needs every metric to meet its target', () => {
  assert.equal(summarizeEffectRating([{ rating: 'good' }, { rating: 'warn' }]), 'bad')
})
