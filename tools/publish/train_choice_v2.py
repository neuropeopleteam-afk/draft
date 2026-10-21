#!/usr/bin/env python3
"""Выбор «правила решения v2» на TRAIN по docs/validation/RULE_V2_2110.md (записано до запуска сетки) — без ручного выбора.

Метрики — независимым скриптом А15 (tools/publish/a15_recompute.py, точка stage2), время — по строкам (min_main + min_refine).
    python3 tools/publish/train_choice_v2.py <каталог шардов S_*/T_*> --out docs/validation/TRAIN_CHOICE_2110d.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
FC_MAX, P90_MAX, TIE = 0.025, 75.0, 0.5
# строка: (ключ, лучший известный соперник, больше-лучше) — таблица RULE_V2_2110.md
REF = [("exact_5", 0.745, True), ("exact_4", 0.81, True), ("within_one_4", 0.998, True),
       ("decision_kappa", 0.49, True), ("decision_agreement", 0.86, True), ("grade_kappa_w_6", 0.85, True),
       ("kappa_w_truth_4", 0.90, True), ("grade_agreement_6", 0.75, True), ("grade_agreement_5", 0.714, True),
       ("adaptive_minus_fixed_4", 0.10, True), ("exact_4_far_all_cuts_0.25", 0.90, True),
       ("above_true_5", 0.033, False), ("verdict_accuracy_far_0.3", 0.91, True)]


def _a15():
    spec = importlib.util.spec_from_file_location("a15_recompute", HERE / "a15_recompute.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _v(x):
    return x.get("value") if isinstance(x, dict) else x


def metrics(files: list[Path], a15) -> dict:
    rows, pairs = a15.load([str(f) for f in files])
    st = a15.point_metrics(rows, "grade_stage2", "verdict_stage2")
    rt = a15.retest(pairs) if pairs else {}
    av = a15.adaptive_vs_fixed(rows) or {}
    mins = sorted(float(r.get("min_main") or 0) + float(r.get("min_refine") or 0) for r in rows)
    p90 = mins[min(len(mins) - 1, int(math.ceil(0.9 * len(mins))) - 1)] if mins else None
    err = 0
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            err += int(((d.get("summary") or {}).get("engine_errors")) or d.get("engine_errors") or 0)
        except Exception:  # noqa: BLE001
            pass
    fc = st["false_confirm_all"]
    out = {"n": st["n"], "fc_k": fc["k"], "fc": fc["value"], "p90_min": p90, "mean_min": sum(mins) / len(mins) if mins else None,
           "engine_errors": err, "confident_accuracy": _v(st["confident_accuracy"]), "confident_share": _v(st["confident_share"])}
    for k, _, _ in REF:
        if k in st:
            out[k] = _v(st[k])
        elif k in rt:
            out[k] = _v(rt[k])
    out["adaptive_minus_fixed_4"] = (av.get("exact_4") or {}).get("diff")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    d = Path(a.dir)
    a15 = _a15()
    names = sorted({p.name.split("__")[0][2:] for p in d.glob("S_*__*.json")}, key=lambda s: int(s[1:]))
    table = {}
    for v in names:
        S = metrics(sorted(d.glob(f"S_{v}__*.json")), a15)
        T = metrics(sorted(d.glob(f"T_{v}__*.json")), a15)
        margins = {}
        for k, r, hi in REF:
            x = S.get(k)
            if x is None:
                continue
            margins[k] = round(100 * ((x - r) if hi else (r - x)), 2)
        score = min(margins.values()) if margins else None
        ok = all(w["fc_k"] <= FC_MAX * w["n"] and (w["p90_min"] or 1e9) <= P90_MAX and w["engine_errors"] == 0 for w in (S, T))
        table[v] = {"S": S, "T": T, "margins_pp": margins, "score_pp": score, "worst_row": min(margins, key=margins.get) if margins else None,
                    "passes_constraints": ok}
    base = table.get("V0", {}).get("score_pp")
    cand = [v for v, t in table.items() if t["passes_constraints"] and v != "V0"]
    choice, why = None, "никто не прошёл ограничения — остаётся FINAL №2"
    if cand:
        best = max(table[v]["score_pp"] for v in cand)
        near = [v for v in cand if table[v]["score_pp"] >= best - TIE]
        near.sort(key=lambda v: (-(table[v]["S"]["confident_accuracy"] or 0), table[v]["S"]["mean_min"] or 1e9))
        top = near[0]
        if base is None or table[top]["score_pp"] > base + TIE:
            choice, why = top, f"максимин {table[top]['score_pp']} п.п. против V0 {base}; ограничения пройдены в обоих мирах"
        else:
            why = f"лучший прошедший {top}: максимин {table[top]['score_pp']} п.п. не выше V0 {base} более чем на {TIE} — остаётся FINAL №2"
    res = {"rule": "docs/validation/RULE_V2_2110.md", "plan": "docs/validation/TRAIN_PLAN_2110d.json", "choice": choice, "why": why,
           "baseline_score_pp": base, "table": table}
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for v, t in table.items():
        print(v, "ok" if t["passes_constraints"] else "--", t["score_pp"], t["worst_row"],
              "FC S/T", round(t["S"]["fc"] * 100, 2), round(t["T"]["fc"] * 100, 2), "p90 S/T", t["S"]["p90_min"], t["T"]["p90_min"],
              "agree", t["S"].get("decision_agreement"), "conf", t["S"]["confident_accuracy"])
    print("ВЫБОР:", choice, "—", why)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
