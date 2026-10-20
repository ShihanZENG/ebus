from test_erp import setup, create_user
from test_oms import demo_basics, make_order
from app import models as m
from app.db import sessions
from app.customer_tickets import CustomerTicket


def create_ticket(client, auth, shop_id, order_id=None):
    return client.post('/api/v1/customer-tickets', headers=auth, json={
        'shop_id': shop_id, 'order_id': order_id, 'subject': '配送问题',
        'description': '客户询问配送进度', 'priority': 'normal',
    })


def test_customer_profile_links_existing_order_and_ticket_without_rewriting_order_snapshot(setup):
    client, auth, engine = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    order = make_order(client, auth, shop, skus[0], currency,
                       source_no='CUSTOMER-LINK-ORDER').json()
    customer_name_snapshot = order['customer_name']
    customer_contact_snapshot = order['customer_contact']
    ticket = create_ticket(client, auth, shop['id'], order['id']).json()

    response = client.post('/api/v1/customers', headers=auth, json={
        'shop_id': shop['id'], 'name': 'Lin Mei', 'contact': 'lin@example.test',
        'notes': ' prefers email',
    })
    assert response.status_code == 201, response.text
    customer = response.json()
    assert customer['name'] == 'Lin Mei'
    assert customer['contact'] == 'lin@example.test'
    assert customer['notes'] == 'prefers email'
    updated = client.patch(f"/api/v1/customers/{customer['id']}", headers=auth, json={
        'notes': ' prefers phone ',
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()['notes'] == 'prefers phone'

    assert client.post(f"/api/v1/customers/{customer['id']}/orders/{order['id']}",
                       headers=auth).status_code == 200
    assert client.post(f"/api/v1/customers/{customer['id']}/tickets/{ticket['id']}",
                       headers=auth).status_code == 200
    links = client.get(f"/api/v1/customers/{customer['id']}/links", headers=auth)
    assert links.status_code == 200, links.text
    assert [row['id'] for row in links.json()['orders']] == [order['id']]
    assert [row['id'] for row in links.json()['tickets']] == [ticket['id']]
    saved_order = client.get(f"/api/v1/orders/{order['id']}", headers=auth).json()
    assert saved_order['customer_name'] == customer_name_snapshot
    assert saved_order['customer_contact'] == customer_contact_snapshot
    with sessions(engine)() as db:
        assert db.get(m.SalesOrder, order['id']).customer_id == customer['id']
        assert db.get(CustomerTicket, ticket['id']).customer_id == customer['id']


def test_customer_scope_and_link_permission_boundaries(setup):
    client, auth, engine = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    other_currency = currency
    with sessions(engine)() as db:
        other_shop = m.Shop(code='CRM-OTHER', name='Other shop', channel='manual', market='US',
                            timezone='UTC', currency_id=other_currency['id'], is_active=True)
        db.add(other_shop)
        db.commit()
        db.refresh(other_shop)
        other_shop_id = other_shop.id
    foreign_order = make_order(client, auth, {**shop, 'id': other_shop_id}, skus[0], currency,
                                source_no='CUSTOMER-LINK-FOREIGN').json()
    customer = client.post('/api/v1/customers', headers=auth, json={
        'shop_id': shop['id'], 'name': 'Shop-scoped customer',
    }).json()

    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'customer_scope_role', 'name': '客户店铺范围',
        'permissions': ['customers:read', 'customers:write', 'orders:read', 'orders:write',
                        'customer_tickets:read', 'customer_tickets:write'],
    }).json()
    _, scoped = create_user(client, auth, role=role['id'], shop_scope=[shop['id']])
    _, empty_scope = create_user(client, auth, role=role['id'], username='empty_customer_scope', shop_scope=[])
    assert client.get('/api/v1/customers', headers=scoped).json()['total'] == 1
    assert client.get('/api/v1/customers', headers=empty_scope).json()['total'] == 0
    assert client.post('/api/v1/customers', headers=scoped, json={
        'shop_id': other_shop_id, 'name': 'Out of scope',
    }).status_code == 404
    assert client.post(f"/api/v1/customers/{customer['id']}/orders/{foreign_order['id']}",
                       headers=scoped).status_code == 404
    with sessions(engine)() as db:
        assert db.get(m.SalesOrder, foreign_order['id']).customer_id is None

    limited_role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'customer_only_role', 'name': '仅客户档案', 'permissions': ['customers:read'],
    }).json()
    _, limited = create_user(client, auth, role=limited_role['id'], username='customer_only_reader',
                             shop_scope=[shop['id']])
    limited_links = client.get(f"/api/v1/customers/{customer['id']}/links", headers=limited)
    assert limited_links.status_code == 200
    assert limited_links.json() == {'orders': [], 'tickets': []}


def test_order_and_ticket_can_be_created_with_shop_matched_customer_profile(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    customer = client.post('/api/v1/customers', headers=auth, json={
        'shop_id': shop['id'], 'name': 'Create-time customer',
    }).json()
    order_response = client.post('/api/v1/orders', headers=auth, json={
        'shop_id': shop['id'], 'customer_id': customer['id'], 'source_channel': 'manual',
        'source_order_no': 'CUSTOMER-CREATE-ORDER', 'currency_id': currency['id'],
        'customer_name': 'legacy snapshot', 'customer_contact': 'snapshot@example.test',
        'items': [{'sku_id': skus[0]['id'], 'quantity': 1, 'unit_price': '9.99'}],
    })
    assert order_response.status_code == 201, order_response.text
    assert order_response.json()['customer_id'] == customer['id']
    assert order_response.json()['customer_name'] == 'legacy snapshot'
    ticket_response = client.post('/api/v1/customer-tickets', headers=auth, json={
        'shop_id': shop['id'], 'customer_id': customer['id'], 'order_id': order_response.json()['id'],
        'subject': '新客户关联工单', 'description': '创建时指定客户档案', 'priority': 'normal',
    })
    assert ticket_response.status_code == 201, ticket_response.text
    assert ticket_response.json()['customer_id'] == customer['id']


def test_unlinked_records_are_visible_and_creating_from_order_links_atomically(setup):
    client, auth, engine = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    order = make_order(client, auth, shop, skus[0], currency,
                       source_no='CRM-UNLINKED-ORDER').json()
    ticket = create_ticket(client, auth, shop['id'], order['id']).json()

    response = client.get('/api/v1/customers/unlinked', headers=auth)
    assert response.status_code == 200, response.text
    assert [row['id'] for row in response.json()['orders']] == [order['id']]
    assert [row['id'] for row in response.json()['tickets']] == [ticket['id']]
    assert response.json()['orders'][0]['currency_code'] == currency['code']

    created = client.post(f"/api/v1/customers/from-order/{order['id']}", headers=auth, json={
        'name': 'Verified customer', 'contact': 'buyer@example.test', 'notes': 'manual confirmation',
    })
    assert created.status_code == 201, created.text
    customer = created.json()
    assert customer['shop_id'] == shop['id']
    assert customer['name'] == 'Verified customer'
    with sessions(engine)() as db:
        saved_order = db.get(m.SalesOrder, order['id'])
        saved_ticket = db.get(CustomerTicket, ticket['id'])
        assert saved_order.customer_id == customer['id']
        assert saved_order.customer_name == order['customer_name']
        assert saved_order.customer_contact == order['customer_contact']
        assert saved_ticket.customer_id is None


def test_creating_customer_from_ticket_links_and_audits_the_ticket(setup):
    client, auth, engine = setup
    shop, _, _, _ = demo_basics(client, auth)
    ticket = create_ticket(client, auth, shop['id']).json()
    response = client.post(f"/api/v1/customers/from-ticket/{ticket['id']}", headers=auth, json={
        'name': 'Ticket-origin customer', 'contact': '', 'notes': '',
    })
    assert response.status_code == 201, response.text
    customer = response.json()
    assert customer['shop_id'] == shop['id']
    with sessions(engine)() as db:
        saved = db.get(CustomerTicket, ticket['id'])
        assert saved.customer_id == customer['id']
