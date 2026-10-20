import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { addItem, cartTotal, createSingleFlight, prepareSubmission, repriceCart } from './cart.mjs'
import './style.css'
import './dialog.css'

type Variant = { id: string; color: string; size: string; price: string; available_qty: number }
type Product = { id: string; slug: string; title: string; description: string; image_url: string; version: number; variants: Variant[] }
type CartLine = { variant_id: string; title: string; color: string; size: string; price: string; quantity: number; available_qty: number; product_version: number }
type Site = { brand_name: string; company_name: string; company_address: string; contact_email: string; demo: boolean }
type Order = { public_id: string; status_label: string; status: string; grand_total: string; tracking_no: string; fulfillment_issue: string; items: { title: string; color: string; size: string; quantity: number; line_total: string }[] }
type Address = { name: string; email: string; line1: string; line2: string; city: string; region: string; postcode: string; country: 'GB' }
type Pending = { key: string; recovery: string; fingerprint: string; payload: object }
type OrderRef = { id: string; token: string; recovery?: Pending }
class ApiError extends Error { constructor(message: string, public status: number) { super(message) } }
const API = '/api/storefront/v1'
const KEYS = { cart: 'zhijian.cart', pending: 'zhijian.pending', order: 'zhijian.order' }
function read<T>(key: string, fallback: T): T { try { return JSON.parse(sessionStorage.getItem(key) || 'null') ?? fallback } catch { return fallback } }
function save(key: string, value: unknown) { sessionStorage.setItem(key, JSON.stringify(value)) }
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(API + path, { ...options, cache: 'no-store', signal: AbortSignal.timeout(20000) })
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const field = data?.error?.fields?.[0]
    const label = field?.field?.includes('postcode') ? '邮编' : field?.field?.includes('email') ? '邮箱' : field?.field?.includes('address') ? '收货地址' : '填写内容'
    const message = field ? `${label}：${String(field.message).replace(/^Value error, /, '')}` : data?.error?.message || `请求失败（${response.status}）`
    throw new ApiError(message, response.status)
  }
  if (!data) throw new Error('服务返回内容无效，请重试')
  return data
}
const errorText = (error: unknown) => error instanceof Error ? error.message : '操作失败，请稍后重试'

function App() {
  const [site, setSite] = useState<Site | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [page, setPage] = useState<'home' | 'bag' | 'checkout' | 'order' | 'story'>('home')
  const [selected, setSelected] = useState<Product | null>(null)
  const [variantId, setVariantId] = useState('')
  const [cart, setCart] = useState<CartLine[]>(() => read(KEYS.cart, []))
  const [pending, setPending] = useState<Pending | null>(() => read(KEYS.pending, null))
  const [orderRef, setOrderRef] = useState<OrderRef | null>(() => read(KEYS.order, null))
  const [order, setOrder] = useState<Order | null>(null)
  const [address, setAddress] = useState<Address>({ name: '', email: '', line1: '', line2: '', city: '', region: '', postcode: '', country: 'GB' })
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [catalogueReady, setCatalogueReady] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const submitGate = useRef(createSingleFlight())
  const refreshGate = useRef(createSingleFlight())
  const modalRef = useRef<HTMLDialogElement>(null)
  const openerRef = useRef<HTMLElement | null>(null)
  const variant = selected?.variants.find(v => v.id === variantId)
  const quote = repriceCart(cart, products)
  const needsReview = catalogueReady && quote.changed
  useEffect(() => { save(KEYS.cart, cart) }, [cart])
  useEffect(() => { if (selected && modalRef.current && !modalRef.current.open) modalRef.current.showModal() }, [selected])
  async function loadCatalogue(preserveError = false) {
    if (!preserveError) setError('')
    setLoading(true); setCatalogueReady(false)
    try {
      const [s, p] = await Promise.all([request<Site>('/site'), request<{ items: Product[] }>('/products')])
      setSite(s); setProducts(p.items); setCatalogueReady(true)
    } catch (e) { setError(errorText(e)) } finally { setLoading(false) }
  }
  useEffect(() => { void loadCatalogue() }, [])
  function navigate(next: typeof page) { setError(''); setNotice(''); setSelected(null); setPage(next); window.scrollTo(0, 0) }
  function openProduct(product: Product) { openerRef.current = document.activeElement as HTMLElement; setSelected(product); setVariantId(''); setError('') }
  function closeProduct() { setSelected(null); queueMicrotask(() => openerRef.current?.focus()) }
  function addSelected() {
    if (!selected || !variant) { setError('请先选择颜色和尺码'); return }
    try {
      const next = { variant_id: variant.id, title: selected.title, color: variant.color, size: variant.size,
        price: variant.price, available_qty: variant.available_qty, product_version: selected.version }
      const old = cart.find(line => line.variant_id === variant.id)
      if (old && (old.product_version !== selected.version || old.price !== variant.price)) {
        setCart(cart.map(line => line === old ? { ...next, quantity: Math.min(old.quantity, variant.available_qty) } : line))
        setNotice('该规格已按当前售价和可售库存更新。请复核购物袋。')
      } else {
        setCart(addItem(cart, next))
        setNotice('已加入购物袋。提交订单前会再次核对售价和库存。')
      }
      closeProduct(); setError('')
    } catch (e) { setError(errorText(e)) }
  }
  async function refreshOrder(ref: OrderRef | null = orderRef) {
    if (!ref || refreshGate.current.active()) return
    return refreshGate.current.run(async () => {
      setLoading(true); setError(''); setOrder(null); setPage('order')
      try {
        setOrder(await request<Order>('/orders/' + encodeURIComponent(ref.id), { headers: { Authorization: 'Bearer ' + ref.token } }))
      } catch (e) {
        if (e instanceof ApiError && e.status === 404 && ref.recovery) {
          try {
            const recovered = await request<{ order: Order; access_token: string }>('/checkout', {
              method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': ref.recovery.key, 'X-Checkout-Recovery': ref.recovery.recovery },
              body: JSON.stringify(ref.recovery.payload),
            })
            if (recovered.order.public_id !== ref.id) throw new Error('恢复订单号不一致，请联系演示管理员')
            const renewed = { ...ref, token: recovered.access_token }
            save(KEYS.order, renewed); setOrderRef(renewed); setOrder(recovered.order)
          } catch (recoverError) { setError('查单凭据已失效，原提交恢复失败：' + errorText(recoverError)) }
        } else setError(errorText(e))
      } finally { setLoading(false) }
    })
  }
  async function submit() {
    if (submitGate.current.active() || (!cart.length && !pending) || (!pending && (!catalogueReady || quote.changed))) return
    return submitGate.current.run(async () => {
    setLoading(true); setSubmitting(true); setError('')
    const payload = pending?.payload || { items: cart.map(x => ({ variant_id: x.variant_id, quantity: x.quantity, product_version: x.product_version })), address }
    const identity = pending || { ...prepareSubmission(null, payload), payload }
    try {
      // Save before any network request. An uncertain result must be retried
      // with exactly this identity and payload, never silently submitted twice.
      save(KEYS.pending, identity); setPending(identity)
      const result = await request<{ order: Order; access_token: string }>('/checkout', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': identity.key, 'X-Checkout-Recovery': identity.recovery },
        body: JSON.stringify(identity.payload),
      })
      const ref: OrderRef = { id: result.order.public_id, token: result.access_token, recovery: identity }
      save(KEYS.order, ref); setOrderRef(ref); setOrder(result.order)
      sessionStorage.removeItem(KEYS.pending); setPending(null); setCart([]); navigate('order')
    } catch (e) {
      if (e instanceof ApiError && [409, 422].includes(e.status)) { sessionStorage.removeItem(KEYS.pending); setPending(null) }
      setError(errorText(e) + (e instanceof ApiError ? '' : '。提交结果尚未确认，请使用“重试原提交”，不要重复新建订单。'))
      if (e instanceof ApiError && e.status === 409) void loadCatalogue(true)
    } finally { setLoading(false); setSubmitting(false) }
    })
  }
  function updateQuantity(index: number, amount: number) {
    setCart(cart.map((x, i) => i === index ? { ...x, quantity: Math.min(20, x.available_qty, Math.max(1, amount)) } : x))
  }
  const count = cart.reduce((n, x) => n + x.quantity, 0)
  return <>
    <div className="demo-banner">演示联调环境 · 订单写入独立演示 ERP · 不扣款、不发真实包裹 <a href="http://127.0.0.1:15175/orders" target="_blank" rel="noreferrer">打开演示 ERP ↗</a></div>
    <header className="wrap header"><button className="brand" onClick={() => navigate('home')}>织间</button><nav><button onClick={() => navigate('home')}>当季选款</button><button onClick={() => navigate('story')}>品牌与公司</button>{orderRef && <button onClick={() => void refreshOrder()}>我的演示订单</button>}<button onClick={() => navigate('bag')}>购物袋 {count}</button></nav></header>
    <main className="wrap">
      {error && <div className="alert" role="alert">{error}<button onClick={() => setError('')} aria-label="关闭提示">×</button></div>}
      {notice && <div className="notice" role="status">{notice}</div>}
      {pending && <div className="alert">有一次提交尚未确认。为避免重复订单，请先恢复原提交。<button disabled={submitting} onClick={() => void submit()}>重试原提交</button></div>}
      {page === 'home' && <>
        <section className="hero"><div><p className="eyebrow">为生活里的每一个今天</p><h1>把喜欢，<br/>穿进今天。</h1><p>从平日的通勤，到临时起意的见面。<br/>让普通的一天，也有喜欢的样子。</p><a className="primary" href="#products">挑选今天的喜欢 ↗</a></div><figure><img src="/brand-hero.png" alt="织间原创街头穿搭概念图"/><figcaption>AI 概念穿搭图 · 非商品实拍</figcaption></figure></section>
        <section id="products"><div className="section-heading"><div><p className="eyebrow">先从好穿的一件开始</p><h2>今天，想怎么出门？</h2></div><button disabled={loading} onClick={() => void loadCatalogue()}>刷新商品与库存</button></div><p className="muted">GBP 测试售价 · 数据来自演示 ERP · 提交订单不会立即锁定库存</p>
          {loading && !products.length && <p role="status">正在读取商品…</p>}
          {!loading && !products.length && <p>暂未发布商品，请在演示 ERP 的“独立站运营”中检查发布状态。</p>}
          <div className="product-grid">{products.map(p => <article key={p.id}><button className="product-image" onClick={() => openProduct(p)}><img src={p.image_url || '/knit.svg'} alt={p.title + '版型示意'}/><span>演示款 · 商品实拍待补</span></button><div className="product-title"><h3>{p.title}</h3><span>£{p.variants[0]?.price}</span></div><p className="muted">{p.description}</p><button className="primary" disabled={!!pending} onClick={() => openProduct(p)}>选颜色尺码</button></article>)}</div>
        </section><section className="brand-strip"><h2>喜欢的衣服，<br/>不必等特别的日子。</h2><div><p>一件喜欢的衣服，也可以属于普通的星期二，属于下班后的散步，属于临时起意的见面。</p><button onClick={() => navigate('story')}>认识织间 →</button></div></section>
      </>}
      {(page === 'bag' || page === 'checkout') && <section className="content"><h1>{page === 'bag' ? '你的购物袋' : '确认演示订单'}</h1>{!catalogueReady && !pending && <div className="alert">暂时无法核对最新商品和库存，请先刷新商品。<button onClick={() => void loadCatalogue()}>刷新商品</button></div>}{needsReview && !pending && <div className="alert" role="alert">购物袋的售价、版本或库存有变化。请按最新报价确认后继续。{quote.removed.length > 0 && <p>将移除不可售商品：{quote.removed.join('、')}</p>}<button disabled={loading} onClick={() => { setCart(quote.lines); setNotice('购物袋已按最新售价和库存更新，请再次复核总额。'); setError('') }}>确认最新报价</button></div>}{!cart.length && !pending ? <p>购物袋还是空的。<button onClick={() => navigate('home')}>去选一件喜欢的衣服</button></p> : <div className="checkout-grid"><div>
        {cart.map((x, i) => <article className="bag-line" key={x.variant_id}><div><h3>{x.title}</h3><p>{x.color} / {x.size} · £{x.price}</p><div className="quantity"><button disabled={loading || !!pending || x.quantity <= 1} onClick={() => updateQuantity(i, x.quantity - 1)}>−</button><span>{x.quantity}</span><button disabled={loading || !!pending || x.quantity >= Math.min(20, x.available_qty)} onClick={() => updateQuantity(i, x.quantity + 1)}>+</button><button disabled={loading || !!pending} onClick={() => setCart(cart.filter((_, n) => i !== n))}>移除</button></div></div><strong>£{cartTotal([x])}</strong></article>)}
        {page === 'checkout' && !pending && <form id="checkout-form" onSubmit={e => { e.preventDefault(); void submit() }}><h2>演示收件资料</h2><p className="muted">请使用测试资料，不填写真实个人信息。只支持英格兰、苏格兰、威尔士。</p><button type="button" onClick={() => setAddress({ name: '演示顾客', email: 'buyer@example.invalid', line1: '12 Example Street', line2: '', city: 'London', region: '', postcode: 'SW1A 1AA', country: 'GB' })}>填入虚构测试资料</button><div className="form-grid">{([['name','收件人'],['email','联系邮箱'],['line1','地址第一行'],['line2','地址第二行（选填）'],['city','城市'],['region','地区（选填）'],['postcode','邮编']] as const).map(([key, label]) => <label key={key}>{label}<input value={address[key]} required={!['line2','region'].includes(key)} type={key === 'email' ? 'email' : 'text'} maxLength={key === 'postcode' ? 10 : key === 'name' ? 120 : ['city','region'].includes(key) ? 100 : 200} onChange={e => setAddress({ ...address, [key]: e.target.value })}/></label>)}</div></form>}
      </div><aside className="summary"><h2>订单复核</h2><p>商品小计 <strong>£{cartTotal(cart)}</strong></p><p>演示运费 <strong>£0.00</strong></p><p className="total">测试总额 <strong>£{cartTotal(cart)}</strong></p><p className="muted">演示价格，不计算真实税费。提交后等待商家确认库存；没有任何实际扣款。</p>{page === 'bag' ? <button key="bag-action" className="primary" disabled={!!pending || !catalogueReady || needsReview} onClick={() => navigate('checkout')}>填写演示资料</button> : <button key="checkout-action" className="primary" type="submit" form="checkout-form" disabled={submitting || !!pending || !catalogueReady || needsReview}>{submitting ? '正在提交…' : '提交演示订单（不扣款）'}</button>}</aside></div>}</section>}
      {page === 'order' && <section className="content"><p className="eyebrow">来自演示 ERP 的实际订单状态</p><h1>{order?.status_label || (error ? '暂时无法读取订单状态' : '读取订单中…')}</h1><button disabled={loading} onClick={() => void refreshOrder()}>刷新订单状态</button>{order && <><p>订单号：{order.public_id}</p><div className="notice">未真实收款 · 库存预留在 ERP 申请发货时发生</div>{order.fulfillment_issue && <p role="alert" className="alert">{order.fulfillment_issue}</p>}{order.items.map((x, i) => <div className="bag-line" key={i}><span>{x.title}<br/>{x.color} / {x.size} × {x.quantity}</span><strong>£{x.line_total}</strong></div>)}<p className="total">测试总额 £{order.grand_total}</p>{order.tracking_no && <p>演示出库单号：{order.tracking_no}<br/><span className="muted">未接承运商轨迹，出库不等于已揽收或签收。</span></p>}<p className="muted">去演示 ERP 审核这笔订单、申请发货并确认出库，再回来刷新查看。</p></>}</section>}
      {page === 'story' && <section className="content story"><p className="eyebrow">关于织间</p><h1>把喜欢，<br/>穿进今天。</h1><p>那件喜欢的衣服，不一定要留给生日、旅行，或很久以后的一场聚会。它也可以出现在一个普通的星期二，出现在下班后的散步里，出现在你突然想见朋友的下午。</p><p>织间想做的，是把这些小小的心动，放进真实的生活。衣服不必替你定义什么，只要陪你，自在地成为今天的自己。</p><h2>公司与联系</h2><p>{site?.company_name}<br/>{site?.company_address}<br/>{site?.contact_email}</p><div className="notice">公司信息是虚构演示资料，不代表真实经营主体。本环境不接收真实交易。</div><h2>配送与退换说明</h2><p>本地联调不产生真实包裹、付款或退款。正式营业前需确定实际主体、商品实拍与成分、配送与退货方案、税务及消费者政策；当前不作时效、退货或合规承诺。</p></section>}
    </main>
    <footer className="wrap footer">织间 · 把喜欢，穿进今天。<span>独立数据库联调 / 原 ERP 业务数据不受影响</span></footer>
    {selected && <dialog ref={modalRef} aria-label="选择颜色尺码" className="product-modal" onClose={closeProduct} onClick={e => { if (e.target === e.currentTarget) closeProduct() }}><button className="close" autoFocus aria-label="关闭商品详情" onClick={closeProduct}>×</button><h2>{selected.title}</h2><p className="muted">演示款，版型与尺寸需样衣验证；S/M/L 不直接等同特定英国码。</p><div className="variant-grid">{selected.variants.map(v => <button key={v.id} disabled={v.available_qty <= 0 || !!pending} aria-pressed={variantId === v.id} onClick={() => setVariantId(v.id)}>{v.color} · {v.size}<br/>£{v.price} / {v.available_qty > 0 ? `可用 ${v.available_qty} 件` : '暂时缺货'}</button>)}</div>{error && <p role="alert">{error}</p>}<button className="primary" disabled={!variant || !!pending} onClick={addSelected}>加入购物袋</button></dialog>}
  </>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>)
