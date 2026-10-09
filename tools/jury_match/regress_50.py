"""Регрессия 50 вакансий И8 (docs/realdata): метрики текущих правил против сохранённых в parser_benchmark.json.

Ничего не перезаписывает. Запуск: python tools/jury_match/regress_50.py [OUT.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools/realdata"))

from benchmark import measure  # noqa: E402
from app.modules.matching.need_parser import parse_need  # noqa: E402

OUT = ROOT / "docs/realdata"


def main(out: str | None) -> int:
    rows = json.loads((OUT / "vacancies_50.json").read_text())["vacancies"]
    # База сравнения — правила ветки до правок И18 (docs/jury_match/regress_50_before.json); в parser_benchmark.json
    # грейд «Стажёр» (И13) ещё не учитывался, поэтому «грейд» там 39/39, а measure() без поправки на intern даёт 34/39.
    base = ROOT / "docs/jury_match/regress_50_before.json"
    saved = json.loads(base.read_text())["now"] if base.exists() else \
        json.loads((OUT / "parser_benchmark.json").read_text())["current_rules"]
    snap = json.loads((OUT / "rules_predictions.json").read_text())
    preds = [parse_need(r["text"], use_llm=False) for r in rows]
    now = measure(rows, preds)
    changed = []
    for r, p, s in zip(rows, preds, snap):
        a = ([i["tag"] for i in p["stack_required"]], [i["tag"] for i in p["stack_desired"]])
        b = ([i["tag"] for i in s["stack_required"]], [i["tag"] for i in s["stack_desired"]])
        if a != b:
            changed.append({"id": r["id"], "before": b, "after": a, "expected": sorted(r["expected_stack"])})
    res = {"saved": {k: v for k, v in saved.items() if k != "mismatches"},
           "now": {k: v for k, v in now.items() if k != "mismatches"}, "stack_changed": changed}
    worse = [f for f in now["fields"] if now["fields"][f]["correct"] < saved["fields"][f]["correct"]]
    for k in ("stack_micro_precision", "stack_micro_recall"):
        if now[k] < saved[k]:
            worse.append(k)
    if now["invalid_quotes"]:
        worse.append("invalid_quotes")
    res["worse"] = worse
    print(json.dumps({k: res[k] for k in ("worse",)}, ensure_ascii=False))
    for k in ("stack_micro_precision", "stack_micro_recall", "stack_tp_fp_fn", "invalid_quotes", "quotes"):
        print(k, saved[k], "→", now[k])
    for f in now["fields"]:
        print(f, saved["fields"][f]["correct"], "→", now["fields"][f]["correct"], "/", now["fields"][f]["n"])
    for c in changed:
        print("stack changed", c)
    if out:
        Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return 1 if worse else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
