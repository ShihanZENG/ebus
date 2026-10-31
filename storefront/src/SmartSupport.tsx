import { useEffect, useRef, useState, type FormEvent } from 'react'
import { errorText, request } from './customer-api'
import './smart-support.css'

type Source = { id: string; title: string; version: string }
type Answer = { status: 'answered' | 'handoff'; intent_label: string; answer: string; citations: Source[] }
type Turn = { question: string; result: Answer }

export default function SmartSupport({ productSlug, onHandoff }: { productSlug?: string; onHandoff: (message: string) => void }) {
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const conversation = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (conversation.current) conversation.current.scrollTop = conversation.current.scrollHeight
  }, [turns, busy])

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const message = question.trim()
    if (!message || busy) return
    setBusy(true); setError('')
    try {
      const result = await request<Answer>('/assistant/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, ...(productSlug ? { product_slug: productSlug } : {}) }),
      })
      setTurns(current => [...current.slice(-8), { question: message, result }])
      setQuestion('')
    } catch (cause) { setError(errorText(cause)) }
    finally { setBusy(false) }
  }

  function choosePrompt(value: string) {
    setQuestion(value)
    input.current?.focus()
  }

  return <section className="smart-support" aria-label="智能客服对话">
    <div className="smart-support-turns" ref={conversation} role="log" aria-live="polite" aria-label="客服对话记录">
      {!turns.length && <div className="smart-support-welcome">
        <span className="smart-support-avatar" aria-hidden="true">织</span>
        <h3>你好，想了解什么？</h3>
        <p>我会先查找公开的商品与服务资料，再回答你的问题。</p>
        <div className="smart-support-prompts" aria-label="常见问题">
          <button type="button" onClick={() => choosePrompt('配送怎么安排？')}>配送怎么安排？</button>
          <button type="button" onClick={() => choosePrompt('如何了解商品材质？')}>如何了解商品材质？</button>
        </div>
      </div>}
      {turns.map((turn, index) => <div className="smart-support-exchange" key={index}>
        <p className="smart-support-question">{turn.question}</p>
        <div className="smart-support-answer">
          <div className="smart-support-answer-heading"><span className="smart-support-avatar" aria-hidden="true">织</span><strong>织间智能客服</strong><span className="smart-support-intent">{turn.result.intent_label}</span></div>
          <p>{turn.result.answer}</p>
          {!!turn.result.citations.length && <details className="smart-support-sources"><summary>查看回答依据（{turn.result.citations.length}）</summary><ul>{turn.result.citations.map(source => <li key={source.id}>{source.title} · {source.version}</li>)}</ul></details>}
          {turn.result.status === 'handoff' && <button className="smart-support-handoff" type="button" onClick={() => onHandoff(turn.question)}>转人工，带上这个问题</button>}
        </div>
      </div>)}
      {busy && <p className="smart-support-loading" role="status">正在检索公开资料并整理回答…</p>}
    </div>
    <form className="smart-support-composer" onSubmit={ask}>
      <label htmlFor="smart-support-input">输入问题</label>
      <textarea id="smart-support-input" ref={input} required minLength={1} maxLength={2000} rows={2} value={question} disabled={busy} onChange={event => setQuestion(event.target.value)} placeholder="例如：配送怎么安排？" />
      {error && <p role="alert" className="support-error">{error}</p>}
      <div className="smart-support-composer-bottom"><small>仅根据公开资料回答 · 请勿填写支付信息</small><button className="support-submit" type="submit" disabled={busy || !question.trim()}>{busy ? '查询中…' : '发送问题'}</button></div>
    </form>
  </section>
}
