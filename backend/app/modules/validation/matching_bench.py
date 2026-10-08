"""Бенчмарк подбора со скрытой истиной: N потребностей × M кандидатов синтетического мира (bench_world).

    make bench          # cd backend && python -m app.modules.validation.matching_bench
    python -m app.modules.validation.matching_bench --needs 200 --candidates 2000 --seed 20261006 [--quick]

Что проверяется. Мир генерируется с латентной истиной (bench_world.Latent), функция истинной релевантности
задана явно (bench_world.true_relevance). Платформа ранжирует так же, как в продукте: текст потребности разбирает
need_parser, выдача — фильтр по категории из теста, внутри — ranking.score_candidate по Bundle, собранному только из
наблюдаемого (T0/T1/T2). Истину ранжирование не видит.

Методы: платформа; базовые линии — BM25 по тексту резюме, теги резюме + заявленный грейд, случайный порядок;
абляции — без теста (только T0), только грейд, без ФСП, без защиты от раздувания (заявленное = подтверждённое).
Метрики: p@5, p@10, nDCG@5, nDCG@10 (gain = 2^rel − 1), MRR; 95 % ДИ — бутстреп по потребностям (2000 выборок),
для разниц — парный бутстреп. Веса: подбор по сетке на половине потребностей, отчёт на второй половине и на втором
мире с другим seed (без утечки). Чувствительность: σθ, доля «раздутых», ФСП без связи с умением.

Ограничение: синтетика проверяет механику подбора, а не реальный рынок; экспертная разметка пар — отдельная
проверка на людях.

Результаты: docs/validation/matching_bench.json (полный), docs/validation/MATCHING_BENCH.md (кратко),
app/modules/validation/data/matching_bench.json (сводка для /validation).
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

from app.modules.catalog.seed_data import GRADE_ORDER
from app.modules.matching.need_parser import parse_need
from app.modules.matching.ranking import ALGORITHM_VERSION, WEIGHTS, requirement_priority, score_candidate
from app.modules.profiles.facts import PROVISIONAL_PENALTY
from app.modules.validation.bench_world import (BenchConfig, World, bank_blocks, build_bundle, generate, true_grade)
from app.modules.validation.matching_eval import _tokens, keyword_score, selection_categories
from app.modules.fsp.rating import VERSION as FSP_RATING_VERSION, POLICY as FSP_RATING_POLICY
from app.modules.validation.signature import signature

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
DATA_OUT = HERE / "data" / "matching_bench.json"
DOCS_JSON = REPO / "docs" / "validation" / "matching_bench.json"
DOCS_MD = REPO / "docs" / "validation" / "MATCHING_BENCH.md"

BENCH_VERSION = "bench-v2"  # v2 (07.10): решение по грейду — правилом банка (0,8), «Junior (предварительно)», раздел Junior
COMP_KEYS = ("test", "stack_required", "stack_desired", "fsp", "probe")  # порядок = ranking.WEIGHTS
PENALTIES = (0.0, 0.05, 0.10)  # чувствительность штрафа «предварительно» (в продукте 0,05 — решение владельца 06.10)
METRICS = ("p@5", "p@10", "ndcg@5", "ndcg@10", "mrr")
N_BOOT = 2000
SENS_SIZE = (60, 600)  # размер мира в анализе чувствительности (как у бенчмарка Прототип А), 9 вариантов
CAVEAT = ("Синтетика проверяет механику подбора — что ранжирование достаёт подходящих кандидатов из шумных данных "
          "так, как задумано, — а не реальный рынок: мир, шум и функция истины заданы нами. Экспертная разметка пар "
          "«потребность — кандидат» — отдельная проверка на людях.")
TRUTH_RULES = [
    "Направление кандидата не совпадает с направлением потребности → 0.",
    "Истинный грейд — по истинному уровню θ* и порогам платформы (−1 / 0 / 1), ниже порога Junior — ступень 0. "
    "Равен запрошенному или на ступень выше (может выполнять эту работу) → 2; на ступень ниже или на две выше "
    "(переквалифицирован) → 1; на две ниже → 0.",
    "Может выполнять работу и реально владеет ≥ 75 % обязательных навыков → 3.",
    "Владеет < 50 % обязательных навыков → не выше 1.",
    "Релевантен — метка ≥ 2. Желательные навыки, формат работы и зарплата в истину не входят.",
    "Строгий вариант (в анализе чувствительности): 2 — только точный грейд, соседний в любую сторону → 1.",
]
METHODS = {
    "platform": {"title": "Подбор платформы", "kind": "platform",
                 "text": "Как в продукте: разбор текста потребности, фильтр по категории из теста, внутри — скор по "
                         "T1/T2 (ranking.score_candidate), веса продукта"},
    "bm25": {"title": "BM25 по тексту резюме", "kind": "baseline",
             "text": "Okapi BM25 (k1 = 1,2, b = 0,75) по тексту резюме и тексту потребности, без категорий и теста"},
    "keywords_grade": {"title": "Теги резюме + заявленный грейд", "kind": "baseline",
                       "text": "Сначала совпадение заявленных направления и грейда, затем число заявленных тегов "
                               "потребности (обязательные ×2)"},
    "random": {"title": "Случайный порядок", "kind": "baseline", "text": "Среднее по 20 случайным перестановкам"},
    "no_test": {"title": "Без теста: только самоописание (T0)", "kind": "ablation",
                "text": "Та же функция скоринга, но категория — по заявленному грейду, заявленные навыки считаются "
                        "подтверждёнными, результата теста и ФСП нет"},
    "grade_only": {"title": "Только грейд из теста", "kind": "ablation",
                   "text": "Фильтр по категории из теста, внутри категории — случайный порядок (20 перестановок)"},
    "no_fsp": {"title": "Без ФСП", "kind": "ablation", "text": "Скор платформы без бонуса ФСП (вес 0,10 → 0)"},
    "no_theta": {"title": "Без θ теста в скоре", "kind": "ablation",
                 "text": "Категория из теста остаётся, но вклад θ в скор обнулён (вес 0,45 → 0, вес стека на θ не "
                         "переходит): внутри категории — стек, ФСП, зонды"},
    "no_stack": {"title": "Без стека", "kind": "ablation",
                 "text": "Обязательный и желательный стек не входят в скор (веса 0,35 и 0,05 → 0)"},
    "no_tier": {"title": "Без яруса грейда", "kind": "ablation",
                "text": "Нет первичной сортировки по категории потребности: все кандидаты с категорией — по одному скору"},
    "no_guard": {"title": "Без защиты от раздувания", "kind": "ablation",
                 "text": "Заявленные в резюме навыки (T0) засчитываются как подтверждённые тестом. В продукте "
                         "заявленное в скор не входит и помечено «заявлено — не влияет на ранжирование»"},
}


# ---------------------------------------------------------------- скоринг

def _parsed(world: World) -> list[dict]:
    return [parse_need(n.text, use_llm=False) for n in world.needs]


def _vis(bundles, reqs) -> np.ndarray:
    """2 — в категории потребности (как build_selection), 1 — другая категория, 0 — категории нет (не виден)."""
    cats = np.array([b.profile.current_category_id or "" for b in bundles])
    out = np.zeros((len(reqs), len(bundles)), dtype=np.int8)
    has = cats != ""
    for i, r in enumerate(reqs):
        ok = selection_categories(r)
        inc = has if ok is None else np.isin(cats, sorted(ok))
        out[i] = np.where(inc, 2, np.where(has, 1, 0))
    return out


def score_world(world: World, reqs: list[dict], mode: str = "platform") -> dict:
    """Компоненты скоринга продукта по всем парам. Скор пересобирается из компонент и сверяется с продуктом."""
    bundles = [build_bundle(c.obs, mode) for c in world.candidates]
    n, m = len(reqs), len(bundles)
    comps = np.zeros((n, m, len(COMP_KEYS)))
    prod = np.zeros((n, m))
    for i, r in enumerate(reqs):
        for j, b in enumerate(bundles):
            s, c, _ = score_candidate(b, r)
            prod[i, j] = s
            comps[i, j] = [c[k] for k in COMP_KEYS]
    has_req = np.array([bool(r.get("stack_required")) for r in reqs])
    out = {"comps": comps, "has_req": has_req, "vis": _vis(bundles, reqs),
           "mandatory_gaps": np.array([[requirement_priority(b, r) for b in bundles] for r in reqs]),
           "rating": np.array([b.profile.rating_score or 0.0 for b in bundles]),
           "ref_rank": np.argsort(np.argsort([b.profile.public_ref for b in bundles])),
           "provisional": np.array([1.0 if b.provisional else 0.0 for b in bundles]),  # «Junior (предварительно)»
           "bundles": bundles}
    rebuilt = weighted(out, np.array([WEIGHTS[k] for k in COMP_KEYS]))
    out["max_rebuild_error"] = float(np.abs(rebuilt - prod).max()) if n else 0.0
    assert out["max_rebuild_error"] < 1e-3, "скор из компонент не совпал с ranking.score_candidate"
    return out


def weighted(sc: dict, w: np.ndarray, penalty: float = PROVISIONAL_PENALTY, transfer: bool = True) -> np.ndarray:
    """Скор продукта по весам w (порядок COMP_KEYS); нет обязательного стека — его вес переходит на тест
    (transfer=False — не переходит, для абляции «без θ»); «Junior (предварительно)» — минус penalty (в продукте 0,05)."""
    w_b = w.copy()
    if transfer:
        w_b[0] += w_b[1]
    w_b[1] = 0.0
    raw = np.where(sc["has_req"][:, None], sc["comps"] @ w, sc["comps"] @ w_b)
    return np.round(raw - penalty * sc["provisional"][None, :], 4)


def platform_orders(sc: dict, w: np.ndarray | None = None, penalty: float = PROVISIONAL_PENALTY, *,
                    experimental: bool = False, transfer: bool = True, tier: bool = True) -> np.ndarray:
    """Порядок как в build_selection: категория → −скор (со штрафом «предварительно») → −рейтинг → public_ref;
    эксперимент «сначала без пробелов в обязательных навыках» (И8) включается только явно."""
    s = weighted(sc, np.array([WEIGHTS[k] for k in COMP_KEYS]) if w is None else w, penalty, transfer)
    gaps = sc.get("mandatory_gaps", np.zeros_like(s)) if experimental else np.zeros_like(s)
    # без яруса (абляция): кандидаты с категорией — одним списком по скору, без категории — в конце (их не видно)
    vis = sc["vis"] if tier else np.minimum(sc["vis"], 1)
    return np.stack([np.lexsort((sc["ref_rank"], -sc["rating"], -s[i], gaps[i], -vis[i]))
                     for i in range(len(s))])


class BM25Matrix:
    """Okapi BM25 (k1 = 1,2, b = 0,75) — та же формула и токенизация, что matching_eval.BM25, векторно по документам."""

    def __init__(self, docs: list[str], k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.tf = [Counter(_tokens(t)) for t in docs]
        dl = np.array([sum(c.values()) for c in self.tf], dtype=float)
        self.norm = k1 * (1 - b + b * dl / (dl.mean() if len(dl) else 1.0))
        df = Counter(t for c in self.tf for t in c)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self._col: dict[str, np.ndarray] = {}

    def scores(self, query: str) -> np.ndarray:
        s = np.zeros(len(self.tf))
        for t in sorted(set(_tokens(query))):  # порядок фиксирован: сумма не зависит от хеш-сида
            if t not in self.idf:
                continue
            f = self._col.get(t)
            if f is None:
                f = self._col[t] = np.array([c.get(t, 0) for c in self.tf], dtype=float)
            s += self.idf[t] * f * (self.k1 + 1) / (f + self.norm)
        return s


# ---------------------------------------------------------------- метрики

def per_need(rel: np.ndarray, order: np.ndarray) -> dict[str, np.ndarray]:
    """Метрики по каждой потребности. rel (n, m) — истина 0..3, order (n, m) — индексы кандидатов по местам."""
    ranked = np.take_along_axis(rel, order, axis=1).astype(float)
    disc = 1 / np.log2(np.arange(2, rel.shape[1] + 2))
    gains = 2 ** ranked - 1
    ideal = 2 ** np.sort(rel, axis=1)[:, ::-1].astype(float) - 1
    out = {}
    for k in (5, 10):
        idcg = (ideal[:, :k] * disc[:k]).sum(1)
        out[f"ndcg@{k}"] = np.where(idcg > 0, (gains[:, :k] * disc[:k]).sum(1) / np.maximum(idcg, 1e-12), 0.0)
        out[f"p@{k}"] = (ranked[:, :k] >= 2).mean(1)
    hit = ranked >= 2
    first = hit.argmax(1)
    out["mrr"] = np.where(hit.any(1), 1 / (first + 1), 0.0)
    return {k: out[k] for k in METRICS}


def mean_metrics(rel: np.ndarray, orders: list[np.ndarray]) -> dict[str, np.ndarray]:
    """Среднее метрик по повторам (для методов со случайным разбиением ничьих)."""
    acc = [per_need(rel, o) for o in orders]
    return {k: np.mean([a[k] for a in acc], axis=0) for k in METRICS}


def _ci(x: np.ndarray, idx: np.ndarray) -> dict:
    boots = x[idx].mean(1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"mean": round(float(x.mean()), 3), "lo": round(float(lo), 3), "hi": round(float(hi), 3)}


def boot_idx(n: int, seed: int, b: int = N_BOOT) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, n, size=(b, n))


def _rand_orders(n: int, m: int, rng: np.random.Generator, key_fn, reps: int) -> list[np.ndarray]:
    out = []
    for _ in range(reps):
        noise = rng.random((n, m))
        out.append(np.stack([np.lexsort((noise[i], *key_fn(i))) for i in range(n)]))
    return out


def inverse_positions(order: np.ndarray) -> np.ndarray:
    pos = np.empty_like(order)
    rows = np.arange(order.shape[0])[:, None]
    pos[rows, order] = np.arange(order.shape[1])[None, :]
    return pos


def group_position(rel: np.ndarray, order: np.ndarray, mask: np.ndarray) -> float | None:
    """Средний перцентиль места (0 — вершина выдачи) релевантных кандидатов группы, среднее по потребностям."""
    pct = inverse_positions(order) / max(order.shape[1] - 1, 1)
    vals = [float(pct[i, (rel[i] >= 2) & mask].mean()) for i in range(rel.shape[0]) if ((rel[i] >= 2) & mask).any()]
    return round(float(np.mean(vals)), 4) if vals else None


def top_share(rel: np.ndarray, order: np.ndarray, mask: np.ndarray, k: int = 10, relevant: bool | None = None) -> float:
    """Доля мест топ-k, занятых группой (relevant=False — только нерелевантными из группы)."""
    top = order[:, :k]
    hit = mask[top]
    if relevant is not None:
        r = np.take_along_axis(rel, top, axis=1) >= 2
        hit = hit & (r if relevant else ~r)
    return round(float(hit.mean()), 4)


# ---------------------------------------------------------------- прогон одного мира

ALL_METHODS = tuple(METHODS)
SENS_METHODS = ("platform", "no_fsp", "no_test", "no_guard", "bm25")


def run_methods(world: World, reqs: list[dict], seed: int, methods: tuple[str, ...] = ALL_METHODS) -> dict:
    """Порядки методов (по умолчанию — всех). Для каждого — список порядков (повторы при случайных ничьих)."""
    rel = world.rel
    n, m = rel.shape
    rng = np.random.default_rng(seed + 7)
    t0 = time.process_time()
    sc = score_world(world, reqs, "platform")
    w = np.array([WEIGHTS[k] for k in COMP_KEYS])
    orders: dict[str, list[np.ndarray]] = {"platform": [platform_orders(sc)]}
    if "no_fsp" in methods:
        w_nofsp = w.copy()
        w_nofsp[COMP_KEYS.index("fsp")] = 0.0
        orders["no_fsp"] = [platform_orders(sc, w_nofsp)]
    if "no_theta" in methods:
        w_nt = w.copy()
        w_nt[COMP_KEYS.index("test")] = 0.0
        orders["no_theta"] = [platform_orders(sc, w_nt, transfer=False)]
    if "no_stack" in methods:
        w_ns = w.copy()
        w_ns[COMP_KEYS.index("stack_required")] = w_ns[COMP_KEYS.index("stack_desired")] = 0.0
        orders["no_stack"] = [platform_orders(sc, w_ns)]
    if "no_tier" in methods:
        orders["no_tier"] = [platform_orders(sc, tier=False)]
    if "no_test" in methods:
        orders["no_test"] = [platform_orders(score_world(world, reqs, "t0_only"))]
    if "no_guard" in methods:
        orders["no_guard"] = [platform_orders(score_world(world, reqs, "no_guard"))]
    if "bm25" in methods:
        bm = BM25Matrix([c.obs.resume_text for c in world.candidates])
        bm_s = np.stack([bm.scores(nd.text) for nd in world.needs])
        orders["bm25"] = _rand_orders(n, m, rng, lambda i: (-bm_s[i],), 1)
    if "keywords_grade" in methods:
        kw = np.array([[keyword_score(b, r) for b in sc["bundles"]] for r in reqs], dtype=float)
        decl = np.array([f"{c.obs.direction_declared}.{c.obs.grade_declared}" for c in world.candidates])
        dvis = np.stack([(np.isin(decl, sorted(selection_categories(r) or set(decl)))).astype(int) for r in reqs])
        orders["keywords_grade"] = _rand_orders(n, m, rng, lambda i: (-kw[i], -dvis[i]), 10)
    if "grade_only" in methods:
        orders["grade_only"] = _rand_orders(n, m, rng, lambda i: (-sc["vis"][i],), 20)
    if "random" in methods:
        orders["random"] = _rand_orders(n, m, rng, lambda i: (), 20)
    return {"orders": {k: orders[k] for k in METHODS if k in orders}, "scored": sc,
            "cpu_seconds": round(time.process_time() - t0, 1)}


ABLATIONS = ("no_theta", "no_stack", "no_fsp", "no_tier", "no_test", "bm25")


def ablations(s: dict) -> list[dict]:
    """Абляции подбора: метрика без компоненты и парная разница «полная формула − абляция» (95 % ДИ)."""
    m, pm = s["metrics"], s["paired_platform_minus"]
    out = [{"method": "platform", "p@5": m["platform"]["p@5"], "ndcg@10": m["platform"]["ndcg@10"]}]
    for k in ABLATIONS:
        if k in m:
            out.append({"method": k, "p@5": m[k]["p@5"], "ndcg@10": m[k]["ndcg@10"],
                        "diff_p@5": pm[k]["p@5"], "diff_ndcg@10": pm[k]["ndcg@10"]})
    return out


def summarize(world: World, run: dict, seed: int) -> dict:
    rel = world.rel
    idx = boot_idx(rel.shape[0], seed + 11)
    pn = {k: mean_metrics(rel, o) for k, o in run["orders"].items()}
    metrics = {k: {mt: _ci(v[mt], idx) for mt in METRICS} for k, v in pn.items()}
    paired = {}
    for other in [k for k in pn if k != "platform"]:
        paired[other] = {mt: _ci(pn["platform"][mt] - pn[other][mt], idx) for mt in ("p@5", "ndcg@10", "mrr")}
    return {"metrics": metrics, "paired_platform_minus": paired, "per_need": pn}


# ---------------------------------------------------------------- веса на отложенных данных

def weight_grid(step: float = 0.05) -> np.ndarray:
    """Сетка (тест, обязательный стек, желательный стек, ФСП) с суммой 0,95; зонды — 0,05, как в продукте
    (в синтетике зондов нет, их компонента всегда 0, поэтому вес зондов на порядок не влияет)."""
    units = round(0.95 / step)
    out = []
    for a in range(units + 1):
        for b in range(units + 1 - a):
            for c in range(units + 1 - a - b):
                d = units - a - b - c
                out.append((a * step, b * step, c * step, d * step, 0.05))
    return np.round(np.array(out), 4)


def fast_ndcg10(sc: dict, rel: np.ndarray, rows: np.ndarray, w: np.ndarray, ideal10: np.ndarray) -> float:
    """nDCG@10 по подмножеству потребностей без полного lexsort (для перебора сетки). Порядок: категория → скор →
    рейтинг (как в продукте; разбиение оставшихся ничьих по public_ref здесь не воспроизводится)."""
    sub = {"comps": sc["comps"][rows], "has_req": sc["has_req"][rows], "provisional": sc["provisional"]}
    key = sc["vis"][rows] * 10.0 + weighted(sub, w) + sc["rating"][None, :] * 1e-6
    top = np.argpartition(-key, 10, axis=1)[:, :10]
    kt = np.take_along_axis(key, top, axis=1)
    top = np.take_along_axis(top, np.argsort(-kt, axis=1), axis=1)
    g = 2.0 ** np.take_along_axis(rel[rows], top, axis=1) - 1
    disc = 1 / np.log2(np.arange(2, 12))
    return float(np.mean((g * disc).sum(1) / ideal10[rows]))


def heldout(world: World, run: dict, world2: World, run2: dict, seed: int) -> dict:
    rel = world.rel
    n = rel.shape[0]
    perm = np.random.default_rng(seed + 23).permutation(n)
    train, test = np.sort(perm[: n // 2]), np.sort(perm[n // 2:])
    disc = 1 / np.log2(np.arange(2, 12))
    ideal = (2.0 ** np.sort(rel, axis=1)[:, ::-1][:, :10] - 1) @ disc
    grid = weight_grid()
    sc = run["scored"]
    vals = np.array([fast_ndcg10(sc, rel, train, w, ideal) for w in grid])
    best = grid[int(np.argmax(vals))]
    w_prod = np.array([WEIGHTS[k] for k in COMP_KEYS])
    prod_val = fast_ndcg10(sc, rel, train, w_prod, ideal)

    def full(sc_, rel_, rows, w):
        o = platform_orders({**sc_, "comps": sc_["comps"][rows], "has_req": sc_["has_req"][rows],
                             "vis": sc_["vis"][rows], "mandatory_gaps": sc_["mandatory_gaps"][rows]}, w)
        return per_need(rel_[rows], o)["ndcg@10"]

    t_prod, t_best = full(sc, rel, test, w_prod), full(sc, rel, test, best)
    all2 = np.arange(world2.rel.shape[0])
    w2_prod, w2_best = full(run2["scored"], world2.rel, all2, w_prod), full(run2["scored"], world2.rel, all2, best)
    i_test, i_w2 = boot_idx(len(test), seed + 29), boot_idx(len(all2), seed + 31)
    return {
        "method": "Перебор сетки весов (шаг 0,05; тест, обязательный стек, желательный стек, ФСП; сумма 0,95, "
                  "зонды 0,05) по nDCG@10 на обучающей половине потребностей. Отчёт — на второй половине (её истина "
                  "в подборе не участвовала) и на втором мире с другим seed (другие кандидаты и потребности).",
        "grid_size": int(len(grid)), "train_needs": int(len(train)), "test_needs": int(len(test)),
        "world2_seed": world2.config.seed, "world2_needs": int(len(all2)),
        "weights_product": dict(zip(COMP_KEYS, map(float, w_prod), strict=True)),
        "weights_tuned": dict(zip(COMP_KEYS, map(float, best), strict=True)),
        "product_rank_in_grid": int((vals > prod_val + 1e-12).sum()) + 1,
        "train": {"product": round(prod_val, 3), "tuned": round(float(vals.max()), 3)},
        "test": {"product": _ci(t_prod, i_test), "tuned": _ci(t_best, i_test), "tuned_minus_product": _ci(t_best - t_prod, i_test)},
        "world2": {"product": _ci(w2_prod, i_w2), "tuned": _ci(w2_best, i_w2),
                   "tuned_minus_product": _ci(w2_best - w2_prod, i_w2)},
        "decision": "Веса продукта не меняются по итогам бенчмарка: подобранные на синтетике веса — подсказка, "
                    "а не настройка под истину, которую мы сами задали.",
    }


# ---------------------------------------------------------------- описания и разрезы

def world_stats(world: World, reqs: list[dict]) -> dict:
    c = world.candidates
    rel = world.rel
    n_rel = (rel >= 2).sum(1)
    par = {"direction": np.mean([r.get("direction") == nd.direction for r, nd in zip(reqs, world.needs, strict=True)]),
           "grade": np.mean([r.get("grade") == nd.grade for r, nd in zip(reqs, world.needs, strict=True)])}
    tp = fp = fn = 0
    for r, nd in zip(reqs, world.needs, strict=True):
        got = {i["tag"] for i in r.get("stack_required") or []}
        tp += len(got & set(nd.required))
        fp += len(got - set(nd.required))
        fn += len(set(nd.required) - got)
    cat = [x for x in c if x.obs.category_grade]
    testable = [np.mean([t in world.bank_coverage[nd.direction] for t in nd.required]) for nd in world.needs]
    return {
        "n_needs": int(rel.shape[0]), "n_candidates": int(rel.shape[1]), "n_pairs": int(rel.size),
        "labels": {str(k): int(v) for k, v in enumerate(np.bincount(rel.ravel(), minlength=4))},
        "relevant_per_need": {"mean": round(float(n_rel.mean()), 1), "min": int(n_rel.min()), "max": int(n_rel.max())},
        "needs_resampled": world.resampled_needs,
        "personas": dict(Counter(x.latent.persona for x in c)),
        "with_fsp": sum(1 for x in c if any(a["verified"] for a in x.obs.achievements)),
        "unverified_fsp_badge": sum(1 for x in c if any(not a["verified"] for a in x.obs.achievements)),
        "no_category": sum(1 for x in c if not x.obs.category_grade),
        "provisional": sum(1 for x in c if x.obs.category_provisional),
        "retake": sum(1 for x in c if x.obs.sessions > 1),
        "category_equals_true_grade": round(float(np.mean([x.obs.category_grade == x.latent.true_grade for x in cat])), 3),
        "declared_equals_true_grade": round(float(np.mean([x.obs.grade_declared == (x.latent.true_grade or GRADE_ORDER[0])
                                                           for x in c])), 3),
        "parser": {"direction_accuracy": round(float(par["direction"]), 3), "grade_accuracy": round(float(par["grade"]), 3),
                   "required_precision": round(tp / max(tp + fp, 1), 3), "required_recall": round(tp / max(tp + fn, 1), 3)},
        "required_testable_share": round(float(np.mean(testable)), 3),
        "bank_coverage": world.bank_coverage,
    }


def groups(world: World, orders: dict) -> dict:
    c = world.candidates
    fsp = np.array([any(a["verified"] for a in x.obs.achievements) for x in c])
    infl = np.array([x.latent.persona == "inflated" for x in c])
    modest = np.array([x.latent.persona == "modest" for x in c])
    rel = world.rel
    first = {k: v[0] for k, v in orders.items()}
    rel_any = rel >= 2
    share_nofsp_rel = float((rel_any & ~fsp[None, :]).sum() / max(rel_any.sum(), 1))
    out = {"fsp": {}, "inflated": {}, "modest": {}}
    for k in ("platform", "no_fsp", "bm25", "no_test"):
        if k not in first:
            continue
        o = first[k]
        top = o[:, :10]
        r_top = np.take_along_axis(rel, top, axis=1) >= 2
        nof = (~fsp[top]) & r_top
        out["fsp"][k] = {"with_fsp_percentile": group_position(rel, o, fsp),
                         "without_fsp_percentile": group_position(rel, o, ~fsp),
                         "without_fsp_share_of_relevant_top10": round(float(nof.sum() / max(r_top.sum(), 1)), 3)}
    out["fsp"]["without_fsp_share_of_all_relevant"] = round(share_nofsp_rel, 3)
    for k in ("platform", "bm25", "keywords_grade", "no_test", "no_guard"):
        if k in first:
            out["inflated"][k] = {"irrelevant_inflated_top10": top_share(rel, first[k], infl, 10, relevant=False),
                                  "inflated_top10": top_share(rel, first[k], infl, 10)}
            out["modest"][k] = {"relevant_modest_percentile": group_position(rel, first[k], modest)}
    out["inflated"]["population_share"] = round(float(infl.mean()), 3)
    return out


def breakdown(world: World, pn: dict) -> dict:
    out: dict = {"by_direction": {}, "by_grade": {}, "by_testable": {}}
    dirs = np.array([nd.direction for nd in world.needs])
    grades = np.array([nd.grade for nd in world.needs])
    testable = np.array([np.mean([t in world.bank_coverage[nd.direction] for t in nd.required]) for nd in world.needs])
    keys = [k for k in ("platform", "bm25", "no_test", "grade_only") if k in pn]
    for name, mask_fn, vals in (("by_direction", lambda v: dirs == v, sorted(set(dirs))),
                                ("by_grade", lambda v: grades == v, GRADE_ORDER),
                                ("by_testable", lambda v: (testable >= 0.5) if v == "most" else (testable < 0.5),
                                 ("most", "few"))):
        for v in vals:
            msk = mask_fn(v)
            if msk.any():
                out[name][v] = {"n": int(msk.sum()), **{k: round(float(pn[k]["ndcg@10"][msk].mean()), 3) for k in keys}}
    return out


SENSITIVITY = [
    ("base", "Основные параметры", {}),
    ("sigma_035", "Погрешность теста σθ = 0,35", {"theta_sigma": 0.35}),
    ("sigma_065", "Погрешность теста σθ = 0,65", {"theta_sigma": 0.65}),
    ("inflated_0", "Без «раздутых» резюме", {"share_inflated": 0.0}),
    ("inflated_40", "«Раздутых» резюме 40 %", {"share_inflated": 0.40}),
    ("inflated_60", "«Раздутых» резюме 60 %", {"share_inflated": 0.60}),
    ("inflated_all_40", "40 % «раздутых», дописывают все навыки направления", {"share_inflated": 0.40, "inflate_all": True}),
    ("fsp_noise", "ФСП не связан с умением", {"fsp_informative": False}),
    ("strict_truth", "Строгая истина: только точный грейд", {"truth": "strict"}),
]


def sensitivity(base: BenchConfig, blocks: dict, n_needs: int, n_cands: int) -> list[dict]:
    out = []
    for vid, title, kw in SENSITIVITY:
        cfg = replace(base, n_needs=n_needs, n_candidates=n_cands, **kw)
        w = generate(cfg, blocks)
        r = run_methods(w, _parsed(w), cfg.seed, SENS_METHODS)
        pn = {k: mean_metrics(w.rel, o) for k, o in r["orders"].items()}
        out.append({"id": vid, "title": title, "overrides": kw, "n_needs": n_needs, "n_candidates": n_cands,
                    **{k: {mt: round(float(pn[k][mt].mean()), 3) for mt in ("p@5", "ndcg@10", "mrr")} for k in pn}})
        print(f"    {vid}: платформа nDCG@10 {out[-1]['platform']['ndcg@10']}, без защиты от раздувания "
              f"{out[-1]['no_guard']['ndcg@10']}, BM25 {out[-1]['bm25']['ndcg@10']}", flush=True)
    return out


def _examples(world: World, reqs: list[dict], orders: dict, k: int = 5, n: int = 30) -> list[dict]:
    out = []
    for i, (nd, r) in enumerate(zip(world.needs[:n], reqs[:n], strict=True)):
        row = {"need": nd.text, "truth": {"direction": nd.direction, "grade": nd.grade, "required": nd.required,
                                          "desired": nd.desired},
               "parsed": {"direction": r.get("direction"), "grade": r.get("grade"),
                          "required": [x["tag"] for x in r.get("stack_required") or []]}}
        for meth in ("platform", "bm25"):
            row[meth] = [{"ref": world.candidates[j].obs.public_ref, "rel": int(world.rel[i, j]),
                          "persona": world.candidates[j].latent.persona} for j in orders[meth][0][i, :k]]
        out.append(row)
    return out


# ---------------------------------------------------------------- Junior: решение банка, «предварительно», штраф

JUNIOR_COLUMNS = (
    ("stub06", "Как было: заглушка, порог 0,6", {"decision": "stub06", "provisional": False}),
    ("bank08", "Как в продукте: правило банка, порог 0,8", {"decision": "bank", "provisional": False}),
    ("provisional", "После: порог 0,8 + «Junior (предварительно)»", {"decision": "bank", "provisional": True}),
)


def _junior_world_stats(world: World) -> dict:
    """Что стало с кандидатами у порога Junior: категории, предварительные, ложные предварительные и отказы."""
    c = world.candidates
    theta = np.array([x.latent.theta for x in c])
    cat = np.array([x.obs.category_grade or "" for x in c])
    prov = np.array([x.obs.category_provisional for x in c])
    true_jun_or_above = theta >= -1.0  # истинный уровень не ниже порога Junior
    declared_jun = np.array([x.obs.grade_declared == "junior" for x in c])
    tested_jun = np.array([bool(x.obs.test and x.obs.test.get("claimed") == "junior") for x in c])
    return {"n_candidates": len(c), "no_category": int((cat == "").sum()),
            "junior_category": int((cat == "junior").sum()), "provisional": int(prov.sum()),
            "provisional_share_of_junior": round(float(prov.sum() / max((cat == "junior").sum(), 1)), 3),
            # ложные предварительные: категория Junior присвоена предварительно, а истинный уровень ниже порога
            "provisional_true_below": int((prov & ~true_jun_or_above).sum()),
            "provisional_true_below_share": round(float((prov & ~true_jun_or_above).sum() / max(prov.sum(), 1)), 3),
            # ложные отказы: истинный уровень не ниже Junior, заявлен Junior, категории нет
            "rejected_true_junior": int((declared_jun & true_jun_or_above & (cat == "")).sum()),
            "rejected_true_junior_share": round(float((declared_jun & true_jun_or_above & (cat == "")).sum()
                                                      / max((declared_jun & true_jun_or_above).sum(), 1)), 3),
            "declared_junior": int(declared_jun.sum()), "tested_junior": int(tested_jun.sum()),
            "true_junior_or_above_declared_junior": int((declared_jun & true_jun_or_above).sum())}


def _metrics_subset(pn: dict, mask: np.ndarray) -> dict:
    return {m: round(float(pn[m][mask].mean()), 3) for m in ("p@5", "p@10", "ndcg@10", "mrr")}


def junior_section(cfg: BenchConfig, blocks: dict, main_world: World | None = None, main_scored: dict | None = None) -> dict:
    """Три столбца при одной и той же истине (тот же seed → те же θ*, навыки, тексты и потребности):
    решение заглушки с порогом 0,6 (как считал бенчмарк раньше) / правило банка с порогом 0,8 (как в продукте
    до «предварительно») / правило банка + «Junior (предварительно)» со штрафом 0,05. Плюс чувствительность
    штрафа 0 / 0,05 / 0,10 на третьем мире (порядок меняется только внутри категории)."""
    cols = []
    rel_ref = None
    third = None
    for cid, title, kw in JUNIOR_COLUMNS:
        c = replace(cfg, **kw)
        if main_world is not None and main_scored is not None and c.to_dict() == cfg.to_dict():
            w, sc = main_world, main_scored
        else:
            w = generate(c, blocks)
            sc = score_world(w, _parsed(w))
        if rel_ref is None:
            rel_ref = w.rel
        assert np.array_equal(rel_ref, w.rel), "истина должна совпадать между столбцами"
        pn = per_need(w.rel, platform_orders(sc))
        jun = np.array([nd.grade == "junior" for nd in w.needs])
        cols.append({"id": cid, "title": title, "overrides": kw, "world": _junior_world_stats(w),
                     "all": _metrics_subset(pn, np.ones(len(w.needs), bool)), "junior_needs": _metrics_subset(pn, jun),
                     "n_junior_needs": int(jun.sum())})
        print(f"    Junior/{cid}: nDCG@10 по Junior-потребностям {cols[-1]['junior_needs']['ndcg@10']}, "
              f"без категории {cols[-1]['world']['no_category']}, предварительных {cols[-1]['world']['provisional']}",
              flush=True)
        if cid == "provisional":
            third = (w, sc, jun)
    pen = []
    if third is not None:
        w, sc, jun = third
        prov = sc["provisional"].astype(bool)
        rel_any = w.rel >= 2
        for pv in PENALTIES:
            o = platform_orders(sc, penalty=pv)
            pn = per_need(w.rel, o)
            top = o[:, :10]
            in_top = prov[top]
            r_top = np.take_along_axis(w.rel, top, axis=1) >= 2
            top20 = prov[o[:, :20]]
            pen.append({"penalty": pv, "all": _metrics_subset(pn, np.ones(len(w.needs), bool)),
                        "junior_needs": _metrics_subset(pn, jun),
                        "provisional_in_top10_junior_needs": round(float(in_top[jun].mean()), 3),
                        "provisional_in_top20_junior_needs": round(float(top20[jun].mean()), 3),
                        "irrelevant_provisional_in_top10_junior_needs":
                            round(float((in_top & ~r_top)[jun].sum() / max(in_top[jun].sum(), 1)), 3),
                        # средний перцентиль места подходящих предварительных по Junior-потребностям (0 — вершина)
                        "relevant_provisional_percentile_junior_needs": group_position(w.rel[jun], o[jun], prov),
                        "relevant_provisional_share": round(float((rel_any[:, prov]).mean()), 3) if prov.any() else None})
    return {"columns": cols, "penalty_sensitivity": pen, "penalty_product": PROVISIONAL_PENALTY,
            "note": ("Истина одна и та же во всех столбцах: меняется только решение по грейду у порога. Кандидаты без "
                     "категории в бенчмарке стоят после всех с категорией (как «грейд не подтверждён» в продукте), "
                     "поэтому на p@k и nDCG@10 они почти не влияют; дотестирование у порога здесь не моделируется — "
                     "его эффект считает симуляция теста (раздел «Junior у порога» на /validation).")}


# ---------------------------------------------------------------- запуск

def run(cfg: BenchConfig, quick: bool = False, sens_size: tuple[int, int] | None = None, write: bool = True) -> dict:
    t0 = time.time()
    blocks = bank_blocks()
    print(f"1/6 мир: {cfg.n_needs} потребностей × {cfg.n_candidates} кандидатов, seed {cfg.seed}", flush=True)
    world = generate(cfg, blocks)
    reqs = _parsed(world)
    print("2/6 методы и абляции", flush=True)
    r = run_methods(world, reqs, cfg.seed)
    s = summarize(world, r, cfg.seed)
    print(f"    платформа nDCG@10 {s['metrics']['platform']['ndcg@10']['mean']}, "
          f"BM25 {s['metrics']['bm25']['ndcg@10']['mean']} ({r['cpu_seconds']} с CPU)", flush=True)
    print("3/6 второй мир и веса на отложенных данных", flush=True)
    cfg2 = replace(cfg, seed=cfg.seed + 1)
    world2 = generate(cfg2, blocks)
    r2 = run_methods(world2, _parsed(world2), cfg2.seed, ("platform", "bm25"))
    s2 = summarize(world2, r2, cfg2.seed)
    ho = heldout(world, r, world2, r2, cfg.seed)
    print(f"    веса: продукт {ho['test']['product']['mean']} / подобранные {ho['test']['tuned']['mean']} "
          f"на отложенной половине", flush=True)
    print("4/6 чувствительность", flush=True)
    sens = [] if quick else sensitivity(cfg, blocks, *(sens_size or SENS_SIZE))
    print("5/6 Junior: решение банка, «предварительно», штраф", flush=True)
    if quick:
        jcfg = replace(cfg, n_needs=min(cfg.n_needs, 40), n_candidates=min(cfg.n_candidates, 400))
        junior = junior_section(jcfg, blocks, world if jcfg.to_dict() == cfg.to_dict() else None,
                                r["scored"] if jcfg.to_dict() == cfg.to_dict() else None)
    else:
        junior = junior_section(cfg, blocks, world, r["scored"])
    cfg_d = cfg.to_dict()
    rep = {
        "version": BENCH_VERSION, "algorithm": ALGORITHM_VERSION, "weights": WEIGHTS,
        "fsp_rating": {"version": FSP_RATING_VERSION, "policy": FSP_RATING_POLICY},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": "make bench" if not quick else "python -m app.modules.validation.matching_bench --quick",
        "config": cfg_d, "config_hash": hashlib.sha256(json.dumps(cfg_d, sort_keys=True).encode()).hexdigest()[:12],
        "seeds": {"world": cfg.seed, "world2": cfg2.seed, "bootstrap": cfg.seed + 11, "split": cfg.seed + 23,
                  "tie_break": cfg.seed + 7},
        "caveat": CAVEAT, "truth_rules": TRUTH_RULES, "methods": METHODS,
        "world": world_stats(world, reqs),
        "metrics": s["metrics"], "paired_platform_minus": s["paired_platform_minus"],
        "groups": groups(world, r["orders"]), "breakdown": breakdown(world, s["per_need"]),
        "world2": {"seed": cfg2.seed, "metrics": s2["metrics"]},
        "heldout_weights": ho, "sensitivity": sens, "junior": junior,
        "score_rebuild_max_error": r["scored"]["max_rebuild_error"],
        "ablations": ablations(s),
        "signature": signature(seed=cfg.seed, config=cfg_d, n=cfg.n_needs * cfg.n_candidates,
                               world=f"бенчмарк подбора: {cfg.n_needs} потребностей × {cfg.n_candidates} кандидатов",
                               command="make bench" if not quick else "python -m app.modules.validation.matching_bench --quick"),
    }
    rep["seconds"] = round(time.time() - t0, 1)
    if write:
        full = {**rep, "per_need": [{"need": nd.text, "direction": nd.direction, "grade": nd.grade,
                                     "relevant": int((world.rel[i] >= 2).sum()),
                                     **{k: {m: round(float(v[m][i]), 3) for m in METRICS} for k, v in s["per_need"].items()}}
                                    for i, nd in enumerate(world.needs)],
                "examples": _examples(world, reqs, r["orders"])}
        DOCS_JSON.parent.mkdir(parents=True, exist_ok=True)
        DOCS_JSON.write_text(json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8")
        DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
        DATA_OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        DOCS_MD.write_text(markdown(rep), encoding="utf-8")
    where = (f"→ {DOCS_JSON.relative_to(REPO)}, {DATA_OUT.relative_to(REPO)}, {DOCS_MD.relative_to(REPO)}" if write
             else "без записи результатов (--no-write)")
    print(f"6/6 {where} ({rep['seconds']} с)", flush=True)
    return rep


def _f(v, d: int = 3) -> str:
    if v is None:
        return "—"
    v = 0.0 if abs(v) < 0.5 * 10 ** -d else v
    return f"{v:.{d}f}".replace(".", ",").replace("-", "−")


W_TITLES = {"test": "тест", "stack_required": "обязательный стек", "stack_desired": "желательный стек", "fsp": "ФСП",
            "probe": "зонды"}


def _w(w: dict) -> str:
    return " · ".join(f"{W_TITLES.get(k, k)} {_f(v, 2)}" for k, v in w.items())


def _pct(v) -> str:
    return "—" if v is None else f"{round(v * 100)} %"


def findings(rep: dict) -> list[str]:
    """Короткие выводы по цифрам отчёта (формулировки зависят от знака и ДИ, а не написаны заранее)."""
    m, pm, g = rep["metrics"], rep["paired_platform_minus"], rep["groups"]
    nd = lambda k: pm[k]["ndcg@10"]  # noqa: E731
    out = [f"Платформа против BM25 по тексту резюме: nDCG@10 +{_f(nd('bm25')['mean'], 2)} "
           f"[{_f(nd('bm25')['lo'], 2)}; {_f(nd('bm25')['hi'], 2)}], p@5 {_f(m['platform']['p@5']['mean'], 2)} против "
           f"{_f(m['bm25']['p@5']['mean'], 2)}, MRR {_f(m['platform']['mrr']['mean'], 2)} против {_f(m['bm25']['mrr']['mean'], 2)}.",
           f"Тест — главный вклад: без него (только самоописание) nDCG@10 ниже на {_f(nd('no_test')['mean'], 2)} "
           f"[{_f(nd('no_test')['lo'], 2)}; {_f(nd('no_test')['hi'], 2)}]; только грейд из теста без скора внутри категории — "
           f"ниже на {_f(nd('grade_only')['mean'], 2)}."]
    inf = g["inflated"]
    out.append(f"Раздутые резюме: нерелевантные «раздутые» занимают {_pct(inf['platform']['irrelevant_inflated_top10'])} мест "
               f"топ-10 у платформы, {_pct(inf['bm25']['irrelevant_inflated_top10'])} у BM25, "
               f"{_pct(inf['no_test']['irrelevant_inflated_top10'])} без теста и "
               f"{_pct(inf['no_guard']['irrelevant_inflated_top10'])}, если засчитывать заявленные навыки как подтверждённые.")
    sens = {v["id"]: v for v in rep.get("sensitivity", [])}
    gain = -nd("no_guard")["mean"]
    line = (f"Цена защиты от раздувания: засчитывание заявленных навыков дало бы nDCG@10 {'+' if gain > 0 else ''}"
            f"{_f(gain, 2)} "
            f"(при {_pct(rep['config']['share_inflated'])} «раздутых»).")
    if "inflated_all_40" in sens and "base" in sens:
        st, b = sens["inflated_all_40"], sens["base"]
        verb = ("уже не выигрывает у платформы" if st["no_guard"]["ndcg@10"] <= st["platform"]["ndcg@10"] + 0.01
                else "всё ещё выигрывает у платформы")
        line += (f" Если 40 % кандидатов дописывают все навыки направления, такой вариант {verb} "
                 f"({_f(st['no_guard']['ndcg@10'], 2)} против {_f(st['platform']['ndcg@10'], 2)}, мир {st['n_needs']} × "
                 f"{st['n_candidates']}), а у платформы nDCG@10 "
                 f"почти не меняется ({_f(b['platform']['ndcg@10'], 2)} → {_f(st['platform']['ndcg@10'], 2)}).")
    out.append(line + " Заявленное (T0) в скор не входит намеренно — это устойчивость к атаке «дописать навыки вакансии».")
    fp = g["fsp"]
    ci = nd("no_fsp")
    out.append(f"Бонус ФСП: вклад в nDCG@10 {_f(ci['mean'], 3)} [{_f(ci['lo'], 3)}; {_f(ci['hi'], 3)}]"
               + (" — на точность не влияет" if ci["lo"] <= 0 <= ci["hi"] else "") +
               f". Он переставляет подходящих: доля кандидатов без ФСП среди подходящих в топ-10 "
               f"{_pct(fp['platform']['without_fsp_share_of_relevant_top10'])} (без бонуса "
               f"{_pct(fp['no_fsp']['without_fsp_share_of_relevant_top10'])}, среди всех подходящих "
               f"{_pct(fp['without_fsp_share_of_all_relevant'])}); средний перцентиль места подходящих без ФСП "
               f"{_f(fp['platform']['without_fsp_percentile'], 2)}, с ФСП {_f(fp['platform']['with_fsp_percentile'], 2)}.")
    jun = rep["breakdown"]["by_grade"].get("junior")
    jr = {c["id"]: c for c in (rep.get("junior") or {}).get("columns", [])}
    if jun and jun["no_test"] > jun["platform"]:
        out.append(f"Слабое место — потребности уровня Junior: nDCG@10 {_f(jun['platform'], 2)} против {_f(jun['no_test'], 2)} "
                   "у самоописания. Тест у порога Junior осторожен (подтверждение от P = 0,8 при SE ≈ 0,4): часть подходящих "
                   f"не подтверждает грейд ({rep['world']['no_category']} из {rep['world']['n_candidates']} без категории). "
                   "Дотестирование у порога в синтетике не моделируется.")
    if {"stub06", "bank08", "provisional"} <= set(jr):
        a, b, c = jr["stub06"], jr["bank08"], jr["provisional"]
        out.append(f"Junior у порога при одной истине: прежний порог 0,6 оставлял без категории {a['world']['no_category']} "
                   f"кандидатов, правило банка с порогом 0,8 — {b['world']['no_category']}, «Junior (предварительно)» "
                   f"возвращает в категорию {c['world']['provisional']} (ложных предварительных — истинный уровень ниже "
                   f"порога — {_pct(c['world']['provisional_true_below_share'])} из них); ложные отказы заявившим Junior "
                   f"с истинным уровнем не ниже порога: {_pct(a['world']['rejected_true_junior_share'])} → "
                   f"{_pct(b['world']['rejected_true_junior_share'])} → {_pct(c['world']['rejected_true_junior_share'])}. "
                   f"nDCG@10 по Junior-потребностям {_f(a['junior_needs']['ndcg@10'], 2)} / {_f(b['junior_needs']['ndcg@10'], 2)} / "
                   f"{_f(c['junior_needs']['ndcg@10'], 2)}, p@5 {_f(a['junior_needs']['p@5'], 2)} / {_f(b['junior_needs']['p@5'], 2)} / "
                   f"{_f(c['junior_needs']['p@5'], 2)}.")
        pen = {p["penalty"]: p for p in rep["junior"].get("penalty_sensitivity", [])}
        if pen:
            out.append("Штраф «предварительно» 0 / 0,05 / 0,10 меняет nDCG@10 по Junior-потребностям на "
                       + " / ".join(_f(pen[p]["junior_needs"]["ndcg@10"], 3) for p in sorted(pen))
                       + "; доля предварительных в топ-10 Junior-потребностей "
                       + " / ".join(_pct(pen[p]["provisional_in_top10_junior_needs"]) for p in sorted(pen))
                       + ", перцентиль места подходящих предварительных "
                       + " / ".join(_f(pen[p].get("relevant_provisional_percentile_junior_needs")) for p in sorted(pen))
                       + ". Предварительные у порога почти не попадают в верх выдачи и без штрафа (компонент теста у них "
                         "мал), поэтому в мире из 2000 кандидатов штраф на топ-10 не влияет; штраф 0,05 задан до бенчмарка "
                         "(вес одного зонда) и на нём не подбирался.")
    if "strict_truth" in sens:
        st = sens["strict_truth"]
        out.append(f"При строгой истине (подходит только точный грейд) nDCG@10 платформы {_f(st['platform']['ndcg@10'], 2)}, "
                   f"BM25 {_f(st['bm25']['ndcg@10'], 2)}: выбор правила истины меняет абсолютные числа, поэтому сравнивать "
                   "их с бенчмарками других команд нельзя — сравнимы только методы внутри одного мира.")
    return out


def _cell(x: dict) -> str:
    return f"{_f(x['mean'])} [{_f(x['lo'])}; {_f(x['hi'])}]"


def markdown(rep: dict) -> str:
    w, m = rep["world"], rep["metrics"]
    ho = rep["heldout_weights"]
    L = [
        "# Бенчмарк подбора со скрытой истиной",
        "",
        f"{w['n_needs']} потребностей × {w['n_candidates']} кандидатов = {w['n_pairs']:,} пар".replace(",", " ")
        + f". Версия {rep['version']}, алгоритм {rep['algorithm']}, конфиг `{rep['config_hash']}`, "
          f"seed мира {rep['seeds']['world']}, второй мир {rep['seeds']['world2']}. Пересчёт: `make bench` "
          f"({_f(rep['seconds'], 0)} с на общей машине с 2 ядрами).",
        "",
        f"> {rep['caveat']}",
        "",
        "## Выводы",
        "",
        *[f"- {x}" for x in findings(rep)],
        "",
        "## Как устроено",
        "",
        "- Кандидат = скрытая истина (направление, истинный уровень θ*, освоенные навыки, талант) + то, что видит "
        "система: самоописание T0 (шумное; 20 % «раздутых» резюме, 15 % «скромных»), тест T1 (θ̂ = θ* + N(0, σθ), "
        f"σθ = {_f(rep['config']['theta_sigma'], 2)} — RMSE нашего адаптивного теста в симуляции; решение по грейду — "
        "правилом банка (подтверждение от P = 0,8, у порога Junior — «Junior (предварительно)»), при отказе — пересдача "
        "ступенью ниже; навыки — по ответам на задания с тегами из банка), "
        "паспорт ФСП T2 у части кандидатов.",
        "- Потребность = истина (направление, грейд, 2–4 обязательных навыка) + текст; платформа получает только "
        "разбор текста парсером.",
        "- Ранжирование платформы — `ranking.score_candidate` без изменений; Bundle собирается только из наблюдаемого. "
        f"Скор, пересобранный из компонент, совпадает с продуктом (макс. расхождение {rep['score_rebuild_max_error']:.0e}).",
        "",
        "Истинная релевантность (0–3):",
        "",
        *[f"- {t}" for t in rep["truth_rules"]],
        "",
        "## Результаты (95 % ДИ — бутстреп по потребностям)",
        "",
        "| Метод | p@5 | p@10 | nDCG@5 | nDCG@10 | MRR |",
        "|---|---|---|---|---|---|",
    ]
    for k, meta in rep["methods"].items():
        if k in m:
            L.append(f"| {meta['title']} | " + " | ".join(_cell(m[k][mt]) for mt in METRICS) + " |")
    pm = rep["paired_platform_minus"]
    L += ["", "Разница «платформа − метод», nDCG@10 (парный бутстреп): "
          + "; ".join(f"{rep['methods'][k]['title']} {_cell(v['ndcg@10'])}" for k, v in pm.items()) + ".", ""]
    if rep.get("ablations"):
        L += ["## Абляции: что даёт каждая часть формулы", "",
              "Одна и та же истина и тот же разбор потребностей; убирается одна компонента. Разница — «полная формула − "
              "абляция», парный бутстреп по потребностям, 95 % ДИ.", "",
              "| Вариант | p@5 | nDCG@10 | Δ p@5 | Δ nDCG@10 |", "|---|---|---|---|---|"]
        for a in rep["ablations"]:
            meta = rep["methods"][a["method"]]
            L.append(f"| {meta['title']} | {_cell(a['p@5'])} | {_cell(a['ndcg@10'])} | "
                     f"{_cell(a['diff_p@5']) if 'diff_p@5' in a else '—'} | "
                     f"{_cell(a['diff_ndcg@10']) if 'diff_ndcg@10' in a else '—'} |")
        L += ["", "Что убирается: " + "; ".join(f"{rep['methods'][a['method']]['title']} — {rep['methods'][a['method']]['text']}"
                                                for a in rep["ablations"][1:]) + ".", ""]
    L += ["## Веса на отложенных данных", "", ho["method"], "",
          "| | Обучение | Отложенная половина | Второй мир |", "|---|---|---|---|",
          f"| Веса продукта: {_w(ho['weights_product'])} | {_f(ho['train']['product'])} | {_cell(ho['test']['product'])} | "
          f"{_cell(ho['world2']['product'])} |",
          f"| Подобранные: {_w(ho['weights_tuned'])} | {_f(ho['train']['tuned'])} | {_cell(ho['test']['tuned'])} | "
          f"{_cell(ho['world2']['tuned'])} |",
          "", f"Подобранные − продукт: отложенная половина {_cell(ho['test']['tuned_minus_product'])}, второй мир "
          f"{_cell(ho['world2']['tuned_minus_product'])}. Веса продукта — {ho['product_rank_in_grid']}-е место из "
          f"{ho['grid_size']} на обучающей половине. {ho['decision']}", ""]
    g = rep["groups"]
    fp = g["fsp"].get("platform", {})
    L += ["## Группы кандидатов", "",
          f"- Кандидаты без ФСП: средний перцентиль места релевантных кандидатов (0 — вершина) без ФСП "
          f"{_f(fp.get('without_fsp_percentile'), 4)}, с ФСП {_f(fp.get('with_fsp_percentile'), 4)}; среди релевантных "
          f"в топ-10 без ФСП {_f(fp.get('without_fsp_share_of_relevant_top10'))} при доле среди всех релевантных "
          f"{_f(g['fsp']['without_fsp_share_of_all_relevant'])}.",
          f"- «Раздутые» резюме (в популяции {_f(g['inflated']['population_share'], 2)}): доля мест топ-10, занятых "
          "нерелевантными «раздутыми», — " + ", ".join(
              f"{rep['methods'][k]['title']} {_f(v['irrelevant_inflated_top10'])}" for k, v in g["inflated"].items()
              if isinstance(v, dict)) + ".", ""]
    if rep["sensitivity"]:
        v0 = rep["sensitivity"][0]
        L += [f"## Чувствительность (nDCG@10, мир {v0['n_needs']} × {v0['n_candidates']}, тот же seed)", "",
              "| Вариант | Платформа | Без ФСП | Без теста | Без защиты от раздувания | BM25 |", "|---|---|---|---|---|---|"]
        for v in rep["sensitivity"]:
            L.append(f"| {v['title']} | {_f(v['platform']['ndcg@10'])} | {_f(v['no_fsp']['ndcg@10'])} | "
                     f"{_f(v['no_test']['ndcg@10'])} | {_f(v['no_guard']['ndcg@10'])} | {_f(v['bm25']['ndcg@10'])} |")
        L.append("")
    jr = rep.get("junior") or {}
    if jr.get("columns"):
        cols = jr["columns"]
        L += ["## Junior у порога: решение банка и «Junior (предварительно)» (одна истина, три правила)", "",
              "| | " + " | ".join(c["title"] for c in cols) + " |", "|---|" + "---|" * len(cols)]
        rows = [("Без категории", lambda c: str(c["world"]["no_category"])),
                ("Категория Junior", lambda c: str(c["world"]["junior_category"])),
                ("Из них предварительно", lambda c: str(c["world"]["provisional"])),
                ("Ложных предварительных (истинный уровень ниже порога)",
                 lambda c: f"{c['world']['provisional_true_below']} ({_pct(c['world']['provisional_true_below_share'])})"),
                ("Ложные отказы заявившим Junior с истинным уровнем не ниже порога",
                 lambda c: f"{c['world']['rejected_true_junior']} из {c['world']['true_junior_or_above_declared_junior']} "
                           f"({_pct(c['world']['rejected_true_junior_share'])})"),
                ("nDCG@10, Junior-потребности", lambda c: _f(c["junior_needs"]["ndcg@10"])),
                ("p@5, Junior-потребности", lambda c: _f(c["junior_needs"]["p@5"])),
                ("MRR, Junior-потребности", lambda c: _f(c["junior_needs"]["mrr"])),
                ("nDCG@10, все потребности", lambda c: _f(c["all"]["ndcg@10"]))]
        for title, fn in rows:
            L.append(f"| {title} | " + " | ".join(fn(c) for c in cols) + " |")
        L += ["", jr.get("note", ""), ""]
        if jr.get("penalty_sensitivity"):
            L += ["### Чувствительность штрафа «предварительно» (третий мир)", "",
                  "| Штраф | nDCG@10 Junior | p@5 Junior | nDCG@10 все | Предварительных в топ-10 / топ-20 Junior | "
                  "Перцентиль места подходящих предварительных |", "|---|---|---|---|---|---|"]
            for pv in jr["penalty_sensitivity"]:
                L.append(f"| {_f(pv['penalty'], 2)} | {_f(pv['junior_needs']['ndcg@10'])} | {_f(pv['junior_needs']['p@5'])} | "
                         f"{_f(pv['all']['ndcg@10'])} | {_pct(pv['provisional_in_top10_junior_needs'])} / "
                         f"{_pct(pv['provisional_in_top20_junior_needs'])} | "
                         f"{_f(pv.get('relevant_provisional_percentile_junior_needs'))} |")
            L.append("")
    ws = w["parser"]
    L += ["## Данные мира", "",
          f"- Релевантных на потребность: в среднем {_f(w['relevant_per_need']['mean'], 0)}, от "
          f"{w['relevant_per_need']['min']} до {w['relevant_per_need']['max']}; пар с меткой 0 / 1 / 2 / 3: "
          + " / ".join(f"{w['labels'][k]:,}".replace(",", " ") for k in "0123") + ".",
          f"- Без категории (тест не подтвердил ни один грейд): {w['no_category']}; пересдавали ступенью ниже: "
          f"{w['retake']}; категория = истинный грейд у {_f(w['category_equals_true_grade'])} получивших категорию; "
          f"заявленный грейд = истинный у {_f(w['declared_equals_true_grade'])}.",
          f"- Паспорт ФСП: {w['with_fsp']}; неподтверждённый «значок из анкеты»: {w['unverified_fsp_badge']}.",
          f"- Парсер потребностей: направление {_f(ws['direction_accuracy'])}, грейд {_f(ws['grade_accuracy'])}, "
          f"обязательные навыки — точность {_f(ws['required_precision'])}, полнота {_f(ws['required_recall'])}.",
          f"- Доля обязательных навыков, которые банк заданий может подтвердить тестом: {_f(w['required_testable_share'])}.",
          "", "Полные данные: `docs/validation/matching_bench.json` (метрики по каждой потребности, примеры выдачи).", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Бенчмарк подбора со скрытой истиной")
    ap.add_argument("--needs", type=int, default=BenchConfig.n_needs)
    ap.add_argument("--candidates", type=int, default=BenchConfig.n_candidates)
    ap.add_argument("--seed", type=int, default=BenchConfig.seed)
    ap.add_argument("--quick", action="store_true", help="40 × 400, без анализа чувствительности (проверка механики)")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    cfg = BenchConfig(seed=a.seed, n_needs=40 if a.quick else a.needs, n_candidates=400 if a.quick else a.candidates)
    run(cfg, quick=a.quick, write=not a.no_write)
    return 0


if __name__ == "__main__":
    sys.exit(main())
