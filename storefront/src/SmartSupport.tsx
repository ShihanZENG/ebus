import { useState, type FormEvent } from 'react'
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

  return <section className="smart-support" aria-label="智能客服对话">
    <p className="support-hint">登录后可提问。问题和检索资料会发送给本站配置的模型；请勿填写支付资料。回答只依据已公开的商品和客服资料，具体订单处理请查看订单或转人工。</p>
    <div className="smart-support-turns" aria-live="polite">
      {!turns.length && <p className="support-hint">例如：日常针织是什么材质？配送怎么安排？</p>}
      {turns.map((turn, index) => <div className="smart-support-turn" key={index}>
        <p className="smart-support-question"><strong>你：</strong>{turn.question}</p>
        <p><strong>智能客服：</strong>{turn.result.answer}</p>
        <small>识别分类：{turn.result.intent_label}</small>
        {!!turn.result.citations.length && <p className="smart-support-sources">依据：{turn.result.citations.map(source => `${source.title}（${source.version}）`).join('、')}</p>}
        {turn.result.status === 'handoff' && <button type="button" onClick={() => onHandoff(turn.question)}>转人工并带上问题</button>}
      </div>)}
    </div>
    <form onSubmit={ask}>
      <label>输入问题<textarea required minLength={1} maxLength={2000} rows={3} value={question} disabled={busy} onChange={event => setQuestion(event.target.value)} placeholder="请写明商品名称或想了解的事项" /></label>
      {error && <p role="alert" className="support-error">{error}</p>}
      <button className="support-submit" type="submit" disabled={busy || !question.trim()}>{busy ? '正在查询资料…' : '发送问题'}</button>
    </form>
  </section>
}
