import json

import pytest
from app import listing_agent
from test_erp import create_user, setup  # noqa: F401


def make_listing(client, auth):
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    sku = client.get('/api/v1/skus', headers=auth).json()['items'][0]
    return client.post('/api/v1/listings', headers=auth, json={
        'shop_id': shop['id'], 'sku_id': sku['id'], 'asin': 'B0DRAFT001', 'title': 'Existing product title'}).json(), shop


def good_result():
    return json.dumps({'title': 'Insulated Travel Mug 500 mL', 'bullets': ['500 mL travel mug'],
        'description': 'A travel mug.', 'missing_info': ['Confirm material'],
        'change_reasons': ['Added capacity from verified attributes.']})


def test_create_fact_based_reviewed_draft_and_reject_self_review(setup, monkeypatch):
    client, auth, _ = setup
    listing, _ = make_listing(client, auth)
    captured = {}
    def fake(messages, tools, timeout, **kwargs):
        captured['messages'] = messages
        return {'content': good_result()}
    monkeypatch.setattr(listing_agent, 'completion', fake)
    response = client.post('/api/v1/listing-agent/drafts', headers=auth, json={
        'listing_id': listing['id'], 'target_language': 'English', 'keywords': ['travel mug', 'steel'],
        'existing_bullets': ['Vacuum seal'], 'brand_voice': 'Practical'})
    assert response.status_code == 201, response.text
    draft = response.json()
    assert draft['review_status'] == 'pending'
    assert draft['result']['keyword_coverage'] == [
        {'keyword': 'travel mug', 'covered': True}, {'keyword': 'steel', 'covered': False}]
    assert draft['result']['review_warnings'] == []
    assert 'Vacuum seal' in captured['messages'][-1]['content']
    assert client.get('/api/v1/listing-agent/drafts', headers=auth,
        params={'listing_id': listing['id']}).json()['items'][0]['id'] == draft['id']
    assert client.post(f"/api/v1/listing-agent/drafts/{draft['id']}/review", headers=auth,
        params={'approved': 'true', 'note': 'Reviewed'}).status_code == 403


def test_other_reviewer_can_approve(setup, monkeypatch):
    client, auth, _ = setup
    listing, shop = make_listing(client, auth)
    monkeypatch.setattr(listing_agent, 'completion', lambda *args, **kwargs: {'content': good_result()})
    draft = client.post('/api/v1/listing-agent/drafts', headers=auth,
        json={'listing_id': listing['id'], 'target_language': 'English'}).json()
    role = client.post('/api/v1/roles', headers=auth, json={'code': 'listing-reviewer',
        'name': 'Listing Reviewer', 'permissions': ['listings:read', 'listings:write']}).json()
    _, reviewer = create_user(client, auth, role=role['id'], shop_scope=[shop['id']])
    r = client.post(f"/api/v1/listing-agent/drafts/{draft['id']}/review", headers=reviewer,
        params={'approved': 'true', 'note': 'Facts checked'})
    assert r.status_code == 200, r.text
    assert r.json()['review_status'] == 'approved'


def test_source_change_marks_draft_stale_and_blocks_approval(setup, monkeypatch):
    client, auth, _ = setup
    listing, shop = make_listing(client, auth)
    monkeypatch.setattr(listing_agent, 'completion', lambda *args, **kwargs: {'content': good_result()})
    draft = client.post('/api/v1/listing-agent/drafts', headers=auth,
        json={'listing_id': listing['id'], 'target_language': 'English'}).json()
    assert client.patch(f"/api/v1/listings/{listing['id']}", headers=auth,
        json={'title': 'Updated source title'}).status_code == 200
    items = client.get('/api/v1/listing-agent/drafts', headers=auth,
        params={'listing_id': listing['id']}).json()['items']
    assert items[0]['effective_status'] == 'stale'
    role = client.post('/api/v1/roles', headers=auth, json={'code': 'listing-reviewer-stale',
        'name': 'Listing Reviewer', 'permissions': ['listings:read', 'listings:write']}).json()
    _, reviewer = create_user(client, auth, role=role['id'], shop_scope=[shop['id']])
    response = client.post(f"/api/v1/listing-agent/drafts/{draft['id']}/review", headers=reviewer,
        params={'approved': 'true', 'note': 'Reviewed'})
    assert response.status_code == 409


def test_scope_missing_listing_and_permissions(setup):
    client, auth, _ = setup
    listing, _ = make_listing(client, auth)
    _, scoped = create_user(client, auth, shop_scope=[])
    payload = {'listing_id': listing['id'], 'target_language': 'English'}
    assert client.post('/api/v1/listing-agent/drafts', json=payload).status_code == 401
    assert client.post('/api/v1/listing-agent/drafts', headers=scoped, json=payload).status_code == 403
    assert client.post('/api/v1/listing-agent/drafts', headers=auth,
        json={**payload, 'listing_id': '00000000-0000-0000-0000-000000000000'}).status_code == 404
    assert client.get('/api/v1/listing-agent/drafts', headers=scoped,
        params={'listing_id': listing['id']}).status_code == 404


@pytest.mark.parametrize('content', [
    'not JSON', '{"title":"","bullets":[],"missing_info":[],"change_reasons":[]}',
    '{"title":"T","bullets":[1],"missing_info":[],"change_reasons":[]}',
    json.dumps({'title': 'Best official 100% guaranteed product', 'bullets': [],
        'description': 'FDA-approved for cure', 'missing_info': [], 'change_reasons': []}),
])
def test_bad_and_claim_risky_model_output(setup, monkeypatch, content):
    client, auth, _ = setup
    listing, _ = make_listing(client, auth)
    monkeypatch.setattr(listing_agent, 'completion', lambda *args, **kwargs: {'content': content})
    response = client.post('/api/v1/listing-agent/drafts', headers=auth,
        json={'listing_id': listing['id'], 'target_language': 'English'})
    if content.startswith('{') and 'Best official' in content:
        assert response.status_code == 201
        assert len(response.json()['result']['review_warnings']) >= 1
    else:
        assert response.status_code == 502


def test_draft_does_not_change_listing_and_records_audit(setup, monkeypatch):
    client, auth, _ = setup
    listing, _ = make_listing(client, auth)
    monkeypatch.setattr(listing_agent, 'completion', lambda *args, **kwargs: {'content': good_result()})
    response = client.post('/api/v1/listing-agent/drafts', headers=auth,
        json={'listing_id': listing['id'], 'target_language': 'English'})
    assert response.status_code == 201
    assert client.get('/api/v1/listings/'+listing['id'], headers=auth).json()['title'] == listing['title']
    logs = client.get('/api/v1/audit-logs', headers=auth, params={
        'resource': 'listing_copy_drafts', 'record_id': response.json()['id']})
    assert logs.status_code == 200 and logs.json()['total'] >= 1
