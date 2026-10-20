import test from 'node:test'
import assert from 'node:assert/strict'

// Tests exercise cart behavior; a broken quantity merge or floating-point sum fails.
test('cart merges only the same variant and respects stock', async () => {
  const { addItem, cartTotal } = await import('../src/cart.mjs')
  const item = { variant_id: 'a', title: '针织', color: '红', size: 'M', price: '29.00', product_version: 1, available_qty: 2 }
  let cart = addItem([], item)
  cart = addItem(cart, item)
  assert.equal(cart.length, 1)
  assert.equal(cart[0].quantity, 2)
  assert.equal(cartTotal(cart), '58.00')
  assert.throws(() => addItem(cart, item), /库存/)
  assert.equal(addItem(cart, { ...item, variant_id: 'b' }).length, 2)
})

test('money uses pence and rejects malformed prices', async () => {
  const { cartTotal, toPence } = await import('../src/cart.mjs')
  assert.equal(cartTotal([{ price: '0.10', quantity: 1 }, { price: '0.20', quantity: 1 }]), '0.30')
  assert.equal(toPence('29.00'), 2900)
  assert.throws(() => toPence('NaN'))
  assert.throws(() => toPence('-1.00'))
})

test('retries reuse credentials and changed payload gets a new identity', async () => {
  const { prepareSubmission } = await import('../src/cart.mjs')
  const first = prepareSubmission(null, { items: [{ variant_id: 'a', quantity: 1 }] })
  const retry = prepareSubmission(first, { items: [{ variant_id: 'a', quantity: 1 }] })
  assert.deepEqual(retry, first)
  assert.ok(first.recovery.length >= 32)
  const changed = prepareSubmission(first, { items: [{ variant_id: 'a', quantity: 2 }] })
  assert.notEqual(changed.key, first.key)
  assert.notEqual(changed.recovery, first.recovery)
})

test('reprice keeps a variant instead of adding a duplicate and requires confirmation', async () => {
  const { repriceCart } = await import('../src/cart.mjs')
  const cart = [{ variant_id: 'a', title: '旧名称', color: '燕麦', size: 'M', price: '29.00', quantity: 3, available_qty: 3, product_version: 1 }]
  const products = [{ title: '新名称', version: 2, variants: [{ id: 'a', color: '燕麦', size: 'M', price: '31.50', available_qty: 2 }] }]
  assert.deepEqual(repriceCart(cart, products), { lines: [{ variant_id: 'a', title: '新名称', color: '燕麦', size: 'M', price: '31.50', quantity: 2, available_qty: 2, product_version: 2 }], changed: true, removed: [] })
  assert.deepEqual(repriceCart(cart, []), { lines: [], changed: true, removed: ['旧名称'] })
})

test('single flight runs one checkout during overlapping retries', async () => {
  const { createSingleFlight } = await import('../src/cart.mjs')
  const gate = createSingleFlight()
  let release, calls = 0
  const action = () => { calls++; return new Promise(resolve => { release = resolve }) }
  const first = gate.run(action)
  const second = gate.run(action)
  await Promise.resolve()
  assert.equal(calls, 1)
  assert.equal(gate.active(), true)
  release('order-1')
  assert.equal(await first, 'order-1')
  assert.equal(await second, 'order-1')
  assert.equal(gate.active(), false)
  await gate.run(() => { calls++; return 'order-2' })
  assert.equal(calls, 2)
})
