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
платформы (как в продукте: фильтр по категории потребности, внутри — скор по T1/T2), та же подборка без бонуса
ФСП, BM25 по тексту резюме/анкеты кандидата и тексту потребности, «ключевые слова» (число совпавших тегов
в заявленном стеке), случайный порядок (среднее по 200 перестановкам). Ограничение (честно): разметка автоматическая, на синтетических
данных и использует те же поля потребности, что и разбор; экспертная разметка — следующий шаг.
"""
from __future__ import annotations

from collections import Counter
import math
import random
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.catalog.seed_data import GRADE_LEVEL
from app.modules.matching.need_parser import parse_need
from app.modules.matching.ranking import WEIGHTS, score_candidate
from app.modules.profiles.facts import Bundle, load_bundles
from app.modules.profiles.models import CandidateProfile, CandidateResume

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


_TOKEN = re.compile(r"[a-zа-яё0-9+#]+", re.I)


def _tokens(text: str) -> list[str]:
    """Токены для BM25: нижний регистр, грубый стемминг — первые 6 букв (для русских окончаний)."""
    return [t[:6] for t in _TOKEN.findall((text or "").lower().replace("ё", "е")) if len(t) > 1]


def candidate_text(b: Bundle, resume: str = "") -> str:
    """Текст «резюме» кандидата: о себе, всё заявленное (T0) и загруженное резюме — то, что видит поиск по тексту."""
    parts = [b.profile.about or "", resume or ""]
    for kind, facts in b.t0.items():
        for f in facts:
            v = f.value if isinstance(f.value, dict) else {}
            parts.append(" ".join(str(x) for x in (f.key, v.get("title", ""), v.get("text", "")) if x))
    return " ".join(parts)


class BM25:
    """Okapi BM25 (k1 = 1,2, b = 0,75) по текстам кандидатов; IDF — по всему демо-пулу."""

    def __init__(self, docs: dict, k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = {k: Counter(_tokens(t)) for k, t in docs.items()}
        self.len = {k: sum(c.values()) for k, c in self.tf.items()}
        self.avg = (sum(self.len.values()) / len(self.len)) if self.len else 1.0
        df = Counter(t for c in self.tf.values() for t in c)
        n = len(self.tf)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def score(self, key, query: str) -> float:
        c, dl, s = self.tf.get(key, Counter()), self.len.get(key, 0), 0.0
        for t in set(_tokens(query)):
            f = c.get(t, 0)
            if f:
                s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg))
        return s


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


METHODS = ("platform", "platform_no_fsp", "bm25", "keywords", "random")
EVAL_GRADES = ("junior", "middle", "senior")


def evaluate(db: Session, needs: list[str], seed: int = 20261006) -> dict:
    rnd = random.Random(seed)
    # Набор кандидатов для разметки зафиксирован до появления грейда «Стажёр»: стажёры в размеченные пары не входят,
    # иначе изменился бы состав уже размеченных экспертами пар
    profiles = db.scalars(select(CandidateProfile).where(CandidateProfile.current_category_id.is_not(None),
                                                         CandidateProfile.current_grade_id.in_(EVAL_GRADES))).all()
    bundles = sorted(load_bundles(db, [p.user_id for p in profiles]).values(),
                     key=lambda b: (b.profile.telegram or "", b.profile.public_ref or ""))  # детерминированно
    resumes: dict = {}
    for r in db.scalars(select(CandidateResume).where(CandidateResume.user_id.in_([b.profile.user_id for b in bundles]))):
        resumes[r.user_id] = (resumes.get(r.user_id, "") + " " + (r.text_redacted or "")).strip()
    bm25 = BM25({b.profile.user_id: candidate_text(b, resumes.get(b.profile.user_id, "")) for b in bundles})
    rows, pairs = [], []
    agg = {m: {k: [] for k in METHODS} for m in ("p@5", "ndcg@5", "ndcg@10")}
    within = {k: [] for k in METHODS}
    for qi, text in enumerate(needs):
        req = parse_need(text, use_llm=False)
        cand = pick_set(bundles, req, rnd)
        labels = {b.profile.user_id: label(b, req) for b in cand}
        all_rels = list(labels.values())
        # Как в продукте (ranking.build_selection): сначала фильтр по рекомендованным категориям потребности,
        # внутри — скор; кандидаты вне категорий в подборку не попадают (здесь — в конец списка)
        cats_ok = selection_categories(req)
        sc = {b.profile.user_id: score_candidate(b, req) for b in cand}

        def in_cat(b):
            return 0 if (cats_ok is None or b.profile.current_category_id in cats_ok) else 1

        def no_fsp(b):  # тот же ранжировщик без бонуса ФСП (вес 0,10 × сила)
            s0, comps, _ = sc[b.profile.user_id]
            return s0 - WEIGHTS["fsp"] * comps["fsp"]

        kw_rng, bm_rng = random.Random(seed + qi), random.Random(seed + 1000 + qi)
        order = {
            "platform": sorted(cand, key=lambda b: (in_cat(b), -sc[b.profile.user_id][0], -(b.profile.rating_score or 0),
                                                    b.profile.public_ref or "")),
            "platform_no_fsp": sorted(cand, key=lambda b: (in_cat(b), -no_fsp(b), b.profile.public_ref or "")),
            "bm25": sorted(cand, key=lambda b: (-bm25.score(b.profile.user_id, text), bm_rng.random())),
            "keywords": sorted(cand, key=lambda b: (-keyword_score(b, req), kw_rng.random())),
        }
        res = {}
        for k, lst in order.items():
            r = [labels[b.profile.user_id] for b in lst]
            res[k] = {"p@5": precision(r, 5), "ndcg@5": ndcg(r, all_rels, 5), "ndcg@10": ndcg(r, all_rels, 10)}
        rand = {"p@5": 0.0, "ndcg@5": 0.0, "ndcg@10": 0.0}
        for _ in range(200):
            perm = all_rels[:]
            rnd.shuffle(perm)
            rand["p@5"] += precision(perm, 5) / 200
            rand["ndcg@5"] += ndcg(perm, all_rels, 5) / 200
            rand["ndcg@10"] += ndcg(perm, all_rels, 10) / 200
        res["random"] = rand
        for m in agg:
            for k in agg[m]:
                agg[m][k].append(res[k][m])
        # Внутри категории потребности (фильтр одинаков для всех способов): nDCG@3 — порядок по силе доказательств
        inc = [b for b in cand if cats_ok is None or b.profile.current_category_id in cats_ok]
        if len(inc) >= 4 and len({labels[b.profile.user_id] for b in inc}) > 1:
            rel_in = [labels[b.profile.user_id] for b in inc]
            for k, lst in order.items():
                within[k].append(ndcg([labels[b.profile.user_id] for b in lst if b in inc], rel_in, 3))
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
                          "label": labels[b.profile.user_id],
                          **{f"rank_{k}": lst.index(b) + 1 for k, lst in order.items()}})
    summary = {m: {k: round(sum(v) / len(v), 3) for k, v in agg[m].items()} for m in agg}
    summary["within_category_ndcg@3"] = {k: round(sum(v) / len(v), 3) if v else None for k, v in within.items()}
    summary["within_category_needs"] = len(within["platform"])
    return {"n_needs": len(needs), "set_size": K_SET, "n_pairs": len(pairs),
            "relevant_share": round(sum(1 for p in pairs if p["label"] >= 2) / max(len(pairs), 1), 3),
            "methods": {"platform": "Подборка платформы", "platform_no_fsp": "Платформа без бонуса ФСП",
                        "bm25": "BM25 по тексту резюме и потребности", "keywords": "Совпадение тегов заявленного стека",
                        "random": "Случайный порядок"},
            "summary": summary, "per_need": rows, "pairs": pairs,
            "caveat": "Фильтр по категории в подборке и грейд в разметке совпадают по смыслу, поэтому общий p@5 "
                      "завышает преимущество платформы над поиском по тексту; честнее сравнение внутри "
                      "категории (within_category_ndcg@3). Внутри категории разметка различает кандидатов только по "
                      "заявленным навыкам — их платформа намеренно не учитывает, а BM25 и теги учитывают.",
            "method": "Разметка по правилам требований (направление, грейд, обязательные навыки, формат); "
                      "релевантен — метка ≥ 2 из 3. Синтетические демо-данные; экспертная разметка — следующий шаг."}
