import importlib
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest


@pytest.fixture(params=['memory', 'redis'])
def store(request):
    spec = importlib.util.find_spec('app.lim_governance')
    assert spec is not None, 'Missing atomic gateway governance'
    module = importlib.import_module('app.lim_governance')
    if request.param == 'memory':
        return module.MemoryStore()
    url = os.getenv('TEST_REDIS_URL')
    if not url:
        pytest.skip('TEST_REDIS_URL not configured')
    from redis import Redis
    return module.RedisStore(Redis.from_url(url), prefix='lim-test:' + uuid4().hex)


def test_atomic_daily_reservation_prevents_concurrent_overspend(store):
    from app.lim_governance import Policy
    policy = Policy(requests_per_minute=100, concurrency=100, daily_tokens=100)
    def attempt(_):
        try:
            return store.acquire('actor', 30, 30, policy)
        except RuntimeError as exc:
            assert 'MODEL_QUOTA_EXCEEDED' in str(exc)
            return None
    with ThreadPoolExecutor(max_workers=10) as pool:
        leases = list(pool.map(attempt, range(10)))
    accepted = [lease for lease in leases if lease]
    assert len(accepted) == 3
    store.settle(accepted[0], 10)
    replacement = store.acquire('actor', 30, 30, policy)
    assert replacement
    # Duplicate settlement must not refund quota twice or remove someone else's slot.
    store.settle(accepted[0], 0)
    with pytest.raises(RuntimeError, match='MODEL_QUOTA_EXCEEDED'):
        store.acquire('actor', 30, 30, policy)


def test_concurrency_and_rate_limit_are_enforced(store):
    from app.lim_governance import Policy
    policy = Policy(requests_per_minute=2, concurrency=1, daily_tokens=100)
    first = store.acquire('a', 10, 30, policy)
    with pytest.raises(RuntimeError, match='MODEL_CONCURRENCY_LIMITED'):
        store.acquire('a', 10, 30, policy)
    store.settle(first, 5)
    second = store.acquire('a', 10, 30, policy)
    store.settle(second, 5)
    with pytest.raises(RuntimeError, match='MODEL_RATE_LIMITED'):
        store.acquire('a', 10, 30, policy)
    assert store.acquire('another-actor', 10, 30, policy)


def test_circuit_opens_then_recovers_on_success(store):
    assert store.circuit_allowed('p')
    store.circuit_failure('p', 2, 30)
    assert store.circuit_allowed('p')
    store.circuit_failure('p', 2, 30)
    assert not store.circuit_allowed('p')
    store.circuit_success('p')
    assert store.circuit_allowed('p')


def test_configured_redis_outage_fails_closed(monkeypatch):
    spec = importlib.util.find_spec('app.lim_governance')
    assert spec is not None
    g = importlib.import_module('app.lim_governance')
    monkeypatch.setenv('LIM_REDIS_URL', 'redis://127.0.0.1:1/0')
    with pytest.raises(RuntimeError, match='MODEL_GOVERNANCE_UNAVAILABLE') as error:
        g.get_store().acquire('a', 10, 30, g.Policy())
    assert '127.0.0.1' not in str(error.value)


def test_stale_failures_do_not_trip_memory_circuit(monkeypatch):
    from app import lim_governance as g
    clock = [1000.0]
    monkeypatch.setattr(g.time, 'time', lambda: clock[0])
    store = g.MemoryStore()
    store.circuit_failure('p', 2, 30)
    clock[0] += 31
    store.circuit_failure('p', 2, 30)
    assert store.circuit_allowed('p')


def test_memory_windows_reset_without_refunding_previous_day(monkeypatch):
    from app import lim_governance as g
    clock = [86400.0 - 1]
    monkeypatch.setattr(g.time, 'time', lambda: clock[0])
    store, limits = g.MemoryStore(), g.Policy(requests_per_minute=1, concurrency=2, daily_tokens=100)
    old = store.acquire('a', 80, 30, limits)
    clock[0] += 2
    new = store.acquire('a', 80, 30, limits)
    store.settle(old, 0)
    store.settle(new, 80)
    clock[0] += 60
    with pytest.raises(RuntimeError, match='MODEL_QUOTA_EXCEEDED'):
        store.acquire('a', 30, 30, limits)


def test_expired_lease_releases_slot_but_keeps_reservation(store):
    import time
    from app.lim_governance import Policy
    limits = Policy(requests_per_minute=100, concurrency=1, daily_tokens=100)
    store.acquire('a', 70, 1, limits)
    time.sleep(1.1)
    with pytest.raises(RuntimeError, match='MODEL_QUOTA_EXCEEDED'):
        store.acquire('a', 40, 1, limits)
    assert store.acquire('a', 20, 1, limits)
