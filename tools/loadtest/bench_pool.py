"""Локальный замер до/после (10.10): N потоков, каждый по кругу: отчёт /validation, статус теста, приглашения.
Печатает по операциям: запросов, коды, p50/p95/max (с). Использование: bench_pool.py <base> <threads> <seconds> <label>"""
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

base, n, dur, label = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), sys.argv[4]


def call(method, path, tok=None, body=None, timeout=90):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"content-type": "application/json",
                                          **({"Authorization": "Bearer " + tok} if tok else {})})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            return r.status, time.time() - t0, r.headers.get("Retry-After")
    except urllib.error.HTTPError as e:
        e.read()
        return e.code, time.time() - t0, e.headers.get("Retry-After")
    except Exception:  # noqa: BLE001
        return 0, time.time() - t0, None


tok = json.loads(urllib.request.urlopen(urllib.request.Request(
    base + "/api/jury/login", data=b'{"persona":"candidate"}', headers={"content-type": "application/json"}),
    timeout=120).read())["access_token"]
ops = [("отчёт /validation", "/api/validation/report"), ("статус теста", "/api/assessment/status"),
       ("приглашения кандидата", "/api/candidate/invitations")]
res = {name: [] for name, _ in ops}
lock = threading.Lock()
stop = time.time() + dur


def worker(k):
    i = k
    while time.time() < stop:
        name, path = ops[i % len(ops)]
        i += 1
        code, sec, ra = call("GET", path, tok)
        with lock:
            res[name].append((code, sec, ra))


ts = [threading.Thread(target=worker, args=(k,)) for k in range(n)]
t0 = time.time()
for t in ts:
    t.start()
for t in ts:
    t.join()
out = {"label": label, "threads": n, "seconds": round(time.time() - t0, 1), "ops": {}}
for name, rows in res.items():
    lat = sorted(s for _, s, _ in rows)
    codes = {}
    for c, _, _ in rows:
        codes[str(c)] = codes.get(str(c), 0) + 1
    out["ops"][name] = {"n": len(rows), "codes": codes, "p50": round(statistics.median(lat), 2) if lat else None,
                        "p95": round(lat[int(0.95 * (len(lat) - 1))], 2) if lat else None,
                        "max": round(lat[-1], 2) if lat else None,
                        "retry_after": sorted({ra for c, _, ra in rows if ra})}
allr = [r for rows in res.values() for r in rows]
out["total"] = {"n": len(allr), "rps": round(len(allr) / out["seconds"], 1),
                "errors_5xx": sum(1 for c, _, _ in allr if c >= 500 or c == 0)}
print(json.dumps(out, ensure_ascii=False, indent=1))
