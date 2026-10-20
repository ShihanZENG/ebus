"""DataLab 数据仓库代理路由。"""
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import httpx

from .config import load_env
from .security import require

load_env()

router = APIRouter(prefix="/datalab", tags=["DataLab 数据看板"])

DATALAB_BASE = os.getenv("DATALAB_API_BASE_URL", "https://47.107.76.124/data-lab").rstrip("/")
DATALAB_KEY = os.getenv("DATALAB_API_KEY", "").strip()

# 跳过 SSL 验证（自签名证书）
verify_ssl = False


async def _datalab_get(path: str, params: Optional[dict] = None):
    if not DATALAB_KEY:
        raise HTTPException(503, "DataLab API 未配置，请在 backend/.env 中设置 DATALAB_API_KEY。")
    async with httpx.AsyncClient(verify=verify_ssl, timeout=30.0) as client:
        r = await client.get(
            f"{DATALAB_BASE}{path}",
            headers={"X-API-Key": DATALAB_KEY},
            params=params,
        )
        r.raise_for_status()
        return r.json()


@router.get("/overview")
async def overview(_=Depends(require("dashboard:read"))):
    """数据看板总览：销售日报 + 库存健康 + 待采购 + 补货审核。"""
    result = {}
    try:
        result["sales_daily"] = await _datalab_get("/warehouse/tables/ads_sales_daily", {"limit": 30})
    except Exception as e:
        result["sales_daily"] = {"error": str(e)}
    try:
        result["inventory_health"] = await _datalab_get("/warehouse/tables/ads_inventory_health", {"limit": 50})
    except Exception as e:
        result["inventory_health"] = {"error": str(e)}
    try:
        result["purchase_open"] = await _datalab_get("/warehouse/tables/ads_purchase_open", {"limit": 50})
    except Exception as e:
        result["purchase_open"] = {"error": str(e)}
    try:
        result["replenishment"] = await _datalab_get("/warehouse/tables/ads_replenishment_review", {"limit": 50})
    except Exception as e:
        result["replenishment"] = {"error": str(e)}
    try:
        result["data_quality"] = await _datalab_get("/warehouse/tables/ads_data_quality", {"limit": 20})
    except Exception as e:
        result["data_quality"] = {"error": str(e)}
    return result


@router.get("/table/{name}")
async def query_table(name: str, limit: int = Query(50, le=100), user=Depends(require("dashboard:read"))):
    """查询任意数据仓库表。"""
    if name == "dws_ads_campaign" and user.shop_scope is not None:
        raise HTTPException(
            403,
            "广告数据尚未与账号的店铺范围建立映射，暂不能读取；请管理员完成店铺映射后重试。",
        )
    return await _datalab_get(f"/warehouse/tables/{name}", {"limit": limit})


@router.get("/tables")
async def list_tables(_=Depends(require("dashboard:read"))):
    """列出所有数据仓库表。"""
    return await _datalab_get("/warehouse/tables")


@router.post("/knowledge/search")
async def knowledge_search(body: dict, _=Depends(require("dashboard:read"))):
    """行业知识检索。"""
    if not DATALAB_KEY:
        raise HTTPException(503, "DataLab API 未配置，请在 backend/.env 中设置 DATALAB_API_KEY。")
    async with httpx.AsyncClient(verify=verify_ssl, timeout=30.0) as client:
        r = await client.post(
            f"{DATALAB_BASE}/knowledge/search",
            headers={"X-API-Key": DATALAB_KEY, "Content-Type": "application/json"},
            json=body,
        )
        r.raise_for_status()
        return r.json()
