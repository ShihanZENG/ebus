import asyncio
import time

import httpx
import pytest
from sqlalchemy import select

from app import lim_model_gateway as gw, models as m
from app.db import build_engine, sessions
from app.lim_models import LimModelProvider, LimModelCatalog, LimModelCall


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    engine = build_engine('sqlite:///' + str(tmp_path / 'gateway.db'))
    m.Base.metadata.create_all(engine)
    factory = sessions(engine)
    monkeypatch.setattr(gw, '_session_factory', factory)
    monkeypatch.setenv('GATEWAY_TEST_KEY', 'secret-not-in-logs')
    monkeypatch.setenv('LIM_MAX_ATTEMPTS', '2')
    monkeypatch.delenv('LIM_REDIS_URL', raising=False)
    # Keep individual tests independent; defaults must still work without Redis.
    from app import lim_governance as g
    monkeypatch.setattr(g, '_memory', g.MemoryStore())
    with factory() as db:
        for number in (1, 2):
            db.add(LimModelProvider(provider_id=f'p{number}', name=f'p{number}',
                base_url=f'https://p{number}.example/v1', api_key_env='GATEWAY_TEST_KEY', status='ACTIVE'))
            db.flush()
            db.add(LimModelCatalog(alias_id=f'a{number}', alias='default', provider_id=f'p{number}',
                model_name=f'm{number}', scene='*', enabled=True, priority=number))
        db.commit()
    yield factory
    engine.dispose()


def transport(monkeypatch, handler):
    real_sync, real_async = httpx.Client, httpx.AsyncClient
    monkeypatch.setattr(gw.httpx, 'Client', lambda **kw: real_sync(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(gw.httpx, 'AsyncClient', lambda **kw: real_async(transport=httpx.MockTransport(handler), **kw))


def success():
    return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': 'ok'}}],
                                    'usage': {'prompt_tokens': 8, 'completion_tokens': 2, 'total_tokens': 10}})


def test_transient_failure_uses_backup_and_records_both_attempts(gateway, monkeypatch):
    def respond(request):
        return httpx.Response(503, text='secret-not-in-logs') if request.url.host == 'p1.example' else success()
    transport(monkeypatch, respond)
    answer = gw.complete([{'role': 'user', 'content': 'private-prompt'}], [], 3, return_metadata=True)
    assert answer['provider_id'] == 'p2' and answer['attempt_count'] == 2
    with gateway() as db:
        record = db.scalar(select(LimModelCall))
        assert record.status == 'SUCCEEDED'
        assert [a['status'] for a in record.attempts] == ['FAILED', 'SUCCEEDED']
        assert 'secret-not-in-logs' not in str(record.__dict__)
        assert 'private-prompt' not in str(record.__dict__)


def test_auth_failure_never_retries(gateway, monkeypatch):
    seen = []
    def respond(request):
        seen.append(request.url.host)
        return httpx.Response(401)
    transport(monkeypatch, respond)
    with pytest.raises(RuntimeError, match='MODEL_HTTP_ERROR'):
        gw.complete([], [], 2)
    assert seen == ['p1.example']


def test_quota_rejection_never_sends_a_request(gateway, monkeypatch):
    monkeypatch.setenv('LIM_DAILY_TOKEN_BUDGET', '1')
    transport(monkeypatch, lambda request: pytest.fail('quota rejection contacted provider'))
    with pytest.raises(RuntimeError, match='MODEL_QUOTA_EXCEEDED'):
        gw.complete([], [], 2)
    with gateway() as db:
        record = db.scalar(select(LimModelCall))
        assert record.status == 'REJECTED'


def test_open_circuit_skips_provider(gateway, monkeypatch):
    monkeypatch.setenv('LIM_CIRCUIT_THRESHOLD', '1')
    seen = []
    def respond(request):
        seen.append(request.url.host)
        return httpx.Response(503) if request.url.host == 'p1.example' else success()
    transport(monkeypatch, respond)
    gw.complete([], [], 3)
    gw.complete([], [], 3)
    assert seen == ['p1.example', 'p2.example', 'p2.example']


def test_transport_total_deadline_cancels_slow_response(monkeypatch):
    assert hasattr(gw, '_post_with_deadline'), 'Missing cancellable total deadline transport'
    cancelled = []
    async def slow(request):
        try:
            await asyncio.sleep(1)
            return success()
        finally:
            cancelled.append(True)
    transport(monkeypatch, slow)
    started = time.monotonic()
    with pytest.raises(httpx.TimeoutException):
        gw._post_with_deadline('https://p1.example/v1', 'key', {}, .05)
    assert time.monotonic() - started < .5
    assert cancelled == [True]


def test_audit_failure_is_visible_but_does_not_leak_exception(monkeypatch, caplog):
    def unavailable():
        raise RuntimeError('secret-not-in-logs')
    monkeypatch.setattr(gw, '_sessions', unavailable)
    gw._record(call_id='c', alias='default', provider_id='p', model='m', status='FAILED')
    assert 'LIM_MODEL_AUDIT_WRITE_FAILED' in caplog.text
    assert 'secret-not-in-logs' not in caplog.text


def test_fallback_keeps_priority_when_failed_route_opens_circuit(gateway, monkeypatch):
    monkeypatch.setenv('LIM_CIRCUIT_THRESHOLD', '1')
    with gateway() as db:
        db.add(LimModelCatalog(alias_id='a3', alias='default', provider_id='p2',
                              model_name='last-choice', scene='*', enabled=True, priority=3))
        db.commit()
    transport(monkeypatch, lambda req: httpx.Response(503) if req.url.host == 'p1.example' else success())
    result = gw.complete([], [], 3, return_metadata=True)
    assert result['model'] == 'm2'


def test_successful_fallback_keeps_partial_unknown_usage_visible(gateway, monkeypatch):
    from app.lim_gateway_metrics import aggregate_model_calls
    transport(monkeypatch, lambda req: httpx.Response(503) if req.url.host == 'p1.example' else success())
    gw.complete([], [], 3)
    with gateway() as db:
        metrics = aggregate_model_calls(db, [])
    assert metrics['known_total_tokens'] == 10
    assert metrics['unknown_usage_count'] == 1
    assert metrics['unknown_attempt_usage_count'] == 1
