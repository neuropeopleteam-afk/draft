"""Подбор в сопоставимых условиях: наш подбор (продукт, без изменений) на мирах, построенных по описанию чужих бенчмарков.

    make match-bench-compare      # cd backend && python -m app.modules.validation.matching_compare
    python -m app.modules.validation.matching_compare --quick --no-write   # 20 × 200, проверка механики

Зачем. Абсолютные числа бенчмарков разных команд несопоставимы: у каждой свой мир, шум и функция истины. Наш строгий
протокол (`make bench`, 200 × 2000, docs/validation/MATCHING_BENCH.md) не меняется; здесь тот же код ранжирования
(`matching_bench.run_methods` → `ranking.score_candidate`, порядок `platform_orders`) пересчитан в условиях, которые
описали сами авторы других бенчмарков в открытых документах: размер мира, шкала релевантности 0–3 или 0–2, правило
«релевантен», те же метрики P@5, P@10, nDCG@10 (gain = 2^rel − 1, идеальный порядок — по всем кандидатам мира), MRR.

Условия (по документам авторов; их код не запускался и не копировался — правила переписаны по описанию):
* «Прототип А» (внешний репозиторий, docs/matching.md §6): 60 потребностей × 600 кандидатов, метка 0–3 по полезности
  найма, релевантен — метка ≥ 2;
* Прототип Б (внешний автор, docs/validation.md §2): 40 вакансий × 1000 кандидатов, метка 0–2, релевантен — метка 2.
Для каждого — два мира: «их размер и шкала, наш шум» (наши кандидаты и тест, σθ = 0,48) и «их размер, шкала и шум»
(параметры шума из их описания: погрешность теста, доли завышения грейда и приписок, распределение уровней).

Диагностика «почему nDCG@10 ниже MRR» — для каждого мира: состав топ-10 по меткам против идеального, nDCG@10 при
пересортировке своего топ-10 по истине, потолок при знании истины внутри ярусов выдачи, линейная и бинарная шкалы,
ничьи, где лежат кандидаты с меткой 3.

Ограничение: синтетика проверяет механику подбора, а не реальный рынок; чужой мир воспроизведён по описанию, а не
кодом, поэтому совпадение условий — приближённое (различия перечислены в отчёте).
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

from app.modules.matching.ranking import WEIGHTS, algorithm
from app.modules.validation import matching_bench as mb
from app.modules.validation.bench_world import BenchConfig, World, bank_blocks, generate
from app.modules.validation.signature import config_hash, signature

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
DOCS_JSON = REPO / "docs" / "validation" / "matching_compare.json"
DOCS_MD = REPO / "docs" / "validation" / "MATCHING_COMPARE.md"
DATA_OUT = HERE / "data" / "matching_compare.json"
COMPARE_VERSION = "compare-v1"
METRICS4 = ("p@5", "p@10", "ndcg@10", "mrr")
SEED = BenchConfig.seed
EXTRA_SEEDS = (SEED + 1, SEED + 2)  # устойчивость: те же условия, другие миры (только платформа и BM25)
METHODS_MAIN = ("platform", "bm25", "keywords_grade", "random", "no_test", "no_guard")

FT_URL = "(адрес внешнего репозитория скрыт)"
ITM_URL = "(адрес внешнего репозитория скрыт)"
OURS_MD = "MATCHING_BENCH.md"

# Опубликованные авторами числа (их мир, их код) — только для подписи рядом, не наш расчёт
PUBLISHED = {
    "ft": {"title": "«Прототип А» (внешний автор)", "url": FT_URL, "world": "60 потребностей × 600 кандидатов, seed 11",
           "rows": [
               {"method": "Их подбор (сбалансированный профиль)", "p@5": 0.880, "p@10": 0.807, "ndcg@10": 0.808, "mrr": 0.933},
               {"method": "Ключевые слова + заявленный грейд", "p@5": 0.700, "p@10": 0.608, "ndcg@10": 0.692, "mrr": 0.817},
               {"method": "Поиск по ключевым словам резюме", "p@5": 0.377, "p@10": 0.412, "ndcg@10": 0.461, "mrr": 0.655},
               {"method": "Случайный (та же специализация)", "p@5": 0.193, "p@10": 0.202, "ndcg@10": 0.168, "mrr": 0.311},
           ]},
    "itm": {"title": "Прототип Б (внешний автор)", "url": ITM_URL, "world": "40 вакансий × 1000 кандидатов, seed 2026",
            "rows": [
                {"method": "Их подбор", "p@5": 0.755, "p@10": 0.775, "ndcg@10": 0.83, "mrr": None},
                {"method": "По резюме (заявленное)", "p@5": 0.635, "p@10": 0.648, "ndcg@10": 0.75, "mrr": None},
                {"method": "Случайный порядок", "p@5": 0.045, "p@10": 0.053, "ndcg@10": 0.07, "mrr": None},
            ]},
}

# Миры. Наш строгий протокол — отдельной строкой в размере 60 × 600 (как в анализе чувствительности MATCHING_BENCH.md).
FT_NOISE = {"dirs": ("backend", "frontend", "data_ml", "qa"), "need_grade_p": (0.0, 0.25, 0.45, 0.30),
            "theta_model": "bands", "band_p": (0.35, 0.40, 0.25), "band_top": 2.3, "t0_model": "claims",
            "claim_over": 0.30, "claim_under": 0.10, "claim_stuff": 0.40, "claim_stuff_n": (1, 3), "claim_omit": 0.10,
            "theta_sigma": 0.33, "se_reported": 0.33, "fsp_base": 0.0}
ITM_NOISE = {"t0_model": "claims", "claim_over": 0.25, "claim_under": 0.10, "claim_stuff": 0.35, "claim_stuff_n": (4, 4),
             "claim_omit": 0.0}
VARIANTS = {
    "grade_cap": {"title": "Флаг MATCH_GRADE_CAP: тест не даёт бонуса выше порога следующего грейда",
                  "env": {"MATCH_GRADE_CAP": "1"}, "where": "продукт, флаг выключен по умолчанию"},
    "w_req45_fsp05": {"title": "Веса: тест 0,40 · обязательное 0,45 · ФСП 0,05 (подобранные на синтетике)",
                      "weights": {"test": 0.40, "stack_required": 0.45, "stack_desired": 0.05, "fsp": 0.05,
                                  "probe": 0.05}, "where": "только стенд"},
    "w_req40": {"title": "Веса: тест 0,40 · обязательное 0,40 · ФСП 0,10 (ФСП не трогаем)",
                "weights": {"test": 0.40, "stack_required": 0.40, "stack_desired": 0.05, "fsp": 0.10, "probe": 0.05},
                "where": "только стенд"},
}
CONDITIONS = [
    {"id": "ours_strict", "other": None, "strict": True, "title": "Наш строгий протокол, 200 × 2000",
     "text": "Как `make bench`: наша истина и шум; здесь — только продукт, BM25 и варианты порядка (правило «не хуже»)",
     "cfg": {}},
    {"id": "ours_60x600", "other": None, "title": "Наш строгий протокол, мир 60 × 600",
     "text": "Наша истина «может выполнять работу» (0–3), наш шум; размер — как у «Прототип А»",
     "cfg": {"n_needs": 60, "n_candidates": 600}},
    {"id": "ft_scale", "other": "ft", "title": "«Прототип А»: их размер и шкала, наш шум",
     "text": "60 × 600, метка 0–3 по их правилу полезности найма, релевантен — ≥ 2; кандидаты, тест и резюме — наши",
     "cfg": {"n_needs": 60, "n_candidates": 600, "truth": "ft"}},
    {"id": "ft_world", "other": "ft", "title": "«Прототип А»: их размер, шкала и шум",
     "text": "То же + шум из их описания: 4 направления, уровни Junior/Middle/Senior 35/40/25 % (θ* равномерно в полосе), "
             "погрешность теста 0,33, завышают грейд 30 %, занижают 10 %, приписывают 1–3 навыка своего направления 40 %, "
             "не указывают 10 % своих навыков, ФСП у ~50 %, потребности Junior/Middle/Senior 25/45/30 %",
     "cfg": {"n_needs": 60, "n_candidates": 600, "truth": "ft", **FT_NOISE}},
    {"id": "itm_scale", "other": "itm", "title": "Прототип Б: их размер и шкала, наш шум",
     "text": "40 × 1000, метка 0–2 по их правилу (2 — то же направление, точный истинный грейд, есть нужная технология), "
             "3 технологии в вакансии; кандидаты, тест и резюме — наши",
     "cfg": {"n_needs": 40, "n_candidates": 1000, "truth": "itm", "need_required": (3, 3)}},
    {"id": "itm_world", "other": "itm", "title": "Прототип Б: их размер, шкала и шум",
     "text": "То же + шум из их описания: завышают грейд 25 %, занижают 10 %, 35 % дописывают 4 популярные технологии, "
             "которых не знают",
     "cfg": {"n_needs": 40, "n_candidates": 1000, "truth": "itm", "need_required": (3, 3), **ITM_NOISE}},
]
MAIN_TITLES = {"platform": "Наш подбор (продукт, без изменений)", "bm25": "BM25 по тексту резюме",
               "keywords_grade": "Теги резюме + заявленный грейд", "random": "Случайный порядок",
               "no_test": "Без теста: только самоописание (T0)",
               "no_guard": "Заявленное засчитано как подтверждённое (в продукте выключено)"}

PROTOCOL_DIFF = [
    ("Мир", "200 потребностей × 2000 кандидатов, 5 направлений, 4 грейда со Стажёром",
     "60 × 600, 4 специализации, 3 грейда", "40 × 1000, грейды Стажёр … Lead"),
    ("Релевантных на потребность", "в среднем ~107 из 2000 (~5 %)", "~20 % кандидатов той же специализации "
     "(случайный порядок внутри специализации даёт P@5 0,193)", "в среднем 37,6 из 1000 (~4 %)"),
    ("Шкала", "0–3: направление; истинный грейд = запрошенному или на ступень выше → 2; ≥ 75 % обязательных → 3; "
     "< 50 % обязательных → не выше 1", "0–3 по «полезности найма»: специализация × грейд (1 / 0,75 выше / 0,45 ниже) × "
     "(0,25 + 0,75 · покрытие обязательного) × сила внутри грейда × зарплата; пороги 0,8 / 0,6 / 0,4",
     "0–2: 2 — то же направление, точный истинный грейд и хотя бы одна нужная технология; 1 — соседний грейд "
     "с технологией или точный без неё"),
    ("Релевантен", "метка ≥ 2", "метка ≥ 2", "метка 2"),
    ("Идеальный порядок (IDCG)", "все кандидаты мира по истинной метке, gain 2^rel − 1", "то же", "то же (максимум — метка 2)"),
    ("Что надо угадать для метки 3", "реальное владение ≥ 75 % обязательных навыков — тест видит только часть",
     "покрытие обязательного и сила внутри грейда", "метки 3 нет: достаточно одной нужной технологии"),
    ("Погрешность теста", "σθ = 0,48 (RMSE нашего адаптивного теста в симуляции)", "SE ≈ 0,33 (форма из 20 заданий)",
     "симуляция 3PL, 15 заданий"),
    ("Шум резюме", "20 % «раздутых» (грейд +1, 4–8 лишних навыков, повтор слов), 15 % «скромных»",
     "40 % приписывают до 3 навыков своей области, 10 % пропусков, 30 % завышают грейд, 10 % занижают",
     "35 % дописывают 4 популярные технологии, 25 % завышают грейд, 10 % занижают"),
    ("Что подбор берёт из резюме", "ничего: заявленное (T0) в скор не входит (защита от раздувания)",
     "заявленные навыки × доказательность теста (0,75 + 0,25 · балл компетенции)", "заявленные навыки и грейд, тест"),
    ("Фильтры выдачи", "нет: ранжируется весь мир, ярусы — категория из теста, ядро роли, обязательное",
     "несмежная специализация, разница грейдов ≥ 2, итог < 35 %", "нет: ранжируется весь мир"),
    ("ДИ", "бутстреп по потребностям, 95 %", "нет", "нет; три seed"),
]


# ---------------------------------------------------------------- диагностика: почему nDCG@10 ниже MRR

def _auc(x: np.ndarray, y: np.ndarray) -> float | None:
    y = y.astype(bool)
    if y.all() or not y.any():
        return None
    r = np.argsort(np.argsort(x, kind="stable"), kind="stable") + 1.0
    # средние ранги для равных значений
    xs, inv = np.unique(x, return_inverse=True)
    if len(xs) < len(x):
        sums = np.bincount(inv, weights=r)
        cnt = np.bincount(inv)
        r = (sums / cnt)[inv]
    n1 = y.sum()
    return round(float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * (~y).sum())), 3)


def diagnostics(world: World, reqs: list[dict], sc: dict, order: np.ndarray) -> dict:
    """Разбор nDCG@10 при высоком MRR: состав топ-10, порядок внутри топ-10, шкала, ничьи, ярусы, что видит тест."""
    rel = world.rel.astype(int)
    n = rel.shape[0]
    disc = 1 / np.log2(np.arange(2, 12))
    top = np.take_along_axis(rel, order[:, :10], axis=1)
    ideal = np.sort(rel, axis=1)[:, ::-1][:, :10]
    idcg = ((2.0 ** ideal - 1) * disc).sum(1)
    ok = idcg > 0

    def nd(g: np.ndarray, gi: np.ndarray) -> float:
        num, den = (g * disc).sum(1), (gi * disc).sum(1)
        return round(float(np.where(den > 0, num / np.maximum(den, 1e-12), 0).mean()), 3)

    resorted = np.sort(top, axis=1)[:, ::-1]
    vis = sc["vis"]
    oracle = np.stack([np.lexsort((-rel[i], -vis[i])) for i in range(n)])
    pn_or = mb.per_need(world.rel, oracle)
    s = mb.weighted(sc, np.array([WEIGHTS[k] for k in mb.COMP_KEYS]))
    ts = np.take_along_axis(s, order[:, :10], axis=1)
    ties = float((np.abs(np.diff(ts, axis=1)) < 1e-9).mean())
    lab3 = rel == 3
    where3 = {name: round(float((lab3 & (vis == t)).sum() / max(lab3.sum(), 1)), 3)
              for name, t in (("exact_category", 2), ("other_category", 1), ("no_category", 0))}
    # что видит тест о навыках: внутри точной категории потребности (с обязательными навыками) — насколько балл
    # продукта и только заявленное в резюме (в скор не входит) отделяют релевантных (метка ≥ 2)
    xs, x0, ys, y3 = [], [], [], []
    for i, r in enumerate(reqs):
        tags = [x["tag"] for x in r.get("stack_required") or []]
        if not tags:
            continue
        for j in np.where(vis[i] == 2)[0]:
            o = world.candidates[j].obs
            xs.append(s[i, j])
            x0.append(sum(1 for t in tags if t in o.stack_declared) / len(tags))
            ys.append(rel[i, j] >= 2)
            y3.append(rel[i, j] == 3)
    xs, x0, ys, y3 = map(np.asarray, (xs, x0, ys, y3))
    exact_rel = [float(((rel[i] >= 2) & (vis[i] == 2)).sum() / max((vis[i] == 2).sum(), 1)) for i in range(n)]
    # метка 1 в топ-10: почему не релевантен (по истине) — мало обязательных навыков или грейд
    why1 = {"low_required": 0, "grade": 0, "other": 0}
    for i, need in enumerate(world.needs):
        for j in order[i, :10]:
            if rel[i, j] != 1:
                continue
            lat = world.candidates[j].latent
            cov = (sum(1 for t in need.required if t in lat.known) / len(need.required)) if need.required else 1.0
            why1["low_required" if cov < world.config.cov_min else "grade" if lat.direction == need.direction else
                 "other"] += 1
    return {
        "top10_label_mix": [round(float(x), 3) for x in np.bincount(top.ravel(), minlength=4)[:4] / top.size],
        "ideal10_label_mix": [round(float(x), 3) for x in np.bincount(ideal.ravel(), minlength=4)[:4] / ideal.size],
        "ndcg10": round(float(np.where(ok, ((2.0 ** top - 1) * disc).sum(1) / np.maximum(idcg, 1e-12), 0).mean()), 3),
        "ndcg10_top10_resorted_by_truth": round(float(np.where(ok, ((2.0 ** resorted - 1) * disc).sum(1)
                                                              / np.maximum(idcg, 1e-12), 0).mean()), 3),
        "oracle_within_tiers": {m: round(float(pn_or[m].mean()), 3) for m in METRICS4},
        "ndcg10_linear_gain": nd(top.astype(float), ideal.astype(float)),
        "ndcg10_binary": nd((top >= 2).astype(float), (ideal >= 2).astype(float)),
        "ties_adjacent_top10": round(ties, 3),
        "label3_location": where3,
        "relevant_share_exact_category": round(float(np.mean(exact_rel)), 3),
        "label1_top10_reasons": {k: round(v / max(sum(why1.values()), 1), 3) for k, v in why1.items()},
        "auc_exact_category": {"pairs": int(len(ys)), "relevant_share": round(float(ys.mean()), 3) if len(ys) else None,
                               "score_vs_rel2": _auc(xs, ys) if len(ys) else None,
                               "score_vs_rel3": _auc(xs, y3) if len(ys) else None,
                               "declared_required_vs_rel2": _auc(x0, ys) if len(ys) else None,
                               "declared_required_vs_rel3": _auc(x0, y3) if len(ys) else None},
    }


# ---------------------------------------------------------------- прогон

def _round_metrics(m: dict) -> dict:
    return {k: m[k] for k in METRICS4 if k in m}


def scored_with_flag(world: World, reqs: list[dict], env: dict[str, str]) -> dict:
    """Скоринг продукта с флагами (через переменные окружения, как на сервере); флаги снимаются после расчёта."""
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return mb.score_world(world, reqs)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def variants(world: World, reqs: list[dict], sc: dict, seed: int) -> dict:
    """Варианты порядка против продукта на одном мире: флаг продукта (пересчёт кодом продукта) и веса (только стенд)."""
    rel = world.rel
    idx = mb.boot_idx(rel.shape[0], seed + 11)
    base = mb.per_need(rel, mb.platform_orders(sc))
    out = {}
    for vid, v in VARIANTS.items():
        if "env" in v:
            o = mb.platform_orders(scored_with_flag(world, reqs, v["env"]))
        else:
            o = mb.platform_orders(sc, np.array([v["weights"][k] for k in mb.COMP_KEYS]))
        pn = mb.per_need(rel, o)
        out[vid] = {"metrics": {m: round(float(pn[m].mean()), 3) for m in METRICS4},
                    "minus_product": {m: mb._ci(pn[m] - base[m], idx) for m in METRICS4}}
    return out


def run_condition(cond: dict, blocks: dict, quick: bool = False, extra_seeds: tuple[int, ...] = EXTRA_SEEDS) -> dict:
    cfg = replace(BenchConfig(seed=SEED), **cond["cfg"])
    if quick:
        cfg = replace(cfg, n_needs=min(cfg.n_needs, 20), n_candidates=min(cfg.n_candidates, 200))
    t0 = time.time()
    world = generate(cfg, blocks)
    reqs = mb._parsed(world)
    strict = cond.get("strict", False)
    r = mb.run_methods(world, reqs, cfg.seed, ("platform", "bm25") if strict else METHODS_MAIN)
    s = mb.summarize(world, r, cfg.seed)
    ws = mb.world_stats(world, reqs)
    out = {"id": cond["id"], "other": cond["other"], "title": cond["title"], "text": cond["text"],
           "config": cfg.to_dict(), "config_hash": config_hash(cfg.to_dict()),
           "world": {k: ws[k] for k in ("n_needs", "n_candidates", "labels", "relevant_per_need", "personas", "with_fsp",
                                        "no_category", "category_equals_true_grade", "parser")},
           "metrics": {k: _round_metrics(v) for k, v in s["metrics"].items()},
           "paired_platform_minus": s["paired_platform_minus"],
           "diagnostics": diagnostics(world, reqs, r["scored"], r["orders"]["platform"][0]),
           "variants": variants(world, reqs, r["scored"], cfg.seed)}
    out["world"]["relevant_share"] = round(float((world.rel >= 2).mean()), 4)
    seeds = []
    for sd in (() if quick else extra_seeds[:1] if strict else extra_seeds):
        c2 = replace(cfg, seed=sd)
        w2 = generate(c2, blocks)
        q2 = mb._parsed(w2)
        r2 = mb.run_methods(w2, q2, sd, ("platform", "bm25"))
        pn = {k: mb.mean_metrics(w2.rel, o) for k, o in r2["orders"].items()}
        seeds.append({"seed": sd, **{k: {m: round(float(pn[k][m].mean()), 3) for m in METRICS4} for k in pn},
                      "variants": variants(w2, q2, r2["scored"], sd)})
    out["other_seeds"] = seeds
    out["seconds"] = round(time.time() - t0, 1)
    p = out["metrics"]["platform"]
    print(f"    {cond['id']}: P@5 {p['p@5']['mean']}, P@10 {p['p@10']['mean']}, nDCG@10 {p['ndcg@10']['mean']}, "
          f"MRR {p['mrr']['mean']} ({out['seconds']} с)", flush=True)
    return out


def run(quick: bool = False, write: bool = True, only: list[str] | None = None) -> dict:
    t0 = time.time()
    blocks = bank_blocks()
    conds = [c for c in CONDITIONS if not only or c["id"] in only]
    res = []
    for i, c in enumerate(conds, 1):
        print(f"{i}/{len(conds)} {c['title']}", flush=True)
        res.append(run_condition(c, blocks, quick))
    cmd = "make match-bench-compare" if not quick else "python -m app.modules.validation.matching_compare --quick"
    rep = {"version": COMPARE_VERSION, "algorithm": algorithm(), "weights": WEIGHTS,
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "command": cmd,
           "caveat": mb.CAVEAT + " Чужие миры воспроизведены по описанию авторов, а не их кодом: совпадение условий "
                                 "приближённое.",
           "published": PUBLISHED, "protocol_diff": [dict(zip(("aspect", "ours", "ft", "itm"), row, strict=True))
                                                    for row in PROTOCOL_DIFF],
           "conditions": res, "variants": {k: {kk: vv for kk, vv in v.items()} for k, v in VARIANTS.items()},
           "signature": signature(seed=SEED, config={c["id"]: c["config_hash"] for c in res},
                                  n=sum(c["world"]["n_needs"] * c["world"]["n_candidates"] for c in res),
                                  world="подбор в сопоставимых условиях: " + ", ".join(
                                      f"{c['world']['n_needs']} × {c['world']['n_candidates']}" for c in res),
                                  command=cmd)}
    rep["not_worse"] = {vid: not_worse(rep, vid) for vid in VARIANTS}
    rep["strict_bench"] = strict_bench_reference()
    rep["seconds"] = round(time.time() - t0, 1)
    if write:
        for p in (DOCS_JSON, DATA_OUT):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        DOCS_MD.write_text(markdown(rep), encoding="utf-8")
    print(f"готово за {rep['seconds']} с" + (f" → {DOCS_MD.relative_to(REPO)}, {DOCS_JSON.relative_to(REPO)}" if write
                                            else " (без записи)"), flush=True)
    return rep


# ---------------------------------------------------------------- отчёт

_f = mb._f


def _ci(x: dict | None) -> str:
    if not x:
        return "—"
    return f"{_f(x['mean'])} [{_f(x['lo'])}; {_f(x['hi'])}]"


def _cond(rep: dict, cid: str) -> dict | None:
    return next((c for c in rep["conditions"] if c["id"] == cid), None)


def _verdict(ours: float, theirs: float | None) -> str:
    if theirs is None:
        return "—"
    d = ours - theirs
    return "выше" if d > 0.0005 else "ниже" if d < -0.0005 else "равно"


def markdown(rep: dict) -> str:
    L: list[str] = []
    a = L.append
    a("# Подбор в сопоставимых условиях")
    a("")
    a(f"Наш подбор (алгоритм {rep['algorithm']}, веса и код продукта без изменений) пересчитан в условиях открытых "
      f"бенчмарков двух других команд: тот же размер мира, та же шкала релевантности, те же метрики P@5, P@10, nDCG@10, "
      f"MRR. Пересчёт: `{rep['command']}` ({rep['seconds']:.0f} с). Наш строгий протокол — "
      f"[{OURS_MD}]({OURS_MD}) (200 × 2000), он не меняется.")
    a("")
    a(f"> {rep['caveat']} Числа — синтетика (модель, не люди).")
    a("")
    a("## Выводы")
    a("")
    for line in conclusions(rep):
        a(f"* {line}")
    a("")
    a("## Итог: в их условиях")
    a("")
    a("| Условия | P@5 | P@10 | nDCG@10 | MRR | Их опубликованные числа (их мир) |")
    a("|---|---|---|---|---|---|")
    for c in rep["conditions"]:
        p = c["metrics"]["platform"]
        pub = ""
        if c["other"]:
            r0 = rep["published"][c["other"]]["rows"][0]
            pub = (f"P@5 {_f(r0['p@5'])}, P@10 {_f(r0['p@10'])}, nDCG@10 {_f(r0['ndcg@10'], 2 if c['other'] == 'itm' else 3)}"
                   + (f", MRR {_f(r0['mrr'])}" if r0["mrr"] is not None else ", MRR не считали"))
        a(f"| {c['title']} | {_ci(p['p@5'])} | {_ci(p['p@10'])} | {_ci(p['ndcg@10'])} | {_ci(p['mrr'])} | {pub or '—'} |")
    a("")
    a("95 % ДИ — бутстреп по потребностям. Опубликованные числа получены авторами на их мире и их кодом; наш расчёт — на "
      "мире, построенном по их описанию. Поэтому честное сравнение — «наш подбор против базовых линий в одном мире» и "
      "«наш подбор в их условиях против их опубликованного», а не «наш строгий протокол против их чисел».")
    a("")
    for comp in ("ft", "itm"):
        pub = rep["published"][comp]
        a(f"## {pub['title']}: методы в одном мире")
        a("")
        a(f"Опубликовано авторами ([документ]({pub['url']}), {pub['world']}):")
        a("")
        a("| Метод (их расчёт) | P@5 | P@10 | nDCG@10 | MRR |")
        a("|---|---|---|---|---|")
        for r in pub["rows"]:
            a(f"| {r['method']} | {_f(r['p@5'])} | {_f(r['p@10'])} | {_f(r['ndcg@10'], 2 if comp == 'itm' else 3)} | "
              f"{_f(r['mrr']) if r['mrr'] is not None else 'не считали'} |")
        a("")
        for c in [x for x in rep["conditions"] if x["other"] == comp]:
            a(f"**{c['title']}.** {c['text']}. Релевантных на потребность: в среднем "
              f"{_f(c['world']['relevant_per_need']['mean'], 1)} (от {c['world']['relevant_per_need']['min']} до "
              f"{c['world']['relevant_per_need']['max']}), доля релевантных пар {_f(c['world']['relevant_share'], 3)}.")
            a("")
            a("| Метод (наш расчёт) | P@5 | P@10 | nDCG@10 | MRR |")
            a("|---|---|---|---|---|")
            for k, title in MAIN_TITLES.items():
                if k in c["metrics"]:
                    m = c["metrics"][k]
                    a(f"| {title} | {_ci(m['p@5'])} | {_ci(m['p@10'])} | {_ci(m['ndcg@10'])} | {_ci(m['mrr'])} |")
            a("")
            if c["other_seeds"]:
                a("Другие миры тех же условий (платформа / BM25): " + "; ".join(
                    f"seed {x['seed']}: P@5 {_f(x['platform']['p@5'])} / {_f(x['bm25']['p@5'])}, nDCG@10 "
                    f"{_f(x['platform']['ndcg@10'])} / {_f(x['bm25']['ndcg@10'])}, MRR {_f(x['platform']['mrr'])}"
                    for x in c["other_seeds"]) + ".")
                a("")
            pm = c["paired_platform_minus"]
            a("Разница «наш подбор − метод», nDCG@10 (парный бутстреп): " + "; ".join(
                f"{MAIN_TITLES[k]} {mb._signed(pm[k]['ndcg@10'])}" for k in MAIN_TITLES if k in pm) + ".")
            a("")
    a("## Чем различаются протоколы")
    a("")
    a(f"| | Наш строгий протокол | «Прототип А» ([docs]({FT_URL})) | Прототип Б ([docs]({ITM_URL})) |")
    a("|---|---|---|---|")
    for r in rep["protocol_diff"]:
        a(f"| {r['aspect']} | {r['ours']} | {r['ft']} | {r['itm']} |")
    a("")
    a("Чего нет в нашем воспроизведении их мира: смежных специализаций, графа близких навыков (FastAPI ≈ Flask) и "
      "зарплат — в нашем мире этих сущностей нет, соответствующие множители их шкалы равны 1 (или 0 для другой "
      "специализации); у Прототип Б — грейда Lead (у нас четыре грейда). Наш подбор ранжирует весь мир (без порога 35 % "
      "и без отсечения по разнице грейдов); P@k везде делится на k.")
    a("")
    a("## Почему nDCG@10 ниже MRR")
    a("")
    a("| Условия | Метки 0/1/2/3 в нашем топ-10 | В идеальном топ-10 | nDCG@10 | Топ-10 пересортирован по истине | "
      "Потолок: истина внутри ярусов | Линейная шкала | Бинарная | Ничьи в топ-10 |")
    a("|---|---|---|---|---|---|---|---|---|")
    for c in rep["conditions"]:
        d = c["diagnostics"]
        mix = " / ".join(_pct(x) for x in d["top10_label_mix"])
        imix = " / ".join(_pct(x) for x in d["ideal10_label_mix"])
        a(f"| {c['title']} | {mix} | {imix} | {_f(d['ndcg10'])} | {_f(d['ndcg10_top10_resorted_by_truth'])} | "
          f"{_f(d['oracle_within_tiers']['ndcg@10'])} | {_f(d['ndcg10_linear_gain'])} | {_f(d['ndcg10_binary'])} | "
          f"{_pct(d['ties_adjacent_top10'])} |")
    a("")
    a("| Условия | Метка 3: в точной категории / в другой / без категории | Релевантных в точной категории | "
      "AUC балла продукта (≥ 2 / = 3) | AUC заявленного в резюме, в скор не входит (≥ 2 / = 3) |")
    a("|---|---|---|---|---|")
    for c in rep["conditions"]:
        d = c["diagnostics"]
        l3 = d["label3_location"]
        au = d["auc_exact_category"]
        a(f"| {c['title']} | {_pct(l3['exact_category'])} / {_pct(l3['other_category'])} / {_pct(l3['no_category'])} | "
          f"{_pct(d['relevant_share_exact_category'])} | {_f(au['score_vs_rel2'])} / {_f(au['score_vs_rel3'])} | "
          f"{_f(au['declared_required_vs_rel2'])} / {_f(au['declared_required_vs_rel3'])} |")
    a("")
    st = _cond(rep, "ours_strict") or rep["conditions"][0]
    d = st["diagnostics"]
    pm = st["metrics"]["platform"]
    a(f"Как читать (строка «{st['title']}»). MRR {_f(pm['mrr']['mean'])} — место первого релевантного (метка ≥ 2): в "
      f"точной категории потребности релевантны {_pct(d['relevant_share_exact_category'])} кандидатов, поэтому первый "
      f"релевантный почти всегда в первых строках. nDCG@10 {_f(d['ndcg10'])} со шкалой 2^rel − 1 требует в топ-10 именно "
      f"метку 3 (вес 7 против 3 у метки 2 и 1 у метки 1): в нашем топ-10 меток 3 — {_pct(d['top10_label_mix'][3])}, в "
      f"идеальном — {_pct(d['ideal10_label_mix'][3])}; меток 1 — {_pct(d['top10_label_mix'][1])}"
      + (f" (из них {_pct(d['label1_top10_reasons']['low_required'])} реально владеют меньше чем "
         f"{_pct(st['config'].get('cov_min', 0.5))} обязательных навыков)" if "label1_top10_reasons" in d else "")
      + ".")
    a("")
    a(f"* Порядок внутри топ-10: если переставить наши же 10 кандидатов по истине, nDCG@10 "
      f"{_f(d['ndcg10'])} → {_f(d['ndcg10_top10_resorted_by_truth'])}. Ничьих в топ-10 — {_pct(d['ties_adjacent_top10'])}: "
      f"порядок не случайный.")
    a(f"* Состав топ-10: если знать истину внутри тех же ярусов выдачи (категория из теста, ядро, обязательное), "
      f"nDCG@10 {_f(d['oracle_within_tiers']['ndcg@10'])}, P@5 {_f(d['oracle_within_tiers']['p@5'])} — главный разрыв в том, "
      f"кого мы берём в топ-10, а не в порядке внутри него.")
    a(f"* Шкала: та же выдача в линейной шкале (gain = rel) — {_f(d['ndcg10_linear_gain'])}, в бинарной (релевантен / нет) — "
      f"{_f(d['ndcg10_binary'])}: экспоненциальная шкала строже к недобору меток 3.")
    a(f"* Что видит подбор: внутри точной категории балл продукта отделяет метку 3 с AUC "
      f"{_f(d['auc_exact_category']['score_vs_rel3'])}, а заявленное в резюме покрытие обязательных — "
      f"{_f(d['auc_exact_category']['declared_required_vs_rel3'])}. Заявленное (T0) мы в балл намеренно не берём: в "
      f"нашем мире 20 % резюме раздуты, и атака «дописать навыки вакансии» не должна поднимать в выдаче "
      f"([{OURS_MD}]({OURS_MD}), абляция «заявленное как подтверждённое»). Тест подтверждает навыки выборочно — задания "
      f"сессии покрывают часть обязательных навыков конкретной потребности; честный рычаг — больше доказательств по "
      f"обязательным навыкам (дотестирование, зонд работодателя), а не перестановка.")
    a("")
    a("## Что улучшает порядок: варианты и правило «не хуже»")
    a("")
    a("Разница «вариант − продукт» на тех же мирах (парный бутстреп по потребностям, 95 % ДИ). Правило «не хуже»: "
      "на нашем строгом протоколе (оба мира 200 × 2000) P@5 и MRR не ниже продукта; три числа на вакансиях hh от "
      "порядка выдачи не зависят (разбор текста и пул кандидатов те же).")
    a("")
    a("| Мир | " + " | ".join(f"{v['title']} ({v['where']})" for v in VARIANTS.values()) + " |")
    a("|---|" + "---|" * len(VARIANTS))
    for c in rep["conditions"]:
        rows = [(c["title"] + f", seed {c['config']['seed']}", c["variants"])] + [
            (f"{c['title']}, seed {x['seed']}", x["variants"]) for x in c["other_seeds"] if "variants" in x]
        for title, vv in rows:
            cells = []
            for vid in VARIANTS:
                dd = vv[vid]["minus_product"]
                cells.append(" / ".join(mb._signed(dd[m]).split(" [")[0] for m in ("p@5", "ndcg@10", "mrr")))
            a(f"| {title} | " + " | ".join(cells) + " |")
    a("")
    a("В ячейке — ΔP@5 / ΔnDCG@10 / ΔMRR (среднее по потребностям); 95 % ДИ каждой разницы — в json (`variants`).")
    a("")
    for line in verdicts(rep):
        a(f"* {line}")
    a("")
    a("Полные данные: `docs/validation/matching_compare.json`.")
    a("")
    return "\n".join(L)


def _pct(v) -> str:
    return "—" if v is None else f"{round(v * 100)} %"


def strict_bench_reference() -> dict | None:
    """Строгий протокол (make bench) из его записанного json: методы и доля «раздутых» в топ-10 — для выводов."""
    path = REPO / "docs" / "validation" / "matching_bench.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    keep = ("platform", "bm25", "keywords_grade", "no_test", "no_guard")
    return {"metrics": {k: {m: d["metrics"][k][m]["mean"] for m in METRICS4} for k in keep if k in d["metrics"]},
            "inflated": (d.get("groups") or {}).get("inflated"), "commit": (d.get("signature") or {}).get("commit")}


def conclusions(rep: dict) -> list[str]:
    out = []
    ft, itm = _cond(rep, "ft_world"), _cond(rep, "itm_world")
    pub_ft, pub_itm = rep["published"]["ft"]["rows"], rep["published"]["itm"]["rows"]
    if ft and itm:
        pf, pi = ft["metrics"]["platform"], itm["metrics"]["platform"]
        out.append(f"В их условиях наш подбор ниже опубликованных ими чисел: «Прототип А» — P@5 {_f(pf['p@5']['mean'])} "
                   f"против {_f(pub_ft[0]['p@5'])}, nDCG@10 {_f(pf['ndcg@10']['mean'])} против {_f(pub_ft[0]['ndcg@10'])}, "
                   f"MRR {_f(pf['mrr']['mean'])} против {_f(pub_ft[0]['mrr'])}; Прототип Б — P@10 {_f(pi['p@10']['mean'])} "
                   f"против {_f(pub_itm[0]['p@10'])}, nDCG@10 {_f(pi['ndcg@10']['mean'])} против {_f(pub_itm[0]['ndcg@10'], 2)} "
                   f"(их размер, шкала и шум; другие seed — в разделах ниже).")
        kf, ki = ft["metrics"]["keywords_grade"], itm["metrics"]["keywords_grade"]
        out.append(f"Их мир воспроизведён близко к описанию: базовая линия «ключевые слова + заявленный грейд» у нас "
                   f"P@5 {_f(kf['p@5']['mean'])}, MRR {_f(kf['mrr']['mean'])} (у них {_f(pub_ft[1]['p@5'])} и "
                   f"{_f(pub_ft[1]['mrr'])}); «по резюме» в мире Прототип Б — P@10 {_f(ki['p@10']['mean'])}, nDCG@10 "
                   f"{_f(ki['ndcg@10']['mean'])} (у них {_f(pub_itm[1]['p@10'])} и {_f(pub_itm[1]['ndcg@10'], 2)}).")
        nf, ni = ft["metrics"]["no_test"], itm["metrics"]["no_test"]
        sb = rep.get("strict_bench") or {}
        sm = sb.get("metrics") or {}
        txt = (f"Главная причина разрыва — допущение мира о резюме. В их описании самоописание информативнее нашего: "
               f"приписки мягче (до 3 навыков своего направления или 4 популярные технологии), настоящие навыки почти "
               f"всегда указаны, — и подбор по одному самоописанию в их мире сильнее нашего: P@5 {_f(nf['p@5']['mean'])} / nDCG@10 "
               f"{_f(nf['ndcg@10']['mean'])} («Прототип А») и {_f(ni['p@5']['mean'])} / {_f(ni['ndcg@10']['mean'])} "
               f"(Прототип Б). Наш подбор заявленное (T0) в балл намеренно не берёт")
        if sm.get("no_test") and sm.get("platform"):
            txt += (f": в нашем строгом мире (20 % раздутых резюме: грейд +1 и 4–8 лишних навыков) подбор по "
                    f"самоописанию даёт P@5 "
                    f"{_f(sm['no_test']['p@5'])} / nDCG@10 {_f(sm['no_test']['ndcg@10'])} против "
                    f"{_f(sm['platform']['p@5'])} / {_f(sm['platform']['ndcg@10'])} у продукта")
            inf = sb.get("inflated") or {}
            if inf.get("platform") and inf.get("no_test"):
                txt += (f", а нерелевантные «раздутые» занимают {_pct(inf['no_test']['irrelevant_inflated_top10'])} мест "
                        f"топ-10 против {_pct(inf['platform']['irrelevant_inflated_top10'])} у продукта "
                        f"([{OURS_MD}]({OURS_MD}))")
        out.append(txt + ".")
    nw = rep.get("not_worse", {}).get("grade_cap") or {}
    their = [c["variants"]["grade_cap"]["minus_product"]["ndcg@10"]["mean"] for c in rep["conditions"] if c["other"]]
    if nw.get("checked") and their:
        out.append("Второе отличие — шкала: у них кандидат на ступень выше запрошенного грейда «переквалифицирован» "
                   "(множитель 0,75 / метка 1), у нас — подходит (метка 2–3). Флаг MATCH_GRADE_CAP (тест не даёт бонуса "
                   f"выше порога следующего грейда) в их условиях даёт ΔnDCG@10 от {mb._f(min(their))} до "
                   f"{mb._f(max(their))}, но на нашем строгом протоколе ΔMRR "
                   + " / ".join(mb._f(x["mrr"]) for x in nw["deltas"])
                   + (" — правило «не хуже» не выполнено, флаг выключен." if not nw["passed"] else
                      " — правило «не хуже» выполнено."))
    b = [(c["title"], c["paired_platform_minus"]["bm25"]["ndcg@10"]) for c in rep["conditions"]
         if "bm25" in c["paired_platform_minus"]]
    if b:
        weak = [(t, x) for t, x in b if x["lo"] <= 0]
        out.append(f"В одном мире наш подбор по среднему выше BM25 по тексту резюме во всех {len(b)} условиях: ΔnDCG@10 "
                   f"от {mb._f(min(x['mean'] for _, x in b))} до {mb._f(max(x['mean'] for _, x in b))}"
                   + ("; в пределах шума (ДИ включает 0): " + "; ".join(f"{t} {mb._signed(x)}" for t, x in weak)
                      if weak else "") + ".")
    st = _cond(rep, "ours_strict")
    if st:
        d = st["diagnostics"]
        out.append(f"nDCG@10 {_f(d['ndcg10'])} при MRR {_f(st['metrics']['platform']['mrr']['mean'])} на строгом протоколе — "
                   f"из-за состава топ-10, а не порядка и не ничьих: меток 3 в нашем топ-10 {_pct(d['top10_label_mix'][3])} "
                   f"против {_pct(d['ideal10_label_mix'][3])} в идеальном; пересортировка своего топ-10 по истине — "
                   f"{_f(d['ndcg10_top10_resorted_by_truth'])}, знание истины внутри тех же ярусов — "
                   f"{_f(d['oracle_within_tiers']['ndcg@10'])} (раздел «Почему nDCG@10 ниже MRR»).")
    return out


def not_worse(rep: dict, vid: str) -> dict:
    """Правило «не хуже» на строгом протоколе: P@5 и MRR варианта не ниже продукта (по среднему) на обоих мирах."""
    c = _cond(rep, "ours_strict")
    if not c:
        return {"checked": False}
    worlds = [c["variants"]] + [x["variants"] for x in c["other_seeds"] if "variants" in x]
    d = [{m: w[vid]["minus_product"][m]["mean"] for m in METRICS4} for w in worlds]
    ok = all(x["p@5"] >= 0 and x["mrr"] >= 0 for x in d)
    return {"checked": True, "passed": ok, "worlds": len(d), "deltas": d}


def verdicts(rep: dict) -> list[str]:
    out = []
    for vid, v in VARIANTS.items():
        nw = not_worse(rep, vid)
        if not nw["checked"]:
            continue
        their = [c["variants"][vid]["minus_product"]["ndcg@10"]["mean"] for c in rep["conditions"] if c["other"]]
        out.append(f"{v['title']} ({v['where']}): на строгом протоколе ΔP@5 "
                   + " / ".join(mb._f(x["p@5"]) for x in nw["deltas"]) + ", ΔMRR "
                   + " / ".join(mb._f(x["mrr"]) for x in nw["deltas"]) + ", ΔnDCG@10 "
                   + " / ".join(mb._f(x["ndcg@10"]) for x in nw["deltas"])
                   + (f"; в чужих условиях ΔnDCG@10 от {mb._f(min(their))} до {mb._f(max(their))}. " if their else ". ")
                   + (("Правило «не хуже» выполнено" if nw["passed"] else "Правило «не хуже» не выполнено")
                      + ("; это проверка на стенде: веса подобраны на той же синтетике (подгонка под нашу же истину), "
                         "в продукт без данных о людях не переносим." if "weights" in v else
                         "." if nw["passed"] else " — флаг в продукте остаётся выключенным.")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Подбор в сопоставимых условиях (миры по описанию чужих бенчмарков)")
    ap.add_argument("--quick", action="store_true", help="20 × 200 без дополнительных seed (проверка механики)")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--only", nargs="*", help="id условий (по умолчанию все)")
    ap.add_argument("--md-only", action="store_true", help="только пересобрать MATCHING_COMPARE.md из сохранённого json")
    a = ap.parse_args()
    if a.md_only:
        rep = json.loads(DOCS_JSON.read_text(encoding="utf-8"))
        if "strict_bench" not in rep:
            rep["strict_bench"] = strict_bench_reference()
            for p in (DOCS_JSON, DATA_OUT):
                p.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        DOCS_MD.write_text(markdown(rep), encoding="utf-8")
        print(f"→ {DOCS_MD.relative_to(REPO)}")
        return 0
    run(quick=a.quick, write=not a.no_write, only=a.only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
