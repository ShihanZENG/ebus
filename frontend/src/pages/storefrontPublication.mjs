export function pricePatch(variants, edits) {
  const prices = {}
  for (const variant of variants) {
    if (!(variant.id in edits)) continue
    const value = String(edits[variant.id]).trim()
    if (!/^\d{1,4}(\.\d{1,2})?$/.test(value) || Number(value) <= 0 || Number(value) > 9999) {
      throw new Error('价格须为 0.01–9999.00 英镑，最多两位小数')
    }
    const normalized = Number(value).toFixed(2)
    if (normalized !== variant.price) prices[variant.id] = normalized
  }
  return prices
}
