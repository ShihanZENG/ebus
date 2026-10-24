import test from 'node:test'
import assert from 'node:assert/strict'
import { decideAnalyticsConsent, getAnalyticsConsent, readLocalEvents, trackLocalEvent } from '../src/analytics.mjs'

class MemoryStorage {
  constructor() { this.values = new Map() }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null }
  setItem(key, value) { this.values.set(key, String(value)) }
  removeItem(key) { this.values.delete(key) }
}

test('local analytics is off until explicit consent', () => {
  const local = new MemoryStorage(), session = new MemoryStorage()
  assert.equal(getAnalyticsConsent(local), 'unset')
  assert.equal(trackLocalEvent(local, session, 'page_view', { page: 'home' }), false)
  assert.deepEqual(readLocalEvents(local), [])
})

test('consented local analytics stores only allowlisted non-personal fields', () => {
  const local = new MemoryStorage(), session = new MemoryStorage()
  decideAnalyticsConsent(local, session, 'granted')
  assert.equal(trackLocalEvent(local, session, 'product_view', {
    product_id: 'product-123', email: 'buyer@example.com', address: '1 High Street', query: 'private search',
  }, new Date('2026-10-21T08:00:00Z')), true)
  const [event] = readLocalEvents(local)
  assert.equal(event.event_name, 'product_view')
  assert.equal(event.product_id, 'product-123')
  assert.equal(event.timestamp, '2026-10-21T08:00:00.000Z')
  assert.equal(event.market, 'GB')
  assert.equal(typeof event.event_id, 'string')
  assert.equal(typeof event.session_id, 'string')
  assert.equal('email' in event, false)
  assert.equal('address' in event, false)
  assert.equal('query' in event, false)
})

test('withdrawing consent clears local event and session identifiers', () => {
  const local = new MemoryStorage(), session = new MemoryStorage()
  decideAnalyticsConsent(local, session, 'granted')
  trackLocalEvent(local, session, 'page_view', { page: 'home' })
  decideAnalyticsConsent(local, session, 'denied')
  assert.equal(getAnalyticsConsent(local), 'denied')
  assert.deepEqual(readLocalEvents(local), [])
  assert.equal(session.getItem('zhijian.analytics.session'), null)
})

test('local event storage is capped and removes events older than thirty days', () => {
  const local = new MemoryStorage(), session = new MemoryStorage()
  const now = new Date('2026-10-21T08:00:00Z')
  decideAnalyticsConsent(local, session, 'granted')
  for (let i = 0; i < 205; i++) trackLocalEvent(local, session, 'page_view', { page: 'home' }, now)
  assert.equal(readLocalEvents(local, now).length, 200)
  local.setItem('zhijian.analytics.events', JSON.stringify([{ timestamp: '2026-09-01T00:00:00Z' }]))
  assert.deepEqual(readLocalEvents(local, now), [])
  assert.deepEqual(JSON.parse(local.getItem('zhijian.analytics.events')), [])
})
