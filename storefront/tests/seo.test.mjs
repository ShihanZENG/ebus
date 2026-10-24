import test from 'node:test'
import assert from 'node:assert/strict'
import { storefrontMetadata } from '../src/seo.mjs'

test('product metadata uses product content and a clean absolute canonical URL', () => {
  const metadata = storefrontMetadata({
    pathname: '/products/daily-knit', search: '?utm_source=newsletter&color=red',
    origin: 'https://shop.example', siteName: '织间',
    product: { title: '日常针织', description: '柔软针织上衣', image_url: '/media/knit.jpg', variants: [
      { price: '29.00', available_qty: 2 }, { price: '29.00', available_qty: 0 },
    ] },
  })
  assert.equal(metadata.title, '日常针织 · 织间')
  assert.equal(metadata.description, '柔软针织上衣')
  assert.equal(metadata.canonical, 'https://shop.example/products/daily-knit')
  assert.equal(metadata.image, '/media/knit.jpg')
  assert.equal(metadata.robots, 'noindex,nofollow')
  assert.equal(metadata.structuredData['@type'], 'Product')
  assert.deepEqual(metadata.structuredData.offers.map(offer => offer.availability), [
    'https://schema.org/InStock', 'https://schema.org/OutOfStock',
  ])
  assert.equal(metadata.structuredData.offers[0].priceCurrency, 'GBP')
  assert.equal(metadata.structuredData.image, 'https://shop.example/media/knit.jpg')
})

test('collection canonical omits filter query and search pages canonicalize to the storefront root', () => {
  const collection = storefrontMetadata({ pathname: '/collections/针织/', search: '?size=M', origin: 'https://shop.example' })
  assert.equal(collection.canonical, 'https://shop.example/collections/%E9%92%88%E7%BB%87')
  const search = storefrontMetadata({ pathname: '/search', search: '?q=针织', origin: 'https://shop.example' })
  assert.equal(search.title, '搜索：针织 · 织间')
  assert.equal(search.canonical, 'https://shop.example/')
})

test('private order pages never expose order identifiers as canonical URLs', () => {
  const metadata = storefrontMetadata({ pathname: '/orders/lookup', origin: 'https://shop.example' })
  assert.equal(metadata.canonical, 'https://shop.example/')
  assert.equal(metadata.robots, 'noindex,nofollow')
})
