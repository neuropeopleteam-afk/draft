#!/usr/bin/env python3
"""docs/perf/load.json из CSV Locust (run_load.py run … --tag <tag> → <tag>_stats.csv, <tag>_meta.json).

  python3 tools/perf/load_json.py --dir <LT_OUT> --tags pod_20,pod_50,pod_100 --cond "<условия>" --out docs/perf/load.json

Числа берутся из CSV как есть (p50/p95/p99 — перцентили Locust по операции; «Всего» — строка Aggregated).
Ничего не округляется сверх Locust и не подбирается: какие прогоны в --tags, такие и в файле.
"""
import argparse, csv, json, os
from pathlib import Path

# Сценарии задания А12 (P1) → операции Locust из tools/loadtest/jury_load.py
SCENARIOS = {
    "формирование подборки": ["потребность: создать + подборка v1", "подборка: версия", "подборка: сравнение 2–3"],
    "открытие профиля": ["подборка: карточка кандидата"],
    "поиск": ["поиск по базе"],
    "вход": ["вход жюри (песочница)"],
}


def row(r: dict) -> dict:
    n, f = int(r["Request Count"]), int(r["Failure Count"])
    num = lambda k: (None if r.get(k) in (None, "", "N/A") else float(r[k]))
    return {"requests": n, "failures": f, "error_rate": round(f / n, 4) if n else None,
            "p50_ms": num("50%"), "p95_ms": num("95%"), "p99_ms": num("99%"), "max_ms": num("Max Response Time"),
            "rps": round(float(r["Requests/s"]), 3)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True); ap.add_argument("--tags", required=True)
    ap.add_argument("--cond", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--recompute", default="")
    a = ap.parse_args()
    d = Path(a.dir); runs = []
    for tag in a.tags.split(","):
        rows = {r["Name"]: r for r in csv.DictReader(open(d / f"{tag}_stats.csv", encoding="utf-8"))}
        meta = json.load(open(d / f"{tag}_meta.json", encoding="utf-8")) if (d / f"{tag}_meta.json").exists() else {}
        runs.append({
            "tag": tag, "users": meta.get("users"), "users_max": meta.get("users_max"), "ramp_per_s": meta.get("ramp_per_s"),
            "duration": meta.get("time"), "start": meta.get("start"), "end": meta.get("end"),
            "total": row(rows["Aggregated"]),
            "scenarios": {s: {op: row(rows[op]) for op in ops if op in rows} for s, ops in SCENARIOS.items()},
        })
    out = {"what": "нагрузка по сценариям жюри (Locust, tools/loadtest/jury_load.py)", "cond": a.cond,
           "recompute": a.recompute, "runs": runs}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for r in runs:
        t = r["total"]; print(f'{r["tag"]}: {t["requests"]} запр., ошибок {t["failures"]} ({t["error_rate"]}), p50 {t["p50_ms"]} p95 {t["p95_ms"]}')


if __name__ == "__main__":
    main()
