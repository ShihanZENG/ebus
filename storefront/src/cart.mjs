export function toPence(price) {
  if (!/^\d+\.\d{2}$/.test(price)) throw new Error('价格格式无效')
  const [major, minor] = price.split('.')
  return Number(major) * 100 + Number(minor)
}

export function cartTotal(cart) {
  return (cart.reduce((sum, item) => sum + toPence(item.price) * item.quantity, 0) / 100).toFixed(2)
}

export function addItem(cart, item, quantity = 1) {
  if (!Number.isInteger(quantity) || quantity < 1) throw new Error('数量必须为正整数')
  const row = cart.find(r => r.variant_id === item.variant_id)
  const total = (row?.quantity || 0) + quantity
  if (total > 20) throw new Error('单个规格最多购买 20 件')
  if (total > item.available_qty) throw new Error('可用库存不足')
  return row ? cart.map(r => r === row ? { ...item, quantity: total } : r) : [...cart, { ...item, quantity }]
}

export function prepareSubmission(previous, payload) {
  const fingerprint = JSON.stringify(payload)
  if (previous && previous.fingerprint === fingerprint) return previous
  return { key: crypto.randomUUID().replaceAll('-', ''), recovery: crypto.randomUUID().replaceAll('-', '') + crypto.randomUUID().replaceAll('-', ''), fingerprint }
}

export function repriceCart(cart, products) {
  const lines = [], removed = []
  let changed = false
  for (const old of cart) {
    const product = products.find(p => p.variants.some(v => v.id === old.variant_id))
    const variant = product?.variants.find(v => v.id === old.variant_id)
    if (!variant || variant.available_qty < 1) {
      removed.push(old.title)
      changed = true
      continue
    }
    const next = {
      variant_id: variant.id, title: product.title, color: variant.color, size: variant.size,
      price: variant.price, quantity: Math.min(old.quantity, variant.available_qty, 20),
      available_qty: variant.available_qty, product_version: product.version,
    }
    if (Object.keys(next).some(key => next[key] !== old[key])) changed = true
    lines.push(next)
  }
  return { lines, changed, removed }
}

export function createSingleFlight() {
  let pending = null
  return {
    active: () => pending !== null,
    run(fn) {
      if (pending) return pending
      const current = Promise.resolve().then(fn)
      pending = current
      current.finally(() => { if (pending === current) pending = null }).catch(() => {})
      return current
    },
  }
}
