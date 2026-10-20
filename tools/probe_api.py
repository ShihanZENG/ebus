"""带 token 探测后端接口：打印状态码 + 返回条数 + 顶层字段名。"""
import json, sys, urllib.request, urllib.parse, urllib.error

BASE = "http://127.0.0.1:18080"
TOKEN = None


def call(method, path, body=None, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if TOKEN:
        req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:
        return -1, str(e)


def summarize(v):
    if isinstance(v, list):
        return f"list[{len(v)}]", (list(v[0].keys()) if v and isinstance(v[0], dict) else None)
    if isinstance(v, dict):
        keys = list(v.keys())
        if "items" in v and isinstance(v["items"], list):
            return f"items[{len(v['items'])}]/total={v.get('total')}", (list(v['items'][0].keys()) if v["items"] else None)
        return f"dict{keys}", None
    return f"{type(v).__name__}={str(v)[:60]}", None


def probe(method, path, body=None, params=None, note=""):
    st, data = call(method, path, body, params)
    if st >= 400 or st < 0:
        print(f"  !! {method} {path} -> {st} :: {json.dumps(data, ensure_ascii=False)[:260]}")
        return st, data
    s, keys = summarize(data)
    print(f"  OK {method} {path} [{note}] -> {st} {s} keys={keys}")
    return st, data


def login():
    global TOKEN
    st, d = call("POST", "/api/v1/auth/login", {"username": "admin", "password": "Admin@2026"})
    if st != 200:
        print("LOGIN FAIL", st, d)
        sys.exit(1)
    TOKEN = d.get("access_token") or d.get("token")
    print("login ok")


if __name__ == "__main__":
    login()
    mode = sys.argv[1] if len(sys.argv) > 1 else "lists"
    if mode == "lists":
        for p in [
            "/api/v1/products", "/api/v1/skus", "/api/v1/listings", "/api/v1/orders",
            "/api/v1/inventory", "/api/v1/inventory/transactions",
            "/api/v1/inbound-orders", "/api/v1/shipments",
            "/api/v1/fba-plans", "/api/v1/purchase-orders", "/api/v1/purchase-plans",
            "/api/v1/purchase-amendments", "/api/v1/supplier-quotes", "/api/v1/supply-infos",
            "/api/v1/shops", "/api/v1/warehouses", "/api/v1/suppliers", "/api/v1/dictionaries",
            "/api/v1/users", "/api/v1/audit-logs", "/api/v1/customer-tickets", "/api/v1/after-sales",
            "/api/v1/replenishment-suggestions", "/api/v1/agent-generations/operations",
            "/api/v1/generation-reviews", "/api/v1/purchase-agent/supply-drafts",
            "/api/v1/purchase-agent/drafts", "/api/v1/purchase-agent/profiles",
            "/api/v1/purchase-agent/runs", "/api/v1/purchase-agent/lookups",
            "/api/v1/purchase-agent/runtime", "/api/v1/agent-generations/rules",
            "/api/v1/channels", "/api/v1/channels/authorizations",
        ]:
            probe("GET", p, params={"page": 1, "page_size": 5})
    elif mode == "inv":
        st, w = call("GET", "/api/v1/warehouses", None, {"page": 1, "page_size": 100})
        st, s = call("GET", "/api/v1/skus", None, {"page": 1, "page_size": 100})
        whs = w["items"]
        skus = s["items"]
        print("warehouses", [(x["id"], x["name"], x.get("warehouse_type")) for x in whs][:12])
        print("skus", [(x["id"], x.get("code"), x.get("name")) for x in skus][:12])
        dom = next((x for x in whs if x.get("warehouse_type") == "domestic"), None)
        ovs = next((x for x in whs if x.get("warehouse_type") == "overseas"), None)
        for w0 in whs[:3]:
            for s0 in skus[:2]:
                params = {"warehouse_id": w0["id"], "sku_id": s0["id"]}
                probe("GET", "/api/v1/inventory/allocation-overview", params=params, note=f"{w0['name']}/{s0.get('code')}")
                probe("GET", "/api/v1/inventory/demand-summary", params=params, note=f"{w0['name']}/{s0.get('code')}")
                probe("GET", "/api/v1/inventory/dated-supply-demand", params={**params, "business_date": "2026-10-15", "days": 21})
        if dom and ovs and skus:
            probe("GET", "/api/v1/inventory/route-demand", params={
                "domestic_warehouse_id": dom["id"], "overseas_warehouse_id": ovs["id"], "sku_id": skus[0]["id"]})
    elif mode == "datalab":
        for t in ["dws_ads_campaign", "dws_finance_day", "dws_sales_store_day", "dwd_inventory",
                  "dwd_fba_delivery_orders", "dwd_fba_receipts", "dwd_fba_local_shipments",
                  "dwd_listing_fba_dimensions"]:
            probe("GET", "/api/v1/datalab/table/" + t, params={"limit": 3})
