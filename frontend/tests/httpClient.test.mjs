import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import http from '../src/api/http.ts'
import { request, requestBlob, setToken, getToken, ApiError } from '../src/api/client.ts'

test('JSON and download clients preserve query, body, errors and session expiry over HTTP', async () => {
  const values = new Map()
  globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  globalThis.window = new EventTarget()
  let expired = 0
  window.addEventListener('erp:unauthorized', () => expired++)
  const server = createServer(async (req, res) => {
    let body = ''
    for await (const chunk of req) body += chunk
    // axios 的 Node 适配器在带 params 时会发送 absolute-form 请求行（RFC 7230 §5.3.2），
    // 这里统一归一化成 path + query 再做路由匹配。
    const parsed = new URL(req.url, 'http://localhost')
    const path = parsed.pathname
    const search = parsed.search
    if (path === '/unauthorized') { res.writeHead(401); res.end('{}'); return }
    if (path === '/empty') { res.writeHead(204); res.end(); return }
    if (path === '/invalid') { res.writeHead(422, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ error: { message: '输入无效' } })); return }
    if (path === '/download') { res.end('download contents'); return }
    if (path === '/plain') { res.end('plain response'); return }
    res.setHeader('Content-Type', 'application/json')
    res.end(JSON.stringify({ url: path + search, token: req.headers.authorization, body, contentType: req.headers['content-type'] }))
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const originalBase = http.defaults.baseURL
  http.defaults.baseURL = `http://127.0.0.1:${server.address().port}`
  try {
    setToken('test-token')
    const result = await request('/echo', { method: 'POST', body: { hello: '你好' }, params: { skip: '', zero: 0, flag: false, nil: null } })
    assert.equal(result.url, '/echo?zero=0&flag=false')
    assert.equal(result.token, 'Bearer test-token')
    assert.deepEqual(JSON.parse(result.body), { hello: '你好' })
    assert.match(result.contentType, /application\/json/)
    assert.equal((await http.get('/echo')).data.token, 'Bearer test-token')
    assert.equal(await request('/empty'), undefined)
    assert.equal(await request('/plain'), 'plain response')
    assert.equal(await (await requestBlob('/download')).text(), 'download contents')
    for (const call of [() => request('/invalid'), () => requestBlob('/invalid')]) {
      await assert.rejects(call, error => error instanceof ApiError && error.status === 422 && error.message === '输入无效')
    }
    for (const call of [() => request('/unauthorized'), () => requestBlob('/unauthorized'), () => http.get('/unauthorized')]) {
      setToken('test-token')
      const before = expired
      await assert.rejects(call)
      assert.equal(getToken(), null)
      assert.equal(expired, before + 1)
    }
  } finally {
    http.defaults.baseURL = originalBase
    await new Promise(resolve => server.close(resolve))
    delete globalThis.localStorage
    delete globalThis.window
  }
})
