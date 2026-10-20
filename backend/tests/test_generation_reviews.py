"""Generated results have one scoped and auditable human review decision."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import agent_generation as gen
from app.agent_generation import Generation
from app.generation_reviews import router
from app.main import create_app
from app.db import sessions
from test_erp import create_user, setup  # noqa: F401


def profit_payload(shop_id):
    return {
        'shop_id': shop_id,
        'source_reference': 'review-test-statement',
        'period_start': '2026-10-01',
        'period_end': '2026-10-02',
        'currency': 'USD',
        'lines': [
            {'source_event_id': 'sale-1', 'category': 'sale', 'amount': '100.00'},
            {'source_event_id': 'cost-1', 'category': 'cogs', 'amount': '40.00'},
            {'source_event_id': 'fee-1', 'category': 'platform_fee', 'amount': '8.00'},
        ],
    }


def review_client(engine):
    app = create_app(engine)
    if not any(getattr(route, 'path', None) == '/api/v1/generation-reviews' for route in app.routes):
        app.include_router(router)
    return TestClient(app)


def test_generation_defaults_to_pending_and_scoped_reader_can_list(setup, monkeypatch):
    client, admin_auth, engine = setup
    shops = client.get('/api/v1/shops', headers=admin_auth).json()['items']
    shop = shops[0]
    monkeypatch.setattr(gen, 'completion', lambda messages, tools, timeout: {
        'content': '基于所列数据的待审核说明。',
    })
    created = client.post(
        '/api/v1/agent-generations/profit', headers=admin_auth, json=profit_payload(shop['id']))
    assert created.status_code == 200, created.text
    assert created.json()['review_status'] == 'pending'

    role = client.post('/api/v1/roles', headers=admin_auth, json={
        'code': 'generation_profit_reader',
        'name': '利润生成读者',
        'permissions': ['finance_agent:read'],
    }).json()
    _, reader_auth = create_user(
        client, admin_auth, role=role['id'], shop_scope=[shop['id']], warehouse_scope=[])

    with review_client(engine) as reviews:
        listed = reviews.get('/api/v1/generation-reviews', headers=reader_auth)
        assert listed.status_code == 200, listed.text
        assert listed.json()['total'] == 1
        assert listed.json()['items'][0]['id'] == created.json()['id']
        assert listed.json()['items'][0]['review_required'] is True
        denied_kind = reviews.get(
            '/api/v1/generation-reviews', headers=reader_auth, params={'kind': 'ads'})
        assert denied_kind.status_code == 403


def test_admin_decision_is_single_use_and_audited(setup, monkeypatch):
    client, admin_auth, engine = setup
    shop = client.get('/api/v1/shops', headers=admin_auth).json()['items'][0]
    monkeypatch.setattr(gen, 'completion', lambda messages, tools, timeout: {
        'content': '基于所列数据的待审核说明。',
    })
    created = client.post(
        '/api/v1/agent-generations/profit', headers=admin_auth, json=profit_payload(shop['id'])).json()

    role = client.post('/api/v1/roles', headers=admin_auth, json={
        'code': 'generation_reviewer_denied',
        'name': '非管理员审核测试',
        'permissions': ['finance_agent:read'],
    }).json()
    _, reader_auth = create_user(
        client, admin_auth, role=role['id'], shop_scope=[shop['id']], warehouse_scope=[])

    path = f"/api/v1/generation-reviews/{created['id']}/decision"
    with review_client(engine) as reviews:
        denied = reviews.post(path, headers=reader_auth, json={'status': 'approved'})
        assert denied.status_code == 403
        missing_reason = reviews.post(path, headers=admin_auth, json={'status': 'rejected'})
        assert missing_reason.status_code == 422

        decided = reviews.post(path, headers=admin_auth, json={
            'status': 'rejected', 'note': '费率来源待重新核对',
        })
        assert decided.status_code == 200, decided.text
        assert decided.json()['review_status'] == 'rejected'
        assert decided.json()['review_required'] is False
        assert decided.json()['reviewed_by']
        assert decided.json()['reviewed_at']
        assert decided.json()['review_note'] == '费率来源待重新核对'

        repeated = reviews.post(path, headers=admin_auth, json={'status': 'approved'})
        assert repeated.status_code == 409
        audit = reviews.get('/api/v1/audit-logs', headers=admin_auth, params={'record_id': created['id']}).json()
        review_entries = [item for item in audit['items'] if item['action'] == 'review']
        assert len(review_entries) == 1
        assert review_entries[0]['before']['review_status'] == 'pending'
        assert review_entries[0]['after']['review_status'] == 'rejected'

    with sessions(engine)() as db:
        row = db.scalar(select(Generation).where(Generation.id == created['id']))
        assert row.review_status == 'rejected'
        assert row.review_note == '费率来源待重新核对'
