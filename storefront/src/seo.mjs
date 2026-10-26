const PRIVATE_ROUTES = new Set(['/cart', '/checkout', '/checkout/result', '/orders/lookup', '/account/orders'])

/** @param {{ pathname: string; search?: string; origin?: string; siteName?: string; product?: { title?: string; description?: string; gallery?: string[]; image_url?: string; variants?: { price?: string; available_qty?: number }[] } | null }} input */
export function storefrontMetadata({ pathname, search = '', origin = '', siteName = '织间', product = null }) {
  let path = pathname || '/'
  if (path === '/orders/lookup') path = '/checkout/result'
  if (path.length > 1) path = path.replace(/\/+$/, '')
  const privateRoute = PRIVATE_ROUTES.has(path) || path === '/search' || path.startsWith('/policies/')
  const query = new URLSearchParams(search)
  let title = `${siteName} · 英国女装演示商城`
  let description = '浏览织间演示商城商品、颜色尺码与商品说明。此站点为本地联调演示，不处理真实付款或配送。'
  let type = 'website'
  if (path.startsWith('/products/') && product) {
    title = `${product.title} · ${siteName}`
    description = String(product.description || `${product.title}，查看颜色、尺码与商品说明。`).slice(0, 160)
    type = 'product'
  } else if (path.startsWith('/collections/')) {
    let collection = path.slice('/collections/'.length)
    try { collection = decodeURIComponent(collection) } catch { /* Keep the encoded route readable in metadata. */ }
    title = `${collection} · ${siteName}`
    description = `浏览${collection}商品与可选尺码。织间演示商城仅供本地联调。`
  } else if (path === '/search' && query.get('q')) {
    title = `搜索：${query.get('q')} · ${siteName}`
    description = `织间演示商城商品搜索结果。`
  } else if (path === '/about') {
    title = `关于我们 · ${siteName}`
    description = '了解织间演示品牌与本地商城体验。'
  }
  const canonicalPath = path === '/search' || PRIVATE_ROUTES.has(path) || path.startsWith('/policies/') ? '/' : path
  let structuredData = null
  if (path.startsWith('/products/') && product && Array.isArray(product.variants)) {
    const offers = product.variants
      .filter(variant => typeof variant.price === 'string' && /^\d+(?:\.\d{1,2})?$/.test(variant.price))
      .map(variant => ({
        '@type': 'Offer',
        url: origin ? new URL(path, origin).href : path,
        priceCurrency: 'GBP',
        price: variant.price,
        availability: Number(variant.available_qty) > 0
          ? 'https://schema.org/InStock'
          : 'https://schema.org/OutOfStock',
      }))
    if (offers.length) {
      structuredData = {
        '@context': 'https://schema.org',
        '@type': 'Product',
        name: product.title,
        description: String(product.description || '').slice(0, 5000),
        url: origin ? new URL(path, origin).href : path,
        brand: { '@type': 'Brand', name: siteName },
        offers,
      }
      if (metadataImage(product, origin)) structuredData.image = metadataImage(product, origin)
    }
  }
  return {
    title,
    description,
    canonical: origin ? new URL(canonicalPath, origin).href : canonicalPath,
    robots: 'noindex,nofollow',
    type,
    image: product?.gallery?.[0] || product?.image_url || '',
    structuredData,
  }
}

function metadataImage(product, origin) {
  const image = product?.gallery?.[0] || product?.image_url
  return image ? (origin ? new URL(image, origin).href : image) : ''
}

export function applyStorefrontMetadata(metadata, doc = document) {
  doc.title = metadata.title
  const ensureMeta = (key, value, attribute = 'name') => {
    let element = doc.head.querySelector(`meta[${attribute}="${key}"]`)
    if (!element) {
      element = doc.createElement('meta')
      element.setAttribute(attribute, key)
      doc.head.append(element)
    }
    element.setAttribute('content', value)
  }
  ensureMeta('description', metadata.description)
  ensureMeta('robots', metadata.robots)
  ensureMeta('og:title', metadata.title, 'property')
  ensureMeta('og:description', metadata.description, 'property')
  ensureMeta('og:type', metadata.type, 'property')
  ensureMeta('og:url', metadata.canonical, 'property')
  if (metadata.image) ensureMeta('og:image', new URL(metadata.image, metadata.canonical).href, 'property')
  let canonical = doc.head.querySelector('link[rel="canonical"]')
  if (!canonical) {
    canonical = doc.createElement('link')
    canonical.rel = 'canonical'
    doc.head.append(canonical)
  }
  canonical.href = metadata.canonical
  let structuredData = doc.head.querySelector('script[data-storefront-structured-data]')
  if (metadata.structuredData) {
    if (!structuredData) {
      structuredData = doc.createElement('script')
      structuredData.type = 'application/ld+json'
      structuredData.dataset.storefrontStructuredData = 'true'
      doc.head.append(structuredData)
    }
    structuredData.textContent = JSON.stringify(metadata.structuredData)
  } else {
    structuredData?.remove()
  }
}
