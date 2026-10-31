import test from 'node:test'
import assert from 'node:assert/strict'
import { signInDemoCustomer } from '../src/demo-account.mjs'

test('existing demo customer signs in without registering again', async () => {
  const calls = []
  const result = await signInDemoCustomer(async (path, options) => {
    calls.push([path, options.method])
    return { customer: { username: 'zhijian_demo' } }
  })
  assert.equal(result.customer.username, 'zhijian_demo')
  assert.deepEqual(calls, [['/account/login', 'POST']])
})

test('first use creates the demo customer after a missing login', async () => {
  const calls = []
  const result = await signInDemoCustomer(async (path, options) => {
    calls.push([path, options.method])
    if (path.endsWith('/login')) throw Object.assign(new Error('not found'), { status: 401 })
    return { customer: { username: 'zhijian_demo' } }
  })
  assert.equal(result.customer.username, 'zhijian_demo')
  assert.deepEqual(calls, [['/account/login', 'POST'], ['/account/register', 'POST']])
})

test('server errors do not create a new customer', async () => {
  const calls = []
  await assert.rejects(signInDemoCustomer(async (path) => {
    calls.push(path)
    throw Object.assign(new Error('service unavailable'), { status: 503 })
  }), /service unavailable/)
  assert.deepEqual(calls, ['/account/login'])
})
