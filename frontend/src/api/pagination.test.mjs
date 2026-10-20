import test from 'node:test'
import assert from 'node:assert/strict'

test('loads selectable records beyond the first 100', async () => {
  const module = await import('./pagination.ts').catch(() => ({}))
  assert.equal(typeof module.loadAllPages, 'function', 'pagination loader is missing')
  const rows = Array.from({ length: 205 }, (_, id) => ({ id }))
  const result = await module.loadAllPages(async page => ({ items: rows.slice((page - 1) * 100, page * 100), total: 205 }))
  assert.equal(result.length, 205)
  assert.equal(result[204].id, 204)
})

test('does not silently return partial results when a later page fails', async () => {
  const module = await import('./pagination.ts').catch(() => ({}))
  assert.equal(typeof module.loadAllPages, 'function', 'pagination loader is missing')
  await assert.rejects(module.loadAllPages(async page => {
    if (page === 2) throw new Error('offline')
    return { items: [{ id: 1 }], total: 2 }
  }), /offline/)
})
