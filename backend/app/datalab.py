"""DataLab 数据仓库代理路由。

可靠性设计（对应"数据源经常断"的根因）：
1. trust_env=False —— 本机环境里挂着随会话变端口的本地代理
   (HTTP_PROXY=http://127.0.0.1:xxxxx)。若不关掉，httpx 会把对外部数仓的请求
   路由到那个代理；代理一挂或端口一变，数仓调用立刻失败。关掉后直连公网 IP，
   实测稳定返回 200。
2. 连接/读取分离超时 + 指数退避重试 —— 外部数仓偶发 4~6s 延迟或瞬时 5xx，重试可吃掉。
3. 进程内 TTL 缓存兜底 —— 上游真挂时，把最后一次成功结果标 stale 继续返回，
   面板不会整片空白；data_meta 里如实带 served_from_cache / stale / upstream_error。
"""
import os
import time
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
import httpx

from .config import load_env
from .security import require

load_env()

router = APIRouter(prefix="/datalab", tags=["DataLab 数据看板"])

DATALAB_BASE = os.getenv("DATALAB_API_BASE_URL", "https://47.107.76.124/data-lab").rstrip("/")
DATALAB_KEY = os.getenv("DATALAB_API_KEY", "").strip()

# 跳过 SSL 验证（自签名证书）。TODO: 改为 DATALAB_CA_BUNDLE 指定 CA，消除 MITM 风险。
verify_ssl = False

# 进程内缓存：TTL 内命中直接返回；TTL 外但上游失败则降级返回旧值并标 stale。
CACHE_TTL = float(os.getenv("DATALAB_CACHE_TTL", "60"))
_cache: dict = {}

# httpx 超时：连接 10s、读取 30s。连接阶段失败（代理/DNS）与读取超时分开处理。
_TIMEOUT = httpx.Timeout(10.0, read=30.0)
# 直连外部数仓，绝不经本机代理。
_CLIENT_KW = dict(verify=verify_ssl, trust_env=False, timeout=_TIMEOUT)
_MAX_RETRIES = 3


def _data_meta(rows, *, queried_at=None, status=None, stale=False,
               served_from_cache=False, upstream_error=None):
    now = queried_at or datetime.now(timezone.utc)
    if status is None:
        status = 'available' if isinstance(rows, list) and rows else 'missing'
        if stale:
            status = 'stale'
    return {
        'source': 'datalab',
        'source_mode': 'warehouse_snapshot',
        'data_status': status,
        'record_count': len(rows) if isinstance(rows, list) else 0,
        'upstream_updated_at': None,
        'upstream_freshness': 'not_provided',
        'queried_at': now.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'sample_status': 'unclassified',
        'served_from_cache': served_from_cache,
        'stale': stale,
        'upstream_error': upstream_error,
    }


def _decorate_table(payload, *, stale=False, served_from_cache=False, upstream_error=None):
    if isinstance(payload, dict):
        result = dict(payload)
    elif isinstance(payload, list):
        result = {'rows': payload}
    else:
        result = {'rows': []}
    result['data_meta'] = _data_meta(
        result.get('rows'),
        stale=stale,
        served_from_cache=served_from_cache,
        upstream_error=upstream_error,
    )
    return result


def _cache_get(key):
    item = _cache.get(key)
    if item is None:
        return None
    ts, payload = item
    return payload, (time.time() - ts) < CACHE_TTL


def _cache_put(key, payload):
    _cache[key] = (time.time(), payload)


async def _request_json(method: str, path: str, *,
                        params: Optional[dict] = None,
                        json: Optional[dict] = None):
    """带指数退避重试的 JSON 请求。trust_env=False 绕过本机代理。"""
    headers = {"X-API-Key": DATALAB_KEY}
    if json is not None:
        headers["Content-Type"] = "application/json"
    last_exc = None
    async with httpx.AsyncClient(**_CLIENT_KW) as client:
        for attempt in range(_MAX_RETRIES):
            try:
                r = await client.request(
                    method, f"{DATALAB_BASE}{path}",
                    headers=headers, params=params, json=json,
                )
                r.raise_for_status()
                return r.json()
            except Exception as exc:  # noqa: BLE001 - 任何异常都重试
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
    raise last_exc


async def _safe_source(cache_key: str, path: str, limit: int):
    """取数：未过期缓存直接命中；过期/未缓存则实时请求，失败才降级旧值（stale）。"""
    cached = _cache_get(cache_key)  # (payload, fresh) 或 None
    if cached is not None and cached[1]:  # 缓存未过期：直接命中，不实时请求
        return _decorate_table(cached[0], stale=False, served_from_cache=True)
    try:
        data = await _request_json('GET', path, params={'limit': limit})
        _cache_put(cache_key, data)
        return _decorate_table(data)
    except Exception as exc:
        if cached is not None:  # 实时失败：降级返回旧值并标 stale
            return _decorate_table(
                cached[0], stale=True, served_from_cache=True,
                upstream_error=str(exc),
            )
        return {
            'error': str(exc),
            'data_meta': _data_meta([], status='unavailable', upstream_error=str(exc)),
        }


@router.get("/overview")
async def overview(_=Depends(require("dashboard:read"))):
    """数据看板总览：销售日报 + 库存健康 + 待采购 + 补货审核。"""
    sources = {
        'sales_daily': ('/warehouse/tables/ads_sales_daily', 30),
        'inventory_health': ('/warehouse/tables/ads_inventory_health', 50),
        'purchase_open': ('/warehouse/tables/ads_purchase_open', 50),
        'replenishment': ('/warehouse/tables/ads_replenishment_review', 50),
        'data_quality': ('/warehouse/tables/ads_data_quality', 20),
    }
    result = {}
    for key, (path, limit) in sources.items():
        result[key] = await _safe_source(f"overview:{key}", path, limit)
    return result


@router.get("/table/{name}")
async def query_table(name: str, limit: int = Query(50, le=100), user=Depends(require("dashboard:read"))):
    """查询任意数据仓库表。"""
    if name == "dws_ads_campaign" and user.shop_scope is not None:
        raise HTTPException(
            403,
            "广告数据尚未与账号的店铺范围建立映射，暂不能读取；请管理员完成店铺映射后重试。",
        )
    return await _safe_source(f"table:{name}", f"/warehouse/tables/{name}", limit)


@router.get("/tables")
async def list_tables(_=Depends(require("dashboard:read"))):
    """列出所有数据仓库表。"""
    return await _safe_source("tables", "/warehouse/tables", 100)


@router.post("/knowledge/search")
async def knowledge_search(body: dict, _=Depends(require("dashboard:read"))):
    """行业知识检索。"""
    if not DATALAB_KEY:
        raise HTTPException(503, "DataLab API 未配置，请在 backend/.env 中设置 DATALAB_API_KEY。")
    try:
        return await _request_json('POST', "/knowledge/search", json=body)
    except Exception as exc:
        raise HTTPException(502, f"DataLab 知识检索失败：{exc}")
