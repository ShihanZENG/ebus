import json
from urllib.parse import urlparse

import httpx
import pytest
from sqlalchemy import select

from app import lim_model_gateway as gw
from app.db import sessions
from app.lim_models import LimModelProvider, LimModelCatalog, LimModelCall
from test_erp import setup, create_user  # noqa: F401


def register(db, provider='first', scene='*', priority=100, enabled=True):
    if db.scalar(select(LimModelProvider).where(LimModelProvider.provider_id == provider)) is None:
        db.add(LimModelProvider(provider_id=provider, name=provider, base_url='https://model.example/v1',
                                api_key_env='GATEWAY_TEST_KEY', enabled=enabled, status='ACTIVE'))
        db.flush()
    row = LimModelCatalog(alias_id=f'{provider}-{scene}', alias='default', provider_id=provider,
                          model_name=f'{provider}-model', scene=scene, priority=priority, enabled=True)
    db.add(row)
    db.commit()
    return row


def test_routing_skips_disabled_provider_and_respects_explicit_disable(setup, monkeypatch):
    client, auth, engine = setup
    monkeypatch.setenv('GATEWAY_TEST_KEY', 'test-only-key')
    monkeypatch.setenv('PURCHASE_AGENT_LLM_BASE_URL', 'https://fallback.example/v1')
    monkeypatch.setenv('PURCHASE_AGENT_LLM_API_KEY', 'test-only-key')
    monkeypatch.setenv('PURCHASE_AGENT_LLM_MODEL', 'fallback-model')
    with sessions(engine)() as db:
        register(db, 'blocked', 'inventory', 1, False)
        selected = register(db, 'second', 'inventory', 2)
        wildcard = register(db, 'wildcard', '*', 0)
        assert gw.resolve(db, scene='inventory')[2] == 'second-model'
        selected.enabled = False
        wildcard.enabled = False
        db.commit()
        with pytest.raises(RuntimeError, match='MODEL_ROUTE_UNAVAILABLE'):
            gw.resolve(db, scene='inventory')
        with pytest.raises(RuntimeError, match='MODEL_ROUTE_UNAVAILABLE'):
            gw.resolve(db, alias='unknown')
        register(db, 'supply-provider', 'supply')
    for key in ('PURCHASE_AGENT_LLM_BASE_URL', 'PURCHASE_AGENT_LLM_API_KEY', 'PURCHASE_AGENT_LLM_MODEL'):
        monkeypatch.delenv(key, raising=False)
    runtime = client.get('/api/v1/purchase-agent/runtime', headers=auth)
    assert runtime.status_code == 200
    assert runtime.json()['model_configured'] is True
    assert runtime.json()['model'] == 'supply-provider-model'


def test_text_payload_omits_empty_tool_fields():
    payload = gw._build_payload(urlparse('https://model.example/v1'), 'model', [{'role': 'user', 'content': 'hello'}], [])
    assert 'tools' not in payload
    assert 'tool_choice' not in payload


def test_gateway_chat_auth_metadata_and_private_logging(setup, monkeypatch):
    client, auth, engine = setup
    monkeypatch.setattr(gw, '_session_factory', sessions(engine))
    monkeypatch.setenv('GATEWAY_TEST_KEY', 'test-only-key')
    with sessions(engine)() as db:
        register(db)
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': '收到'}}],
                                        'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}})
    real_client = httpx.Client
    monkeypatch.setattr(gw.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    url = '/api/v1/lim/model-chat'
    assert client.post(url, json={'prompt': 'hello'}).status_code == 401
    result = client.post(url, headers=auth, json={'prompt': 'private-input', 'scene': 'inventory'})
    assert result.status_code == 200, result.text
    data = result.json()
    assert data['reply'] == '收到'
    assert data['model'] == 'first-model'
    assert data['total_tokens'] == 12
    assert data['cost'] is None
    assert data['latency_ms'] >= 0
    assert len(requests) == 1 and 'tools' not in requests[0]
    with sessions(engine)() as db:
        row = db.scalar(select(LimModelCall).where(LimModelCall.call_id == data['call_id']))
        assert row is not None and row.actor_id and row.total_tokens == 12
        assert 'private-input' not in str(row.__dict__)
    assert client.post(url, headers=auth, json={'prompt': ''}).status_code == 422
    _, reader = create_user(client, auth)
    assert client.post(url, headers=reader, json={'prompt': 'hello'}).status_code == 403
    monkeypatch.setattr(gw.httpx, 'Client', lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text='test-only-key')), **kwargs))
    failed = client.post(url, headers=auth, json={'prompt': 'hello'})
    assert failed.status_code == 503 and 'test-only-key' not in failed.text
    with sessions(engine)() as db:
        failures = db.scalars(select(LimModelCall).where(LimModelCall.status == 'FAILED')).all()
        assert len(failures) == 1 and failures[0].error_code == 'MODEL_HTTP_ERROR'
    for content in [None, {}, [], '', '  ']:
        monkeypatch.setattr(gw.httpx, 'Client', lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
                'choices': [{'message': {'content': content}}]})), **kwargs))
        response = client.post(url, headers=auth, json={'prompt': 'hello'})
        assert response.status_code == 503 and 'MODEL_RESPONSE_INVALID' in response.text
    with sessions(engine)() as db:
        invalid = db.scalars(select(LimModelCall).where(LimModelCall.error_code == 'MODEL_RESPONSE_INVALID')).all()
        assert len(invalid) == 5
