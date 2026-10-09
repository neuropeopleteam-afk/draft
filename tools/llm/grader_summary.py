"""Сводка прогона оценщика на наборе grader_check (406 ответов, промпт v2) для docs/llm/*.json.

Каталог прогона — как у `python -m app.modules.validation.grader_check report`: v2_1.jsonl / v2_1_out.jsonl (первая
оценка), v2_2.jsonl / v2_2_out.jsonl (вторая). В отличие от report, файл продукта
backend/app/modules/validation/data/grader_check.json не перезаписывается: полный отчёт — в <dir>/report.json,
строки — в <dir>/rows.json, компактная сводка — в --out.

  cd backend && ../../.venv/bin/python ../tools/llm/grader_summary.py --dir /tmp/g --out ../docs/llm/grader_check_qwen.json \
      --first "qwen/qwen3.5-9b (OpenRouter, bf16)" --second "та же модель" --how "..."
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

KEEP = ("v2_quote", "v2")  # промпт v2 + проверка цитат; полный конвейер (фильтр, цитаты, вторая оценка)


def _lat(path: Path) -> dict | None:
    xs = []
    if path.exists():
        for line in open(path, encoding="utf-8"):
            o = json.loads(line)
            if not o.get("error") and o.get("latency") is not None:
                xs.append(float(o["latency"]))
    if not xs:
        return None
    xs.sort()
    return {"median": round(statistics.median(xs), 2), "p90": round(xs[int(0.9 * (len(xs) - 1))], 2), "n": len(xs)}


def summarize(d: str, first: str, second: str, how: str, caveat: str) -> dict:
    from app.modules.assessment import grader as G
    from app.modules.validation import grader_check as GC

    base = Path(d)
    GC.OUT = base / "report.json"  # не трогать data/grader_check.json продукта
    rep = GC.report(d, write=True)
    rows = json.loads((base / "rows.json").read_text(encoding="utf-8"))
    sec = [r for r in rows if r.get("v2_doubts")]
    got = [r for r in sec if r.get("v2_second") is not None and r.get("v2_quote") is not None]
    deltas = [abs(r["v2_quote"] - r["v2_second"]) for r in got]
    doubts: dict[str, int] = {}
    for r in sec:
        for x in r["v2_doubts"]:
            doubts[x] = doubts.get(x, 0) + 1
    first_calls = sum(1 for r in rows if r.get("v2_quote") is not None)
    return {
        "dataset": rep["dataset"],
        "prompt_version": rep["prompt_version"],
        "disagree": rep["disagree"],
        "models": {"first": first, "second": second, "panel": "yandexgpt/latest (старый промпт, панель 06.10)",
                   "reference": rep["reference"]},
        "latency_s": {"first": _lat(base / "v2_1_out.jsonl"), "second": _lat(base / "v2_2_out.jsonl")},
        "tokens": {k: v for k, v in rep["tokens"].items() if v["calls"]},
        "routes_v2": rep["routes_v2"],
        "conditions": {k: v for k, v in rep["conditions"].items() if k in KEEP},
        "second_opinion": {"second_calls": len(sec), "agree": sum(1 for x in deltas if x <= G.DISAGREE + 1e-9),
                           "disagree": sum(1 for x in deltas if x > G.DISAGREE + 1e-9), "failed": len(sec) - len(got),
                           "doubts": doubts, "share_of_first_calls": round(len(sec) / max(1, first_calls), 3),
                           "mean_abs_delta": round(statistics.mean(deltas), 3) if deltas else None},
        "worst_attacks_v2": rep["worst_attacks_v2"],
        "filter_false_positives": rep["filter_false_positives"],
        "attack_filter_caught": rep["attack_filter_caught"],
        "how": how,
        "caveat": caveat,
        "date": time.strftime("%Y-%m-%d"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--first", required=True, help="подпись модели первой оценки")
    ap.add_argument("--second", required=True, help="подпись модели второй оценки")
    ap.add_argument("--how", default="")
    ap.add_argument("--caveat", default="Эталон сравнения — gpt-oss-120b (модель, не эксперты).")
    a = ap.parse_args()
    out = summarize(a.dir, a.first, a.second, a.how, a.caveat)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    c = out["conditions"].get("v2", {})
    print(f"→ {a.out}: A {c.get('vs_gptoss_A')}, B {c.get('vs_gptoss_B')}, атаки {c.get('attacks')}, "
          f"порядок {c.get('ordering')}, вторая оценка {out['second_opinion']}")


if __name__ == "__main__":
    main()
