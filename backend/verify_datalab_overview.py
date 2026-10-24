"""End-to-end check: login as admin, hit running /api/v1/datalab/overview.

Reads creds from .env (never CLI). Base URL defaults to the local 18080.
Proves the configured DATALAB_API_KEY (loaded by the running backend at
import via config.load_env) actually pulls live upstream data.
"""
import asyncio
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = os.getenv("DATALAB_LOCAL_BASE", "http://127.0.0.1:18080").rstrip("/")


def load_dotenv(path):
    d = {}
    for line in open(path, encoding="utf-8").read().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        d[k.strip()] = v.strip()
    return d


async def main():
    env = load_dotenv(os.path.join(ROOT, ".env"))
    import httpx
    async with httpx.AsyncClient(base_url=BASE, verify=False, trust_env=False, timeout=30.0) as c:
        # login (read creds from .env)
        r = await c.post("/api/v1/auth/login", json={
            "username": env.get("ERP_ADMIN_USERNAME", "admin"),
            "password": env.get("ERP_ADMIN_PASSWORD", ""),
        })
        print(f"login status={r.status_code}")
        if r.status_code != 200:
            print("  login body:", r.text[:200])
            return
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # 503 expected if key missing in running process; 200 if wired
        r = await c.get("/api/v1/datalab/overview", headers=h)
        print(f"overview status={r.status_code}")
        try:
            j = r.json()
        except Exception:
            print("  non-json body:", r.text[:300])
            return
        if r.status_code != 200:
            print("  error body:", str(j)[:400])
            return
        for k, v in j.items():
            if isinstance(v, dict):
                meta = v.get("data_meta", {})
                print(f"  {k}: status={meta.get('data_status')} records={meta.get('record_count')} source={meta.get('source')}/{meta.get('source_mode')} err={v.get('error')}")
                rows = v.get("rows") if isinstance(v.get("rows"), list) else None
                if rows:
                    print(f"     sample: {rows[0]}")
            else:
                print(f"  {k}: {type(v).__name__}")


if __name__ == "__main__":
    asyncio.run(main())
