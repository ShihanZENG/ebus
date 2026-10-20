import test from 'node:test'
import assert from 'node:assert/strict'
import {
  canConfirmShipment,
  isTrackingNumberValid,
  STATUS_TAG,
} from '../src/pages/shipmentStatus.mjs'

test('picking shipments can be confirmed but terminal shipments cannot', () => {
  assert.equal(canConfirmShipment('picking'), true)
  assert.equal(canConfirmShipment('shipped'), false)
  assert.equal(canConfirmShipment('cancelled'), false)
})

test('shipment states use labels matching the WMS API', () => {
  assert.equal(STATUS_TAG.picking.text, '拣货中')
  assert.equal(STATUS_TAG.shipped.text, '已发货')
  assert.equal(STATUS_TAG.cancelled.text, '已取消')
})

test('tracking number validation rejects empty and whitespace values', () => {
  assert.equal(isTrackingNumberValid(''), false)
  assert.equal(isTrackingNumberValid('   '), false)
  assert.equal(isTrackingNumberValid(' TEST-AD8294D3 '), true)
})
