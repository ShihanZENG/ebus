import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { addItem, cartTotal, createSingleFlight, prepareSubmission, repriceCart } from './cart.mjs'
import { resolveProductRoute } from './product-route.mjs'
import { decideAnalyticsConsent, getAnalyticsConsent, readLocalEvents, trackLocalEvent } from './analytics.mjs'
import { applyStorefrontMetadata, storefrontMetadata } from './seo.mjs'
import './style.css'
import './dialog.css'
import './editorial.css'
import CustomerAccount from './CustomerAccount'
import SupportContact, { type SupportContactHandle } from './SupportContact'
import { ApiError, errorText, request, type Customer } from './customer-api'

type Variant = { id: string; color: string; size: string; price: string; available_qty: number }
type Product = { id: string; slug: string; title: string; description: string; category?: string; image_url: string; gallery?: string[]; material?: string; care_instructions?: string; size_guide?: { size: string; chest_cm?: string; waist_cm?: string; hip_cm?: string; length_cm?: string; sleeve_cm?: string }[]; version: number; created_at?: string; variants: Variant[] }
type CartLine = { variant_id: string; title: string; color: string; size: string; price: string; quantity: number; available_qty: number; product_version: number }
type Site = { brand_name: string; company_name: string; company_address: string; contact_email: string; demo: boolean; shipping_amount: string; delivery_regions: string[]; shipping_note: string }
type Order = { public_id: string; status_label: string; status: string; customer_masked: string; status_updated_at: string | null; fulfilment_events: { status: string; label: string; occurred_at: string | null }[]; grand_total: string; subtotal: string; discount_amount: string; promo_code: string; tracking_no: string; fulfillment_issue: string; payment_status: string; payment_method: string; payment_provider_ref: string; payment_amount: string; paid_at: string | null; items: { title: string; color: string; size: string; quantity: number; line_total: string }[] }
type Address = { name: string; email: string; line1: string; line2: string; city: string; region: string; postcode: string; country: 'GB' }
type AddressBookItem = { id: string; name: string; phone: string; line1: string; line2: string; city: string; region: string; postcode: string; country: 'GB'; is_default: boolean }
type AfterSalesRequest = { id: string; public_ref: string; order_ref: string; kind: 'return' | 'refund'; items: { title: string; color: string; size: string; quantity: number; line_total: string }[]; reason: string; message: string; status: 'submitted' | 'processing' | 'completed' | 'rejected'; note: string; created_at: string | null; updated_at: string | null }
type Pending = { key: string; recovery: string; fingerprint: string; payload: object; customerId?: string | null }
type ServerQuote = { subtotal: string; discount_amount: string; shipping_amount: string; tax_amount: string; grand_total: string; currency: string; limitations: string; fingerprint: string }
type OrderRef = { id: string; token: string; recovery?: Pending }
type SupportIssue = 'product' | 'delivery' | 'return' | 'other'
type SupportSummary = { ticket_ref: string; issue: SupportIssue; status: 'open' | 'in_progress' | 'resolved' | 'closed'; reply?: string; created_at: string | null }
type CatalogueFilters = { search: string; category: string; sizeFilter: string; colorFilter: string; priceRange: string; sort: 'featured' | 'price_asc' | 'price_desc' | 'newest' }
type CatalogueFacets = { categories: string[]; sizes: string[]; colors: string[] }
function initialCatalogueFilters(): CatalogueFilters {
  const params = new URLSearchParams(window.location.search)
  const path = window.location.pathname
  const min = params.get('min_price'), max = params.get('max_price'), sort = params.get('sort')
  return {
    search: params.get('q') || '',
    category: path.startsWith('/collections/') ? decodeURIComponent(path.slice('/collections/'.length)) : params.get('category') || '全部',
    sizeFilter: params.get('size') || '全部', colorFilter: params.get('color') || '全部',
    priceRange: min !== null && max !== null ? `${min}-${max}` : '',
    sort: sort === 'newest' || sort === 'price_asc' || sort === 'price_desc' ? sort : 'featured',
  }
}
function cataloguePath(filters: CatalogueFilters) {
  const params = new URLSearchParams()
  if (filters.search.trim()) params.set('q', filters.search.trim())
  if (filters.category !== '全部') params.set('category', filters.category)
  if (filters.sizeFilter !== '全部') params.set('size', filters.sizeFilter)
  if (filters.colorFilter !== '全部') params.set('color', filters.colorFilter)
  if (filters.priceRange) {
    const [min, max] = filters.priceRange.split('-')
    params.set('min_price', min); params.set('max_price', max)
  }
  if (filters.sort !== 'featured') params.set('sort', filters.sort)
  if (VISUAL_PREVIEW) params.set('preview', '1')
  const path = filters.category !== '全部' ? '/collections/' + encodeURIComponent(filters.category) : filters.search.trim() || filters.sizeFilter !== '全部' || filters.colorFilter !== '全部' || filters.priceRange || filters.sort !== 'featured' ? '/search' : '/'
  const query = params.toString()
  return path + (query ? '?' + query : '')
}
// 预览模式只在开发构建里可用；生产构建即使带上 ?preview=1 也不会被识别，避免假商品冒充目录。
const VISUAL_PREVIEW = import.meta.env.DEV && new URLSearchParams(window.location.search).get('preview') === '1'
// Explicit visual-only preview. Never used as real catalogue or sent to ERP.
const PREVIEW_PRODUCTS: Product[] = [
  {id:'preview-01',slug:'autumn-textures',title:'秋日层次 · 酒红针织',description:'柔软纹理与利落廓形，适合每一个不想刻意打扮的日常。视觉概念款，非在售商品。',category:'针织',image_url:'/look-01.jpg',gallery:['/look-01.jpg'],material:'视觉概念示例',version:1,variants:[{id:'vp-01-s',color:'酒红',size:'S',price:'68.00',available_qty:10},{id:'vp-01-m',color:'酒红',size:'M',price:'68.00',available_qty:10}]},
  {id:'preview-02',slug:'soft-tailoring',title:'自在有型 · 羊毛感外套',description:'带一点结构感的经典外套，以轻松的方式完成整日穿搭。视觉概念款，非在售商品。',category:'外套',image_url:'/look-02.jpg',gallery:['/look-02.jpg'],material:'视觉概念示例',version:1,variants:[{id:'vp-02-s',color:'燕麦',size:'S',price:'128.00',available_qty:10},{id:'vp-02-m',color:'燕麦',size:'M',price:'128.00',available_qty:10}]},
  {id:'preview-03',slug:'city-stories',title:'城市漫步 · 慵懒叠搭',description:'从晨间咖啡到傍晚街角，把温暖与轻盈留给自己。视觉概念款，非在售商品。',category:'穿搭灵感',image_url:'/look-03.jpg',gallery:['/look-03.jpg'],version:1,variants:[{id:'vp-03-s',color:'深灰',size:'S',price:'86.00',available_qty:10}]},
  {id:'preview-04',slug:'quiet-essential',title:'日常精选 · 经典内搭',description:'四季可以重复搭配的经典基本款。视觉概念款，非在售商品。',category:'基础款',image_url:'/look-04.jpg',gallery:['/look-04.jpg'],version:1,variants:[{id:'vp-04-s',color:'奶油白',size:'S',price:'49.00',available_qty:10}]},
]
const CAMPAIGNS: Record<string, { title: string; tagline: string; description: string; category: string; image: string }> = {
  'autumn-edit': { title: '秋日专题 · 把日常穿松一点', tagline: 'AUTUMN EDIT / 26', description: '围绕“松弛感”挑选的针织单品集合：同色系叠穿、宽松廓形与低饱和色，适合初秋到深秋的日常。', category: '针织', image: '/look-01.jpg' },
}
const KEYS = { cart: 'zhijian.cart', pending: 'zhijian.pending', order: 'zhijian.order', orders: 'zhijian.orders', afterSales: 'zhijian.afterSales' } /* 售后申请列表缓存键 */
type Page = 'home' | 'product' | 'bag' | 'checkout' | 'order' | 'account' | 'story' | 'help' | 'policies' | 'status' | 'campaign' | 'notFound'
const ROUTES: Record<Page, string> = { home: '/', product: '/products', bag: '/cart', checkout: '/checkout', order: '/checkout/result', account: '/account/orders', story: '/about', help: '/help', policies: '/policies/privacy', campaign: '/campaigns/autumn-edit', status: '/status', notFound: '/404' }
function pageFromPath(path: string): Page {
  if (path === '/cart') return 'bag'
  if (path === '/checkout') return 'checkout'
  if (path === '/checkout/result' || path === '/orders/lookup') return 'order'
  if (['/account/orders', '/account/login', '/account/register'].includes(path)) return 'account'
  if (path === '/about') return 'story'
  if (path === '/help') return 'help'
  if (path === '/status') return 'status'
  if (path === '/404') return 'notFound'
  if (path.startsWith('/policies/')) return 'policies'
  if (path.startsWith('/campaigns/')) return 'campaign'
  if (path.startsWith('/products/')) return 'product'
  if (path.startsWith('/collections/') || path === '/search') return 'home'
  return path === '/' ? 'home' : 'notFound'
}
function read<T>(key: string, fallback: T): T { try { return JSON.parse(sessionStorage.getItem(key) || 'null') ?? fallback } catch { return fallback } }
function save(key: string, value: unknown) { sessionStorage.setItem(key, JSON.stringify(value)) }

function App() {
  const [customer, setCustomer] = useState<Customer | null>(null)
  const [customerReady, setCustomerReady] = useState(false)
  const [sessionError, setSessionError] = useState('')
  const [showGuestOrders, setShowGuestOrders] = useState(false)
  const customerIdRef = useRef<string | null>(null)
  const privateVersion = useRef(0)
  const sessionLoadVersion = useRef(0)
  const [site, setSite] = useState<Site | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [catalogueTotal, setCatalogueTotal] = useState(0)
  const [cataloguePage, setCataloguePage] = useState(1)
  const [catalogueFacets, setCatalogueFacets] = useState<CatalogueFacets>({ categories: [], sizes: [], colors: [] })
  const [page, setPage] = useState<Page>(() => pageFromPath(window.location.pathname))
  const [urlVersion, setUrlVersion] = useState(0)
  const [selected, setSelected] = useState<Product | null>(null)
  const [galleryIndex, setGalleryIndex] = useState(0)
  const [variantId, setVariantId] = useState('')
  const [selectedQuantity, setSelectedQuantity] = useState(1)
  useEffect(() => { setSelectedQuantity(1) }, [variantId, selected?.id])
  const [cart, setCart] = useState<CartLine[]>(() => read(KEYS.cart, []))
  const [pending, setPending] = useState<Pending | null>(() => read(KEYS.pending, null))
  const [orderRef, setOrderRef] = useState<OrderRef | null>(() => read(KEYS.order, null))
  const [orderRefs, setOrderRefs] = useState<OrderRef[]>(() => read<OrderRef[]>(KEYS.orders, (() => { const legacy = read<OrderRef | null>(KEYS.order, null); return legacy ? [legacy] : [] })()))
  const [history, setHistory] = useState<Order[]>([])
  const [order, setOrder] = useState<Order | null>(null)
  const [supportIssue, setSupportIssue] = useState<SupportIssue>('delivery')
  const [supportMessage, setSupportMessage] = useState('')
  const [supportTicketRef, setSupportTicketRef] = useState('')
  const [supportRequests, setSupportRequests] = useState<SupportSummary[]>([])
  const [supportSending, setSupportSending] = useState(false)
  const [paymentSending, setPaymentSending] = useState(false)
  const [afterSaleKind, setAfterSaleKind] = useState<'return' | 'refund'>('return')
  const [afterSaleReason, setAfterSaleReason] = useState('')
  const [afterSaleMessage, setAfterSaleMessage] = useState('')
  const [afterSaleSending, setAfterSaleSending] = useState(false)
  const [afterSales, setAfterSales] = useState<AfterSalesRequest[]>([])
  const [promoCode, setPromoCode] = useState('')
  const [serverQuote, setServerQuote] = useState<ServerQuote | null>(null)
  const [savedAddresses, setSavedAddresses] = useState<AddressBookItem[]>([])
  const [saveAddressBook, setSaveAddressBook] = useState(false)
  const [address, setAddress] = useState<Address>({ name: '', email: '', line1: '', line2: '', city: '', region: '', postcode: '', country: 'GB' })
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [catalogueReady, setCatalogueReady] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [serviceStatus, setServiceStatus] = useState<'checking' | 'available' | 'unavailable'>('checking')
  const [statusRefresh, setStatusRefresh] = useState(0)
  const [search, setSearch] = useState(() => initialCatalogueFilters().search)
  const [category, setCategory] = useState(() => initialCatalogueFilters().category)
  const [sizeFilter, setSizeFilter] = useState(() => initialCatalogueFilters().sizeFilter)
  const [colorFilter, setColorFilter] = useState(() => initialCatalogueFilters().colorFilter)
  const [priceRange, setPriceRange] = useState(() => initialCatalogueFilters().priceRange)
  const [sort, setSort] = useState<CatalogueFilters['sort']>(() => initialCatalogueFilters().sort)
  const [analyticsConsent, setAnalyticsConsent] = useState<'unset' | 'granted' | 'denied'>(() => getAnalyticsConsent())
  const [analyticsSettingsOpen, setAnalyticsSettingsOpen] = useState(false)
  const [analyticsEventCount, setAnalyticsEventCount] = useState(() => readLocalEvents().length)
  const submitGate = useRef(createSingleFlight())
  const refreshGate = useRef(createSingleFlight())
  const orderAutoLoad = useRef('')
  const modalRef = useRef<HTMLDialogElement>(null)
  const supportContactRef = useRef<SupportContactHandle>(null)
  const openerRef = useRef<HTMLElement | null>(null)
  const privacyDialogRef = useRef<HTMLDialogElement>(null)
  const privacyOpenerRef = useRef<HTMLElement | null>(null)
  const lastPageViewRef = useRef('')
  const lastProductViewRef = useRef('')
  const quoteChangedRef = useRef(false)
  const lastViewedOrderStatusRef = useRef('')
  const lastAddressInvalidAtRef = useRef(0)
  function updateCustomer(next: Customer | null) {
    sessionLoadVersion.current += 1
    if (customerIdRef.current !== (next?.id ?? null)) {
      privateVersion.current += 1
      setOrder(null); setOrderRef(null); setHistory([]); setSupportRequests([]); setSavedAddresses([]); setSaveAddressBook(false); setAfterSales([]); setPromoCode('')
      setSupportMessage(''); setSupportTicketRef(''); setError(''); setNotice('')
      sessionStorage.removeItem(KEYS.order)
      orderAutoLoad.current = ''
      // Never retain a member's order capabilities in browser storage.
      setOrderRefs(current => current.filter(ref => !!ref.token))
      setAddress({ name: '', email: '', line1: '', line2: '', city: '', region: '', postcode: '', country: 'GB' })
    }
    customerIdRef.current = next?.id ?? null
    setCustomer(next); setCustomerReady(true); setSessionError(''); setShowGuestOrders(false)
  }
  async function loadCustomer() {
    const version = ++sessionLoadVersion.current
    try {
      const result = await request<{ customer: Customer | null }>('/account/me')
      if (version === sessionLoadVersion.current) updateCustomer(result.customer)
    } catch (cause) {
      if (version !== sessionLoadVersion.current) return
      if (cause instanceof ApiError && cause.status === 401) updateCustomer(null)
      else { setSessionError('暂时无法读取登录状态，请重试。'); setCustomerReady(false) }
    }
  }
  useEffect(() => {
    void loadCustomer()
    const refresh = () => { void loadCustomer() }
    window.addEventListener('focus', refresh)
    return () => { sessionLoadVersion.current += 1; window.removeEventListener('focus', refresh) }
  }, [])
  const variant = selected?.variants.find(v => v.id === variantId)
  const quote = repriceCart(cart, products)
  const needsReview = catalogueReady && quote.changed
  const checkoutPayload = { items: cart.map(x => ({ variant_id: x.variant_id, quantity: x.quantity, product_version: x.product_version })), address, ...(promoCode.trim() ? { promo_code: promoCode.trim() } : {}) }
  const checkoutFingerprint = JSON.stringify({ ...checkoutPayload, customerId: customer?.id ?? null })
  const quoteReady = !!serverQuote && serverQuote.fingerprint === checkoutFingerprint && !needsReview
  function recordLocal(name: Parameters<typeof trackLocalEvent>[2], properties: Parameters<typeof trackLocalEvent>[3] = {}) {
    if (trackLocalEvent(undefined, undefined, name, properties)) {
      setAnalyticsEventCount(readLocalEvents().length)
    }
  }
  useEffect(() => { save(KEYS.cart, cart) }, [cart])
  useEffect(() => { save(KEYS.orders, orderRefs.slice(0, 20)) }, [orderRefs])
  useEffect(() => {
    const product = page === 'product' ? selected : null
    const canonicalPath = window.location.pathname
    applyStorefrontMetadata(storefrontMetadata({
      pathname: canonicalPath,
      search: window.location.search,
      origin: window.location.origin,
      siteName: site?.brand_name || '织间',
      product,
    }))
  }, [page, selected, site, urlVersion])
  useEffect(() => { if (selected && modalRef.current && !modalRef.current.open) modalRef.current.showModal() }, [selected])
  useEffect(() => {
    if (!analyticsSettingsOpen || !privacyDialogRef.current || privacyDialogRef.current.open) return
    privacyDialogRef.current.showModal()
  }, [analyticsSettingsOpen])
  useEffect(() => {
    if (analyticsConsent !== 'granted') { lastPageViewRef.current = ''; return }
    const pageName = page === 'bag' ? 'cart' : page
    if (lastPageViewRef.current === pageName) return
    lastPageViewRef.current = pageName
    recordLocal('page_view', { page: pageName })
  }, [analyticsConsent, page])
  useEffect(() => {
    if (!selected) { lastProductViewRef.current = ''; return }
    if (analyticsConsent === 'granted' && lastProductViewRef.current !== selected.id) {
      lastProductViewRef.current = selected.id
      recordLocal('product_view', { product_id: selected.id })
    }
  }, [analyticsConsent, selected])
  useEffect(() => {
    if (needsReview && !quoteChangedRef.current) recordLocal('quote_changed')
    quoteChangedRef.current = needsReview
  }, [needsReview])
  useEffect(() => {
    if (!order || analyticsConsent !== 'granted') { lastViewedOrderStatusRef.current = ''; return }
    const key = `${order.status}:${order.status_updated_at || ''}`
    if (lastViewedOrderStatusRef.current !== key) {
      lastViewedOrderStatusRef.current = key
      recordLocal('order_status_viewed')
    }
  }, [analyticsConsent, order])
  function chooseAnalyticsConsent(decision: 'granted' | 'denied') {
    if (!decideAnalyticsConsent(undefined, undefined, decision)) {
      setError('浏览器本地存储不可用，分析保持关闭。')
      return
    }
    setAnalyticsConsent(decision)
    setAnalyticsEventCount(readLocalEvents().length)
    if (privacyDialogRef.current?.open) privacyDialogRef.current.close()
  }
  function openAnalyticsSettings(event: React.MouseEvent<HTMLElement>) {
    privacyOpenerRef.current = event.currentTarget
    setAnalyticsEventCount(readLocalEvents().length)
    setAnalyticsSettingsOpen(true)
  }
  function closeAnalyticsSettings() {
    setAnalyticsSettingsOpen(false)
    queueMicrotask(() => privacyOpenerRef.current?.focus())
  }
  async function loadCatalogue(preserveError = false, requestedPage = 1, filterOverride?: CatalogueFilters) {
    if (!preserveError) setError('')
    setLoading(true); setCatalogueReady(false)
    try {
      if (VISUAL_PREVIEW) {
        const f = filterOverride || {search,category,sizeFilter,colorFilter,priceRange,sort}
        let items = PREVIEW_PRODUCTS.filter(x => (f.category === '全部' || x.category === f.category) && (!f.search.trim() || x.title.includes(f.search.trim())))
        if (f.sizeFilter !== '全部') items = items.filter(x => x.variants.some(v => v.size === f.sizeFilter))
        if (f.colorFilter !== '全部') items = items.filter(x => x.variants.some(v => v.color === f.colorFilter))
        if (f.priceRange) { const [low, high] = f.priceRange.split('-').map(Number); items = items.filter(x => Number(x.variants[0]?.price || 0) >= low && Number(x.variants[0]?.price || 0) <= high) }
        if (f.sort === 'price_asc') items.sort((a,b) => Number(a.variants[0].price)-Number(b.variants[0].price))
        if (f.sort === 'price_desc') items.sort((a,b) => Number(b.variants[0].price)-Number(a.variants[0].price))
        setSite({brand_name:'织间',company_name:'视觉预览',company_address:'仅供设计演示',contact_email:'demo@example.invalid',demo:true,shipping_amount:'0.00',delivery_regions:['英格兰','苏格兰','威尔士'],shipping_note:'视觉预览环境，不接真实配送。'})
        setProducts(items); setCatalogueTotal(items.length); setCataloguePage(1)
        setCatalogueFacets({categories:[...new Set(PREVIEW_PRODUCTS.map(x => x.category || '女装'))],sizes:['S','M'],colors:['酒红','燕麦','深灰','奶油白']})
        setCatalogueReady(true)
        return
      }
      const f = filterOverride || { search, category, sizeFilter, colorFilter, priceRange, sort }
      const query = new URLSearchParams({ page: String(requestedPage), page_size: '12', sort: f.sort })
      if (f.search.trim()) query.set('q', f.search.trim())
      if (f.category !== '全部') query.set('category', f.category)
      if (f.sizeFilter !== '全部') query.set('size', f.sizeFilter)
      if (f.colorFilter !== '全部') query.set('color', f.colorFilter)
      if (f.priceRange) {
        const [min, max] = f.priceRange.split('-')
        query.set('min_price', min); query.set('max_price', max)
      }
      const [s, p] = await Promise.all([request<Site>('/site'), request<{ items: Product[]; total: number; facets: CatalogueFacets }>('/products?' + query.toString())])
      if (!Array.isArray(p.items) || !Number.isFinite(p.total)) throw new Error('商品目录返回内容无效')
      setSite(s); setProducts(p.items); setCatalogueTotal(p.total)
      setCatalogueFacets({
        categories: Array.isArray(p.facets?.categories) ? p.facets.categories : [],
        sizes: Array.isArray(p.facets?.sizes) ? p.facets.sizes : [],
        colors: Array.isArray(p.facets?.colors) ? p.facets.colors : [],
      })
      setCataloguePage(requestedPage); setCatalogueReady(true)
    } catch (e) { setError(errorText(e)) } finally { setLoading(false) }
  }
  useEffect(() => { void loadCatalogue() }, [])
  useEffect(() => {
    const onPopState = () => {
      setUrlVersion(version => version + 1)
      setError(''); setNotice(''); setSelected(null); setPage(pageFromPath(window.location.pathname))
      const restored = initialCatalogueFilters()
      setSearch(restored.search); setCategory(restored.category); setSizeFilter(restored.sizeFilter)
      setColorFilter(restored.colorFilter); setPriceRange(restored.priceRange); setSort(restored.sort)
      if (pageFromPath(window.location.pathname) === 'home') void loadCatalogue(true, 1, restored)
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])
  useEffect(() => {
    if (page === 'order' && orderRef && !order && !loading && orderAutoLoad.current !== orderRef.id) {
      orderAutoLoad.current = orderRef.id
      void refreshOrder(orderRef)
    }
  }, [page, orderRef, order, loading])
  useEffect(() => {
    if (page !== 'account' || !showGuestOrders) return
    let active = true
    Promise.all(orderRefs.filter(ref => !!ref.token).slice(0, 20).map(ref => request<Order>('/orders/' + encodeURIComponent(ref.id), {
      headers: { Authorization: 'Bearer ' + ref.token },
    }).catch(() => null))).then(rows => { if (active) setHistory(rows.filter((row): row is Order => row !== null)) })
    return () => { active = false }
  }, [page, orderRefs, showGuestOrders])
  useEffect(() => {
    if (page !== 'order' || !order || !orderRef) return
    let active = true
    request<{ items: SupportSummary[] }>('/support-requests?order_ref=' + encodeURIComponent(order.public_id), {
      headers: orderRef.token ? { Authorization: 'Bearer ' + orderRef.token } : {},
    }).then(result => { if (active) setSupportRequests(result.items) }).catch(() => { if (active) setSupportRequests([]) })
    return () => { active = false }
  }, [page, order, orderRef])
  useEffect(() => {
    if (page !== 'checkout' || !customer) { setSavedAddresses([]); return }
    let active = true
    request<{ items: AddressBookItem[] }>('/account/addresses').then(result => { if (active) setSavedAddresses(result.items) }).catch(() => { if (active) setSavedAddresses([]) })
    return () => { active = false }
  }, [page, customer?.id])
  useEffect(() => {
    if (page !== 'order' || !order || !orderRef) { setAfterSales([]); return }
    let active = true
    request<{ items: AfterSalesRequest[] }>('/after-sales?order_ref=' + encodeURIComponent(order.public_id), {
      headers: orderRef.token ? { Authorization: 'Bearer ' + orderRef.token } : {},
    }).then(result => { if (active) setAfterSales(result.items) }).catch(() => { if (active) setAfterSales([]) })
    return () => { active = false }
  }, [page, order?.public_id, orderRef?.token])
  useEffect(() => {
    if (page !== 'campaign') return
    const slug = window.location.pathname.replace(/^\/campaigns\//, '')
    if (!CAMPAIGNS[slug]) return
    void loadCatalogue(false, 1, { search: '', category: CAMPAIGNS[slug].category, sizeFilter: '全部', colorFilter: '全部', priceRange: '', sort: 'featured' })
  }, [page])

  useEffect(() => {
    if (page !== 'status') return
    let active = true
    setServiceStatus('checking')
    request<Site>('/site').then(() => { if (active) setServiceStatus('available') }).catch(() => { if (active) setServiceStatus('unavailable') })
    return () => { active = false }
  }, [page, statusRefresh])
  useEffect(() => {
    if (page !== 'product' || selected) return
    let active = true
    const routeProducts = VISUAL_PREVIEW ? PREVIEW_PRODUCTS : products
    const route = resolveProductRoute(window.location.pathname, routeProducts)
    if (route.kind === 'not_found') { navigate('notFound'); return () => { active = false } }
    if (route.kind === 'loaded') {
      setVariantId(''); setGalleryIndex(0); setSelected(route.product)
      return () => { active = false }
    }
    request<Product>(route.path).then(value => {
      if (active) { setVariantId(''); setGalleryIndex(0); setSelected(value) }
    }).catch(() => { if (active) navigate('notFound') })
    return () => { active = false }
  }, [page, products, selected])
  function navigate(next: Page) {
    if (page === 'bag' && next === 'checkout') recordLocal('checkout_started')
    setError(''); setNotice(''); setSelected(null)
    const route = ROUTES[next] + (VISUAL_PREVIEW ? '?preview=1' : '')
    if (window.location.pathname + window.location.search !== route) window.history.pushState({}, '', route)
    setUrlVersion(version => version + 1)
    setPage(next); window.scrollTo(0, 0)
  }
  function showNewIn() {
    const next: CatalogueFilters = { search: '', category: '全部', sizeFilter: '全部', colorFilter: '全部', priceRange: '', sort: 'newest' }
    setSearch(next.search); setCategory(next.category); setSizeFilter(next.sizeFilter)
    setColorFilter(next.colorFilter); setPriceRange(next.priceRange); setSort(next.sort)
    setSelected(null); setPage('home')
    applyCatalogueFilters(next)
  }
  function focusCatalogueSearch() {
    if (page !== 'home') navigate('home')
    requestAnimationFrame(() => requestAnimationFrame(() => document.getElementById('catalogue-search')?.focus()))
  }
  function openProduct(product: Product) {
    openerRef.current = document.activeElement as HTMLElement
    const path = '/products/' + encodeURIComponent(product.slug) + (VISUAL_PREVIEW ? '?preview=1' : '')
    if (window.location.pathname !== path) window.history.pushState({}, '', path)
    setUrlVersion(version => version + 1)
    setPage('product'); setSelected(product); setVariantId(''); setGalleryIndex(0); setError('')
  }
  function closeProduct() {
    setSelected(null)
    if (window.location.pathname.startsWith('/products/')) { window.history.replaceState({}, '', VISUAL_PREVIEW ? '/?preview=1' : '/'); setPage('home'); setUrlVersion(version => version + 1) }
    queueMicrotask(() => openerRef.current?.focus())
  }
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
        setCart(addItem(cart, next, selectedQuantity))
        setNotice('已加入购物袋。提交订单前会再次核对售价和库存。')
      }
      recordLocal('add_to_cart', { product_id: selected.id, sku_id: variant.id })
      recordLocal('cart_updated', { product_id: selected.id, sku_id: variant.id })
      closeProduct(); setError('')
    } catch (e) { setError(errorText(e)) }
  }
  async function refreshOrder(ref: OrderRef | null = orderRef) {
    if (!ref || refreshGate.current.active()) return
    const version = privateVersion.current
    orderAutoLoad.current = ref.id
    return refreshGate.current.run(async () => {
      setLoading(true); setError(''); setOrder(null); navigate('order')
      try {
        const result = await request<Order>('/orders/' + encodeURIComponent(ref.id), { headers: ref.token ? { Authorization: 'Bearer ' + ref.token } : {} })
        if (version === privateVersion.current) setOrder(result)
      } catch (e) {
        if (version !== privateVersion.current) return
        if (e instanceof ApiError && e.status === 404 && ref.recovery) {
          try {
            const recovered = await request<{ order: Order; access_token: string }>('/checkout', {
              method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': ref.recovery.key, 'X-Checkout-Recovery': ref.recovery.recovery, 'X-Customer-Id': ref.recovery.customerId || 'guest' },
              body: JSON.stringify(ref.recovery.payload),
            })
            if (version !== privateVersion.current) return
            if (recovered.order.public_id !== ref.id) throw new Error('恢复订单号不一致，请联系演示管理员')
            const renewed = { ...ref, token: recovered.access_token }
            save(KEYS.order, renewed); setOrderRef(renewed); setOrder(recovered.order)
            setOrderRefs(current => [renewed, ...current.filter(item => item.id !== renewed.id)].slice(0, 20))
          } catch (recoverError) { setError('查单凭据已失效，原提交恢复失败：' + errorText(recoverError)) }
        } else setError(errorText(e))
      } finally { setLoading(false) }
    })
  }
  async function submit() {
    if (VISUAL_PREVIEW) { setError('视觉预览模式不可提交订单。请连接演示 ERP 后使用正式联调流程。'); return }
    if (!customerReady) { setError('请先确认顾客登录状态，再提交订单。'); return }
    if (submitGate.current.active() || (!cart.length && !pending) || (!pending && (!catalogueReady || quote.changed))) return
    if (!pending) recordLocal('checkout_submitted')
    return submitGate.current.run(async () => {
    setLoading(true); setSubmitting(true); setError('')
    const version = privateVersion.current
    try {
      if (!pending && !quoteReady) {
        const result = await request<Omit<ServerQuote, 'fingerprint'>>('/checkout/quote', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(checkoutPayload),
        })
        if (version !== privateVersion.current) return
        setServerQuote({ ...result, fingerprint: checkoutFingerprint })
        setNotice('金额已由服务端核算，请核对最终总额后确认创建订单。')
        return
      }
      const payload = pending?.payload || { ...checkoutPayload, expected_total: serverQuote!.grand_total }
      const identity: Pending = pending || { ...prepareSubmission(null, payload), payload, customerId: customer?.id ?? null }
      // Save before any network request. An uncertain result must be retried
      // with exactly this identity and payload, never silently submitted twice.
      save(KEYS.pending, identity); setPending(identity)
      const result = await request<{ order: Order; access_token: string }>('/checkout', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': identity.key, 'X-Checkout-Recovery': identity.recovery, 'X-Customer-Id': identity.customerId || 'guest' },
        body: JSON.stringify(identity.payload),
      })
      if (version !== privateVersion.current) return
      const ref: OrderRef = identity.customerId ? { id: result.order.public_id, token: '' } : { id: result.order.public_id, token: result.access_token, recovery: identity }
      save(KEYS.order, ref); setOrderRef(ref); setOrder(result.order)
      setOrderRefs(current => [ref, ...current.filter(item => item.id !== ref.id)].slice(0, 20))
      recordLocal('order_accepted')
      if (customer && saveAddressBook) request('/account/addresses', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: address.name, phone: '', line1: address.line1, line2: address.line2, city: address.city, region: address.region, postcode: address.postcode, country: address.country }) }).catch(() => {})
      sessionStorage.removeItem(KEYS.pending); setPending(null); setCart([]); navigate('order')
    } catch (e) {
      if (version !== privateVersion.current) return
      recordLocal('checkout_failed')
      if (page === 'checkout' && e instanceof ApiError && e.status === 422) recordLocal('address_validation_failed')
      if (e instanceof ApiError && [409, 422].includes(e.status)) { sessionStorage.removeItem(KEYS.pending); setPending(null); setServerQuote(null) }
      setError(errorText(e) + (!pending && !quoteReady ? '。金额核算未完成，尚未创建订单，请重试。' : e instanceof ApiError ? '' : '。提交结果尚未确认，请使用“重试原提交”，不要重复新建订单。'))
      if (e instanceof ApiError && e.status === 409) void loadCatalogue(true)
    } finally { setLoading(false); setSubmitting(false) }
    })
  }
  async function submitSupport(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!orderRef || !order || !supportMessage.trim() || supportSending) return
    setSupportSending(true); setError('')
    const version = privateVersion.current
    try {
      const form = new FormData()
      form.set('order_ref', order.public_id); form.set('issue', supportIssue); form.set('message', supportMessage.trim())
      const attachment = (document.getElementById('support-attachment') as HTMLInputElement | null)?.files?.[0]
      if (attachment) form.set('file', attachment)
      const result = await request<{ ticket_ref: string; status: string }>('/support-requests', {
        method: 'POST', headers: orderRef.token ? { Authorization: 'Bearer ' + orderRef.token } : {}, body: form,
      })
      if (version !== privateVersion.current) return
      setSupportTicketRef(result.ticket_ref); setSupportMessage('')
      setSupportRequests(current => [{ ticket_ref: result.ticket_ref, issue: supportIssue, status: 'open', created_at: new Date().toISOString() }, ...current])
      const input = document.getElementById('support-attachment') as HTMLInputElement | null
      if (input) input.value = ''
    } catch (e) { setError(errorText(e)) } finally { setSupportSending(false) }
  }
  async function submitPayment(scenario: 'success' | 'fail') {
    if (!order || !orderRef) return
    setPaymentSending(true); setError('')
    const version = privateVersion.current
    try {
      const result = await request<{ payment: { status: string; public_ref: string }; order: Order; created: boolean }>(
        '/orders/' + encodeURIComponent(order.public_id) + '/payments',
        { method: 'POST', headers: orderRef.token ? { Authorization: 'Bearer ' + orderRef.token } : {}, body: JSON.stringify({ scenario }) })
      if (version !== privateVersion.current) return
      setOrder(result.order)
      recordLocal('payment_simulation', { scenario, status: result.payment.status })
    } catch (e) {
      if (version !== privateVersion.current) return
      setError(errorText(e))
    } finally { setPaymentSending(false) }
  }
  async function submitAfterSales(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!order || !orderRef || !afterSaleReason.trim() || afterSaleSending) return
    setAfterSaleSending(true); setError('')
    const version = privateVersion.current
    try {
      const items = order.items.map((_, line) => ({ line, quantity: order.items[line].quantity }))
      const result = await request<{ request: { public_ref: string; status: string } }>(
        '/orders/' + encodeURIComponent(order.public_id) + '/after-sales',
        { method: 'POST', headers: orderRef.token ? { Authorization: 'Bearer ' + orderRef.token } : {},
          body: JSON.stringify({ kind: afterSaleKind, items, reason: afterSaleReason.trim(), message: afterSaleMessage.trim() }) })
      if (version !== privateVersion.current) return
      setAfterSaleReason(''); setAfterSaleMessage('')
      setNotice('售后申请已提交：' + result.request.public_ref)
    } catch (e) {
      if (version !== privateVersion.current) return
      setError(errorText(e))
    } finally { setAfterSaleSending(false) }
  }
  function updateQuantity(index: number, amount: number) {
    recordLocal('cart_updated', { sku_id: cart[index]?.variant_id })
    setCart(cart.map((x, i) => i === index ? { ...x, quantity: Math.min(20, x.available_qty, Math.max(1, amount)) } : x))
  }
  const count = cart.reduce((n, x) => n + x.quantity, 0)
  const categories = ['全部', ...new Set(products.map(p => p.category || '女装'))]
  const visibleProducts = products
  const totalPages = Math.max(1, Math.ceil(catalogueTotal / 12))
  const filters: CatalogueFilters = { search, category, sizeFilter, colorFilter, priceRange, sort }
  const hasFilters = !!search.trim() || category !== '全部' || sizeFilter !== '全部' || colorFilter !== '全部' || !!priceRange
  const campaign = page === 'campaign' ? CAMPAIGNS[window.location.pathname.replace(/^\/campaigns\//, '')] : null
  function applyCatalogueFilters(next = filters) {
    const path = cataloguePath(next)
    if (window.location.pathname + window.location.search !== path) window.history.pushState({}, '', path)
    setUrlVersion(version => version + 1)
    void loadCatalogue(false, 1, next)
  }
  return <>
    <a className="skip-link" href="#main-content">跳至主要内容</a>
    <div className="demo-banner"><span>{VISUAL_PREVIEW ? '视觉预览 · 图片与商品为概念示例 · 不开放下单' : '演示联调环境 · 不收款 / 不发真实包裹'}</span><span className="announcement-right">以日常为灵感，以舒适为日常 <span aria-hidden="true">✦</span></span></div>
    <header className="wrap header">
      <nav className="header-left" aria-label="商品导航"><button onClick={() => navigate('home')}>精选系列</button><button onClick={showNewIn}>新季上架</button><button onClick={focusCatalogueSearch}>探索单品 <span aria-hidden="true">↗</span></button></nav>
      <button className="brand" onClick={() => navigate('home')} aria-label="织间 · 返回首页"><span className="brand-chinese">织间</span><span className="brand-english">ZHIJIAN  /  STUDIO</span></button>
      <nav className="header-actions" aria-label="账户与购物袋"><button onClick={() => navigate('story')}>品牌故事</button><button className="customer-nav" onClick={() => { setShowGuestOrders(false); navigate('account') }}>我的订单</button><button className="customer-nav" onClick={() => { setShowGuestOrders(false); navigate('account') }}>{customer ? customer.username : '登录 / 注册'}</button><button onClick={() => navigate('help')}>帮助</button><button className="bag-trigger" onClick={() => navigate('bag')} aria-label={`购物袋，目前 ${count} 件商品`}><span aria-hidden="true" className="bag-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M5.5 8.5h13L17.4 20H6.6L5.5 8.5Z" /><path d="M9 8.5V6.8a3 3 0 0 1 6 0v1.7" /></svg></span> 购物袋 <strong>{count}</strong></button></nav>
    </header>
    <main className="wrap" id="main-content" tabIndex={-1}>
      {error && <div className="alert" role="alert">{error}<button onClick={() => setError('')} aria-label="关闭提示">×</button></div>}
      {notice && <div className="notice" role="status">{notice}</div>}
      {pending && <div className="alert">有一次提交尚未确认。为避免重复订单，请先恢复原提交。<button disabled={submitting} onClick={() => void submit()}>重试原提交</button></div>}
      {(page === 'home' || page === 'product') && <>
        <section className="hero" aria-label="织间本季精选">
          <div className="hero-copy"><div className="hero-index">ZHIJIAN STUDIO <span>——</span> AUTUMN EDITION / 26</div><p className="hero-overline">把日常，穿成喜欢的样子</p><h1>让每一天，<br/><em>都值得好好穿。</em></h1><p className="hero-description">从出门的第一杯咖啡，到傍晚的城市微光。<br/>一件真正喜欢的衣服，陪你自在地走过日常。</p><a className="primary hero-cta" href="#products">探索本季精选 <span aria-hidden="true">↗</span></a><div className="hero-endnote"><span className="tiny-line"/> THE BEAUTY OF EVERYDAY</div></div>
          <figure><img src="/brand-hero.png" alt="两位模特在秋日伦敦街道上穿着酒红针织与驼色外套"/><figcaption>EDITORIAL / 001 <span>AI 概念穿搭图 · 非商品实拍</span></figcaption><div className="hero-vertical">EVERYDAY  /  IN STYLE</div></figure>
        </section>
        <div className="values-strip" aria-label="品牌理念"><span>✳&nbsp; SELF EXPRESSION</span><span>每一天，都有自己的穿搭节奏</span><span>✳&nbsp; EFFORTLESS STYLE</span></div>
        <section id="products" className="collection-section"><div className="section-heading"><div><p className="eyebrow">01 / THE CURATED EDIT</p><h2>日常精选 <em>·</em> The Edit</h2><p className="collection-intro">不为特别的日子准备，只为每一个当下的自己。</p></div><button className="text-action" disabled={loading} onClick={() => void loadCatalogue()}>更新商品与库存 <span aria-hidden="true">↗</span></button></div><p className="catalogue-disclaimer">{VISUAL_PREVIEW ? '以下为视觉预览概念商品，不代表真实库存或在售价格。' : 'GBP 演示价格 · 商品来自演示 ERP · 下单不代表已经锁定库存或扣款'}</p>
          {loading && !products.length && <p role="status">正在读取商品…</p>}
          {error && !products.length && <div className="empty-state"><p>暂时无法读取商品目录，请检查连接后重试。</p><button disabled={loading} onClick={() => void loadCatalogue()}>重试读取商品</button></div>}
          {!loading && catalogueReady && !products.length && <p>{hasFilters ? '没有符合条件的商品，请调整筛选条件。' : '暂未发布商品，请在演示 ERP 的“独立站运营”中检查发布状态。'}</p>}
          {!!products.length && <div className="catalogue-tools" role="group" aria-label="商品搜索和筛选">
            <label>搜索商品<input id="catalogue-search" type="search" value={search} placeholder="输入商品名称" onChange={e => setSearch(e.target.value)} /></label>
            <label>分类<select value={category} onChange={e => setCategory(e.target.value)}>{['全部', ...catalogueFacets.categories].map(x => <option key={x}>{x}</option>)}</select></label>
            <label>尺码<select value={sizeFilter} onChange={e => setSizeFilter(e.target.value)}>{['全部', ...catalogueFacets.sizes].map(x => <option key={x}>{x}</option>)}</select></label>
            <label>颜色<select value={colorFilter} onChange={e => setColorFilter(e.target.value)}>{['全部', ...catalogueFacets.colors].map(x => <option key={x}>{x}</option>)}</select></label>
            <label>价格区间<select value={priceRange} onChange={e => setPriceRange(e.target.value)}><option value="">全部</option><option value="0-25">£25 以下</option><option value="25-50">£25–£50</option><option value="50-100">£50–£100</option><option value="100-9999">£100 以上</option></select></label>
            <label>排序<select value={sort} onChange={e => setSort(e.target.value as typeof sort)}><option value="featured">推荐</option><option value="newest">最新</option><option value="price_asc">价格从低到高</option><option value="price_desc">价格从高到低</option></select></label>
            <button className="primary" disabled={loading} onClick={() => applyCatalogueFilters(filters)}>应用筛选</button>
          </div>}
          {!loading && catalogueTotal === 0 && hasFilters && <div className="empty-state"><p>没有符合条件的商品。</p><button onClick={() => { const cleared = { search: '', category: '全部', sizeFilter: '全部', colorFilter: '全部', priceRange: '', sort: 'featured' as const }; setSearch(''); setCategory('全部'); setSizeFilter('全部'); setColorFilter('全部'); setPriceRange(''); setSort('featured'); applyCatalogueFilters(cleared) }}>清除筛选</button></div>}
          <div className="product-grid">{visibleProducts.map((p, index) => <article className="product-card" key={p.id}><button className="product-image" onClick={() => openProduct(p)} aria-label={`查看 ${p.title} 详情`}><img loading="lazy" src={p.gallery?.[0] || p.image_url || '/knit.svg'} alt={p.title + '商品图'} onError={e => { e.currentTarget.onerror = null; e.currentTarget.src = '/knit.svg' }}/><span className="product-badge">{VISUAL_PREVIEW ? 'VISUAL CONCEPT' : p.gallery?.length ? 'THE EDIT' : 'DEMO PRODUCT'}</span><span className="product-hover-action">查看单品 <span aria-hidden="true">↗</span></span></button><div className="product-category">{p.category || '日常女装'} <span> / {String(index + 1).padStart(2, '0')}</span></div><div className="product-title"><h3>{p.title}</h3><span>£{p.variants[0]?.price || '—'}</span></div><p className="product-description">{p.description}</p><button className="product-cta" disabled={!!pending} onClick={() => openProduct(p)}>选择颜色与尺码 <span aria-hidden="true">↗</span></button></article>)}</div>
          {catalogueTotal > 12 && <div className="pagination" aria-label="商品分页"><button disabled={loading || cataloguePage <= 1} onClick={() => void loadCatalogue(true, cataloguePage - 1)}>上一页</button><span>第 {cataloguePage} / {totalPages} 页，共 {catalogueTotal} 件</span><button disabled={loading || cataloguePage >= totalPages} onClick={() => void loadCatalogue(true, cataloguePage + 1)}>下一页</button></div>}
        </section><section className="brand-strip"><div className="brand-strip-numeral">02 / OUR PHILOSOPHY</div><div><p className="eyebrow">DRESSED FOR REAL LIFE</p><h2>喜欢的衣服，<br/><em>不必等特别的日子。</em></h2></div><div className="brand-story-copy"><p>一件喜欢的衣服，也可以属于普通的星期二，属于下班后的散步，属于临时起意的见面。</p><button className="text-action" onClick={() => navigate('story')}>走近织间 <span aria-hidden="true">↗</span></button></div></section>
      </>}
      {(page === 'bag' || page === 'checkout') && <section className="content"><h1>{page === 'bag' ? '你的购物袋' : '确认演示订单'}</h1>{VISUAL_PREVIEW && <div className="notice">视觉预览商品不开放结账，真实联调请移除 URL 中的 ?preview=1 并连接演示 ERP。</div>}{!catalogueReady && !pending && <div className="alert">暂时无法核对最新商品和库存，请先刷新商品。<button onClick={() => void loadCatalogue()}>刷新商品</button></div>}{needsReview && !pending && <div className="alert" role="alert">购物袋的售价、版本或库存有变化。请按最新报价确认后继续。{quote.removed.length > 0 && <p>将移除不可售商品：{quote.removed.join('、')}</p>}<button disabled={loading} onClick={() => { setCart(quote.lines); setNotice('购物袋已按最新售价和库存更新，请再次复核总额。'); setError('') }}>确认最新报价</button></div>}{!cart.length && !pending ? <p>购物袋还是空的。<button onClick={() => navigate('home')}>去选一件喜欢的衣服</button></p> : <div className="checkout-grid"><div>
        {cart.map((x, i) => <article className="bag-line" key={x.variant_id}><div><h3>{x.title}</h3><p>{x.color} / {x.size} · £{x.price}</p><div className="quantity" role="group" aria-label={`${x.title} ${x.color} ${x.size} 数量`}><button aria-label={`${x.title} ${x.color} ${x.size} 数量减一`} disabled={loading || !!pending || x.quantity <= 1} onClick={() => updateQuantity(i, x.quantity - 1)}>−</button><span aria-live="polite">{x.quantity}</span><button aria-label={`${x.title} ${x.color} ${x.size} 数量加一`} disabled={loading || !!pending || x.quantity >= Math.min(20, x.available_qty)} onClick={() => updateQuantity(i, x.quantity + 1)}>+</button><button aria-label={`移除 ${x.title} ${x.color} ${x.size}`} disabled={loading || !!pending} onClick={() => { recordLocal('cart_updated', { sku_id: x.variant_id }); setCart(cart.filter((_, n) => n !== i)) }}>移除</button></div></div><strong>£{cartTotal([x])}</strong></article>)}
        {page === 'checkout' && <div className="customer-checkout-note">{!customerReady ? <span>正在确认登录状态。{sessionError && <button onClick={() => void loadCustomer()}>重试连接</button>}</span> : customer ? <span>以顾客 <strong>{customer.username}</strong> 下单，订单将保存到「我的订单」。</span> : <span>当前为游客下单，关闭标签页可能丢失查单凭据。<button onClick={() => navigate('account')}>先登录 / 注册</button>登录后可从购物袋继续结账。</span>}</div>}
        {page === 'checkout' && !pending && <form id="checkout-form" aria-labelledby="checkout-heading" onInvalidCapture={() => {
          const now = Date.now()
          if (now - lastAddressInvalidAtRef.current > 1000) { lastAddressInvalidAtRef.current = now; recordLocal('address_validation_failed') }
        }} onSubmit={e => { e.preventDefault(); void submit() }}><h2 id="checkout-heading">演示收件资料</h2><p className="muted">请使用测试资料，不填写真实个人信息。只支持英格兰、苏格兰、威尔士。</p><button type="button" onClick={() => setAddress({ name: '演示顾客', email: 'buyer@example.invalid', line1: '12 Example Street', line2: '', city: 'London', region: '', postcode: 'SW1A 1AA', country: 'GB' })}>填入虚构测试资料</button>{customer && savedAddresses.length > 0 && <label>从地址簿选择<select defaultValue="" onChange={e => { const picked = savedAddresses.find(x => x.id === e.target.value); if (picked) setAddress({ name: picked.name, email: address.email, line1: picked.line1, line2: picked.line2, city: picked.city, region: picked.region, postcode: picked.postcode, country: picked.country }) }}><option value="">手动填写</option>{savedAddresses.map(x => <option key={x.id} value={x.id}>{x.name} · {x.line1} · {x.postcode}{x.is_default ? '（默认）' : ''}</option>)}</select></label>}<div className="form-grid">{([['name','收件人'],['email','联系邮箱'],['line1','地址第一行'],['line2','地址第二行（选填）'],['city','城市'],['region','地区（选填）'],['postcode','邮编']] as const).map(([key, label]) => <label key={key}>{label}<input value={address[key]} required={!['line2','region'].includes(key)} type={key === 'email' ? 'email' : 'text'} maxLength={key === 'postcode' ? 10 : key === 'name' ? 120 : ['city','region'].includes(key) ? 100 : 200} onChange={e => setAddress({ ...address, [key]: e.target.value })}/></label>)}</div><label>优惠码（选填）<input value={promoCode} onChange={e => setPromoCode(e.target.value)} maxLength={40} placeholder="提交订单时由服务端核验，例如 WELCOME10 / SAVE5" autoComplete="off" /></label>{customer && <label className="check-line"><input type="checkbox" checked={saveAddressBook} onChange={e => setSaveAddressBook(e.target.checked)} /> 保存此地址到我的地址簿</label>}</form>}
      </div><aside className="summary"><h2>订单复核</h2>{page === 'checkout' && quoteReady && serverQuote && <div className="notice" role="status"><h3>服务端确认金额</h3><p>商品 £{serverQuote.subtotal} · 优惠 -£{serverQuote.discount_amount}</p><p>演示运费 £{serverQuote.shipping_amount} · 演示税费 £{serverQuote.tax_amount}</p><p className="total">最终测试总额 <strong>£{serverQuote.grand_total}</strong></p><small>{serverQuote.limitations}</small></div>}<p>商品小计 <strong>£{cartTotal(cart)}</strong></p><p>演示运费 <strong>£0.00</strong></p><p>折扣前商品金额 <strong>£{cartTotal(cart)}</strong></p><p className="muted">演示价格，不计算真实税费。提交后等待商家确认库存；没有任何实际扣款。</p>{promoCode.trim() && <p className="muted">优惠码将在提交时由服务端核验，折扣以订单确认结果为准。</p>}{page === 'bag' ? <button key="bag-action" className="primary" disabled={!!pending || !catalogueReady || needsReview || VISUAL_PREVIEW} onClick={() => navigate('checkout')}>填写演示资料</button> : <button key="checkout-action" className="primary" type="submit" form="checkout-form" disabled={submitting || !!pending || !catalogueReady || needsReview || VISUAL_PREVIEW}>{submitting ? '正在处理…' : quoteReady ? '确认总额并创建订单（不扣款）' : '核算最终金额'}</button>}</aside></div>}</section>}
      {page === 'account' && !showGuestOrders && <CustomerAccount key={customer?.id || 'guest'} customer={customer} ready={customerReady} sessionError={sessionError} guestCount={orderRefs.filter(ref => !!ref.token).length} onCustomer={updateCustomer} onRetrySession={() => void loadCustomer()} onGuestOrders={() => setShowGuestOrders(true)} onShop={() => navigate('home')} onView={id => { const ref = { id, token: '' }; setOrderRef(ref); setOrder(null); void refreshOrder(ref) }} />}
      {page === 'account' && showGuestOrders && <section className="content"><p className="eyebrow">仅限当前浏览器会话</p><h1>本会话游客订单</h1><button onClick={() => setShowGuestOrders(false)}>返回顾客中心</button><p className="muted">此列表使用本会话保存的订单访问凭据，不是登录账户。关闭浏览器会话后，订单凭据将无法继续使用。</p>{orderRefs.length === 0 && <p>本会话没有已保存的订单。</p>}{history.map(item => <article className="support-box" key={item.public_id}><h2>{item.status_label}</h2><p>订单号：{item.public_id} · {item.customer_masked || '联系邮箱未提供'}</p><p>测试总额 £{item.grand_total} · {item.items.length} 项商品</p><button onClick={() => { const ref = orderRefs.find(x => x.id === item.public_id); if (ref) { setOrderRef(ref); setOrder(item); navigate('order') } }}>查看订单</button></article>)}{orderRefs.length > history.length && <p className="muted">部分订单凭据已失效或不可用。</p>}</section>}
      {page === 'order' && <section className="content"><p className="eyebrow">来自演示 ERP 的实际订单状态</p><button className="customer-nav" onClick={() => { setShowGuestOrders(false); navigate('account') }}>返回我的订单</button><h1>{order?.status_label || (error ? '暂时无法读取订单状态' : orderRef ? '读取订单中…' : '本次会话没有可查询订单')}</h1>{!orderRef && <div className="empty-state"><p>订单查询凭据只保存在创建订单的当前浏览器会话中。游客订单暂不支持通过订单号找回；如果是登录后下单，请到「我的订单」登录查询。</p><button onClick={() => navigate('home')}>返回商城</button></div>}{error && <div className="alert" role="alert">{error}<button disabled={loading} onClick={() => void refreshOrder()}>重试查单</button></div>}{orderRef && <button disabled={loading} onClick={() => void refreshOrder()}>刷新订单状态</button>}{order && <><p>订单号：{order.public_id} · 联系邮箱：{order.customer_masked || '未提供'}</p><div className="notice">演示订单，未真实收款。订单受理不代表已付款；库存预留在 ERP 申请发货时发生。</div>
{order.payment_status === 'succeeded' && <div className="notice payment-ok"><strong>已模拟支付成功</strong> · 方式 {order.payment_method || 'test_card'} · 凭证 {order.payment_provider_ref} · £{order.payment_amount}{order.paid_at ? ' · ' + new Date(order.paid_at).toLocaleString('zh-CN') : ''}</div>}
{Number(order.grand_total) === 0 && order.status !== 'cancelled' && <div className="notice">订单应付金额为零，无需测试支付。</div>}{order.payment_status === 'failed' && <div className="alert" role="alert">上一次模拟支付未通过（演示网关拒绝）。可重新发起测试支付。</div>}
{['unpaid', 'failed'].includes(order.payment_status) && order.status !== 'cancelled' && Number(order.grand_total) > 0 && <section className="support-box pay-panel"><h2>测试支付（演示沙盒）</h2><p className="muted">本环境不接真实支付。点击下方按钮向演示网关发起一次模拟扣款；测试结果按所选情景由服务端记录，不代表真实收款。</p><div className="pay-actions"><button className="primary" disabled={paymentSending} onClick={() => void submitPayment('success')}>{paymentSending ? '正在模拟…' : '模拟支付成功'}</button><button disabled={paymentSending} onClick={() => void submitPayment('fail')}>{paymentSending ? '正在模拟…' : '模拟支付被拒'}</button></div></section>}<ol className="order-timeline" aria-label="订单履约进度">{order.fulfilment_events.map((event, index) => <li key={`${event.status}-${event.occurred_at || index}`} className={index === order.fulfilment_events.length - 1 ? 'current' : ''} aria-current={index === order.fulfilment_events.length - 1 ? 'step' : undefined}>{event.label}{index === order.fulfilment_events.length - 1 && <span> · 当前</span>}{event.occurred_at && <time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString('zh-CN')}</time>}</li>)}</ol>{order.fulfillment_issue && <p role="alert" className="alert">{order.fulfillment_issue}</p>}{order.items.map((x, i) => <div className="bag-line" key={i}><span>{x.title}<br/>{x.color} / {x.size} × {x.quantity}</span><strong>£{x.line_total}</strong></div>)}<p>商品小计 <strong>£{order.subtotal}</strong></p>{Number(order.discount_amount) > 0 && <p>优惠{order.promo_code ? `（${order.promo_code}）` : ''} <strong>-£{order.discount_amount}</strong></p>}<p className="total">测试总额 <strong>£{order.grand_total}</strong></p>{order.tracking_no && <p>演示出库单号：{order.tracking_no}<br/><span className="muted">未接承运商轨迹，出库不等于已揽收或签收。</span></p>}<p className="muted">去演示 ERP 审核这笔订单、申请发货并确认出库，再回来刷新查看。</p><section className="support-box"><h2>订单帮助</h2><p className="muted">请勿在演示请求中填写真实个人或支付信息。当前只创建待处理的演示客服请求。</p>{supportRequests.map(ticket => <p className="support-ticket" key={ticket.ticket_ref}><strong>{ticket.ticket_ref}</strong> · {ticket.issue === 'delivery' ? '订单/配送' : ticket.issue === 'product' ? '商品' : ticket.issue === 'return' ? '退换/售后' : '其他'} · {({ open: '待处理', in_progress: '处理中', resolved: '已解决', closed: '已关闭' } as const)[ticket.status]}{ticket.reply && <span> · 客服回复：{ticket.reply}</span>}</p>)}{supportTicketRef && <p className="notice" role="status">客服请求已创建：{supportTicketRef}</p>}<form onSubmit={e => void submitSupport(e)}><label>问题类型<select value={supportIssue} onChange={e => setSupportIssue(e.target.value as SupportIssue)}><option value="product">商品问题</option><option value="delivery">订单/配送问题</option><option value="return">退换/售后问题</option><option value="other">其他</option></select></label><label>附件（可选，PNG/JPEG/PDF，最多5 MiB）<input id="support-attachment" type="file" accept="image/png,image/jpeg,application/pdf" /></label><label>问题说明<textarea value={supportMessage} onChange={e => setSupportMessage(e.target.value)} required maxLength={2000} rows={4} placeholder="请描述你需要演示客服协助的内容" /></label><button className="primary" disabled={supportSending}>{supportSending ? '正在提交…' : '提交客服请求'}</button></form></section>
<section className="support-box"><h2>申请售后 / 退换（演示）</h2><p className="muted">本环境为演示，售后请求仅创建待处理记录，不含真实退货物流或退款。将对本订单全部商品发起。</p>{afterSales.length > 0 && <div className="after-sales-list">{afterSales.map(req => <p className="support-ticket" key={req.public_ref}><strong>{req.public_ref}</strong> · {req.kind === 'return' ? '退货' : '退款'} · {({ submitted: '待处理', processing: '处理中', completed: '已完成', rejected: '已拒绝' } as const)[req.status]}{req.reason && <small> · {req.reason}</small>}{req.note && <small> · 备注：{req.note}</small>}</p>)}</div>}<form onSubmit={e => void submitAfterSales(e)}><label>售后类型<select value={afterSaleKind} onChange={e => setAfterSaleKind(e.target.value as 'return' | 'refund')}><option value="return">退货</option><option value="refund">退款</option></select></label><label>原因（必填）<textarea value={afterSaleReason} onChange={e => setAfterSaleReason(e.target.value)} required maxLength={200} rows={3} placeholder="请简述需要售后的原因" /></label><label>补充说明（可选）<textarea value={afterSaleMessage} onChange={e => setAfterSaleMessage(e.target.value)} maxLength={2000} rows={3} placeholder="可选补充信息" /></label><button className="primary" disabled={afterSaleSending}>{afterSaleSending ? '正在提交…' : '提交售后申请'}</button></form></section></>}</section>}
      {page === 'campaign' && (campaign ? <section className="content"><section className="campaign-hero"><div><p className="eyebrow">{campaign.tagline}</p><h1>{campaign.title}</h1><p>{campaign.description}</p></div><img src={campaign.image} alt="" /></section><section className="collection-section"><div className="section-heading"><div><p className="eyebrow">CURATED FOR THE SEASON</p><h2>专题商品 <em>·</em> {campaign.category}</h2><p className="collection-intro">以下为演示 ERP 中已发布的 {campaign.category} 类商品集合。</p></div><button className="text-action" disabled={loading} onClick={() => void loadCatalogue()}>更新商品与库存 <span aria-hidden="true">↗</span></button></div>{loading && !products.length && <p role="status">正在读取商品…</p>}{!!products.length && <div className="product-grid">{products.map((p, index) => <article className="product-card" key={p.id}><button className="product-image" onClick={() => openProduct(p)} aria-label={`查看 ${p.title} 详情`}><img loading="lazy" src={p.gallery?.[0] || p.image_url || '/knit.svg'} alt={p.title + '商品图'} onError={e => { e.currentTarget.onerror = null; e.currentTarget.src = '/knit.svg' }}/><span className="product-badge">THE EDIT</span></button><div className="product-category">{p.category || '日常女装'} <span> / {String(index + 1).padStart(2, '0')}</span></div><div className="product-title"><h3>{p.title}</h3><span>£{p.variants[0]?.price || '—'}</span></div><button className="product-cta" disabled={!!pending} onClick={() => openProduct(p)}>选择颜色与尺码 <span aria-hidden="true">↗</span></button></article>)}</div>}{!loading && catalogueReady && !products.length && <p>暂无已发布的 {campaign.category} 类商品。</p>}<button className="text-action" onClick={() => navigate('home')}>返回首页 <span aria-hidden="true">↗</span></button></section></section> : <section className="content story"><p className="eyebrow">专题不存在</p><h1>找不到这个专题</h1><button className="primary" onClick={() => navigate('home')}>返回商城</button></section>)}
      {page === 'story' && <section className="content story"><p className="eyebrow">关于织间</p><h1>把喜欢，<br/>穿进今天。</h1><p>那件喜欢的衣服，不一定要留给生日、旅行，或很久以后的一场聚会。它也可以出现在一个普通的星期二，出现在下班后的散步里，出现在你突然想见朋友的下午。</p><p>织间想做的，是把这些小小的心动，放进真实的生活。衣服不必替你定义什么，只要陪你，自在地成为今天的自己。</p><h2>公司与联系</h2><p>{site?.company_name}<br/>{site?.company_address}<br/>{site?.contact_email}</p><div className="notice">公司信息是虚构演示资料，不代表真实经营主体。本环境不接收真实交易。</div><h2>配送与退换说明</h2><p>本地联调不产生真实包裹、付款或退款。正式营业前需确定实际主体、商品实拍与成分、配送与退货方案、税务及消费者政策；当前不作时效、退货或合规承诺。</p></section>}
      {page === 'help' && <section className="content story"><p className="eyebrow">帮助中心</p><h1>关于本次演示</h1><div className="notice">这是本地演示商城。请只使用虚构测试资料；订单不会扣款，也不会创建真实包裹。</div><h2>订单状态</h2><p>“已受理”表示演示 ERP 收到订单，不表示付款成功或库存已经预留。仅在 ERP 完成相应操作后，状态才会更新为备货中或已出库。</p><h2>查询订单</h2><p>订单查询使用当前浏览器会话中保存的专属访问凭据。清除浏览器会话后可能无法恢复，请保留提交结果页。演示环境不提供邮件找回。</p><h2>联系演示支持</h2><p>演示联系邮箱：{site?.contact_email || 'hello@loomandlane.example'}。此邮箱为虚构占位信息，不接收真实客服请求。</p></section>}
      {page === 'policies' && <section className="content story"><p className="eyebrow">政策与消费者信息</p><h1>{window.location.pathname.startsWith('/policies/shipping') ? '配送政策（演示稿）' : window.location.pathname.startsWith('/policies/returns') ? '退货与退款政策（演示稿）' : '隐私与政策（演示稿）'}</h1><div className="alert">正式经营所需政策尚未核验。本页面不是隐私声明、消费者条款或法律意见，请勿提交真实个人信息。</div>{!window.location.pathname.startsWith('/policies/shipping') && !window.location.pathname.startsWith('/policies/returns') && <><h2>隐私与数据</h2><p>演示结账资料仅用于隔离演示订单流程，不应输入真实姓名、邮箱、电话或地址。请使用页面提供的虚构资料。</p><p>可选的使用事件分析默认关闭。只有你在“本地分析设置”中明确启用后，少量不含姓名、邮箱、地址或搜索内容的事件才会保存在当前浏览器本地；不会发送到服务器或第三方。你可以随时关闭并清除这些本地事件。此说明仅描述本地演示实现，不替代正式隐私政策。</p></>}{window.location.pathname.startsWith('/policies/shipping') ? <><h2>配送政策（演示稿）</h2><p>演示运费：£{site?.shipping_amount || '0.00'} · 配送区域：{site?.delivery_regions?.join('、') || '英格兰、苏格兰、威尔士'}</p><p>{site?.shipping_note || '演示配送：提交订单后由演示 ERP 确认库存并备货，不接真实快递。'}</p></> : window.location.pathname.startsWith('/policies/returns') ? <><h2>退货政策（演示稿）</h2><p>本演示商城的售后申请仅创建待处理记录，处理状态包括：待处理、处理中、已完成、已拒绝。正式营业前需确认真实退货流程与消费者权利。</p></> : <><h2>配送与退换</h2><p>当前没有真实配送、税费、退货或退款服务。演示运费显示为 £0.00，不代表真实配送报价或免税承诺。</p></>}<h2>条款状态</h2><p>真实经营主体、适用市场、政策版本及生效日期待确认；完成核验前，不作为正式交易网站使用。</p></section>}
      {page === 'status' && <section className="content story"><p className="eyebrow">服务状态</p><h1>演示商城状态</h1><p role="status">商城 API：{serviceStatus === 'checking' ? '检查中…' : serviceStatus === 'available' ? '可连接' : '暂时不可用'}</p>{serviceStatus === 'unavailable' && <button onClick={() => setStatusRefresh(x => x + 1)}>重新检查</button>}<p className="muted">此检查仅确认演示站点接口可响应，不代表支付、库存或物流服务状态。</p><button onClick={() => navigate('home')}>返回商城</button></section>}
      {page === 'notFound' && <section className="content story"><p className="eyebrow">页面不存在</p><h1>找不到这个页面</h1><p>可以返回商城首页，或查看演示帮助与订单查询说明。</p><button className="primary" onClick={() => navigate('home')}>返回商城</button><button onClick={() => navigate('help')}>帮助中心</button></section>}
    </main>
    {analyticsConsent === 'unset' && <aside className="consent-banner" aria-label="可选本地使用事件"><p>可选使用事件分析默认关闭。启用后，事件只保存在当前浏览器本地，不含联系资料，也不会发送到服务器或第三方。</p><div><button onClick={() => chooseAnalyticsConsent('granted')}>启用本地分析</button><button onClick={() => chooseAnalyticsConsent('denied')}>保持关闭</button><button onClick={openAnalyticsSettings}>查看设置</button></div></aside>}
    <footer className="site-footer"><div className="wrap"><div className="footer-grid"><div className="footer-brand-block"><div className="footer-logo">织间</div><p className="footer-en">ZHIJIAN / STUDIO</p><p>把喜欢，穿进今天。<br/>自在，舒适，有自己的模样。</p></div><div><h3>探索</h3><button onClick={() => navigate('home')}>本季精选</button><button onClick={showNewIn}>新季上架</button><button onClick={() => navigate('campaign')}>秋日专题</button><button onClick={() => navigate('story')}>关于织间</button></div><div><h3>顾客服务</h3><button onClick={() => navigate('help')}>帮助中心</button><button className="customer-nav" onClick={() => { setShowGuestOrders(false); navigate('account') }}>我的订单 / 顾客登录</button><button onClick={() => { window.history.pushState({}, '', '/policies/privacy'); setUrlVersion(v => v + 1) }}>隐私政策（演示稿）</button><button onClick={() => { window.history.pushState({}, '', '/policies/shipping'); setUrlVersion(v => v + 1) }}>配送政策（演示稿）</button><button onClick={() => { window.history.pushState({}, '', '/policies/returns'); setUrlVersion(v => v + 1) }}>退货政策（演示稿）</button><button onClick={() => navigate('status')}>服务状态</button></div><div><h3>设计演示</h3><p>英国女装独立站视觉与 ERP 联调演示。没有真实付款、配送或正式销售。</p><button onClick={openAnalyticsSettings}>本地分析设置：{analyticsConsent === 'granted' ? '已启用' : '关闭'}</button></div></div><div className="footer-bottom"><span>© 2026 ZHIJIAN STUDIO · DEMO EXPERIENCE</span><span>用日常，穿出自己的故事。</span></div></div></footer>
    <dialog ref={privacyDialogRef} className="privacy-dialog" aria-labelledby="analytics-title" onClose={closeAnalyticsSettings}>
      <button className="close" aria-label="关闭本地分析设置" onClick={() => privacyDialogRef.current?.close()}>×</button>
      <h2 id="analytics-title">本地分析设置</h2>
      <p>默认关闭。启用后，只记录本地页面/商品操作事件、随机事件编号、当前标签页随机会话编号和时间。不会记录姓名、邮箱、地址、搜索词、订单号、金额，也不会向服务器或第三方发送。</p>
      <p>事件只保存在当前浏览器，最多保留最近 200 条且不超过 30 天。关闭时会清除事件和会话编号。正式经营前需另行确认政策与合规要求。</p>
      <p role="status">当前状态：{analyticsConsent === 'granted' ? `已启用，本地有 ${analyticsEventCount} 条事件` : '关闭，未记录使用事件'}</p>
      <div className="privacy-actions"><button className="primary" onClick={() => chooseAnalyticsConsent('granted')}>{analyticsConsent === 'granted' ? '保持启用' : '同意并启用'}</button><button onClick={() => chooseAnalyticsConsent('denied')}>关闭并清除本地数据</button></div>
    </dialog>
    <SupportContact key={customer?.id ?? 'guest'} ref={supportContactRef} preview={VISUAL_PREVIEW}
      order={page === 'order' && order && orderRef ? { id: order.public_id, token: orderRef.token } : null}
      onOrders={() => { setShowGuestOrders(false); navigate('account') }}
      onSubmitted={() => { const version = privateVersion.current; if (order && orderRef) request<{ items: SupportSummary[] }>('/support-requests?order_ref=' + encodeURIComponent(order.public_id), { headers: orderRef.token ? { Authorization: 'Bearer ' + orderRef.token } : {} }).then(result => { if (version === privateVersion.current) setSupportRequests(result.items) }).catch(() => {}) }} />
    {selected && <dialog ref={modalRef} aria-label="商品详情与颜色尺码选择" className="product-modal" onClose={closeProduct} onClick={e => { if (e.target === e.currentTarget) closeProduct() }}>
      <button className="close" autoFocus aria-label="关闭商品详情" onClick={closeProduct}>×</button>
      <div className="product-modal-grid"><div className="modal-gallery"><div className="detail-gallery"><img src={(selected.gallery?.[galleryIndex] || selected.image_url) || '/knit.svg'} alt={`${selected.title}商品图 ${galleryIndex + 1}`} onError={e => { e.currentTarget.onerror = null; e.currentTarget.src = '/knit.svg' }}/>{(selected.gallery?.length || 0) > 1 && <div className="gallery-picks" aria-label="商品图片">{selected.gallery?.map((src, index) => <button key={src} aria-label={`查看第 ${index + 1} 张商品图`} aria-pressed={galleryIndex === index} onClick={() => setGalleryIndex(index)}><img src={src} alt=""/></button>)}</div>}</div><div className="modal-gallery-caption">THE DAILY EDIT · ZHIJIAN STUDIO</div></div>
      <div className="modal-product-info"><p className="eyebrow">{selected.category || 'EVERYDAY WARDROBE'} / THE EDIT</p><h2>{selected.title}</h2><div className="modal-price">£{variant?.price || selected.variants[0]?.price || '—'} <span>GBP · {VISUAL_PREVIEW ? '概念价格' : '演示售价'}</span></div><p className="modal-description">{selected.description}</p><div className="modal-rule"/>
      <div className="option-heading"><strong>选择颜色与尺码</strong><span>{selected.variants.length} 个规格</span></div><div className="variant-grid">{selected.variants.map(v => <button key={v.id} disabled={v.available_qty <= 0 || !!pending} aria-pressed={variantId === v.id} onClick={() => { setVariantId(v.id); recordLocal('variant_selected', { product_id: selected.id, sku_id: v.id }) }}><span>{v.color} · {v.size}</span><small>{v.available_qty > 0 ? `演示可用 ${v.available_qty} 件` : '暂时缺货'}</small></button>)}</div>
      <label>购买数量 <input aria-label="购买数量" type="number" min={1} max={Math.min(20, variant?.available_qty ?? 1)} step={1} disabled={!variant || variant.available_qty < 1} value={selectedQuantity} onChange={e => setSelectedQuantity(Number(e.target.value))} style={{ width: 80, padding: 8, margin: 12 }} /></label>
      {error && <p role="alert" className="alert">{error}</p>}<button className="primary modal-add" disabled={!variant || !!pending} onClick={addSelected}>加入购物袋 <span aria-hidden="true">↗</span></button><p className="modal-detail-note">{VISUAL_PREVIEW ? '视觉概念款，不能结账。' : '下单前重新核实价格与库存，本站不处理真实付款。'}</p>
      <button className="product-contact" onClick={() => supportContactRef.current?.open({ slug: selected.slug, title: selected.title })}>咨询这件商品 · 联系客服</button>
      <details className="modal-accordion"><summary>商品材质与护理说明</summary><p>{selected.material || '材质信息待补充'}</p><p>{selected.care_instructions || '护理信息待补充'}</p></details>
      <details className="modal-accordion"><summary>查看商品尺寸表</summary>{selected.size_guide?.length ? <div className="size-guide-scroll"><table><thead><tr><th>尺码</th>{(['chest_cm', 'waist_cm', 'hip_cm', 'length_cm', 'sleeve_cm'] as const).map(key => selected.size_guide?.some(row => row[key] != null) && <th key={key}>{({ chest_cm: '胸围', waist_cm: '腰围', hip_cm: '臀围', length_cm: '衣长', sleeve_cm: '袖长' })[key]}</th>)}</tr></thead><tbody>{selected.size_guide.map(row => <tr key={row.size}><th>{row.size}</th>{(['chest_cm', 'waist_cm', 'hip_cm', 'length_cm', 'sleeve_cm'] as const).map(key => selected.size_guide?.some(item => item[key] != null) && <td key={key}>{row[key] ?? '—'}</td>)}</tr>)}</tbody></table></div> : <p>商品尺寸信息待补充。</p>}<p>尺寸请以样衣实测为准，S/M/L 不对应固定英国码。</p></details>
      <details className="modal-accordion"><summary>配送说明</summary><p>币种：GBP · 演示运费：£{site?.shipping_amount || '0.00'}</p><p>配送区域：{site?.delivery_regions?.join('、') || '英格兰、苏格兰、威尔士'}</p><p>{site?.shipping_note || '演示配送：提交订单后由演示 ERP 确认库存并备货，不接真实快递。'}</p></details>
      </div></div>
    </dialog>}

  </>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>)
