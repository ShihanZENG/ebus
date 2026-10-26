import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeOmsExport, reconcileOrders } from '../src/pages/orderReconciliation.ts'

const row = (overrides = {}) => ({
  shop_id: 'erp-1', shop_code: 'SHOP-A', source_channel: 'manual',
  source_order_no: 'ORDER-1', currency: 'USD', grand_total: '10.00',
  status: 'approved', created_at: '2026-10-01T00:00:00Z', ...overrides,
})
const file = (source_system, items) => ({
  schema_version: '1.0.0', source_system, truncated: false, count: items.length,
  period: { from: '2026-10-01', to: '2026-10-01', time_basis: 'created_at_utc' }, items,
})

test('maps one exact order and compares cents without floating point rounding', () => {
  const result = reconcileOrders([row()], [row({ shop_id: 'oms-1' })], { 'SHOP-A': 'SHOP-A' })
  assert.equal(result.length, 1)
  assert.equal(result[0].status, '一致')
  assert.equal(result[0].erp.source_order_no, 'ORDER-1')
})

test('reports ambiguous ERP candidates without silently selecting one', () => {
  const result = reconcileOrders([row(), row({ shop_id: 'erp-2' })], [row({ shop_id: 'oms-1' })], { 'SHOP-A': 'SHOP-A' })
  assert.equal(result.length, 1)
  assert.equal(result[0].status, '重复键，需人工核对')
  assert.equal(result[0].erp, undefined)
  assert.equal(result[0].candidates.length, 2)
})

test('reports amount and status differences while keeping unmatched currencies separate', () => {
  const changed = reconcileOrders([row({ grand_total: '10.01', status: 'fulfilled' })], [row({ shop_id: 'oms-1' })], { 'SHOP-A': 'SHOP-A' })
  assert.equal(changed[0].status, '金额差异')
  const currency = reconcileOrders([row()], [row({ shop_id: 'oms-1', currency: 'CAD' })], { 'SHOP-A': 'SHOP-A' })
  assert.deepEqual(currency.map(item => item.status).sort(), ['ERP 缺少订单', 'OMS 缺少订单'])
})

test('does not call ERP shops missing from OMS when no OMS shop is mapped to them', () => {
  const result = reconcileOrders([row(), row({ shop_id: 'erp-2', shop_code: 'SHOP-B' })], [row({ shop_id: 'oms-1', shop_code: 'OMS-A' })], { 'OMS-A': 'SHOP-A' })
  assert.equal(result.length, 1)
  assert.equal(result[0].status, '一致')
})

test('projects imported OMS data to the allowlisted order fields and discards PII extras', () => {
  const input = {
    ...file('OMS', [row({ customer_name: 'Private', customer_contact: 'private@example.com', address: 'Secret' })]),
    generated_at: '2026-10-21T00:00:00Z', private_note: 'discard',
  }
  const parsed = normalizeOmsExport(input, { from: '2026-10-01', to: '2026-10-01' })
  assert.deepEqual(Object.keys(parsed.items[0]).sort(), ['created_at', 'currency', 'grand_total', 'shop_code', 'shop_id', 'source_channel', 'source_order_no', 'status'])
  assert.equal('private_note' in parsed, false)
  assert.equal('customer_contact' in parsed.items[0], false)
})

test('rejects an OMS export whose date range differs from the selected ERP range', () => {
  const input = { ...file('OMS', [row()]), generated_at: '2026-10-21T00:00:00Z' }
  assert.throws(() => normalizeOmsExport(input, { from: '2026-10-02', to: '2026-10-02' }), /日期范围/)
})
