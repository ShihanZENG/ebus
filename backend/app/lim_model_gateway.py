"""LIM 模型网关：统一的模型调用出口 + 调用级观测。

V1.1：注册表路由、原子准入、有限故障切换及脱敏调用观测。
模型聚合见 lim_gateway_metrics；工具聚合与模型聚合保持各自口径。

设计约束（改本文件前请先读）：
1. 对外保持 supply_agent_llm.completion() 的签名与 MODEL_* 错误码完全不变。
2. 观测记录使用**独立会话**：业务侧（如 supply_agent_llm.chat）失败时会 db.rollback()，
   共用事务会把模型调用记录一起回滚掉。
3. 供应商明文 key 绝不落库：provider 行只存环境变量名，运行时 os.getenv 读取。
4. 错误脱敏：只记 error_code 与 HTTP 状态码，绝不记录供应商响应体（防回显 token）。
5. 观测失败不影响业务返回，但必须输出脱敏的结构化告警。
"""
import hashlib
import asyncio
import logging
import math
from concurrent.futures import ThreadPoolExecutor
import json
import os
import time
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import select, update, func

from .db import build_engine, sessions
from .lim_models import LimModelCall, LimModelCatalog, LimModelProvider, LimRun, LimSpan
from .lim_governance import GovernanceError, get_store, policy

logger = logging.getLogger(__name__)

DEFAULT_ALIAS = 'default'
DEFAULT_PROVIDER_ID = 'env-default'
DEFAULT_TIMEOUT_MS = 40000

_engine = None
_session_factory = None


def _sessions():
    """惰性建连，避免 import 时就连数据库（与 bootstrap.py 的做法一致）。"""
    global _engine, _session_factory
    if _session_factory is None:
        _engine = build_engine()
        _session_factory = sessions(_engine)
    return _session_factory


def env_config():
    """回退配置：注册表为空时仍能用环境变量工作，保证向后兼容。"""
    base = os.getenv('PURCHASE_AGENT_LLM_BASE_URL', '').strip().rstrip('/')
    key = os.getenv('PURCHASE_AGENT_LLM_API_KEY', '').strip()
    model = os.getenv('PURCHASE_AGENT_LLM_MODEL', '').strip()
    return base, key, model


def _require_config(base, key, model):
    """保持与既有实现一致的错误码与抛出顺序。"""
    if not all([base, key, model]):
        raise RuntimeError('MODEL_NOT_CONFIGURED：请配置采购 Agent 模型地址、API Key 和模型名')
    parsed = urlparse(base)
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')):
        raise RuntimeError('MODEL_CONFIG_INVALID：模型地址需为 HTTPS 或本机 HTTP')
    return parsed


def resolve_candidates(db, alias=DEFAULT_ALIAS, scene='*'):
    """解析 (base_url, api_key, model, provider_id, timeout_ms)。

    优先精确匹配 scene，其次通配 '*'；仅默认别名从未注册时兼容环境变量配置。
    """
    rows = db.scalars(
        select(LimModelCatalog)
        .where(LimModelCatalog.alias == alias,
               LimModelCatalog.scene.in_([scene, '*']))
        .order_by(LimModelCatalog.priority, LimModelCatalog.alias_id)
    ).all()
    candidates = sorted(rows, key=lambda row: (row.scene != scene, row.priority, row.alias_id))
    routes = []
    for chosen in candidates:
        if not chosen.enabled:
            continue
        provider = db.scalar(
            select(LimModelProvider)
            .where(LimModelProvider.provider_id == chosen.provider_id,
                   LimModelProvider.enabled.is_(True),
                   LimModelProvider.status == 'ACTIVE')
        )
        if provider is not None:
            key = os.getenv(provider.api_key_env, '').strip()
            base = provider.base_url.rstrip('/')
            model = chosen.model_name
            # 注册表里的地址同样要过安全校验，防止配置被改成明文 HTTP 外发 key。
            route = (base, key, model, provider.provider_id, provider.timeout_ms or DEFAULT_TIMEOUT_MS)
            if route not in routes:
                routes.append(route)
    if routes:
        return routes
    # Explicit registry configuration is authoritative, including disabled routes.
    configured = db.scalar(select(LimModelCatalog.id).where(LimModelCatalog.alias == alias).limit(1))
    if configured is not None or alias != DEFAULT_ALIAS:
        raise RuntimeError('MODEL_ROUTE_UNAVAILABLE：当前别名和场景没有可用模型，请检查路由及供应商状态')
    base, key, model = env_config()
    _require_config(base, key, model)
    return [(base, key, model, DEFAULT_PROVIDER_ID, DEFAULT_TIMEOUT_MS)]


def resolve(db, alias=DEFAULT_ALIAS, scene='*'):
    route = resolve_candidates(db, alias, scene)[0]
    _require_config(*route[:3])
    return route


def ensure_default_provider(db):
    """注册表为空且环境变量已配置时补一条默认供应商/别名，保证网关开箱可用。"""
    if db.scalar(select(LimModelCatalog.id).where(LimModelCatalog.alias == DEFAULT_ALIAS).limit(1)):
        return
    base, key, model = env_config()
    if not all([base, key, model]):
        return
    exists = db.scalar(select(LimModelProvider).where(LimModelProvider.provider_id == DEFAULT_PROVIDER_ID))
    if exists:
        return
    parsed = urlparse(base)
    db.add(LimModelProvider(
        provider_id=DEFAULT_PROVIDER_ID,
        name=f'环境变量默认供应商（{parsed.hostname or base}）',
        protocol='openai_compatible', base_url=base,
        api_key_env='PURCHASE_AGENT_LLM_API_KEY',
        enabled=True, priority=100, timeout_ms=DEFAULT_TIMEOUT_MS, status='ACTIVE'))
    # 必须先落 provider：catalog 的外键指向 provider_id，
    # 同批 add 时 SQLAlchemy 识别不出依赖顺序，会先插 catalog 而违反外键。
    db.flush()
    db.add(LimModelCatalog(
        alias_id=str(uuid4()), alias=DEFAULT_ALIAS, provider_id=DEFAULT_PROVIDER_ID,
        model_name=model, scene='*', enabled=True, priority=100))
    db.commit()


def _build_payload(parsed, model, messages, tools):
    payload = {'model': model, 'messages': messages, 'max_tokens': 2048, 'stream': False}
    if tools:
        payload.update(tools=tools, tool_choice='auto')
    if os.getenv('PURCHASE_AGENT_LLM_DISABLE_THINKING', 'false').lower() == 'true':
        if parsed.hostname == 'api.deepseek.com':
            payload['thinking'] = {'type': 'disabled'}
        else:
            payload['enable_thinking'] = False
    return payload


def _extract_usage(data):
    """宽容读取 token 用量：不同供应商字段名不同（prompt_tokens / input_tokens …）。

    读不到就返回 None —— 绝不填 0 假装准确。
    """
    usage = (data or {}).get('usage') if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return None, None, None

    def _int(*names):
        for name in names:
            value = usage.get(name)
            if isinstance(value, bool):
                continue
            if isinstance(value, int) and value >= 0:
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
        return None

    prompt = _int('prompt_tokens', 'input_tokens', 'prompt_token_count')
    completion = _int('completion_tokens', 'output_tokens', 'completion_token_count')
    total = _int('total_tokens', 'total_token_count')
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    return prompt, completion, total


def _request_hash(model, messages, tools):
    raw = json.dumps({'model': model, 'messages': messages, 'tools': tools},
                     ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _error_code(message):
    return (message or '').split('：', 1)[0][:64] or 'MODEL_ERROR'


def _record(*, call_id, alias, provider_id, model, status, error_code=None, latency_ms=None,
            prompt_tokens=None, completion_tokens=None, total_tokens=None, cost=None,
            cache_hit=False, request_hash=None, run_id=None, span_id=None, actor_id=None,
            scene='*', attempts=None):
    try:
        with _sessions()() as db:
            db.add(LimModelCall(
                call_id=call_id, run_id=run_id, span_id=span_id, actor_id=actor_id,
                alias=alias, provider_id=provider_id, model=model or '', status=status,
                error_code=error_code, latency_ms=latency_ms,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                total_tokens=total_tokens, cost=cost, cache_hit=cache_hit,
                request_hash=request_hash, scene=scene, attempts=attempts or []))
            db.commit()
    except Exception:
        # 观测写入失败绝不能影响业务调用。
        logger.error('LIM_MODEL_AUDIT_WRITE_FAILED call_id=%s', call_id)


def _write_back(run_id, span_id, total_tokens):
    """把 token 用量累加回 LIM 的 span / run（这两处字段早已存在，此前无人写入）。"""
    if total_tokens is None or (not run_id and not span_id):
        return
    try:
        with _sessions()() as db:
            if span_id:
                db.execute(update(LimSpan).where(LimSpan.span_id == span_id).values(
                    token_usage=func.coalesce(LimSpan.token_usage, 0) + total_tokens))
            if run_id:
                db.execute(update(LimRun).where(LimRun.run_id == run_id).values(
                    token_usage=func.coalesce(LimRun.token_usage, 0) + total_tokens))
            db.commit()
    except Exception:
        logger.warning('LIM_MODEL_USAGE_WRITE_FAILED')


def _post_with_deadline(base, key, payload, seconds):
    """Cancel the whole HTTP exchange, not just an individual socket read."""
    async def run():
        async def request():
            async with httpx.AsyncClient(timeout=seconds, follow_redirects=False) as client:
                return await client.post(base + '/chat/completions',
                                         headers={'Authorization': 'Bearer ' + key}, json=payload)
        try:
            return await asyncio.wait_for(request(), timeout=seconds)
        except TimeoutError:
            raise httpx.ReadTimeout('model deadline exceeded') from None
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run())
    # Some legacy async handlers call this synchronous facade directly.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(run())).result()


def complete(messages, tools, timeout, *, alias=DEFAULT_ALIAS, scene='*',
             actor_id=None, run_id=None, span_id=None, return_metadata=False):
    """Bounded, governed model attempts behind the legacy synchronous contract."""
    call_id, started = str(uuid4()), time.monotonic()
    provider_id, model_name, request_hash = DEFAULT_PROVIDER_ID, '', None
    attempts, lease, store = [], None, None
    charged, prompt, completion_tokens, total = 0, None, None, None
    status, error = 'FAILED', None
    try:
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise RuntimeError('MODEL_TIMEOUT：调用时间预算无效')
        deadline = started + timeout
        limits, store = policy(), get_store()
        with _sessions()() as db:
            try:
                ensure_default_provider(db)
            except Exception:
                db.rollback()
            routes = resolve_candidates(db, alias, scene)
        # Reserve for every possible attempt. UTF-8 bytes plus framing is a
        # conservative estimate, not a provider-specific exact token counter.
        estimate = len(json.dumps({'messages': messages, 'tools': tools}, ensure_ascii=False).encode('utf-8')) + 256 + 2048
        lease = store.acquire(actor_id or '__system__', estimate * limits.max_attempts, timeout + 10, limits)
        tried = set()
        for number in range(limits.max_attempts):
            available = [route for route in routes if store.circuit_allowed(route[3] + ':' + route[2])]
            if not available:
                raise GovernanceError('MODEL_CIRCUIT_OPEN', '模型暂时熔断，请稍后重试', 503)
            route = next((candidate for candidate in available if candidate not in tried), available[-1])
            tried.add(route)
            base, key, model_name, provider_id, timeout_ms = route
            circuit_key = provider_id + ':' + model_name
            parsed = _require_config(base, key, model_name)
            payload = _build_payload(parsed, model_name, messages, tools)
            request_hash = _request_hash(model_name, messages, tools)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('MODEL_TIMEOUT：模型调用总时间预算已耗尽')
            effective = min(remaining, timeout_ms / 1000.0)
            attempt_started = time.monotonic()
            attempt = {'number': number + 1, 'provider_id': provider_id, 'model': model_name,
                       'status': 'FAILED', 'error_code': None, 'total_tokens': None}
            attempts.append(attempt)
            # Unknown/failed exchanges may still have been billed upstream.
            charged += estimate
            retryable, failure, http_status = False, None, None
            try:
                response = _post_with_deadline(base, key, payload, effective)
                http_status = response.status_code
                if http_status != 200:
                    retryable = http_status in (408, 429, 500, 502, 503, 504)
                    failure = RuntimeError(f'MODEL_HTTP_ERROR：模型服务返回 HTTP {http_status}，请检查配置、额度及模型权限')
                else:
                    data = response.json()
                    message = data['choices'][0]['message']
                    if not isinstance(message, dict):
                        raise ValueError()
                    if return_metadata and (not isinstance(message.get('content'), str) or not message['content'].strip()):
                        raise ValueError()
                    prompt, completion_tokens, total = _extract_usage(data)
                    if total is not None:
                        charged += total - estimate
                    attempt.update(status='SUCCEEDED', total_tokens=total)
            except httpx.TimeoutException:
                retryable, failure = True, RuntimeError('MODEL_TIMEOUT：模型调用超时，请稍后重试')
            except httpx.HTTPError:
                retryable, failure = True, RuntimeError('MODEL_CONNECTION_ERROR：模型服务无法连接')
            except (KeyError, IndexError, ValueError, TypeError):
                failure = RuntimeError('MODEL_RESPONSE_INVALID：模型返回格式无效')
            attempt.update(latency_ms=int((time.monotonic() - attempt_started) * 1000), http_status=http_status)
            if failure is None:
                status = 'SUCCEEDED'
                try:
                    store.circuit_success(circuit_key)
                except GovernanceError:
                    logger.warning('LIM_CIRCUIT_UPDATE_FAILED call_id=%s', call_id)
                result = {k: v for k, v in message.items() if k in ('role', 'content', 'tool_calls')}
                if return_metadata:
                    return {'reply': result.get('content') or '', 'call_id': call_id, 'alias': alias,
                            'scene': scene, 'provider_id': provider_id, 'model': model_name,
                            'latency_ms': int((time.monotonic() - started) * 1000),
                            'prompt_tokens': prompt, 'completion_tokens': completion_tokens,
                            'total_tokens': total, 'cost': None, 'cost_status': 'unavailable',
                            'attempt_count': len(attempts)}
                return result
            attempt['error_code'] = _error_code(str(failure))
            if retryable:
                store.circuit_failure(circuit_key, limits.circuit_threshold, limits.circuit_seconds)
            if not retryable or number + 1 >= limits.max_attempts:
                raise failure
            delay = .1 * (2 ** number)
            if deadline - time.monotonic() <= delay:
                raise RuntimeError('MODEL_TIMEOUT：模型调用总时间预算已耗尽')
            time.sleep(delay)
    except RuntimeError as exc:
        error = _error_code(str(exc))
        if isinstance(exc, GovernanceError) and not attempts:
            status = 'REJECTED'
        raise
    finally:
        if lease is not None:
            try:
                store.settle(lease, charged)
            except GovernanceError:
                # Retain reservation until UTC rollover; never refund unknown work.
                logger.error('LIM_QUOTA_SETTLEMENT_FAILED call_id=%s', call_id)
        _record(call_id=call_id, alias=alias, provider_id=provider_id, model=model_name,
                status=status, error_code=error, latency_ms=int((time.monotonic() - started) * 1000),
                prompt_tokens=prompt, completion_tokens=completion_tokens, total_tokens=total,
                request_hash=request_hash, run_id=run_id, span_id=span_id, actor_id=actor_id,
                scene=scene, attempts=attempts)
        if status == 'SUCCEEDED':
            _write_back(run_id, span_id, total)
