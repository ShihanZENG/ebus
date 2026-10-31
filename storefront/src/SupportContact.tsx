import { forwardRef, useImperativeHandle, useRef, useState } from 'react'
import { errorText, request, type Customer } from './customer-api'
import SmartSupport from './SmartSupport'
import './support-contact.css'

type ProductContext = { slug: string; title: string }
type OrderContext = { id: string; token: string }
type Receipt = { ticket_ref: string; receipt_token: string }
const RECEIPT_KEY = 'zhijian.presales.receipt'
function savedReceipt(): Receipt | null {
  try {
    const value = JSON.parse(localStorage.getItem(RECEIPT_KEY) || 'null')
    return typeof value?.ticket_ref === 'string' && typeof value?.receipt_token === 'string' ? value : null
  } catch { return null }
}
export type SupportContactHandle = { open: (product?: ProductContext) => void }

const SupportContact = forwardRef<SupportContactHandle, {
  order: OrderContext | null
  onOrders: () => void
  onSubmitted: () => void
  preview: boolean
  customer: Customer | null
  onLogin: () => void
}>(function SupportContact({ order, onOrders, onSubmitted, preview, customer, onLogin }, ref) {
  const dialog = useRef<HTMLDialogElement>(null)
  const pending = useRef(false)
  const [product, setProduct] = useState<ProductContext | null>(null)
  const [mode, setMode] = useState<'presales' | 'order'>('presales')
  const [supportMode, setSupportMode] = useState<'ai' | 'human'>('human')
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [issue, setIssue] = useState('delivery')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [ticket, setTicket] = useState('')
  const [receipt, setReceipt] = useState<Receipt | null>(savedReceipt)
  const [receiptStatus, setReceiptStatus] = useState('')
  const [receiptReply, setReceiptReply] = useState('')
  const [receiptError, setReceiptError] = useState('')

  async function checkReceipt(value: Receipt) {
    setReceiptError('')
    try {
      const result = await request<{ status: string; reply: string }>(`/support-requests/enquiries/${encodeURIComponent(value.ticket_ref)}`, {
        headers: { Authorization: 'Bearer ' + value.receipt_token },
      })
      setReceiptStatus(({ open: '待处理', in_progress: '处理中', resolved: '已解决', closed: '已关闭' } as Record<string, string>)[result.status] || result.status)
      setReceiptReply(result.reply || '')
    } catch (err) { setReceiptError(errorText(err)) }
  }

  function open(context?: ProductContext) {
    if (pending.current) return
    setProduct(context ?? null)
    setMode(!context && order ? 'order' : 'presales')
    setSupportMode(customer ? 'ai' : 'human')
    setError(''); setTicket(''); setMessage(''); setReceiptStatus(''); setReceiptReply(''); setReceiptError('')
    dialog.current?.showModal()
  }
  useImperativeHandle(ref, () => ({ open }))

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending.current || preview || !message.trim()) return
    pending.current = true; setBusy(true); setError('')
    try {
      if (mode === 'order' && !order) throw new Error('请重新打开订单详情后提交')
      const result = await request<{ ticket_ref: string; receipt_token?: string }>(mode === 'order' ? '/support-requests' : '/support-requests/enquiries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(mode === 'order' && order?.token ? { Authorization: 'Bearer ' + order.token } : {}) },
        body: JSON.stringify(mode === 'order'
          ? { order_ref: order!.id, issue, message: message.trim() }
          : { contact_email: email.trim(), message: message.trim(), ...(product ? { product_slug: product.slug } : {}) }),
      })
      setTicket(result.ticket_ref); setMessage('')
      if (result.receipt_token) {
        const next = { ticket_ref: result.ticket_ref, receipt_token: result.receipt_token }
        setReceipt(next)
        try { localStorage.setItem(RECEIPT_KEY, JSON.stringify(next)) }
        catch { setReceiptError('浏览器未能保存查询凭据；请在关闭页面前查看处理进度。') }
      }
      onSubmitted()
    } catch (err) { setError(errorText(err)) }
    finally { pending.current = false; setBusy(false) }
  }

  return <>
    <button className="support-launcher" onClick={() => open()} aria-label="联系客服，打开智能客服与留言咨询">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M20 11.5a8 8 0 0 1-8 8H4l-2 2V11.5a9 9 0 0 1 18 0Z"/><path d="M7 10h8M7 14h5"/></svg>
      <span>联系客服<small>智能问答 / 留言</small></span>
    </button>
    <dialog ref={dialog} className={`support-dialog ${supportMode === 'ai' && customer && !preview ? 'support-dialog-ai' : ''}`} aria-labelledby="support-title" onCancel={e => { if (busy) e.preventDefault() }}>
      <button className="support-close" aria-label="关闭客服咨询" disabled={busy} onClick={() => dialog.current?.close()}>×</button>
      <p className="eyebrow">CUSTOMER CARE</p>
      <h2 id="support-title">有什么可以帮你？</h2>
      <p className="support-hint">先问智能客服；需要处理订单时可转人工。</p>
      {preview && <p role="status">当前为视觉预览，暂不支持提交留言。</p>}
      {customer && !preview ? <div className="support-mode-switch"><button type="button" aria-pressed={supportMode === 'ai'} onClick={() => setSupportMode('ai')}>智能客服</button><button type="button" aria-pressed={supportMode === 'human'} onClick={() => setSupportMode('human')}>人工留言</button></div> : !preview && <p className="support-hint">登录后可使用智能客服。<button type="button" onClick={() => { dialog.current?.close(); onLogin() }}>前往登录</button></p>}
      {customer && !preview && <div className="support-ai-panel" hidden={supportMode !== 'ai'}><SmartSupport productSlug={product?.slug} onHandoff={question => { setMessage(question); setSupportMode('human') }} /></div>}
      {(supportMode !== 'ai' || !customer || preview) && <>
      {ticket ? <div role="status" className="support-success"><h3>留言已提交</h3><p>请求编号：<strong>{ticket}</strong></p><p>可在本浏览器内查询客服回复。当前为演示环境，不会自动发送邮件。</p><button onClick={() => dialog.current?.close()}>完成</button></div> : <form onSubmit={submit}>
        <fieldset disabled={busy || preview}>
          {order && !product && <label>咨询范围<select value={mode} onChange={e => setMode(e.target.value as 'presales' | 'order')}><option value="order">当前订单</option><option value="presales">售前 / 其他咨询</option></select></label>}
          {mode === 'order' && order ? <><p className="support-context">关联订单：{order.id}</p><label>问题类型<select value={issue} onChange={e => setIssue(e.target.value)}><option value="delivery">订单 / 配送</option><option value="product">商品问题</option><option value="return">退换 / 售后</option><option value="other">其他</option></select></label></> : <>
            {product && <p className="support-context">咨询商品：{product.title}</p>}
            <label>联系邮箱<input type="email" autoComplete="email" required maxLength={254} value={email} onChange={e => setEmail(e.target.value)} placeholder="例如 buyer@example.invalid" /></label>
          </>}
          <label>留言内容<textarea required minLength={1} maxLength={2000} rows={4} value={message} onChange={e => setMessage(e.target.value)} placeholder="告诉我们你想了解的商品、尺码或遇到的问题" /></label>
          <p className="support-hint">当前为本地演示，请使用虚构联系信息，勿填写支付资料。</p>
          {error && <p role="alert" className="support-error">{error}</p>}
          <button className="support-submit" type="submit" disabled={!message.trim()}>{busy ? '正在提交…' : '提交留言'}</button>
          {!order && <button type="button" className="support-order-link" onClick={() => { dialog.current?.close(); onOrders() }}>已有订单？前往我的订单咨询</button>}
        </fieldset>
      </form>}
      {receipt && !preview && <section className="support-success" aria-label="最近一次售前咨询"><p>最近一次售前咨询：<strong>{receipt.ticket_ref}</strong></p><button type="button" disabled={busy} onClick={() => void checkReceipt(receipt)}>查询处理进度</button>{receiptError && <p role="alert" className="support-error">{receiptError}</p>}{receiptStatus && <p role="status">处理状态：{receiptStatus}</p>}{receiptReply && <p>客服回复：{receiptReply}</p>}</section>}
      </>}
    </dialog>
  </>
})

export default SupportContact
