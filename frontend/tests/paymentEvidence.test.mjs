import test from 'node:test'
import assert from 'node:assert/strict'
import { calculatePaymentNet, evidenceFileError, paymentTypeLabel, canReconcilePayment } from '../src/pages/paymentEvidence.mjs'

test('calculates settlement net after fee without floating point drift', () => {
  assert.equal(calculatePaymentNet(100, 15), 85)
  assert.equal(calculatePaymentNet(19.99, 0.8), 19.19)
})

test('does not calculate a net amount for invalid fees or amounts', () => {
  assert.equal(calculatePaymentNet(-1, 0), null)
  assert.equal(calculatePaymentNet(10, 11), null)
  assert.equal(calculatePaymentNet(Number.NaN, 0), null)
})

test('requires an allowed evidence type and enforces the 10 MiB limit', () => {
  assert.equal(evidenceFileError({ name: 'settlement.pdf', type: 'application/pdf', size: 10 }), null)
  assert.equal(evidenceFileError({ name: 'statement.exe', type: 'application/octet-stream', size: 10 }), '凭据仅支持 PDF、PNG、JPG 文件')
  assert.equal(evidenceFileError({ name: 'statement.pdf', type: 'image/png', size: 10 }), '凭据文件类型与扩展名不一致')
  assert.equal(evidenceFileError({ name: 'large.jpg', type: 'image/jpeg', size: 10 * 1024 * 1024 + 1 }), '凭据文件不能超过10 MiB')
})

test('labels simulated and legacy records distinctly and only allows evidence-backed real reviews', () => {
  assert.equal(paymentTypeLabel('simulated'), '模拟 / 非真实')
  assert.equal(paymentTypeLabel('legacy'), '历史未分类')
  assert.equal(canReconcilePayment({ record_type: 'real', reconciliation_status: 'pending', evidence_status: 'ready', evidence_key: 'proof' }, true), true)
  assert.equal(canReconcilePayment({ record_type: 'real', reconciliation_status: 'pending', evidence_key: 'proof' }, false), false)
  assert.equal(canReconcilePayment({ record_type: 'real', reconciliation_status: 'pending', evidence_status: 'staged', evidence_key: 'proof' }, true), false)
  assert.equal(canReconcilePayment({ record_type: 'simulated', reconciliation_status: 'pending', evidence_key: 'proof' }, true), false)
  assert.equal(canReconcilePayment({ record_type: 'real', reconciliation_status: 'pending', evidence_key: 'proof' }, undefined), false)
})
