"""Качество подбора на размеченных парах «потребность — кандидат» (15 потребностей × 20 кандидатов).

Набор: 15 потребностей демо-данных (app.modules.demo.seed.NEEDS) × 20 кандидатов из демо-пула на каждую:
до 8 из точной категории, до 6 из соседних грейдов того же направления, остальные — из других направлений
(детерминированно по seed). Разметка — по правилам требований (не по формуле ранжирования):

* направление не совпадает → 0;
* грейд совпадает → 2, соседний → 1, через ступень → 0;
* все обязательные навыки потребности есть у кандидата (заявлены или проверены тестом) и грейд совпадает → 3;
  покрыто меньше половины обязательных → не выше 1;
* формат работы несовместим (офис ↔ удалённо) → −1 (не ниже 0).

Релевантен — метка ≥ 2. Метрики: precision@5, nDCG@5, nDCG@10 (gain = 2^rel − 1). Сравнение: подборка
платформы (как в продукте: фильтр по категории потребности, внутри — скор по T1/T2), «ключевые слова» (число совпавших тегов в заявленном стеке — как у поиска по резюме), случайный
порядок (среднее по 200 перестановкам). Ограничение (честно): разметка автоматическая, на синтетических
данных и использует те же поля потребности, что и разбор; экспертная разметка — следующий шаг.
"""
from __future__ import annotations

import math
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.catalog.seed_data import GRADE_LEVEL
from app.modules.matching.need_parser import parse_need
from app.modules.matching.ranking import score_candidate
from app.modules.profiles.facts import Bundle, load_bundles
from app.modules.profiles.models import CandidateProfile

K_SET = 20


def label(b: Bundle, req: dict) -> int:
    p = b.profile
    if not req.get("direction") or p.current_direction_id != req["direction"]:
        return 0
    g_need, g_have = req.get("grade"), p.current_grade_id
    dist = abs(GRADE_LEVEL[g_need] - GRADE_LEVEL[g_have]) if g_need and g_have else 0
    rel = {0: 2, 1: 1}.get(dist, 0)
    must = [i["tag"] for i in req.get("stack_required") or []]
    have = b.stack_t0 | set(b.skills_t1)
    cov = (sum(1 for t in must if t in have) / len(must)) if must else 1.0
    if dist == 0 and cov >= 0.999:
        rel = 3
    if cov < 0.5:
        rel = min(rel, 1)
    wf = req.get("work_format")
    if wf in ("office", "remote") and p.work_format.value in ("office", "remote") and p.work_format.value != wf:
        rel -= 1
    return max(0, rel)


def keyword_score(b: Bundle, req: dict) -> float:
    req_t = [i["tag"] for i in req.get("stack_required") or []]
    des_t = [i["tag"] for i in req.get("stack_desired") or []]
    return 2 * sum(1 for t in req_t if t in b.stack_t0) + sum(1 for t in des_t if t in b.stack_t0)


def dcg(rels: list[int], k: int) -> float:
    return sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(rels[:k]))


def ndcg(rels: list[int], all_rels: list[int], k: int) -> float:
    ideal = dcg(sorted(all_rels, reverse=True), k)
    return dcg(rels, k) / ideal if ideal > 0 else 0.0


def precision(rels: list[int], k: int) -> float:
    return sum(1 for r in rels[:k] if r >= 2) / k


def selection_categories(req: dict) -> set[str] | None:
    d, g = req.get("direction"), req.get("grade")
    if not d:
        return None
    from app.modules.catalog.seed_data import GRADES

    return {f"{d}.{x}" for x in GRADES} if not g else {f"{d}.{g}"}


def pick_set(bundles: list[Bundle], req: dict, rnd: random.Random) -> list[Bundle]:
    d, g = req.get("direction"), req.get("grade")
    same = [b for b in bundles if b.profile.current_direction_id == d]
    exact = [b for b in same if b.profile.current_grade_id == g] if g else same
    near = [b for b in same if b not in exact and g and abs(GRADE_LEVEL[b.profile.current_grade_id] - GRADE_LEVEL[g]) == 1]
    far = [b for b in same if b not in exact and b not in near]
    other = [b for b in bundles if b.profile.current_direction_id != d]
    for lst in (exact, near, far, other):
        lst.sort(key=lambda b: (b.profile.telegram or "", b.profile.public_ref or ""))
        rnd.shuffle(lst)
    out = exact[:8] + near[:6]
    out += far[:max(0, 14 - len(out))]
    out += other[:K_SET - len(out)]
    return out[:K_SET]


def evaluate(db: Session, needs: list[str], seed: int = 20261006) -> dict:
    rnd = random.Random(seed)
    profiles = db.scalars(select(CandidateProfile).where(CandidateProfile.current_category_id.is_not(None))).all()
    bundles = sorted(load_bundles(db, [p.user_id for p in profiles]).values(),
                     key=lambda b: (b.profile.telegram or "", b.profile.public_ref or ""))  # детерминированно
    rows, pairs = [], []
    agg = {m: {"platform": [], "keywords": [], "random": []} for m in ("p@5", "ndcg@5", "ndcg@10")}
    within = {"platform": [], "keywords": [], "random": []}
    for qi, text in enumerate(needs):
        req = parse_need(text, use_llm=False)
        cand = pick_set(bundles, req, rnd)
        labels = {b.profile.user_id: label(b, req) for b in cand}
        all_rels = list(labels.values())
        # Как в продукте (ranking.build_selection): сначала фильтр по рекомендованным категориям потребности,
        # внутри — скор; кандидаты вне категорий в подборку не попадают (здесь — в конец списка)
        cats_ok = selection_categories(req)
        ours = sorted(cand, key=lambda b: (0 if (cats_ok is None or b.profile.current_category_id in cats_ok) else 1,
                                           -score_candidate(b, req)[0], -(b.profile.rating_score or 0),
                                           b.profile.public_ref or ""))
        kw_rng = random.Random(seed + qi)
        kw = sorted(cand, key=lambda b: (-keyword_score(b, req), kw_rng.random()))
        r_ours = [labels[b.profile.user_id] for b in ours]
        r_kw = [labels[b.profile.user_id] for b in kw]
        rand = {"p@5": 0.0, "ndcg@5": 0.0, "ndcg@10": 0.0}
        for _ in range(200):
            perm = all_rels[:]
            rnd.shuffle(perm)
            rand["p@5"] += precision(perm, 5) / 200
            rand["ndcg@5"] += ndcg(perm, all_rels, 5) / 200
            rand["ndcg@10"] += ndcg(perm, all_rels, 10) / 200
        res = {"platform": {"p@5": precision(r_ours, 5), "ndcg@5": ndcg(r_ours, all_rels, 5),
                            "ndcg@10": ndcg(r_ours, all_rels, 10)},
               "keywords": {"p@5": precision(r_kw, 5), "ndcg@5": ndcg(r_kw, all_rels, 5),
                            "ndcg@10": ndcg(r_kw, all_rels, 10)},
               "random": rand}
        for m in agg:
            for k in agg[m]:
                agg[m][k].append(res[k][m])
        # Внутри категории потребности (фильтр одинаков для всех способов): nDCG@3 — порядок по силе доказательств
        inc = [b for b in cand if cats_ok is None or b.profile.current_category_id in cats_ok]
        if len(inc) >= 4 and len({labels[b.profile.user_id] for b in inc}) > 1:
            rel_in = [labels[b.profile.user_id] for b in inc]
            within["platform"].append(ndcg([labels[b.profile.user_id] for b in ours if b in inc], rel_in, 3))
            within["keywords"].append(ndcg([labels[b.profile.user_id] for b in kw if b in inc], rel_in, 3))
            acc = 0.0
            for _ in range(200):
                perm = rel_in[:]
                rnd.shuffle(perm)
                acc += ndcg(perm, rel_in, 3) / 200
            within["random"].append(acc)
        rows.append({"need": text, "direction": req.get("direction"), "grade": req.get("grade"),
                     "relevant": sum(1 for r in all_rels if r >= 2), "labels": {str(r): all_rels.count(r) for r in range(4)},
                     **{k: {m: round(v, 3) for m, v in res[k].items()} for k in res}})
        for b in cand:
            pairs.append({"need_index": qi, "candidate_ref": b.profile.public_ref, "category": b.profile.current_category_id,
                          "label": labels[b.profile.user_id], "rank_platform": ours.index(b) + 1,
                          "rank_keywords": kw.index(b) + 1})
    summary = {m: {k: round(sum(v) / len(v), 3) for k, v in agg[m].items()} for m in agg}
    summary["within_category_ndcg@3"] = {k: round(sum(v) / len(v), 3) if v else None for k, v in within.items()}
    summary["within_category_needs"] = len(within["platform"])
    return {"n_needs": len(needs), "set_size": K_SET, "n_pairs": len(pairs),
            "relevant_share": round(sum(1 for p in pairs if p["label"] >= 2) / max(len(pairs), 1), 3),
            "summary": summary, "per_need": rows, "pairs": pairs,
            "caveat": "Фильтр по категории в подборке и грейд в разметке совпадают по смыслу, поэтому общий p@5 "
                      "завышает преимущество платформы над поиском по ключевым словам; честнее сравнение внутри "
                      "категории (within_category_ndcg@3).",
            "method": "Разметка по правилам требований (направление, грейд, обязательные навыки, формат); "
                      "релевантен — метка ≥ 2 из 3. Синтетические демо-данные; экспертная разметка — следующий шаг."}
