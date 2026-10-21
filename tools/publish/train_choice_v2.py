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


def row_metrics(rows: list, pairs: list, a15) -> dict:
    """Только строки сравнения (для парного бутстрэпа по зёрнам)."""
    st = a15.point_metrics(rows, "grade_stage2", "verdict_stage2")
    rt = a15.retest(pairs) if pairs else {}
    av = a15.adaptive_vs_fixed(rows) or {}
    out = {}
    for k, _, _ in REF:
        if k in st:
            out[k] = _v(st[k])
        elif k in rt:
            out[k] = _v(rt[k])
    out["adaptive_minus_fixed_4"] = (av.get("exact_4") or {}).get("diff")
    return out


def score(m: dict) -> tuple[float | None, dict]:
    margins = {}
    for k, r, hi in REF:
        x = m.get(k)
        if x is not None:
            margins[k] = round(100 * ((x - r) if hi else (r - x)), 2)
    return (min(margins.values()) if margins else None), margins


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
    out["_rows"], out["_pairs"] = rows, pairs
    return out


def by_seed(rows: list, pairs: list) -> dict:
    g: dict = {}
    for r in rows:
        g.setdefault(r["seed"], [[], []])[0].append(r)
    for p in pairs:
        g.setdefault(p["seed"], [[], []])[1].append(p)
    return g


def paired_boot(SV: dict, S0: dict, a15, B: int, seed: int = 2110) -> dict:
    """Парный бутстрэп по зёрнам (кластер = зерно; те же зёрна и люди у V и V0): ДИ разности счёта и SE счёта V."""
    import random
    gv, g0 = by_seed(SV["_rows"], SV["_pairs"]), by_seed(S0["_rows"], S0["_pairs"])
    seeds = sorted(set(gv) & set(g0))
    rnd = random.Random(seed)
    diffs, sv = [], []
    for _ in range(B):
        pick = [rnd.choice(seeds) for _ in seeds]
        rv = [x for s in pick for x in gv[s][0]]; pv = [x for s in pick for x in gv[s][1]]
        r0 = [x for s in pick for x in g0[s][0]]; p0 = [x for s in pick for x in g0[s][1]]
        a, _ = score(row_metrics(rv, pv, a15)); b, _ = score(row_metrics(r0, p0, a15))
        if a is not None and b is not None:
            diffs.append(a - b); sv.append(a)
    diffs.sort()
    m = sum(sv) / len(sv)
    return {"B": len(diffs), "diff_ci95": [round(diffs[int(0.025 * len(diffs))], 2), round(diffs[int(0.975 * len(diffs)) - 1], 2)],
            "score_se": round((sum((x - m) ** 2 for x in sv) / max(1, len(sv) - 1)) ** 0.5, 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--boot", type=int, default=200)
    a = ap.parse_args()
    d = Path(a.dir)
    a15 = _a15()
    names = sorted({p.name.split("__")[0][2:] for p in d.glob("S_*__*.json")}, key=lambda s: int(s[1:]))
    plan = json.loads((HERE.parents[1] / "docs" / "validation" / "TRAIN_PLAN_2110d.json").read_text(encoding="utf-8"))
    nchg = {v: len(e) for v, e in (plan.get("variants") or {}).items()}
    table, raw = {}, {}
    for v in names:
        S = metrics(sorted(d.glob(f"S_{v}__*.json")), a15)
        T = metrics(sorted(d.glob(f"T_{v}__*.json")), a15)
        raw[v] = S
        sc, margins = score(S)
        ok = all(w["fc_k"] <= FC_MAX * w["n"] and (w["p90_min"] or 1e9) <= P90_MAX and w["engine_errors"] == 0 for w in (S, T))
        table[v] = {"S": {k: x for k, x in S.items() if not k.startswith("_")}, "T": {k: x for k, x in T.items() if not k.startswith("_")},
                    "margins_pp": margins, "score_pp": sc, "worst_row": min(margins, key=margins.get) if margins else None,
                    "passes_constraints": ok, "n_changes_from_V0": nchg.get(v)}
    for v in names:
        if v != "V0" and "V0" in raw:
            table[v]["paired_vs_V0"] = paired_boot(raw[v], raw["V0"], a15, a.boot)
    base = table.get("V0", {}).get("score_pp")
    cand = [v for v, t in table.items() if t["passes_constraints"] and v != "V0"]
    choice, why = None, "никто не прошёл ограничения — остаётся FINAL №2"
    if cand:
        best = max(cand, key=lambda v: table[v]["score_pp"])
        se = table[best]["paired_vs_V0"]["score_se"]
        near = [v for v in cand if table[v]["score_pp"] >= table[best]["score_pp"] - se]
        near.sort(key=lambda v: (table[v]["n_changes_from_V0"] or 99, -(table[v]["S"]["confident_accuracy"] or 0)))
        top = near[0]
        lo = table[top]["paired_vs_V0"]["diff_ci95"][0]
        if lo > 0:
            choice, why = top, (f"максимин {table[top]['score_pp']} п.п. (V0 {base}); нижняя граница парного 95 % ДИ разности с V0 "
                                f"{lo} > 0; в пределах 1 SE ({se}) от лучшего {best} — меньше всего изменений от V0")
        else:
            why = (f"лучший прошедший {top}: нижняя граница парного 95 % ДИ разности счёта с V0 = {lo} ≤ 0 — "
                   "не лучше FINAL №2, остаётся №2")
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
