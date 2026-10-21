#!/usr/bin/env python3
# Копия независимого скрипта А15 (reviews/a15_scripts/a15_recompute.py в файлах проекта, 21.10) — без изменений; ею считает train_choice_v2.
"""А15: независимый пересчёт метрик теста (А4) по построчным результатам.

Вход: шарды product_sim (JSON с _raw.rows/_raw.pairs) или *.rows.jsonl.gz (+ *.pairs.jsonl.gz, если есть).
Считает те же величины, что summarize() А4, своим кодом, плюс строки сопоставимости из отчёта А13 (4 / 5 / 6 грейдов,
κ Коэна решения при повторе, «выше истинного», вне ±0,25 / ±0,3, κw с истиной, адаптивный против фиксированного).
Три точки пути: main (основная часть), stage2 (после второго этапа — только автоматика), final (с моделью устной
защиты, как в product_sim). Решение бинарное: подтверждён / нет («решения нет» = не подтверждён).
ДИ: Уилсон по людям и перцентильный бутстрэп по зёрнам (кластер = зерно), 2000 повторов, seed 7702115.
Запуск: python3 a15_recompute.py <файлы...> [--out x.json]
"""
import argparse, gzip, json, math, random, sys
from collections import defaultdict
from pathlib import Path

ORDER = ("none", "intern", "junior", "middle", "senior", "lead", "principal")
R = {g: i for i, g in enumerate(ORDER)}
CUTS = {"intern": -1.75, "junior": -1.0, "middle": 0.0, "senior": 1.0, "lead": 2.0, "principal": 3.0}
# слияние ступеней для строк сопоставимости (А15, Приложение А): 5 = Lead ∪ Principal; 4 = ещё Intern ∪ Junior.
# «ниже Стажёра» (none) — отдельный класс, как в поправке №3 А4 (строже: выданный «none» у истинного Стажёра — ошибка).
# Номера классов подряд — для κw и «±1».
M6 = {g: R[g] for g in ORDER}
M5 = {"none": 0, "intern": 1, "junior": 2, "middle": 3, "senior": 4, "lead": 5, "principal": 5}
M4 = {"none": 0, "intern": 1, "junior": 1, "middle": 2, "senior": 3, "lead": 4, "principal": 4}
MERGES = {"6": M6, "5": M5, "4": M4}


def load(files):
    rows, pairs = [], []
    for f in files:
        p = Path(f)
        if p.name.endswith(".rows.jsonl.gz"):
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                rows += [json.loads(x) for x in fh if x.strip()]
            pp = Path(str(p).replace(".rows.jsonl.gz", ".pairs.jsonl.gz"))
            if pp.exists():
                with gzip.open(pp, "rt", encoding="utf-8") as fh:
                    pairs += [json.loads(x) for x in fh if x.strip()]
        else:
            d = json.loads(p.read_text(encoding="utf-8"))
            raw = d.get("_raw") or {}
            rows += raw.get("rows") or []
            pairs += raw.get("pairs") or []
    return rows, pairs


def wilson(k, n, z=1.959964):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def kappa(a, b, k=None, weighted=False):
    """κ Коэна; weighted=True — квадратичные веса, нормированные на (k−1)² (как у соперника с κw 0,90)."""
    labs = sorted(set(a) | set(b)) if k is None else list(range(k))
    idx = {l: i for i, l in enumerate(labs)}
    m = len(labs)
    if m < 2 or not a:
        return None
    M = [[0.0] * m for _ in range(m)]
    for x, y in zip(a, b):
        M[idx[x]][idx[y]] += 1
    n = float(len(a))
    ra = [sum(M[i]) for i in range(m)]
    cb = [sum(M[i][j] for i in range(m)) for j in range(m)]
    w = [[((i - j) ** 2) / ((m - 1) ** 2) if weighted else float(i != j) for j in range(m)] for i in range(m)]
    obs = sum(w[i][j] * M[i][j] for i in range(m) for j in range(m))
    exp = sum(w[i][j] * ra[i] * cb[j] / n for i in range(m) for j in range(m))
    return None if exp <= 0 else round(1 - obs / exp, 4)


def truth_ok(r):
    return R[r["true_grade"]] >= R[r["claim"]]


def conf(v):  # бинарное решение: подтверждён / нет
    return v == "confirmed"


def point_metrics(rs, gk, vk):
    """Метрики одной точки пути: gk — поле грейда, vk — поле вердикта."""
    n = len(rs)
    out = {"n": n}
    ok = [truth_ok(r) for r in rs]
    cf = [conf(r.get(vk)) for r in rs]
    over = [not o for o in ok]
    fc = sum(1 for c, o in zip(cf, ok) if c and not o)
    fr = sum(1 for c, o in zip(cf, ok) if not c and o)
    out["verdict_accuracy"] = frac(sum(1 for c, o in zip(cf, ok) if c == o), n)
    out["false_confirm_all"] = frac(fc, n)
    out["false_confirm_among_overclaim"] = frac(fc, sum(over))
    out["false_reject_among_true"] = frac(fr, sum(ok))
    out["undecided_share"] = frac(sum(1 for r in rs if r.get(vk) in ("needs_followup", "undecided")), n)
    dec = [(r, conf(r.get(vk)), o) for r, o in zip(rs, ok) if r.get(vk) in ("confirmed", "not_confirmed")]
    out["confident_share"] = frac(len(dec), n)
    out["confident_accuracy"] = frac(sum(1 for _, c, o in dec if c == o), len(dec))
    for lab, M in MERGES.items():
        t = [M[r["true_grade"]] for r in rs]
        g = [M[r.get(gk) or "none"] for r in rs]
        ex = sum(1 for a, b in zip(t, g) if a == b)
        nu = [(a, b) for a, b, r in zip(t, g, rs) if R[r["claim"]] >= R[r["true_grade"]]]  # без занизивших
        out[f"exact_{lab}"] = frac(ex, n)
        out[f"exact_{lab}_not_underclaim"] = frac(sum(1 for a, b in nu if a == b), len(nu))
        out[f"within_one_{lab}"] = frac(sum(1 for a, b in zip(t, g) if abs(a - b) <= 1), n)
        out[f"gross_2plus_{lab}"] = frac(sum(1 for a, b in zip(t, g) if abs(a - b) >= 2), n)
        out[f"above_true_{lab}"] = frac(sum(1 for a, b in zip(t, g) if b > a), n)
        out[f"kappa_w_truth_{lab}"] = kappa(t, g, k=max(M.values()) + 1, weighted=True)
    # вне зоны безразличия у порога заявки (вердикт) и у всех порогов (точный грейд, 4 ступени)
    for z in (0.25, 0.3, 0.5):
        far = [(c, o) for r, c, o in zip(rs, cf, ok) if abs(r["theta_true"] - r["cut_claim"]) > z]
        out[f"verdict_accuracy_far_{z}"] = frac(sum(1 for c, o in far if c == o), len(far))
        out[f"false_confirm_all_far_{z}"] = frac(sum(1 for c, o in far if c and not o), len(far))
    far4 = [r for r in rs if min(abs(r["theta_true"] - c) for c in (0.0, 1.0, 2.0)) > 0.25]  # пороги шкалы 4 ступеней
    out["exact_4_far_all_cuts_0.25"] = frac(sum(1 for r in far4 if M4[r["true_grade"]] == M4[r.get(gk) or "none"]),
                                            len(far4))
    return out


def frac(k, n):
    return {"k": int(k), "n": int(n), "value": round(k / n, 4) if n else None, "wilson95": wilson(k, n)}


def seed_bootstrap(rows, fn, reps=2000, seed=7702115):
    by = defaultdict(list)
    for r in rows:
        by[r.get("seed")].append(r)
    keys = sorted(by)
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        s = [r for k in (rng.choice(keys) for _ in keys) for r in by[k]]
        v = fn(s)
        if v is not None:
            vals.append(v)
    vals.sort()
    if not vals:
        return None
    return [round(vals[int(0.025 * len(vals))], 4), round(vals[int(0.975 * len(vals)) - 1], 4)]


def retest(pairs):
    if not pairs:
        return {"n": 0, "note": "строк повтора нет — пересчёт повтора невозможен"}
    out = {"n": len(pairs)}
    d1 = [bool(p["c1"]) if "c1" in p else conf(p.get("v1")) for p in pairs]
    d2 = [bool(p["c2"]) if "c2" in p else conf(p.get("v2")) for p in pairs]
    out["decision_agreement"] = frac(sum(1 for a, b in zip(d1, d2) if a == b), len(pairs))
    out["decision_kappa"] = kappa([int(x) for x in d1], [int(x) for x in d2], k=2)
    for lab, M in MERGES.items():
        g1 = [M[p.get("g1") or "none"] for p in pairs]
        g2 = [M[p.get("g2") or "none"] for p in pairs]
        out[f"grade_agreement_{lab}"] = frac(sum(1 for a, b in zip(g1, g2) if a == b), len(pairs))
        out[f"grade_kappa_w_{lab}"] = kappa(g1, g2, k=max(M.values()) + 1, weighted=True)
    out["shared_families_mean"] = round(sum(p.get("shared", 0) for p in pairs) / len(pairs), 3)
    return out


def adaptive_vs_fixed(rows):
    rs = [r for r in rows if r.get("fixed_grade") is not None]
    if not rs:
        return None
    out = {"n": len(rs), "compare": "grade_main (основная часть) против fixed_grade той же длины (n_main)"}
    for lab in ("4", "5", "6"):
        M = MERGES[lab]
        a = [int(M[r["true_grade"]] == M[r.get("grade_main") or "none"]) for r in rs]
        f = [int(M[r["true_grade"]] == M[r.get("fixed_grade") or "none"]) for r in rs]
        d = (sum(a) - sum(f)) / len(rs)
        out[f"exact_{lab}"] = {"adaptive": round(sum(a) / len(rs), 4), "fixed": round(sum(f) / len(rs), 4),
                               "diff": round(d, 4),
                               "diff_ci_seed_bootstrap": seed_bootstrap(
                                   rs, lambda s, M=M: (sum(int(M[r["true_grade"]] == M[r.get("grade_main") or "none"])
                                                           - int(M[r["true_grade"]] == M[r.get("fixed_grade") or "none"])
                                                           for r in s) / len(s)) if s else None)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    rows, pairs = load(a.files)
    res = {"n_rows": len(rows), "n_pairs": len(pairs), "seeds": sorted({r.get("seed") for r in rows})}
    # stage2 = заголовок А4 (summary), final = summary_oral_model (с моделью устной защиты)
    pts = {"main": ("grade_main", "verdict_main"), "stage2": ("grade_stage2", "verdict_stage2"),
           "final": ("grade_final", "verdict_final")}
    for name, (gk, vk) in pts.items():
        if rows and gk in rows[0]:
            res[name] = point_metrics(rows, gk, vk)
    # ДИ бутстрэпом по зёрнам для главных строк итога
    if rows and "grade_final" in rows[0]:
        res["final_seed_bootstrap"] = {
            "exact_4": seed_bootstrap(rows, lambda s: sum(M4[r["true_grade"]] == M4[r.get("grade_final") or "none"]
                                                          for r in s) / len(s)),
            "exact_6": seed_bootstrap(rows, lambda s: sum(r["true_grade"] == (r.get("grade_final") or "none")
                                                          for r in s) / len(s)),
            "false_confirm_all": seed_bootstrap(rows, lambda s: sum(conf(r.get("verdict_final")) and not truth_ok(r)
                                                                    for r in s) / len(s)),
        }
    res["retest_stage2"] = retest(pairs)
    res["retest_oral_model"] = retest([{**p, "g1": p.get("g1_final", p.get("g1")), "g2": p.get("g2_final", p.get("g2")),
                                        "c1": p.get("c1_final", p.get("c1")), "c2": p.get("c2_final", p.get("c2"))}
                                       for p in pairs]) if pairs and "g1_final" in pairs[0] else None
    res["adaptive_vs_fixed"] = adaptive_vs_fixed(rows)
    res["by_claim_final"] = {}
    for g in ORDER[1:]:
        rs = [r for r in rows if r["claim"] == g]
        if rs and "grade_final" in rs[0]:
            pm = point_metrics(rs, "grade_final", "verdict_final")
            res["by_claim_final"][g] = {k: pm[k] for k in ("n", "false_confirm_among_overclaim", "false_reject_among_true",
                                                           "exact_6", "undecided_share")}
    s = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(s + "\n", encoding="utf-8")
    print(s[:6000])


if __name__ == "__main__":
    main()
