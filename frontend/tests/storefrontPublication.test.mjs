import test from 'node:test'
import assert from 'node:assert/strict'
import { pricePatch } from '../src/pages/storefrontPublication.mjs'

test('publication prices preserve decimal strings and include only changes', () => {
  const variants = [{ id: 'a', price: '29.00' }, { id: 'b', price: '29.00' }]
  assert.deepEqual(pricePatch(variants, { a: '29', b: '31.50' }), { b: '31.50' })
  assert.deepEqual(pricePatch(variants, {}), {})
})

test('publication rejects invalid or excessive prices', () => {
  for (const value of ['0', '-1', '1.001', 'NaN', '10000', '', '1e2']) {
    assert.throws(() => pricePatch([{ id: 'a', price: '29.00' }], { a: value }))
  }
})
