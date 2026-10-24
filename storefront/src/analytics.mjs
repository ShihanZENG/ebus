const CONSENT_KEY = 'zhijian.analytics.consent'
const EVENTS_KEY = 'zhijian.analytics.events'
const SESSION_KEY = 'zhijian.analytics.session'
const MAX_EVENTS = 200
const RETENTION_MS = 30 * 24 * 60 * 60 * 1000
const ALLOWED_EVENTS = new Set([
  'page_view', 'product_view', 'variant_selected', 'add_to_cart', 'cart_updated',
  'checkout_started', 'address_validation_failed', 'quote_changed', 'checkout_submitted',
  'order_accepted', 'checkout_failed', 'order_status_viewed',
])
const ALLOWED_PAGES = new Set(['home', 'product', 'cart', 'checkout', 'order', 'help', 'story', 'policies', 'status', 'notFound'])

function safeLocalStorage() {
  try { return globalThis.localStorage } catch { return null }
}

function safeSessionStorage() {
  try { return globalThis.sessionStorage } catch { return null }
}

function randomId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

export function getAnalyticsConsent(storage = safeLocalStorage()) {
  try {
    const value = storage?.getItem(CONSENT_KEY)
    return value === 'granted' || value === 'denied' ? value : 'unset'
  } catch { return 'unset' }
}

export function readLocalEvents(storage = safeLocalStorage(), now = new Date()) {
  try {
    const value = JSON.parse(storage?.getItem(EVENTS_KEY) || '[]')
    if (!Array.isArray(value)) return []
    const cutoff = now.getTime() - RETENTION_MS
    const recent = value.filter(item => {
      const timestamp = Date.parse(item?.timestamp)
      return Number.isFinite(timestamp) && timestamp >= cutoff
    })
    if (recent.length !== value.length) storage?.setItem(EVENTS_KEY, JSON.stringify(recent))
    return recent
  } catch { return [] }
}

export function decideAnalyticsConsent(storage = safeLocalStorage(), sessionStorage = safeSessionStorage(), decision) {
  if ((decision !== 'granted' && decision !== 'denied') || !storage) return false
  try { storage.setItem(CONSENT_KEY, decision) } catch { return false }
  if (decision === 'denied') {
    try { storage?.removeItem(EVENTS_KEY) } catch { /* storage may be disabled */ }
    try { sessionStorage?.removeItem(SESSION_KEY) } catch { /* storage may be disabled */ }
  }
  return true
}

export function trackLocalEvent(storage = safeLocalStorage(), sessionStorage = safeSessionStorage(), eventName, properties = {}, now = new Date()) {
  if (getAnalyticsConsent(storage) !== 'granted' || !ALLOWED_EVENTS.has(eventName)) return false
  try {
    let sessionId = sessionStorage.getItem(SESSION_KEY)
    if (!sessionId) {
      sessionId = randomId()
      sessionStorage.setItem(SESSION_KEY, sessionId)
    }
    const event = {
      event_id: randomId(), session_id: sessionId, event_name: eventName,
      market: 'GB', timestamp: now.toISOString(),
    }
    if (typeof properties.page === 'string' && ALLOWED_PAGES.has(properties.page)) event.page = properties.page
    for (const key of ['product_id', 'sku_id']) {
      const value = properties[key]
      if (typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value)) event[key] = value
    }
    const recent = readLocalEvents(storage, now)
    recent.push(event)
    storage.setItem(EVENTS_KEY, JSON.stringify(recent.slice(-MAX_EVENTS)))
    return true
  } catch { return false }
}
