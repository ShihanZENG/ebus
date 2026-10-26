import { forwardRef, useImperativeHandle, useRef, useState } from 'react'
import { errorText, request } from './customer-api'
import './support-contact.css'

type ProductContext = { slug: string; title: string }
type OrderContext = { id: string; token: string }
export type SupportContactHandle = { open: (product?: ProductContext) => void }

const SupportContact = forwardRef<SupportContactHandle, {
  order: OrderContext | null
  onOrders: () => void
  onSubmitted: () => void
  preview: boolean
}>(function SupportContact({ order, onOrders, onSubmitted, preview }, ref) {
  const dialog = useRef<HTMLDialogElement>(null)
  const pending = useRef(false)
  const [product, setProduct] = useState<ProductContext | null>(null)
  const [mode, setMode] = useState<'presales' | 'order'>('presales')
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [issue, setIssue] = useState('delivery')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [ticket, setTicket] = useState('')

  function open(context?: ProductContext) {
    if (pending.current) return
    setProduct(context ?? null)
    setMode(!context && order ? 'order' : 'presales')
    setError(''); setTicket(''); setMessage('')
    dialog.current?.showModal()
  }
  useImperativeHandle(ref, () => ({ open }))

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending.current || preview || !message.trim()) return
    pending.current = true; setBusy(true); setError('')
    try {
      if (mode === 'order' && !order) throw new Error('请重新打开订单详情后提交')
      const result = await request<{ ticket_ref: string }>(mode === 'order' ? '/support-requests' : '/support-requests/enquiries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(mode === 'order' && order?.token ? { Authorization: 'Bearer ' + order.token } : {}) },
        body: JSON.stringify(mode === 'order'
          ? { order_ref: order!.id, issue, message: message.trim() }
          : { contact_email: email.trim(), message: message.trim(), ...(product ? { product_slug: product.slug } : {}) }),
      })
      setTicket(result.ticket_ref); setMessage('')
      onSubmitted()
    } catch (err) { setError(errorText(err)) }
    finally { pending.current = false; setBusy(false) }
  }

  return <>
    <button className="support-launcher" onClick={() => open()} aria-label="联系客服，打开留言咨询">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M20 11.5a8 8 0 0 1-8 8H4l-2 2V11.5a9 9 0 0 1 18 0Z"/><path d="M7 10h8M7 14h5"/></svg>
      <span>联系客服<small>留言咨询</small></span>
    </button>
    <dialog ref={dialog} className="support-dialog" aria-labelledby="support-title" onCancel={e => { if (busy) e.preventDefault() }}>
      <button className="support-close" aria-label="关闭客服咨询" disabled={busy} onClick={() => dialog.current?.close()}>×</button>
      <p className="eyebrow">CUSTOMER CARE</p>
      <h2 id="support-title">有什么可以帮你？</h2>
      <p className="support-hint">留言咨询，非即时聊天。提交后由客服人员查看处理。</p>
      {preview && <p role="status">当前为视觉预览，暂不支持提交留言。</p>}
      {ticket ? <div role="status" className="support-success"><h3>留言已提交</h3><p>请求编号：<strong>{ticket}</strong></p><p>请保存此编号供后续查询。当前为演示环境，不会自动发送邮件。</p><button onClick={() => dialog.current?.close()}>完成</button></div> : <form onSubmit={submit}>
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
    </dialog>
  </>
})

export default SupportContact
