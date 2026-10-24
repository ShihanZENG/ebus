import test from 'node:test'
import assert from 'node:assert/strict'
import { resolveProductRoute } from '../src/product-route.mjs'

test('direct product routes request the slug when it is not in the loaded catalogue', () => {
  assert.deepEqual(resolveProductRoute('/products/daily-knit', []), {
    kind: 'fetch', slug: 'daily-knit', path: '/products/daily-knit',
  })
})

test('direct product routes reuse a matching loaded product', () => {
  const product = { id: 'p1', slug: 'daily-knit' }
  assert.deepEqual(resolveProductRoute('/products/daily-knit', [product]), {
    kind: 'loaded', product,
  })
})

test('malformed product routes resolve to not found', () => {
  assert.deepEqual(resolveProductRoute('/products/', []), { kind: 'not_found' })
})
