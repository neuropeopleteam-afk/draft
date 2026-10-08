"""Расчёт метрик по экспертной разметке для /validation (и проверка расчёта на синтетической разметке).

A → качество подбора: эталон пары — медиана оценок экспертов (при двух — среднее), релевантна при эталоне ≥ 2.
    precision@5 и nDCG@5 (gain = 2^rel − 1) для топ-5 платформы и топ-5 BM25 (размечены полностью), идеальный DCG —
    по всем размеченным кандидатам пула. «Случайный порядок» по всей базе кандидатов — стратифицированная оценка:
    объединение топов размечено целиком, остальная база — по случайной выборке из пула. 95 % ДИ — бутстреп по
    потребностям; разница платформа − BM25 — бутстреп и знаковый критерий Уилкоксона. Сверка с разметкой по
    правилам (на которой построен раздел «Подбор») — квадратично взвешенная каппа.
A, B → межэкспертное согласие: попарная квадратично взвешенная каппа Коэна (95 % ДИ бутстрепом), альфа
    Криппендорфа (порядковая для 0–3, интервальная для долей), доли точных совпадений и ±1.
B → модель-оценщик: балл модели 0..1 → уровень 0–3 (round(3·балл)); каппа с консенсусом экспертов, средняя каппа с
    каждым экспертом против средней межэкспертной («тест подмены эксперта»), MAE по взвешенной сумме критериев,
    разброс между прогонами, контрольный ответ с внедрённой инструкцией. Допустима, если согласие не хуже
    межэкспертного − 0,1, разброс ≤ 0,5 балла и инструкция не подняла балл.
C → пороги Ангоффа: для эксперта и границы — θ, при котором сумма ожидаемых долей (2PL движка теста) по его
    семействам равна сумме его оценок; порог — среднее по экспертам, SE = SD/√n; сравнение с GRADE_CUTS.
"""
from __future__ import annotations

from collections import defaultdict
import math
import statistics

import numpy as np

from app.modules.experts import stats as S

CURRENT_CUTS = {"junior_middle": ("middle", 0.0), "middle_senior": ("senior", 1.0)}
BOUNDARY_TITLES = {"junior_middle": "Junior → Middle", "middle_senior": "Middle → Senior"}
POS5 = sum(1 / math.log2(i + 2) for i in range(5))


def _r(x, d=3):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), d)


# ------------------------------------------------------------------ A: подбор
def gold_labels(items: dict, labels: list[dict]) -> tuple[dict, dict]:
    by_key: dict[str, list] = defaultdict(list)
    for lb in labels:
        if items.get(lb["key"], {}).get("kind") == "A":
            by_key[lb["key"]].append(lb["value"]["relevance"])
    return {k: float(statistics.median(v)) for k, v in by_key.items()}, by_key


def matching(items: dict, labels: list[dict]) -> dict | None:
    gold, raw = gold_labels(items, labels)
    if not gold:
        return None
    needs: dict[str, list] = defaultdict(list)
    for k, it in items.items():
        if it["kind"] == "A":
            needs[it["grp"]].append(k)
    per_need, complete = [], []
    for nid, keys in sorted(needs.items()):
        done = sum(1 for k in keys if k in gold)
        row = {"need": nid, "pairs": len(keys), "labeled": done, "complete": done == len(keys),
               "text": items[keys[0]]["payload"].get("need_text")}
        if done == len(keys):
            h = {k: items[k]["hidden"] for k in keys}
            all_g = [gold[k] for k in keys]
            res = {}
            for m, rk in (("platform", "rank_platform"), ("bm25", "rank_bm25")):
                top = sorted(keys, key=lambda k: h[k][rk])[:5]
                g = [gold[k] for k in top]
                res[m] = {"p@5": S.precision_at(g), "ndcg@5": S.ndcg_at(g, all_g)}
            union = [k for k in keys if "random" not in h[k]["sources"]]
            sample = [k for k in keys if "random" in h[k]["sources"]]
            n_pop = int(h[keys[0]]["n_population"])
            if sample:
                rest = n_pop - len(union)
                rel = (sum(1 for k in union if gold[k] >= 2) + rest * np.mean([gold[k] >= 2 for k in sample])) / n_pop
                gain = (sum(2 ** gold[k] - 1 for k in union) + rest * np.mean([2 ** gold[k] - 1 for k in sample])) / n_pop
                ideal = S.dcg(sorted(all_g, reverse=True), 5)
                res["random"] = {"p@5": float(rel), "ndcg@5": float(gain * POS5 / ideal) if ideal > 0 else 0.0}
            rule = [h[k]["rule_label"] for k in keys]
            top_r = sorted(keys, key=lambda k: h[k]["rank_platform"])[:5]
            top_b = sorted(keys, key=lambda k: h[k]["rank_bm25"])[:5]
            res["rules_platform"] = {"p@5": S.precision_at([h[k]["rule_label"] for k in top_r]),
                                     "ndcg@5": S.ndcg_at([h[k]["rule_label"] for k in top_r], rule)}
            res["rules_bm25"] = {"p@5": S.precision_at([h[k]["rule_label"] for k in top_b]),
                                 "ndcg@5": S.ndcg_at([h[k]["rule_label"] for k in top_b], rule)}
            row.update({m: {x: _r(y) for x, y in v.items()} for m, v in res.items()})
            row["relevant"] = sum(1 for k in keys if gold[k] >= 2)
            complete.append(row)
        per_need.append(row)
    out = {"needs_total": len(needs), "needs_complete": len(complete), "pairs_total": sum(len(v) for v in needs.values()),
           "pairs_labeled": len(gold), "per_need": per_need,
           "ratings_per_pair": _r(np.mean([len(v) for v in raw.values()]), 2) if raw else None}
    if not complete:
        return out
    summ: dict = {}
    for metric in ("p@5", "ndcg@5"):
        summ[metric] = {}
        for m in ("platform", "bm25", "random", "rules_platform", "rules_bm25"):
            vals = [r[m][metric] for r in complete if m in r]
            summ[metric][m] = S.boot_ci(vals)
        for a, b in (("platform", "bm25"), ("platform", "random")):
            d = [r[a][metric] - r[b][metric] for r in complete if a in r and b in r]
            summ[metric][f"diff_{a}_{b}"] = {**S.boot_ci(d), "wilcoxon_p": S.wilcoxon_p(d)}
    out["summary"] = summ
    pairs = [(round(gold[k] + 1e-9), items[k]["hidden"]["rule_label"]) for k in gold]
    out["vs_rules"] = {"n": len(pairs), "kappa": S.weighted_kappa([a for a, _ in pairs], [b for _, b in pairs]),
                       "exact": _r(sum(1 for a, b in pairs if a == b) / len(pairs)),
                       "relevant_agree": _r(sum(1 for a, b in pairs if (a >= 2) == (b >= 2)) / len(pairs))}
    out["vs_rules"]["level"] = S.landis_koch(out["vs_rules"]["kappa"])
    return out


# ------------------------------------------------------------------ согласие
def _ratings(items: dict, labels: list[dict], kind: str, getter, skip_controls: bool = True) -> dict[str, dict]:
    out: dict[str, dict] = defaultdict(dict)
    for lb in labels:
        it = items.get(lb["key"])
        if not it or it["kind"] != kind or (skip_controls and it["hidden"].get("control")):
            continue
        v = getter(lb["value"], it)
        if v is not None:
            out[lb["coder"]][lb["key"]] = v
    return out


def _weighted(value: dict, it: dict) -> float | None:
    crit = (it["payload"].get("rubric") or {}).get("criteria") or []
    tw = sum(float(c["weight"]) for c in crit) or 1.0
    try:
        return sum(float(c["weight"]) * float(value["criteria"][c["id"]]) for c in crit) / tw
    except (KeyError, TypeError):
        return None


def agreement_block(ratings: dict[str, dict], level: str = "ordinal", cats=(0, 1, 2, 3)) -> dict:
    units: dict = defaultdict(list)
    for coder, r in ratings.items():
        for k, v in r.items():
            units[k].append(v)
    multi = {k: v for k, v in units.items() if len(v) >= 2}
    pw = S.pairwise(ratings, cats) if level == "ordinal" else []
    alpha = S.krippendorff_alpha(multi, level) if multi else None
    ks = [p["kappa"] for p in pw if p["kappa"] is not None]
    return {"coders": len(ratings), "units": len(units), "units_multi": len(multi), "pairwise": pw,
            "kappa_mean": _r(np.mean(ks)) if ks else None, "kappa_level": S.landis_koch(_r(np.mean(ks)) if ks else None),
            "alpha": alpha, "alpha_ci": S.alpha_ci(multi, level) if multi else None, "alpha_level": level,
            "alpha_verdict": (None if alpha is None else "надёжно" if alpha >= 0.8 else
                              "только предварительные выводы" if alpha >= 0.667 else "ниже порога")}


def agreement(items: dict, labels: list[dict]) -> dict:
    a = _ratings(items, labels, "A", lambda v, it: v["relevance"])
    bh = _ratings(items, labels, "B", lambda v, it: v["holistic"])
    bw = _ratings(items, labels, "B", _weighted)
    c = defaultdict(dict)
    for lb in labels:
        it = items.get(lb["key"])
        if it and it["kind"] == "C":
            for bnd in ("junior_middle", "middle_senior"):
                c[lb["coder"]][f"{lb['key']}|{bnd}"] = lb["value"][bnd] / 100
    out = {"A": agreement_block(a), "B": agreement_block(bh), "B_weighted": agreement_block(bw, "interval"),
           "C": agreement_block(c, "interval")}
    flags = defaultdict(lambda: {"n": 0, "flagged": 0})
    for lb in labels:
        it = items.get(lb["key"])
        if it and it["kind"] == "B" and it["hidden"].get("control"):
            ctl = it["hidden"]["control"]
            flags[ctl]["n"] += 1
            flags[ctl]["flagged"] += 1 if lb["value"].get("flag") == ctl else 0
    out["B_controls"] = dict(flags)
    return out


# ------------------------------------------------------------------ B: модель-оценщик
# Критерий допуска модели-оценщика.
# * «gap» — панель людей: согласие модели с экспертами не хуже межэкспертного минус GAP (модель заменяет
#   эксперта, если отличается от людей не больше, чем люди между собой).
# * «absolute» — панель модельная (одна модель в ролях E1–E3) или межэкспертная κ ≥ DEGENERATE_INTER: сравнение
#   с «межэкспертной» κ ≈ 1 несправедливо (это разброс прогонов, а не людей). Порог — абсолютный: квадратично
#   взвешенная κ с консенсусом ≥ ABS_KAPPA (порог ETS для автоматической оценки: Williamson, Xi, Breyer, 2012)
#   и MAE по критериям ≤ ABS_MAE. Допуск предварительный — до разметки людьми.
# В обоих случаях: разброс прогонов ≤ MAX_SPREAD балла 0–3, контрольная инструкция не подняла балл.
# Выбор — только среди моделей, работающих в продукте (PRODUCT_MODELS: цепочка оценщика llm/client.py — Claude через
#   OpenRouter и запасная YandexGPT; зарубежные облачные модели разрешены организаторами, VS.3); остальные — эталон.
GAP = 0.10
ABS_KAPPA = 0.70
ABS_MAE = 0.15
MAX_SPREAD = 0.5
DEGENERATE_INTER = 0.98
PRODUCT_MODELS = ("yandexgpt", "anthropic", "claude")


def _injection_runs(items: dict, inj: list[str], model: str) -> tuple[bool | None, str | None]:
    """Контрольный ответ с инструкцией: (не повлияла?, как обработан).

    Фильтр оценщика (grader.injection_signals) не отправляет такой ответ в модель — все прогоны «на проверке»
    с error=prompt_injection_suspected: инструкция не повлияла, ответ ушёл эксперту («blocked»). Раньше такие
    прогоны отбрасывались как неоценённые, и injection_ok оставался пустым."""
    for k in inj:
        runs = (items[k]["hidden"].get("llm") or {}).get(model) or []
        if runs and all(r.get("status") == "pending" and r.get("error") == "prompt_injection_suspected" for r in runs):
            return True, "blocked"
    return None, None


def llm_agreement(items: dict, labels: list[dict], inter_kappa: float | None, panel_kind: str = "human") -> dict | None:
    models: dict[str, dict] = defaultdict(dict)
    for k, it in items.items():
        if it["kind"] != "B":
            continue
        for m, runs in (it["hidden"].get("llm") or {}).items():
            ok = [r for r in runs if r.get("status") == "scored" and r.get("score") is not None]
            if ok:
                models[m][k] = ok
    if not models:
        return None
    bh = _ratings(items, labels, "B", lambda v, it: v["holistic"])
    bw = _ratings(items, labels, "B", _weighted)
    cons_h: dict = defaultdict(list)
    cons_w: dict = defaultdict(list)
    for coder in bh:
        for k, v in bh[coder].items():
            cons_h[k].append(v)
        for k, v in bw.get(coder, {}).items():
            cons_w[k].append(v)
    inj = [k for k, it in items.items() if it["kind"] == "B" and it["hidden"].get("control") == "injection"]
    degenerate = inter_kappa is not None and inter_kappa >= DEGENERATE_INTER
    criterion = "absolute" if panel_kind == "model" or degenerate else "gap"
    for it in items.values():  # модели, у которых есть только заблокированные фильтром прогоны
        if it["kind"] == "B":
            for m in (it["hidden"].get("llm") or {}):
                models.setdefault(m, {})
    out = []
    for m, per in sorted(models.items()):
        plain = [k for k in per if not items[k]["hidden"].get("control")]
        mh = {k: min(3, max(0, round(3 * float(np.mean([r["score"] for r in per[k]]))))) for k in per}
        mw = {k: float(np.mean([r["score"] for r in per[k]])) for k in per}
        spread = [max(round(3 * r["score"]) for r in per[k]) - min(round(3 * r["score"]) for r in per[k])
                  for k in plain if len(per[k]) > 1]
        common = [k for k in plain if k in cons_h]
        kc = S.weighted_kappa([mh[k] for k in common], [round(np.median(cons_h[k]) + 1e-9) for k in common]) if len(
            common) >= 3 else None
        per_exp = []
        for coder, r in bh.items():
            cm = [k for k in plain if k in r]
            if len(cm) >= 3:
                per_exp.append(S.weighted_kappa([mh[k] for k in cm], [r[k] for k in cm]))
        per_exp = [x for x in per_exp if x is not None]
        mae_k = [k for k in plain if k in cons_w]
        inj_k = [k for k in inj if k in mh]
        inj_ok, inj_mode = None, None
        if inj_k:
            k = inj_k[0]
            ref = float(np.median(cons_h[k])) if k in cons_h else 1.0
            inj_ok, inj_mode = mh[k] <= max(1.0, ref), "scored"
        else:
            inj_ok, inj_mode = _injection_runs(items, inj, m)
        mean_exp = _r(np.mean(per_exp)) if per_exp else None
        sp = _r(np.mean(spread), 2) if spread else 0.0
        mae = _r(np.mean([abs(mw[k] - np.mean(cons_w[k])) for k in mae_k])) if mae_k else None
        admissible = None
        if criterion == "gap" and mean_exp is not None and inter_kappa is not None:
            admissible = bool(mean_exp >= inter_kappa - GAP and (sp or 0) <= MAX_SPREAD and inj_ok is not False)
        elif criterion == "absolute" and kc is not None and mae is not None:
            admissible = bool(kc >= ABS_KAPPA and mae <= ABS_MAE and (sp or 0) <= MAX_SPREAD and inj_ok is not False)
        lat = [r.get("latency_ms") for k in per for r in per[k] if r.get("latency_ms")]
        out.append({"model": m, "items": len(per), "runs": max((len(v) for v in per.values()), default=0),
                    "kappa_consensus": kc, "kappa_mean_with_experts": mean_exp, "inter_expert_kappa": inter_kappa,
                    "substitution_gap": _r(mean_exp - inter_kappa) if mean_exp is not None and inter_kappa is not None else None,
                    "mae_weighted": mae, "run_spread": sp, "injection_ok": inj_ok, "injection_mode": inj_mode,
                    "admissible": admissible, "product": m.split("/")[0].startswith(PRODUCT_MODELS),
                    "latency_ms_median": int(np.median(lat)) if lat else None})
    key = "kappa_consensus" if criterion == "absolute" else "kappa_mean_with_experts"
    ok = [x for x in out if x["admissible"]]
    if any(x["product"] for x in out):  # в продукте — модели цепочки оценщика; остальные — эталон для сравнения
        ok = [x for x in ok if x["product"]]
    best = None
    if ok:
        ok.sort(key=lambda x: (-(x[key] or 0), x["latency_ms_median"] or 10 ** 9))
        best = ok[0]["model"]
        if len(ok) > 1 and abs((ok[0][key] or 0) - (ok[1][key] or 0)) < 0.03:
            best = min(ok[:2], key=lambda x: x["latency_ms_median"] or 10 ** 9)["model"]
    caveat = None
    if panel_kind == "model":
        caveat = ("Панель модельная: роли E1–E3 размечала модель, поэтому межэкспертная κ — это согласие прогонов, а не "
                  "людей. Допуск — по абсолютным порогам (κ с консенсусом и MAE); это согласие с другой моделью, "
                  "окончательный допуск — после разметки людьми.")
    elif degenerate:
        caveat = (f"Межэкспертная κ = {inter_kappa} — разметка, похоже, не независимая. Допуск — по абсолютным порогам "
                  "(κ с консенсусом и MAE), предварительный.")
    return {"models": out, "choice": best, "criterion": criterion, "panel_kind": panel_kind, "caveat": caveat,
            "thresholds": {"gap": GAP, "kappa": ABS_KAPPA, "mae": ABS_MAE, "spread": MAX_SPREAD,
                           "degenerate_inter": DEGENERATE_INTER}}


# ------------------------------------------------------------------ C: Ангофф
def angoff(items: dict, labels: list[dict]) -> dict | None:
    by_coder: dict[str, list] = defaultdict(list)
    for lb in labels:
        it = items.get(lb["key"])
        if it and it["kind"] == "C":
            by_coder[lb["coder"]].append((it, lb["value"]))
    if not by_coder:
        return None
    out = {"coders": len(by_coder), "judgements": sum(len(v) * 2 for v in by_coder.values()), "boundaries": []}
    for bnd, (grade, cur) in CURRENT_CUTS.items():
        thetas, fam_sd, by_block = [], [], defaultdict(list)
        for coder, rows in sorted(by_coder.items()):
            params = [(it["hidden"]["a"], it["hidden"]["b"]) for it, _ in rows]
            target = sum(v[bnd] / 100 for _, v in rows)
            thetas.append(S.solve_theta(target, params))
            per_f = [S.solve_theta(v[bnd] / 100, [(it["hidden"]["a"], it["hidden"]["b"])]) for it, v in rows]
            if len(per_f) >= 2:
                fam_sd.append(float(np.std(per_f, ddof=1)))
            blocks: dict = defaultdict(list)
            for it, v in rows:
                blocks[it["hidden"]["block"]].append((it, v))
            for blk, br in blocks.items():
                if len(br) >= 3:
                    by_block[blk].append(S.solve_theta(sum(v[bnd] / 100 for _, v in br),
                                                       [(it["hidden"]["a"], it["hidden"]["b"]) for it, _ in br]))
        cut = float(np.mean(thetas))
        se = float(np.std(thetas, ddof=1) / math.sqrt(len(thetas))) if len(thetas) >= 2 else None
        delta = cut - cur
        out["boundaries"].append({
            "boundary": bnd, "title": BOUNDARY_TITLES[bnd], "grade": grade, "current": cur, "angoff": _r(cut),
            "se": _r(se), "delta": _r(delta), "per_expert": [_r(t) for t in thetas],
            "family_sd": _r(np.mean(fam_sd)) if fam_sd else None,
            "replace_suggested": (abs(delta) > se) if se else None,
            "population_shift": _r(abs(S.norm_cdf(cut) - S.norm_cdf(cur))),
            "by_block": {b: _r(np.mean(v)) for b, v in sorted(by_block.items())},
        })
    return out


# ------------------------------------------------------------------ сводка
def analyze(items: dict, labels: list[dict], panel_kind: str = "human") -> dict:
    agr = agreement(items, labels)
    return {"matching": matching(items, labels), "agreement": agr,
            "llm": llm_agreement(items, labels, agr["B"]["kappa_mean"], panel_kind), "angoff": angoff(items, labels),
            "labels": len(labels), "coders": sorted({lb["coder"] for lb in labels})}
