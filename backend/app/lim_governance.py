"""Atomic admission, conservative daily reservations and circuit state.

Memory mode is explicitly single-process. Configured Redis never falls back.
UTC fixed windows; leases expire after the request deadline, abandoned reservations
remain charged so process crashes cannot refund work the provider may have done.
"""
import hashlib
import json
import math
import os
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from uuid import uuid4


class GovernanceError(RuntimeError):
    def __init__(self, code, message, status_code=429):
        self.code, self.status_code = code, status_code
        super().__init__(f'{code}：{message}')


def unavailable():
    return GovernanceError('MODEL_GOVERNANCE_UNAVAILABLE', '调用治理服务不可用，请稍后重试', 503)


@dataclass(frozen=True)
class Policy:
    requests_per_minute: int = 60
    concurrency: int = 3
    daily_tokens: int = 1000000
    max_attempts: int = 2
    circuit_threshold: int = 3
    circuit_seconds: int = 30


def policy():
    fields = {'requests_per_minute': ('LIM_REQUESTS_PER_MINUTE', 100000),
              'concurrency': ('LIM_MAX_CONCURRENCY', 1000),
              'daily_tokens': ('LIM_DAILY_TOKEN_BUDGET', 1000000000),
              'max_attempts': ('LIM_MAX_ATTEMPTS', 3),
              'circuit_threshold': ('LIM_CIRCUIT_THRESHOLD', 100),
              'circuit_seconds': ('LIM_CIRCUIT_SECONDS', 3600)}
    defaults = Policy()
    values = {}
    try:
        for name, (env, ceiling) in fields.items():
            value = int(os.getenv(env, str(getattr(defaults, name))))
            if not 1 <= value <= ceiling:
                raise ValueError()
            values[name] = value
    except ValueError:
        raise GovernanceError('MODEL_GOVERNANCE_CONFIG_INVALID', '调用治理配置超出允许范围', 503) from None
    return Policy(**values)


ERRORS = {
    1: ('MODEL_RATE_LIMITED', '请求频率超过每分钟限额'),
    2: ('MODEL_CONCURRENCY_LIMITED', '同时进行的模型调用过多'),
    3: ('MODEL_QUOTA_EXCEEDED', '每日 Token 预算不足以预留本次调用'),
}


def checked(code):
    if code:
        raise GovernanceError(*ERRORS[int(code)])


@dataclass(frozen=True)
class Lease:
    actor: str
    token: str


class MemoryStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.actors = {}
        self.circuits = {}

    def acquire(self, actor, reservation, lease_seconds, limits):
        now = time.time()
        minute, day = int(now // 60), int(now // 86400)
        with self.lock:
            # Bounded lifetime for inactive identities, including denied traffic.
            self.actors = {k: v for k, v in self.actors.items() if v['touched'] > now - 172800}
            state = self.actors.setdefault(actor, dict(day=day, used=0, minute=minute, count=0, leases={}, touched=now))
            state['touched'] = now
            if state['day'] != day:
                state.update(day=day, used=0)
            if state['minute'] != minute:
                state.update(minute=minute, count=0)
            state['leases'] = {k: v for k, v in state['leases'].items() if v['expires'] > now}
            checked(1 if state['count'] >= limits.requests_per_minute else
                    2 if len(state['leases']) >= limits.concurrency else
                    3 if state['used'] + reservation > limits.daily_tokens else 0)
            token = uuid4().hex
            state['leases'][token] = dict(expires=now + lease_seconds, reserved=reservation, day=day)
            state['count'] += 1
            state['used'] += reservation
            return Lease(actor, token)

    def settle(self, lease, charged_tokens):
        with self.lock:
            state = self.actors.get(lease.actor)
            entry = state['leases'].pop(lease.token, None) if state else None
            if entry and entry['day'] == state['day']:
                state['used'] += max(0, charged_tokens) - entry['reserved']

    def circuit_allowed(self, key):
        with self.lock:
            count, opened, expires = self.circuits.get(key, (0, False, 0))
            if expires <= time.time():
                self.circuits.pop(key, None)
                return True
            return not opened

    def circuit_failure(self, key, threshold, seconds):
        with self.lock:
            now = time.time()
            self.circuits = {k: v for k, v in self.circuits.items() if v[2] > now}
            count, opened, expires = self.circuits.get(key, (0, False, 0))
            count += 1
            self.circuits[key] = (count, opened or count >= threshold, now + seconds)

    def circuit_success(self, key):
        with self.lock:
            self.circuits.pop(key, None)


# One actor key is updated atomically; all keys work in Redis Cluster too.
ADMIT = """
local now = tonumber(redis.call('TIME')[1])
local day = math.floor(now / 86400)
local minute = math.floor(now / 60)
local raw = redis.call('GET', KEYS[1])
local s = raw and cjson.decode(raw) or {day=day, used=0, minute=minute, count=0, leases={}}
if s.day ~= day then s.day=day; s.used=0 end
if s.minute ~= minute then s.minute=minute; s.count=0 end
local active=0
for k,v in pairs(s.leases) do
  if v.expires <= now then s.leases[k]=nil else active=active+1 end
end
if s.count >= tonumber(ARGV[4]) then return 1 end
if active >= tonumber(ARGV[5]) then return 2 end
if s.used + tonumber(ARGV[2]) > tonumber(ARGV[6]) then return 3 end
s.count=s.count+1; s.used=s.used+tonumber(ARGV[2])
s.leases[ARGV[1]]={expires=now+tonumber(ARGV[3]), reserved=tonumber(ARGV[2]), day=day}
redis.call('SET', KEYS[1], cjson.encode(s), 'EX', 172800)
return 0
"""
SETTLE = """
local raw=redis.call('GET', KEYS[1]); if not raw then return 0 end
local s=cjson.decode(raw); local lease=s.leases[ARGV[1]]
if not lease then return 0 end
if s.day == lease.day then s.used=s.used+tonumber(ARGV[2])-lease.reserved end
s.leases[ARGV[1]]=nil
redis.call('SET', KEYS[1], cjson.encode(s), 'KEEPTTL'); return 1
"""
CIRCUIT_FAILURE = """
local count=redis.call('HINCRBY', KEYS[1], 'failures', 1)
if count >= tonumber(ARGV[1]) then redis.call('HSET', KEYS[1], 'open', 1) end
redis.call('EXPIRE', KEYS[1], ARGV[2]); return count
"""


class RedisStore:
    def __init__(self, client, prefix='lim:governance:v1'):
        self.client, self.prefix = client, prefix

    def _key(self, kind, identity):
        return self.prefix + ':' + kind + ':' + hashlib.sha256(identity.encode()).hexdigest()

    def _call(self, fn, *args):
        from redis.exceptions import RedisError
        try:
            return fn(*args)
        except RedisError:
            raise unavailable() from None

    def acquire(self, actor, reservation, lease_seconds, limits):
        lease = Lease(actor, uuid4().hex)
        code = self._call(self.client.eval, ADMIT, 1, self._key('actor', actor),
                          lease.token, reservation, math.ceil(lease_seconds), limits.requests_per_minute,
                          limits.concurrency, limits.daily_tokens)
        checked(code)
        return lease

    def settle(self, lease, charged_tokens):
        self._call(self.client.eval, SETTLE, 1, self._key('actor', lease.actor), lease.token, max(0, charged_tokens))

    def circuit_allowed(self, key):
        return not self._call(self.client.hget, self._key('circuit', key), 'open')

    def circuit_failure(self, key, threshold, seconds):
        self._call(self.client.eval, CIRCUIT_FAILURE, 1, self._key('circuit', key), threshold, seconds)

    def circuit_success(self, key):
        self._call(self.client.delete, self._key('circuit', key))


_memory = MemoryStore()


@lru_cache(maxsize=4)
def _redis_store(url):
    from redis import Redis
    try:
        return RedisStore(Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1))
    except ValueError:
        raise unavailable() from None


def get_store():
    url = os.getenv('LIM_REDIS_URL', '').strip()
    return _redis_store(url) if url else _memory


def governance_status():
    from dataclasses import asdict
    return {'mode': 'redis' if os.getenv('LIM_REDIS_URL', '').strip() else 'memory_single_process',
            'limits': asdict(policy()), 'quota_basis': 'conservative_reservation', 'window_timezone': 'UTC'}
