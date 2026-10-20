import json, urllib.request, sys

BASE = "http://127.0.0.1:18080"

def get(path):
    req = urllib.request.Request(BASE + path)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

spec = get("/openapi.json")
out = []
for p, ops in sorted(spec.get("paths", {}).items()):
    for m, op in ops.items():
        if m.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            continue
        params = op.get("parameters", [])
        reqs = []
        for pr in params:
            if pr.get("required"):
                reqs.append(f"{pr.get('name')}:{pr.get('in')}")
        out.append({
            "method": m.upper(),
            "path": p,
            "summary": (op.get("summary") or "")[:80],
            "required": reqs,
            "tags": op.get("tags", []),
        })
with open(sys.argv[1], "w", encoding="utf-8") as f:
    for o in out:
        f.write(f"{o['method']} {o['path']}  tags={o['tags']}  req={o['required']}  # {o['summary']}\n")
print("total", len(out))
