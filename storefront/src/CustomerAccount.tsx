import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, errorText, request, type Customer } from './customer-api'
import './customer-account.css'

type OrderSummary = {
  public_id: string; status_label: string; grand_total: string; ordered_at: string | null
  payment_status: string; discount_amount: string; promo_code: string
  items: { title: string; color: string; size: string; quantity: number }[]
}
type AddressItem = {
  id: string; name: string; phone: string; line1: string; line2: string; city: string
  region: string; postcode: string; country: 'GB'; is_default: boolean
}
type AfterSalesItem = {
  id: string; public_ref: string; order_ref: string; kind: 'return' | 'refund'
  items: { title: string; color: string; size: string; quantity: number; line_total: string }[]
  reason: string; status: string; note: string; created_at: string | null
}
type Props = {
  customer: Customer | null; ready: boolean; sessionError: string; guestCount: number
  onCustomer: (customer: Customer | null) => void; onView: (id: string) => void
  onGuestOrders: () => void; onRetrySession: () => void; onShop: () => void
}

const emptyAddressForm = { name: '', phone: '', line1: '', line2: '', city: '', region: '', postcode: '' }

export default function CustomerAccount(props: Props) {
  const { customer, ready, onCustomer } = props
  const [mode, setMode] = useState<'login' | 'register'>(() => window.location.pathname.endsWith('/register') ? 'register' : 'login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [revision, setRevision] = useState(0)
  const [orders, setOrders] = useState<OrderSummary[]>([])
  const [total, setTotal] = useState(0)
  const [listBusy, setListBusy] = useState(false)
  const [listError, setListError] = useState('')
  const [view, setView] = useState<'orders' | 'profile' | 'addresses' | 'afterSales'>('orders')
  const [displayName, setDisplayName] = useState('')
  const [phone, setPhone] = useState('')
  const [preferredSize, setPreferredSize] = useState('')
  const [profileBusy, setProfileBusy] = useState(false)
  const [profileError, setProfileError] = useState('')
  const [profileNotice, setProfileNotice] = useState('')
  const [addresses, setAddresses] = useState<AddressItem[]>([])
  const [addressBusy, setAddressBusy] = useState(false)
  const [addressError, setAddressError] = useState('')
  const [addressNotice, setAddressNotice] = useState('')
  const [editingId, setEditingId] = useState('')
  const [addressForm, setAddressForm] = useState(emptyAddressForm)
  const [afterSales, setAfterSales] = useState<AfterSalesItem[]>([])
  const [afterSalesBusy, setAfterSalesBusy] = useState(false)
  const [afterSalesError, setAfterSalesError] = useState('')

  useEffect(() => {
    if (!customer) { setOrders([]); setTotal(0); return }
    let active = true
    setListBusy(true); setListError(''); setOrders([])
    request<{ items: OrderSummary[]; total: number }>('/account/orders?page=' + page)
      .then(result => { if (active) { setOrders(result.items); setTotal(result.total) } })
      .catch(cause => { if (active) { setListError(errorText(cause)); if (cause instanceof ApiError && cause.status === 401) onCustomer(null) } })
      .finally(() => { if (active) setListBusy(false) })
    return () => { active = false }
  }, [customer?.id, page, revision])

  useEffect(() => {
    if (view !== 'profile' || !customer) return
    let active = true
    request<{ customer: Customer }>('/account/me')
      .then(r => { if (active) { setDisplayName(r.customer.display_name || ''); setPhone(r.customer.phone || ''); setPreferredSize(r.customer.preferences?.preferred_size || '') } })
      .catch(() => {})
    return () => { active = false }
  }, [view, customer?.id])

  useEffect(() => {
    if (view !== 'addresses' || !customer) return
    let active = true
    setAddressBusy(true); setAddressError('')
    request<{ items: AddressItem[] }>('/account/addresses')
      .then(r => { if (active) setAddresses(r.items) })
      .catch(c => { if (active) setAddressError(errorText(c)) })
      .finally(() => { if (active) setAddressBusy(false) })
    return () => { active = false }
  }, [view, customer?.id])

  useEffect(() => {
    if (view !== 'afterSales' || !customer) return
    let active = true
    setAfterSalesBusy(true); setAfterSalesError('')
    request<{ items: AfterSalesItem[] }>('/account/after-sales')
      .then(r => { if (active) setAfterSales(r.items) })
      .catch(c => { if (active) setAfterSalesError(errorText(c)) })
      .finally(() => { if (active) setAfterSalesBusy(false) })
    return () => { active = false }
  }, [view, customer?.id])

  async function saveProfile(event: FormEvent) {
    event.preventDefault(); setProfileBusy(true); setProfileError(''); setProfileNotice('')
    try {
      await request('/account/me', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ display_name: displayName, phone, preferences: preferredSize.trim() ? { preferred_size: preferredSize.trim() } : {} }) })
      setProfileNotice('资料已更新')
    } catch (c) { setProfileError(errorText(c)) } finally { setProfileBusy(false) }
  }

  function resetAddressForm(item?: AddressItem) {
    setEditingId(item?.id || '')
    setAddressForm(item ? { name: item.name, phone: item.phone, line1: item.line1, line2: item.line2, city: item.city, region: item.region, postcode: item.postcode } : emptyAddressForm)
  }

  async function saveAddress(event: FormEvent) {
    event.preventDefault(); setAddressBusy(true); setAddressError(''); setAddressNotice('')
    try {
      const path = editingId ? '/account/addresses/' + editingId : '/account/addresses'
      const result = await request<AddressItem>(path, { method: editingId ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...addressForm, country: 'GB' }) })
      setAddresses(current => editingId ? current.map(x => x.id === result.id ? result : x) : [...current, result])
      setAddressNotice(editingId ? '地址已更新' : '地址已保存')
      resetAddressForm()
    } catch (c) { setAddressError(errorText(c)) } finally { setAddressBusy(false) }
  }

  async function removeAddress(id: string) {
    if (!window.confirm('确认删除这条收货地址？')) return
    setAddressBusy(true); setAddressError('')
    try {
      await request('/account/addresses/' + id, { method: 'DELETE' })
      setAddresses(current => current.filter(x => x.id !== id).map((x, index) => ({ ...x, is_default: index === 0 && current.some(y => y.id === id && y.is_default) })))
      setAddressNotice('地址已删除')
    } catch (c) { setAddressError(errorText(c)) } finally { setAddressBusy(false) }
  }

  async function makeDefault(id: string) {
    setAddressBusy(true); setAddressError('')
    try {
      await request('/account/addresses/' + id + '/default', { method: 'POST' })
      setAddresses(current => current.map(x => ({ ...x, is_default: x.id === id })))
      setAddressNotice('已设为默认地址')
    } catch (c) { setAddressError(errorText(c)) } finally { setAddressBusy(false) }
  }

  async function authenticate(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    if (mode === 'register' && password !== repeat) { setError('两次输入的密码不一致'); return }
    setBusy(true); setError('')
    try {
      const result = await request<{ customer: Customer }>('/account/' + mode, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }),
      })
      setPassword(''); setRepeat(''); setPage(1); onCustomer(result.customer)
      window.history.replaceState({}, '', '/account/orders')
    } catch (cause) { setError(errorText(cause)) } finally { setBusy(false) }
  }

  async function logout() {
    setBusy(true); setError('')
    try {
      await request('/account/logout', { method: 'POST' })
      setOrders([]); setTotal(0); setPage(1); setPassword(''); setRepeat(''); onCustomer(null)
    } catch (cause) { setError(errorText(cause)) } finally { setBusy(false) }
  }

  const afterSalesLabel = (status: string) => ({ submitted: '待处理', processing: '处理中', completed: '已完成', rejected: '已拒绝' } as Record<string, string>)[status] || status

  return <section className="content customer-account">
    <p className="eyebrow">织间 · 顾客中心</p>
    <div className="customer-heading"><div><h1>{customer ? '我的织间' : '欢迎回到织间'}</h1><p className="muted">{customer ? `你好，${customer.username}。在这里查看订单、收货地址与售后。` : '登录后下单，订单会保存在你的账号中。再次登录即可继续查看。'}</p></div>{customer && <button disabled={busy} onClick={() => void logout()}>{busy ? '正在退出…' : '退出登录'}</button>}</div>
    {error && <p className="alert" role="alert">{error}</p>}
    {!ready && !props.sessionError && <p role="status">正在读取顾客登录状态…</p>}
    {props.sessionError && <p className="alert" role="alert">{props.sessionError} <button onClick={props.onRetrySession}>重试连接</button></p>}
    {!customer && ready && <div className="customer-auth-grid"><div className="customer-auth-story"><span>YOUR EVERYDAY, KEPT CLOSE</span><h2>喜欢的衣服，<br />每一单都记得。</h2><p>从挑选、下单到商家出库，<br />随时回来，看看你的订单走到哪一步。</p><ul><li>订单记录随账号保存</li><li>查看最新备货与出库进度</li><li>从订单详情联系售后</li></ul></div><div className="customer-auth-card"><div className="customer-auth-tabs">{(['login', 'register'] as const).map(value => <button key={value} aria-pressed={mode === value} disabled={busy} onClick={() => { setMode(value); setError(''); setPassword(''); setRepeat('') }}>{value === 'login' ? '顾客登录' : '创建账号'}</button>)}</div><form onSubmit={event => void authenticate(event)}><label htmlFor="customer-username">用户名<input id="customer-username" autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} required minLength={3} maxLength={40} pattern="[a-zA-Z0-9_]+" placeholder="3–40 位字母、数字或下划线" /></label><label htmlFor="customer-password">密码<input id="customer-password" type="password" autoComplete={mode === 'register' ? 'new-password' : 'current-password'} value={password} onChange={e => setPassword(e.target.value)} required minLength={10} maxLength={128} placeholder="10–128 位密码" /></label>{mode === 'register' && <label htmlFor="customer-repeat">确认密码<input id="customer-repeat" type="password" autoComplete="new-password" value={repeat} onChange={e => setRepeat(e.target.value)} required minLength={10} maxLength={128} placeholder="再次输入密码" /></label>}<button className="primary" disabled={busy} type="submit">{busy ? '正在处理…' : mode === 'register' ? '注册并登录' : '登录，查看我的订单'}</button></form><p className="muted">这是商城顾客账号，与员工后台账号分开。用户名不区分大小写；目前暂不提供密码找回，请妥善保存。</p></div></div>}
    {customer && <><div className="customer-tabs" role="tablist" aria-label="顾客中心分栏"><button role="tab" aria-selected={view === 'orders'} onClick={() => setView('orders')}>我的订单</button><button role="tab" aria-selected={view === 'profile'} onClick={() => setView('profile')}>个人资料</button><button role="tab" aria-selected={view === 'addresses'} onClick={() => setView('addresses')}>收货地址</button><button role="tab" aria-selected={view === 'afterSales'} onClick={() => setView('afterSales')}>售后申请</button></div>
      {view === 'orders' && <><div className="customer-list-toolbar"><span>共 {total} 笔订单</span><button disabled={listBusy} onClick={() => setRevision(value => value + 1)}>刷新订单</button></div>{listError && <p className="alert" role="alert">{listError}</p>}{listBusy ? <p role="status">正在加载订单…</p> : !listError && !orders.length ? <div className="customer-empty"><h2>你的第一份喜欢，从这里开始</h2><p>当前账号还没有订单。登录后提交的订单会出现在这里。</p><button className="primary" onClick={props.onShop}>去逛逛</button></div> : orders.map(order => <article className="customer-order" key={order.public_id}><header><span>{order.public_id}</span><strong>{order.status_label}</strong></header>{order.ordered_at && <p className="muted">下单时间：{new Date(order.ordered_at).toLocaleString('zh-CN')}</p>}{order.items.map((item, index) => <p key={index}>{item.title}<small> {item.color} / {item.size} × {item.quantity}</small></p>)}<footer><span>演示订单总额 <strong>£{order.grand_total}</strong>{Number(order.discount_amount) > 0 && <small> 优惠 -£{order.discount_amount}{order.promo_code ? `（${order.promo_code}）` : ''}</small>}</span><small className={({ unpaid: 'muted', succeeded: 'payment-ok', failed: 'alert' } as Record<string, string>)[order.payment_status] || 'muted'}>支付：{{ unpaid: '未支付', succeeded: '已支付（演示）', failed: '支付失败' }[order.payment_status] || '—'}</small><button onClick={() => props.onView(order.public_id)}>订单详情 / 查看进度</button></footer></article>)}{total > 12 && <div className="customer-pagination"><button disabled={page === 1 || listBusy} onClick={() => setPage(value => value - 1)}>上一页</button><span>{page} / {Math.ceil(total / 12)}</span><button disabled={page * 12 >= total || listBusy} onClick={() => setPage(value => value + 1)}>下一页</button></div>}</>}
      {view === 'profile' && <div className="customer-panel"><h2>个人资料与偏好</h2>{profileNotice && <p className="notice" role="status">{profileNotice}</p>}{profileError && <p className="alert" role="alert">{profileError}</p>}<form onSubmit={e => void saveProfile(e)}><label>显示名称（可选）<input value={displayName} onChange={e => setDisplayName(e.target.value)} maxLength={120} placeholder="例如：林小姐" /></label><label>联系电话（可选）<input value={phone} onChange={e => setPhone(e.target.value)} maxLength={40} placeholder="例如：07700 900123" /></label><label>尺码偏好（可选）<input value={preferredSize} onChange={e => setPreferredSize(e.target.value)} maxLength={30} placeholder="例如：M / L" /></label><button className="primary" disabled={profileBusy}>{profileBusy ? '正在保存…' : '保存资料'}</button></form><p className="muted">资料仅用于演示订单流程，不会发送到第三方。</p></div>}
      {view === 'addresses' && <div className="customer-panel"><h2>收货地址簿</h2>{addressNotice && <p className="notice" role="status">{addressNotice}</p>}{addressError && <p className="alert" role="alert">{addressError}</p>}{addressBusy && !addresses.length && <p role="status">正在加载地址…</p>}{addresses.map(item => <article className="address-card" key={item.id}><p><strong>{item.name}</strong>{item.is_default && <small> 默认</small>}</p><p>{item.line1}{item.line2 ? `, ${item.line2}` : ''}<br/>{item.city}{item.region ? `, ${item.region}` : ''} {item.postcode}</p>{item.phone && <p className="muted">{item.phone}</p>}<div className="address-actions"><button disabled={addressBusy} onClick={() => resetAddressForm(item)}>编辑</button>{!item.is_default && <button disabled={addressBusy} onClick={() => void makeDefault(item.id)}>设为默认</button>}<button disabled={addressBusy} onClick={() => void removeAddress(item.id)}>删除</button></div></article>)}{!addressBusy && !addresses.length && <p className="muted">还没有保存的收货地址。结账时勾选“保存此地址到我的地址簿”，或直接在此添加。</p>}<form className="address-form" onSubmit={e => void saveAddress(e)}><h3>{editingId ? '编辑地址' : '新增地址'}</h3><div className="form-grid"><label>收件人<input value={addressForm.name} onChange={e => setAddressForm({ ...addressForm, name: e.target.value })} required maxLength={120} /></label><label>电话（选填）<input value={addressForm.phone} onChange={e => setAddressForm({ ...addressForm, phone: e.target.value })} maxLength={40} /></label><label>地址第一行<input value={addressForm.line1} onChange={e => setAddressForm({ ...addressForm, line1: e.target.value })} required maxLength={200} /></label><label>地址第二行（选填）<input value={addressForm.line2} onChange={e => setAddressForm({ ...addressForm, line2: e.target.value })} maxLength={200} /></label><label>城市<input value={addressForm.city} onChange={e => setAddressForm({ ...addressForm, city: e.target.value })} required maxLength={100} /></label><label>地区（选填）<input value={addressForm.region} onChange={e => setAddressForm({ ...addressForm, region: e.target.value })} maxLength={100} /></label><label>邮编<input value={addressForm.postcode} onChange={e => setAddressForm({ ...addressForm, postcode: e.target.value })} required maxLength={10} placeholder="例如：SW1A 1AA" /></label></div><div className="address-actions"><button className="primary" disabled={addressBusy} type="submit">{addressBusy ? '正在保存…' : '保存地址'}</button>{editingId && <button type="button" onClick={() => resetAddressForm()}>取消编辑</button>}</div></form></div>}
      {view === 'afterSales' && <div className="customer-panel"><h2>售后申请记录</h2>{afterSalesError && <p className="alert" role="alert">{afterSalesError}</p>}{afterSalesBusy ? <p role="status">正在加载售后记录…</p> : !afterSalesError && !afterSales.length ? <div className="customer-empty"><h2>暂无售后申请</h2><p>在订单详情页可以对已购商品申请退货或退款，申请后会出现在这里。</p><button className="primary" onClick={() => setView('orders')}>查看我的订单</button></div> : afterSales.map(item => <article className="address-card" key={item.id}><p><strong>{item.public_ref}</strong> · {item.kind === 'return' ? '退货' : '退款'} · <small className={item.status === 'rejected' ? 'alert' : item.status === 'completed' ? 'payment-ok' : 'muted'}>{afterSalesLabel(item.status)}</small></p><p className="muted">订单：{item.order_ref}{item.created_at ? ` · 申请于 ${new Date(item.created_at).toLocaleString('zh-CN')}` : ''}</p>{item.items.map((row, index) => <p key={index}>{row.title} · {row.color} / {row.size} × {row.quantity}<small> £{row.line_total}</small></p>)}<p>原因：{item.reason}</p>{item.note && <p className="muted">处理备注：{item.note}</p>}</article>)}</div>}
    </>}
    <div className="customer-guest-note"><strong>之前以游客身份下过单？</strong><p>账号不会自动认领游客订单。原下单标签页仍有访问凭据时，可以继续查询。</p>{props.guestCount > 0 && <button onClick={props.onGuestOrders}>查看本会话游客订单（{props.guestCount}）</button>}</div>
  </section>
}
