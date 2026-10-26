from sqlalchemy import select

from app import models as m
from app.db import sessions
from app.lim_models import LimModelCall
from test_erp import setup, create_user  # noqa: F401


def test_call_history_and_metrics_share_actor_visibility(setup):
    client, admin, engine = setup
    reader_user, reader = create_user(client, admin)
    with sessions(engine)() as db:
        admin_id = db.scalar(select(m.User.id).where(m.User.username == 'admin'))
        for call_id, actor, status, tokens in [('own', reader_user['id'], 'SUCCEEDED', 12),
                                               ('other', admin_id, 'FAILED', None),
                                               ('system', None, 'SUCCEEDED', None)]:
            db.add(LimModelCall(call_id=call_id, actor_id=actor, alias='default',
                               provider_id='p', model='m', status=status, total_tokens=tokens, latency_ms=10))
        db.commit()
    own = client.get('/api/v1/lim/model-calls', headers=reader).json()
    assert own['total'] == 1
    assert [row['call_id'] for row in own['items']] == ['own']
    assert client.get('/api/v1/lim/model-calls', headers=admin).json()['total'] == 3
    metrics = client.get('/api/v1/lim/model-metrics', headers=reader)
    assert metrics.status_code == 200
    assert metrics.json()['call_count'] == 1
    assert metrics.json()['known_total_tokens'] == 12
    assert metrics.json()['unknown_usage_count'] == 0
    all_metrics = client.get('/api/v1/lim/model-metrics', headers=admin).json()
    assert all_metrics['call_count'] == 3
    assert all_metrics['unknown_usage_count'] == 2
    assert all_metrics['cost_status'] == 'unavailable'
    assert client.get('/api/v1/lim/model-metrics').status_code == 401
    assert client.get('/api/v1/lim/model-metrics?days=0', headers=admin).status_code == 422


def test_model_chat_returns_quota_http_status_without_provider_call(setup, monkeypatch):
    from app import lim_model_gateway as gw
    from app.lim_governance import GovernanceError
    client, admin, engine = setup
    def denied(*args, **kwargs):
        raise GovernanceError('MODEL_QUOTA_EXCEEDED', 'quota reached')
    monkeypatch.setattr(gw, 'complete', denied)
    response = client.post('/api/v1/lim/model-chat', headers=admin, json={'prompt': 'hello'})
    assert response.status_code == 429
    assert response.json()['error']['code'] == 'HTTP_429'
    assert 'MODEL_QUOTA_EXCEEDED' in response.json()['error']['message']
