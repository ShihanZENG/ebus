"""Campaign contracts: public visibility, operator publishing, auth and guards."""
from sqlalchemy import select
from test_erp import setup  # noqa: F401
from test_storefront import storefront, PUBLIC, ADMIN, customer_headers  # noqa: F401
from app.db import sessions

ADMIN_PATH = ADMIN + '/campaigns'


def campaign_payload(slug='autumn-edit', status='published', **override):
    data = {'slug': slug, 'title': '秋日衣橱企划', 'subtitle': 'AUTUMN EDIT / 26',
            'description': '把秋天最常穿的几件放在一起。', 'kind': 'promotion',
            'image_url': '/brand-hero.png', 'promo_code': 'WELCOME10',
            'status': status, 'starts_at': None, 'ends_at': None}
    data.update(override)
    return data


def product_id_of(engine):
    from app.storefront.models import Product
    with sessions(engine)() as db:
        return db.scalar(select(Product.id))


def publish(storefront_env, slug='autumn-edit', status='published', attach=True, **override):
    client, auth, engine, _, _, _, _ = storefront_env
    created = client.put(f'{ADMIN_PATH}/{slug}', headers=auth, json=campaign_payload(slug, status, **override))
    assert created.status_code == 200, created.text
    if attach:
        linked = client.put(f'{ADMIN_PATH}/{slug}/products', headers=auth,
                            json={'product_ids': [product_id_of(engine)]})
        assert linked.status_code == 200, linked.text
        return linked.json()
    return created.json()


def test_campaigns_are_disabled_with_the_storefront(setup):
    client, _, _ = setup
    assert client.get(PUBLIC + '/campaigns').status_code == 404


def test_public_campaign_list_and_detail_only_show_published_items(storefront):
    client, auth, engine, _, _, _, product = storefront
    assert client.get(PUBLIC + '/campaigns').json() == {'items': []}

    publish(storefront, 'draft-edit', status='draft')
    assert client.get(PUBLIC + '/campaigns').json() == {'items': []}
    assert client.get(PUBLIC + '/campaigns/draft-edit').status_code == 404

    detail = publish(storefront, 'autumn-edit', status='published')
    listing = client.get(PUBLIC + '/campaigns').json()['items']
    assert [item['slug'] for item in listing] == ['autumn-edit']
    assert listing[0]['product_count'] == 1
    # The list keeps marketing copy but never leaks internal ids or ERP status.
    assert 'id' not in listing[0] and 'status' not in listing[0]

    page = client.get(PUBLIC + '/campaigns/autumn-edit').json()
    assert page['title'] == detail['title'] and page['promo_code'] == 'WELCOME10'
    assert page['product_count'] == len(page['products']) == 1
    assert page['products'][0]['slug'] == product['slug']
    assert page['products'][0]['variants'], 'campaign items must carry buyable variants'

    missing = client.get(PUBLIC + '/campaigns/nope')
    assert missing.status_code == 404


def test_campaign_without_buyable_products_stays_hidden(storefront):
    client, auth, engine, _, _, _, _ = storefront
    publish(storefront, 'empty-edit', attach=False)
    assert client.get(PUBLIC + '/campaigns').json() == {'items': []}
    assert client.get(PUBLIC + '/campaigns/empty-edit').json()['products'] == []


def test_campaign_window_and_unpublishing_hide_the_page(storefront):
    client, auth, engine, _, _, _, _ = storefront
    from datetime import datetime, timedelta, timezone
    past = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)).isoformat()
    publish(storefront, 'expired-edit', starts_at=None, ends_at=past)
    assert client.get(PUBLIC + '/campaigns').json() == {'items': []}
    # An expired campaign stays reachable by its link but is flagged as ended.
    ended = client.get(PUBLIC + '/campaigns/expired-edit')
    assert ended.status_code == 200 and ended.json()['active'] is False

    # Republishing the same slug as a draft removes it from the shelf.
    draft_again = client.put(ADMIN_PATH + '/autumn-edit', headers=auth,
                             json=campaign_payload('autumn-edit', status='draft'))
    assert draft_again.status_code == 200
    slugs = [item['slug'] for item in client.get(PUBLIC + '/campaigns').json()['items']]
    assert 'autumn-edit' not in slugs


def test_campaign_admin_requires_storefront_permissions(storefront):
    client, _, _, _, _, _, _ = storefront
    assert client.get(ADMIN_PATH).status_code in (401, 403)
    assert client.put(ADMIN_PATH + '/x', json=campaign_payload('x')).status_code in (401, 403)
    # Public reads do not need the customer browser headers.
    assert client.get(PUBLIC + '/campaigns').status_code == 200


def test_campaign_product_ids_must_belong_to_the_site(storefront):
    client, auth, engine, _, _, _, _ = storefront
    publish(storefront, 'link-edit', attach=False)
    wrong = client.put(ADMIN_PATH + '/link-edit/products', headers=auth,
                       json={'product_ids': ['00000000-0000-4000-8000-000000000000']})
    assert wrong.status_code == 422
    missing_campaign = client.put(ADMIN_PATH + '/never/products', headers=auth, json={'product_ids': []})
    assert missing_campaign.status_code == 404


def test_campaign_validation_rejects_bad_slugs_and_windows(storefront):
    client, auth, _, _, _, _, _ = storefront
    assert client.put(ADMIN_PATH + '/Good_Slug', headers=auth,
                      json=campaign_payload('Good_Slug')).status_code == 422
    assert client.put(ADMIN_PATH + '/mismatch', headers=auth,
                      json=campaign_payload('other')).status_code == 422
    reversed_window = campaign_payload('window-edit',
                                       starts_at='2026-12-31T00:00:00', ends_at='2026-01-01T00:00:00')
    assert client.put(ADMIN_PATH + '/window-edit', headers=auth, json=reversed_window).status_code == 422


def test_operator_sees_draft_campaigns_with_ids(storefront):
    client, auth, engine, _, _, _, _ = storefront
    created = publish(storefront, 'ops-edit', status='draft')
    listed = client.get(ADMIN_PATH, headers=auth).json()['items']
    row = next(item for item in listed if item['slug'] == 'ops-edit')
    assert row['id'] == created['id'] and row['status'] == 'draft'
    assert created['product_ids'] == row['product_ids'] == [product_id_of(engine)]
