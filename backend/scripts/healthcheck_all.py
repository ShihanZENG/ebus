"""一次性系统体检：登录 + 批量 GET 所有列表接口，统计状态码与条数。

用法（必须关闭沙箱，否则连不上本机端口）：
  C:/Users/77948/anaconda3/python.exe backend/scripts/healthcheck_all.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("ERP_BASE", "http://127.0.0.1:18080")
USER = os.environ.get("ERP_USER", "admin")
PASSWORD = os.environ.get("ERP_PASSWORD", "Admin@2026")

# 需要从 openapi.json 里挑出来的 GET 集合接口（不含 {id} 详情）
LIST_PATHS = [
    "/api/v1/after-sales",
    "/api/v1/audit-logs",
    "/api/v1/channels/connections",
    "/api/v1/channels/orders",
    "/api/v1/channels/sync-jobs",
    "/api/v1/customer-tickets",
    "/api/v1/datalab/overview",
    "/api/v1/datalab/tables",
    "/api/v1/dictionaries",
    "/api/v1/fba-plans",
    "/api/v1/generation-reviews",
    "/api/v1/inbound-orders",
    "/api/v1/inventory",
    "/api/v1/inventory/allocation-overview",
    "/api/v1/inventory/dated-supply-demand",
    "/api/v1/inventory/demand-summary",
    "/api/v1/inventory/route-demand",
    "/api/v1/inventory/transactions",
    "/api/v1/listings",
    "/api/v1/orders",
    "/api/v1/permissions",
    "/api/v1/products",
    "/api/v1/purchase-agent/chats",
    "/api/v1/purchase-agent/drafts",
    "/api/v1/purchase-agent/profiles",
    "/api/v1/purchase-agent/runs",
    "/api/v1/purchase-agent/runtime",
    "/api/v1/purchase-agent/supply-drafts",
    "/api/v1/purchase-amendments",
    "/api/v1/purchase-orders",
    "/api/v1/purchase-plans",
    "/api/v1/replenishment-suggestions",
    "/api/v1/roles",
    "/api/v1/shipments",
    "/api/v1/shops",
    "/api/v1/skus",
    "/api/v1/supplier-quotes",
    "/api/v1/suppliers",
    "/api/v1/supply-infos",
    "/api/v1/users",
    "/api/v1/warehouses",
]


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


def count_of(payload: str) -> str:
    try:
        obj = json.loads(payload)
    except Exception:  # noqa: BLE001
        return "n/a"
    if isinstance(obj, dict):
        if "items" in obj:
            return f"items={len(obj['items'])} total={obj.get('total', '?')}"
        if "total" in obj:
            return f"total={obj['total']}"
        return f"keys={len(obj)}"
    if isinstance(obj, list):
        return f"list={len(obj)}"
    return "n/a"


def main() -> int:
    status, raw = call("POST", "/api/v1/auth/login", body={"username": USER, "password": PASSWORD})
    if status != 200:
        print(f"LOGIN FAILED status={status} body={raw[:400]}")
        return 1
    token = json.loads(raw).get("access_token") or json.loads(raw).get("token")
    if not token:
        print(f"LOGIN OK but no token: {raw[:400]}")
        return 1
    print("login ok\n")

    bad: list[tuple[str, int, str]] = []
    empty: list[str] = []
    for path in LIST_PATHS:
        st, payload = call("GET", path, token=token)
        cnt = count_of(payload)
        mark = "OK  "
        if st != 200:
            mark = "FAIL"
            bad.append((path, st, payload[:300]))
        elif cnt.startswith("items=0") or cnt == "list=0" or cnt == "total=0":
            mark = "EMPTY"
            empty.append(path)
        print(f"{mark} {st:>4} {path:<48} {cnt}")
        sys.stdout.flush()

    print("\n===== 非 200 接口 =====")
    for path, st, body in bad:
        print(f"{st} {path}\n    {body}\n")
    print("===== 空数据接口 =====")
    for path in empty:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
