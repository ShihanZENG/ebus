/** @template { { slug: string } } T
 * @param {string} pathname
 * @param {T[]} products
 * @returns {{ kind: 'not_found' } | { kind: 'loaded', product: T } | { kind: 'fetch', slug: string, path: string }}
 */
export function resolveProductRoute(pathname, products) {
  const prefix = '/products/'
  if (!pathname.startsWith(prefix)) return { kind: 'not_found' }

  let slug
  try {
    slug = decodeURIComponent(pathname.slice(prefix.length))
  } catch {
    return { kind: 'not_found' }
  }
  if (!slug) return { kind: 'not_found' }

  const product = products.find(item => item.slug === slug)
  if (product) return { kind: 'loaded', product }
  return { kind: 'fetch', slug, path: '/products/' + encodeURIComponent(slug) }
}
