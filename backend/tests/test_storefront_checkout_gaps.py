"""Acceptance gaps in PRD 4.6.4–4.6.8."""
from test_erp import setup  # noqa: F401
from test_storefront import storefront, checkout, submission, PUBLIC, ADMIN  # noqa: F401
from test_storefront import customer_session, customer_headers
import uuid


def test_quote_is_server_priced_and_checkout_rechecks_total(storefront):
    c, auth, _, _, _, _, product = storefront
    payload = submission(product, 2)
    quote = c.post(PUBLIC + '/checkout/quote', json=payload)
    assert quote.status_code == 200, quote.text
    assert quote.json()['subtotal'] == '58.00'
    assert quote.json()['shipping_amount'] == '0.00'
    assert quote.json()['grand_total'] == '58.00'
    bad = {**payload, 'expected_total': '0.01'}
    assert checkout(c, product, payload=bad)[0].status_code == 409
    good = {**payload, 'expected_total': quote.json()['grand_total']}
    placed = checkout(c, product, payload=good)[0]
    assert placed.status_code == 201, placed.text
    assert placed.json()['order']['grand_total'] == '58.00'
    c.patch(ADMIN + '/products/' + product['id'], headers=auth, json={'status': 'draft'})
    assert c.post(PUBLIC + '/checkout/quote', json=payload).status_code == 409


def test_failed_payment_can_retry_without_reversing_success(storefront):
    c, _, _, _, _, _, product = storefront
    placed = checkout(c, product)[0].json()
    headers = {'Authorization': 'Bearer ' + placed['access_token']}
    path = PUBLIC + '/orders/' + placed['order']['public_id'] + '/payments'
    failed = c.post(path, headers=headers, json={'scenario': 'fail'})
    assert failed.json()['order']['payment_status'] == 'failed'
    paid = c.post(path, headers=headers, json={'scenario': 'success'})
    assert paid.json()['order']['payment_status'] == 'succeeded'
    retry = c.post(path, headers=headers, json={'scenario': 'fail'})
    assert retry.json()['order']['payment_status'] == 'succeeded'
    assert retry.json()['payment']['id'] == paid.json()['payment']['id']
    assert retry.json()['created'] is False


def test_quote_rejects_forged_amount_and_out_of_stock(storefront):
    c, _, _, _, _, _, product = storefront
    forged = {**submission(product), 'grand_total': '0.01'}
    assert c.post(PUBLIC + '/checkout/quote', json=forged).status_code == 422
    assert c.post(PUBLIC + '/checkout/quote', json=submission(product, 4)).status_code == 409


def test_other_customer_cannot_read_pay_or_retry_owned_order(storefront):
    c, _, _, _, _, _, product = storefront
    owner = customer_session(c, 'quote_owner')
    recovery = uuid.uuid4().hex + uuid.uuid4().hex
    headers = {**customer_headers(), 'Idempotency-Key': uuid.uuid4().hex,
               'X-Checkout-Recovery': recovery, 'X-Customer-Id': owner['id']}
    payload = submission(product)
    placed = c.post(PUBLIC + '/checkout', headers=headers, json=payload)
    assert placed.status_code == 201, placed.text
    path = PUBLIC + '/orders/' + placed.json()['order']['public_id']
    assert c.get(path).status_code == 200
    c.post(PUBLIC + '/account/logout', headers=customer_headers())
    other = customer_session(c, 'quote_other')
    assert c.get(path).status_code == 404
    assert c.get(PUBLIC + '/account/orders').json()['items'] == []
    assert c.post(path + '/payments', headers=customer_headers(), json={'scenario': 'success'}).status_code == 404
    headers['X-Customer-Id'] = other['id']
    assert c.post(PUBLIC + '/checkout', headers=headers, json=payload).status_code == 403
