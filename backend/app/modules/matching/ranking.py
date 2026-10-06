"""Подбор кандидатов под потребность: категории, ранжирование, объяснения.

Принципы (п. 2.1 ТЗ и бриф):
* Выдача строится по категориям, присвоенным тестом (T1), а не по самоописанию.
* Скор — только по подтверждённым фактам: результат теста (T1), навыки, проверенные заданиями (T1),
  зонды (T1), паспорт ФСП (T2). Самоописание (T0) — только фильтр и пометка «заявлено».
* Для каждого требования — объяснение с уровнем доказанности.

score = 0,45·тест + 0,35·покрытие обязательного стека (T1) + 0,05·желательный стек (T1)
        + 0,10·ФСП (T2, бонус; нет истории — 0 без штрафа) + 0,05·зонды (T1)
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import User
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import GRADE_LEVEL, GRADES, STACK
from app.modules.catalog.seed_data import category_title
from app.modules.profiles.facts import (
    fmt_count,
    Bundle,
    achievement_text,
    card,
    load_bundles,
    skill_confirmed,
    test_component,
)
from app.modules.jury import scope as jury_scope
from app.modules.profiles.models import CandidateProfile

ALGORITHM_VERSION = "match-v1"
WEIGHTS = {"test": 0.45, "stack_required": 0.35, "stack_desired": 0.05, "fsp": 0.10, "probe": 0.05}
LEVELS = {"T2": "подтверждено реестром ФСП", "T1": "подтверждено тестом или зондом", "T0": "заявлено кандидатом",
          "none": "нет данных"}


def visible_pool(db: Session, direction: str | None = None, grades: list[str] | None = None,
                 category_ids: list[str] | None = None) -> list[CandidateProfile]:
    q = (select(CandidateProfile).join(User, User.id == CandidateProfile.user_id)
         .where(CandidateProfile.visible_to_employers.is_(True), CandidateProfile.current_category_id.is_not(None),
                User.is_active.is_(True), User.is_email_verified.is_(True), jury_scope.pool_clause(User.email)))
    if direction:
        q = q.where(CandidateProfile.current_direction_id == direction)
    if grades:
        q = q.where(CandidateProfile.current_grade_id.in_(grades))
    if category_ids:
        q = q.where(CandidateProfile.current_category_id.in_(category_ids))
    return list(db.scalars(q).all())


def category_counts(db: Session) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in visible_pool(db):
        out[p.current_category_id] = out.get(p.current_category_id, 0) + 1
    return out


def recommended_categories(req: dict, counts: dict[str, int], cats: dict[str, Category]) -> list[dict]:
    d, g = req.get("direction"), req.get("grade")
    out = []
    if not d:
        return [{"id": c.id, "title": c.title, "count": counts.get(c.id, 0), "relation": "all",
                 "market_range": _mr(c)} for c in cats.values()]
    for grade in GRADES:
        cid = f"{d}.{grade}"
        c = cats.get(cid)
        if not c:
            continue
        if g is None:
            rel = "direction"
        elif grade == g:
            rel = "exact"
        elif abs(GRADE_LEVEL[grade] - GRADE_LEVEL[g]) == 1:
            rel = "above" if GRADE_LEVEL[grade] > GRADE_LEVEL[g] else "below"
        else:
            continue
        out.append({"id": cid, "title": c.title, "count": counts.get(cid, 0), "relation": rel, "market_range": _mr(c)})
    order = {"exact": 0, "direction": 0, "below": 1, "above": 2}
    return sorted(out, key=lambda x: order.get(x["relation"], 3))


def _mr(c: Category) -> dict:
    return {"from": c.market_salary_from, "to": c.market_salary_to, "median": c.market_salary_median,
            "source": c.market_source, "as_of": c.market_as_of.isoformat() if c.market_as_of else None}


def score_candidate(b: Bundle, req: dict) -> tuple[float, dict, list[dict]]:
    """Скор и объяснение по каждому требованию. Возвращает (score, компоненты, reasons)."""
    p = b.profile
    reasons: list[dict] = []
    t = b.test.value if b.test else {}
    test = test_component(t.get("theta"), t.get("se"), req.get("grade") or p.current_grade_id)
    cat_title = category_title(p.current_category_id)
    if b.test:
        reasons.append({
            "requirement": "Специализация и грейд", "level": "T1", "status": "confirmed",
            "text": f"Категория {cat_title} подтверждена тестом {b.test.created_at:%d.%m.%Y}: "
                    f"{t.get('correct')} из {t.get('answered')} верно, θ = {t.get('theta', 0):+.2f} ± {t.get('se', 0):.2f}",
        })
    else:
        reasons.append({"requirement": "Специализация и грейд", "level": "none", "status": "missing",
                        "text": "Нет результата теста"})
    if req.get("grade") and p.current_grade_id and req["grade"] != p.current_grade_id:
        rel = "выше" if GRADE_LEVEL[p.current_grade_id] > GRADE_LEVEL[req["grade"]] else "ниже"
        reasons[-1]["text"] += f" — грейд на ступень {rel} запрошенного"
        reasons[-1]["status"] = "partial"

    def stack_part(items: list[dict], label: str) -> float:
        if not items:
            return 0.0
        total = sum(i["weight"] for i in items) or 1.0
        got = 0.0
        for i in items:
            tag, w = i["tag"], i["weight"]
            title = STACK.get(tag, (tag,))[0]
            f = b.skills_t1.get(tag)
            if skill_confirmed(f):
                got += w * f.value.get("score", 0)
                reasons.append({"requirement": f"{label}: {title}", "level": "T1", "status": "confirmed", "weight": w,
                                "text": f"Подтверждено заданиями теста: {fmt_count(f.value.get('correct'))} из {fmt_count(f.value.get('total'))}"})
            elif tag in b.stack_t0:
                reasons.append({"requirement": f"{label}: {title}", "level": "T0", "status": "declared", "weight": w,
                                "text": "Заявлено кандидатом — не влияет на ранжирование, можно проверить зондом"})
            else:
                reasons.append({"requirement": f"{label}: {title}", "level": "none", "status": "missing", "weight": w,
                                "text": "Нет данных"})
        return got / total

    sreq = stack_part(req.get("stack_required") or [], "Обязательно")
    sdes = stack_part(req.get("stack_desired") or [], "Желательно")
    fsp = b.fsp
    verified = [a for a in b.achievements if a.verified]
    if verified:
        best = min(verified, key=lambda a: a.place or 99)
        reasons.append({"requirement": "Достижения ФСП", "level": "T2", "status": "confirmed",
                        "text": achievement_text(best) + (f" и ещё {len(verified) - 1}" if len(verified) > 1 else "")})
    else:
        # Неподтверждённые реестром записи (значок «из анкеты») — не T2: ни бонуса, ни пометки «подтверждено»
        extra = len(b.achievements)
        reasons.append({"requirement": "Достижения ФСП", "level": "T0" if extra else "none", "status": "neutral",
                        "text": (f"Заявлено достижений ФСП без подтверждения реестром: {extra} — в ранжирование не входит"
                                 if extra else "Истории ФСП нет — нейтрально, без штрафа")})
    integ = (t or {}).get("integrity")
    if integ:
        lvl = integ.get("level")
        reasons.append({"requirement": "Достоверность результата теста", "level": "T1",
                        "status": {"high": "confirmed", "medium": "partial"}.get(lvl, "mismatch"),
                        "text": f"{(integ.get('title') or '').capitalize()}: " + "; ".join((integ.get("reasons") or [])[:2]),
                        "integrity": lvl})
    probe = max((f.value.get("score", 0) for f in b.probes_t1), default=0.0)
    if b.probes_t1:
        best = max(b.probes_t1, key=lambda f: f.value.get("score", 0))
        reasons.append({"requirement": "Зонд", "level": "T1", "status": "confirmed",
                        "text": f"«{best.title}» — {best.value.get('verdict', 'оценено')}"})
    # Фильтровые требования (T0): показываем, но в скор не включаем
    wf = req.get("work_format")
    if wf:
        ok = p.work_format.value in (wf, "any")
        reasons.append({"requirement": "Формат работы", "level": "T0", "status": "declared" if ok else "mismatch",
                        "text": "Заявленный формат подходит" if ok else "Заявлен другой формат работы"})
    comps = {"test": test, "stack_required": round(sreq, 3), "stack_desired": round(sdes, 3), "fsp": fsp,
             "probe": probe}
    if not req.get("stack_required"):
        # Нет обязательного стека — вес переносим на тест
        comps_w = dict(WEIGHTS, test=WEIGHTS["test"] + WEIGHTS["stack_required"], stack_required=0.0)
    else:
        comps_w = WEIGHTS
    score = sum(comps_w[k] * comps[k] for k in WEIGHTS)
    return round(score, 4), comps, reasons


def apply_filters(bundles: list[Bundle], f: dict) -> list[Bundle]:
    """Фильтры уточнения. T0-фильтры (заявленный стек, формат, город, стаж) только сужают выдачу."""
    out = []
    for b in bundles:
        p = b.profile
        if f.get("fsp_only") and not b.achievements:
            continue
        if f.get("stack_t1") and not all(skill_confirmed(b.skills_t1.get(t)) for t in f["stack_t1"]):
            continue
        if f.get("stack_any"):
            have = b.stack_t0 | {k for k, v in b.skills_t1.items() if skill_confirmed(v)}
            if not all(t in have for t in f["stack_any"]):
                continue
        if f.get("work_format") and p.work_format.value not in (f["work_format"], "any"):
            continue
        if f.get("city") and (p.city or "").strip().lower() != f["city"].strip().lower() and not p.relocation:
            continue
        if f.get("experience_min") is not None and float(p.experience_years or 0) < float(f["experience_min"]):
            continue
        out.append(b)
    return out


def build_selection(db: Session, req: dict, filters: dict, limit: int = 30) -> dict:
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    counts = category_counts(db)
    recs = recommended_categories(req, counts, cats)
    cat_ids = filters.get("categories") or [r["id"] for r in recs if r["relation"] in ("exact", "direction", "all")]
    pool = visible_pool(db, category_ids=cat_ids)
    bundles = list(load_bundles(db, [p.user_id for p in pool]).values())
    bundles = apply_filters(bundles, filters)
    scored = []
    for b in bundles:
        s, comps, reasons = score_candidate(b, req)
        if filters.get("min_score") and s < float(filters["min_score"]):
            continue
        scored.append((s, b, comps, reasons))
    scored.sort(key=lambda x: (-x[0], -(x[1].profile.rating_score or 0), x[1].profile.public_ref or ""))
    results = []
    for rank, (s, b, comps, reasons) in enumerate(scored[:limit], start=1):
        results.append({"ref": b.profile.public_ref, "rank": rank, "score": s, "components": comps,
                        "reasons": reasons, "category_id": b.profile.current_category_id,
                        "card": card(b, cats)})
    return {"categories": recs, "results": results, "total_matched": len(scored), "algorithm": ALGORITHM_VERSION,
            "weights": WEIGHTS}


def search(db: Session, *, direction=None, grade=None, category=None, stack: list[str] | None = None,
           stack_level: str = "any", fsp_only: bool = False, limit: int = 50, offset: int = 0) -> dict:
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    pool = visible_pool(db, direction=direction, grades=[grade] if grade else None,
                        category_ids=[category] if category else None)
    bundles = list(load_bundles(db, [p.user_id for p in pool]).values())
    f = {"fsp_only": fsp_only}
    if stack:
        f["stack_t1" if stack_level == "t1" else "stack_any"] = stack
    bundles = apply_filters(bundles, f)
    bundles.sort(key=lambda b: (-(b.profile.rating_score or 0), b.profile.public_ref or ""))
    # Место в категории — по рейтингу среди видимых
    by_cat: dict[str, list[float]] = {}
    for p in visible_pool(db):
        by_cat.setdefault(p.current_category_id, []).append(p.rating_score or 0)
    items = []
    for b in bundles[offset: offset + limit]:
        peers = by_cat.get(b.profile.current_category_id, [])
        rank = 1 + sum(1 for r in peers if r > (b.profile.rating_score or 0))
        items.append(card(b, cats, rank=rank, rank_total=len(peers)))
    return {"total": len(bundles), "items": items}
