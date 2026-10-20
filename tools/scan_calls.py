import re, os, json

ROOT = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'src')
res = {}
pat = re.compile(r"request\s*(?:<[^>]*>)?\(\s*['`]([^'`]+)['`]")
for dp, dn, fn in os.walk(ROOT):
    for f in fn:
        if not f.endswith(('.ts', '.tsx')):
            continue
        p = os.path.join(dp, f)
        s = open(p, encoding='utf-8').read()
        for m in pat.finditer(s):
            line = s[:m.start()].count('\n') + 1
            key = m.group(1)
            res.setdefault(key, []).append(os.path.relpath(p, ROOT).replace('\\', '/') + ':' + str(line))

out = []
for k in sorted(res):
    out.append({'path': k, 'refs': sorted(set(res[k]))[:5]})
json.dump(out, open(os.path.join(os.path.dirname(__file__), '_frontend_calls.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for o in out:
    print(o['path'], '||', ', '.join(o['refs']))
print('TOTAL', len(out))
