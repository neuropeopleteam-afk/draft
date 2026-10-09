"""Подбор кандидатов под потребность: категории, ранжирование, объяснения.

Принципы (п. 2.1 ТЗ и бриф):
* Выдача строится по категориям, присвоенным тестом (T1), а не по самоописанию.
* Скор — только по подтверждённым фактам: результат теста (T1), навыки, проверенные заданиями (T1),
  зонды (T1), паспорт ФСП (T2). Самоописание (T0) — только фильтр и пометка «заявлено».
* Для каждого требования — объяснение с уровнем доказанности.

score = 0,45·тест + 0,35·покрытие обязательного стека (T1) + 0,05·желательный стек (T1)
        + 0,10·ФСП (T2, бонус; нет истории — 0 без штрафа) + 0,05·зонды (T1)
        − 0,05, если категория «Junior (предварительно)» (ниже подтверждённого при прочих равных)

Статус грейда (profiles.facts.grade_status): подтверждён / предварительно / не подтверждён. Кандидаты без
подтверждённого грейда (опрос пройден, теста нет или он не подтвердил заявленный грейд) видны работодателю
со статусом «грейд не подтверждён (заявлен …)» и всегда ниже подтверждённых и предварительных (отдельный ярус
выдачи); фильтр confirmed_only убирает и их, и «предварительно» (видео организаторов №6, решение Р10).
"""
from __future__ import annotations

from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from app.core.fmt import quoted, theta_se
from app.modules.auth.models import User
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import GRADE_LEVEL, GRADES, STACK
from app.modules.catalog.seed_data import category_title
from app.modules.profiles.facts import (
    GRADE_STATUS_ORDER,
    PROVISIONAL_PENALTY,
    fmt_count,
    Bundle,
    achievement_text,
    card,
    grade_status,
    load_bundles,
    skill_confirmed,
    skill_evidence_text,
    test_component,
)
from app.modules.assignments import signal as assignment_signal
from app.modules.jury import scope as jury_scope
from app.modules.matching import must_have
from app.modules.profiles.models import CandidateProfile, CandidateSpecialization

ALGORITHM_VERSION = "match-v1"
MUST_ALGORITHM = "match-v1.1"  # Ф2: match-v1 + ярусы обязательного (те же веса и балл), флаг MATCH_MUST_FIRST


def algorithm() -> str:
    return MUST_ALGORITHM if must_have.enabled() else ALGORITHM_VERSION
WEIGHTS = {"test": 0.45, "stack_required": 0.35, "stack_desired": 0.05, "fsp": 0.10, "probe": 0.05}
LEVELS = {"T2": "подтверждено реестром ФСП", "T1": "подтверждено тестом или зондом", "T0": "заявлено кандидатом",
          "none": "нет данных"}


def _has_category_clause():
    """Категория есть у профиля (основная) или у любой специализации (подтверждённая или предварительная)."""
    return or_(CandidateProfile.current_category_id.is_not(None),
               select(CandidateSpecialization.user_id).where(
                   CandidateSpecialization.user_id == CandidateProfile.user_id,
                   CandidateSpecialization.category_id.is_not(None),
                   CandidateSpecialization.status.in_(["confirmed", "provisional"])).exists())


def _pool_query(confirmed: bool):
    q = (select(CandidateProfile).join(User, User.id == CandidateProfile.user_id)
         .where(CandidateProfile.visible_to_employers.is_(True), User.is_active.is_(True),
                User.is_email_verified.is_(True), jury_scope.pool_clause(User.email)))
    if confirmed:
        return q.where(_has_category_clause())
    return q.where(~_has_category_clause(), CandidateProfile.onboarding_completed_at.is_not(None))


def visible_pool(db: Session, direction: str | None = None, grades: list[str] | None = None,
                 category_ids: list[str] | None = None) -> list[CandidateProfile]:
    """Кандидаты с категорией (подтверждённой или предварительной, основного или дополнительного направления),
    видимые работодателю."""
    legacy = [CandidateProfile.current_category_id.is_not(None)]
    special = [CandidateSpecialization.user_id == CandidateProfile.user_id,
               CandidateSpecialization.category_id.is_not(None),
               CandidateSpecialization.status.in_(["confirmed", "provisional"])]
    if direction:
        legacy.append(CandidateProfile.current_direction_id == direction)
        special.append(CandidateSpecialization.direction_id == direction)
    if grades:
        legacy.append(CandidateProfile.current_grade_id.in_(grades))
        special.append(CandidateSpecialization.grade_id.in_(grades))
    if category_ids:
        legacy.append(CandidateProfile.current_category_id.in_(category_ids))
        special.append(CandidateSpecialization.category_id.in_(category_ids))
    q = (select(CandidateProfile).join(User, User.id == CandidateProfile.user_id)
         .where(CandidateProfile.visible_to_employers.is_(True),
                or_(and_(*legacy), select(CandidateSpecialization.user_id).where(*special).exists()),
                User.is_active.is_(True), User.is_email_verified.is_(True), jury_scope.pool_clause(User.email)))
    return list(db.scalars(q).all())


def unconfirmed_pool(db: Session, direction: str | None = None, grades: list[str] | None = None,
                     category_ids: list[str] | None = None) -> list[tuple[CandidateProfile, str, str]]:
    """Кандидаты без подтверждённого грейда (опрос пройден, категории нет), видимые работодателю, с заявленными
    направлением и грейдом из последнего опроса: [(профиль, направление, грейд)]. Фильтры — по заявленному."""
    from app.modules.assessment.models import SurveyResponse

    profiles = list(db.scalars(_pool_query(confirmed=False)).all())
    if not profiles:
        return []
    claims: dict = {}
    for sv in db.scalars(select(SurveyResponse).where(SurveyResponse.user_id.in_([p.user_id for p in profiles]))
                         .order_by(SurveyResponse.created_at.desc())).all():
        claims.setdefault(sv.user_id, (sv.direction_id, sv.claimed_grade_id))
    out = []
    for p in profiles:
        d, g = claims.get(p.user_id, (None, None))
        if not d or not g:
            continue
        if direction and d != direction:
            continue
        if grades and g not in grades:
            continue
        if category_ids and f"{d}.{g}" not in category_ids:
            continue
        out.append((p, d, g))
    return out


def unconfirmed_counts(db: Session) -> dict[str, int]:
    """Сколько кандидатов без подтверждённого грейда заявили каждую категорию."""
    out: dict[str, int] = {}
    for _, d, g in unconfirmed_pool(db):
        out[f"{d}.{g}"] = out.get(f"{d}.{g}", 0) + 1
    return out


def category_counts(db: Session) -> dict[str, int]:
    out: dict[str, int] = {}
    for b in load_bundles(db, [p.user_id for p in visible_pool(db)]).values():
        for r in b.specializations.values():
            if r.category_id and r.status in ("confirmed", "provisional"):
                out[r.category_id] = out.get(r.category_id, 0) + 1
    return out


def provisional_counts(db: Session) -> dict[str, int]:
    """Сколько в категории «предварительно» (только Junior: правило нижнего порога)."""
    out: dict[str, int] = {}
    for b in load_bundles(db, [p.user_id for p in visible_pool(db)]).values():
        for r in b.specializations.values():
            if r.category_id and r.status == "provisional":
                out[r.category_id] = out.get(r.category_id, 0) + 1
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
    test = test_component(t.get("theta"), t.get("se"), req.get("grade") or b.grade)
    cat_title = category_title(b.category_id)
    if b.unconfirmed:
        # грейд не подтверждён: заявленное из опроса (T0) и исход последней попытки; результат теста в скор не входит
        gs = grade_status(b)
        reasons.append({"requirement": "Специализация и грейд", "level": "T0", "status": "unconfirmed",
                        "grade_status": "unconfirmed", "text": gs["text"]})
        test = 0.0
    elif b.test and t.get("mini"):  # экспресс-категория по мини-тесту живой демонстрации (app.jury_live)
        reasons.append({
            "requirement": "Специализация и грейд", "level": "T1", "status": "partial",
            "text": f"Экспресс-категория {cat_title} по мини-тесту {b.test.created_at:%d.%m.%Y}: "
                    f"{t.get('correct')} из {t.get('answered')} верно, θ = {theta_se(t.get('theta', 0), t.get('se'))}"
                    " — предварительно, полный тест уточнит грейд",
        })
    elif b.test and b.provisional:
        pv = t.get("provisional") or {}
        pct = f"{round(100 * float(pv['p']))} %" if pv.get("p") is not None else "—"
        reasons.append({
            "requirement": "Специализация и грейд", "level": "T1", "status": "partial", "provisional": True,
            "text": f"Категория {cat_title} — предварительно: тест {b.test.created_at:%d.%m.%Y} не подтвердил грейд, "
                    f"но и не доказал уровень ниже (вероятность уровня не ниже Junior — {pct}, подтверждение — от 80 %; "
                    f"θ = {theta_se(t.get('theta', 0), t.get('se'))}). В ранжировании −{PROVISIONAL_PENALTY:.2f}; "
                    "можно подтвердить зондом",
        })
    elif b.test:
        by = t.get("confirmed_by") if t.get("status") == "confirmed" else None
        how = {"probe": " (предварительный грейд подтверждён зондом)", "cup": " (предварительный грейд подтверждён кубком)",
               "extension": " с дотестированием у порога"}.get(by or "", "")
        reasons.append({
            "requirement": "Специализация и грейд", "level": "T1", "status": "confirmed",
            "text": f"Категория {cat_title} подтверждена тестом {b.test.created_at:%d.%m.%Y}{how}: "
                    f"{t.get('correct')} из {t.get('answered')} верно, θ = {theta_se(t.get('theta', 0), t.get('se'))}",
        })
    else:
        reasons.append({"requirement": "Специализация и грейд", "level": "none", "status": "missing",
                        "text": "Нет результата теста"})
    if req.get("grade") and b.grade and req["grade"] != b.grade:
        rel = "выше" if GRADE_LEVEL[b.grade] > GRADE_LEVEL[req["grade"]] else "ниже"
        distance = abs(GRADE_LEVEL[b.grade] - GRADE_LEVEL[req["grade"]])
        step = {1: "на ступень", 2: "на две ступени"}.get(distance, "на три ступени")
        reasons[-1]["text"] += f" — грейд {step} {rel} запрошенного"
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
                                "text": skill_evidence_text(f)})  # тест и задания работодателя (И7)
            elif f is not None:  # И18: тест проверял навык, порог не набран — это не «нет данных» (как в сравнении)
                reasons.append({"requirement": f"{label}: {title}", "level": "T1", "status": "mismatch", "weight": w,
                                "text": f"Проверено заданиями: {fmt_count(f.value.get('correct'))} из "
                                        f"{fmt_count(f.value.get('total'))} — ниже порога подтверждения"})
            elif tag in b.stack_t0:
                reasons.append({"requirement": f"{label}: {title}", "level": "T0", "status": "declared", "weight": w,
                                "text": "Заявлено кандидатом — не влияет на ранжирование, можно проверить зондом"})
            else:
                reasons.append({"requirement": f"{label}: {title}", "level": "none", "status": "missing", "weight": w,
                                "text": "Не подтверждено: тест кандидата этот навык не проверял, в профиле он не заявлен — "
                                        "можно проверить зондом"})
        return got / total

    sreq = stack_part(req.get("stack_required") or [], "Обязательно")
    sdes = stack_part(req.get("stack_desired") or [], "Желательно")
    fsp = b.fsp
    verified = [a for a in b.achievements if a.verified]
    if verified:
        best = min(verified, key=lambda a: a.place or 99)
        from app.modules.fsp.rating import details

        rating = details(verified)
        reasons.append({"requirement": "Достижения ФСП", "level": "T2", "status": "confirmed",
                        "text": achievement_text(best) + (f" и ещё {len(verified) - 1}" if len(verified) > 1 else "")
                        + f". Сила ФСП {fsp:.3f}, соревнований: {rating['competitions']}"})  # формула — в карточке (И18)
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
                        "text": f"{(integ.get('title') or '').capitalize()}: " + "; ".join((integ.get("reasons") or [])[:2])
                        + ("" if lvl == "high" else ". Не блокирует: на место в подборке не влияет, решение за вами — "
                                                    "можно пригласить или проверить зондом"),
                        "integrity": lvl})
    probe = max((f.value.get("score", 0) for f in b.probes_t1), default=0.0)
    own = [f for f in b.probes_t1 if not assignment_signal.is_assignment_fact(f)]  # задание работодателя — своя строка (К5)
    if own:
        best = max(own, key=lambda f: f.value.get("score", 0))
        reasons.append({"requirement": "Зонд", "level": "T1", "status": "confirmed",
                        "text": f"{quoted(best.title)} — {best.value.get('verdict', 'оценено')}"})
    sig = assignment_signal.reason_for(b.probes_t1)  # К5: адресное задание — одна строка, порядок match-v1 не меняет
    if sig:
        reasons.append(sig)
    # Фильтровые требования (T0): показываем, но в скор не включаем
    cond = need_conditions(req)
    allowed = cond["work_formats"]
    if allowed:
        ok = p.work_format.value in (*allowed, "any")
        reasons.append({"requirement": "Формат работы", "level": "T0", "status": "declared" if ok else "mismatch",
                        "text": "Заявленный формат подходит" if ok else "Заявлен другой формат работы"})
    if cond["city"] and city_applies(p.work_format.value, allowed):
        ok = getattr(p, "relocation", False) or (getattr(p, "city", None) or "").casefold() == cond["city"].casefold()
        reasons.append({"requirement": "Город присутствия", "level": "T0",
                        "status": "declared" if ok else "mismatch",
                        "text": "Город подходит или заявлен переезд" if ok else
                                f"Нужен {cond['city']}; заявлен другой город без переезда"})
    comps = {"test": test, "stack_required": round(sreq, 3), "stack_desired": round(sdes, 3), "fsp": fsp,
             "probe": probe, "provisional": PROVISIONAL_PENALTY if b.provisional else 0.0,
             "grade_status": b.grade_status}
    if not req.get("stack_required"):
        # Нет обязательного стека — вес переносим на тест
        comps_w = dict(WEIGHTS, test=WEIGHTS["test"] + WEIGHTS["stack_required"], stack_required=0.0)
    else:
        comps_w = WEIGHTS
    score = sum(comps_w[k] * comps[k] for k in WEIGHTS) - comps["provisional"]
    return round(score, 4), comps, reasons


def tier(b: Bundle) -> int:
    """Ярус выдачи: 0 — подтверждённые и предварительные (последние — со штрафом в скоре), 1 — грейд не подтверждён."""
    return GRADE_STATUS_ORDER[b.grade_status]


def requirement_priority(b: Bundle, req: dict) -> int:
    """Offline proposal: fewer unverified mandatory skills, then the unchanged T1/T2 score.

    No declared skills, no labels, no tuned coefficients. Existing score/weights remain unchanged.
    Not enabled in build_selection: the 500-candidate hidden-truth guard failed.
    A profile with gaps is not hidden: employer can check it with a probe.
    """
    must = req.get("stack_required") or []
    return sum(not skill_confirmed(b.skills_t1.get(i["tag"])) for i in must)


FORMATS = ("office", "hybrid", "remote")


def need_conditions(req: dict) -> dict:
    """Условия потребности (T0): допустимые форматы и город офиса. Ф2: «удалёнка или офис в Москве» —
    work_formats = [remote, office, hybrid], city = Москва: город относится только к офису и гибриду."""
    formats = [f for f in (req.get("work_formats") or []) if f in FORMATS]
    if not formats and req.get("work_format") in FORMATS:
        formats = [req["work_format"]]
    formats = list(dict.fromkeys(formats)) or None
    city = req.get("city") if formats and any(f in formats for f in ("office", "hybrid")) else None
    return {"work_formats": formats, "city": (city or "").strip() or None}


def city_applies(candidate_format: str, formats: list[str] | None) -> bool:
    """Город проверяется только у тех, кто будет работать на месте: офис и гибрид; «любой формат» — если удалёнка
    условиями не допускается. Без условия формата — у всех (ручной фильтр «Город»)."""
    if not formats:
        return True
    if candidate_format == "remote":
        return False
    if candidate_format == "any":
        return "remote" not in formats
    return True


def condition_filters(req: dict, filters: dict) -> dict:
    """Ф2: условия потребности (формат, город) применяются к подборке по умолчанию; явный фильтр версии важнее,
    conditions_off — показать всех без условий. T0-условия только сужают выдачу и не добавляют баллов."""
    out = {k: v for k, v in filters.items() if k != "conditions_off"}
    if filters.get("conditions_off"):
        return out
    cond = need_conditions(req)
    explicit_fmt = filters.get("work_formats") or filters.get("work_format")
    if not explicit_fmt and cond["work_formats"]:
        out["work_formats"] = cond["work_formats"]
    fmts = out.get("work_formats") or ([out["work_format"]] if out.get("work_format") else None)
    if not filters.get("city") and cond["city"] and fmts and any(f in fmts for f in ("office", "hybrid")):
        out["city"] = cond["city"]
    return out


def conditions_text(f: dict) -> str | None:
    """«Удалённо или офис/гибрид (Москва)» — подпись условий, применённых к версии."""
    titles = {"remote": "удалённо", "office": "офис", "hybrid": "гибрид"}
    fmts = f.get("work_formats") or ([f["work_format"]] if f.get("work_format") else [])
    city = f.get("city")
    onsite = "/".join(titles[x] for x in ("office", "hybrid") if x in fmts)
    if onsite and city:
        onsite += f" ({city})"
    txt = " или ".join((["удалённо"] if "remote" in fmts else []) + ([onsite] if onsite else []))
    if not fmts and city:
        txt = f"город {city}"
    return (txt[:1].upper() + txt[1:]) if txt else None


def apply_filters(bundles: list[Bundle], f: dict) -> list[Bundle]:
    """Фильтры уточнения. T0-фильтры (заявленный стек, формат, город, стаж) только сужают выдачу."""
    out = []
    for b in bundles:
        p = b.profile
        if f.get("fsp_only") and not b.achievements:
            continue
        if f.get("confirmed_only") and (b.provisional or b.unconfirmed):  # только подтверждённый грейд
            continue
        if f.get("stack_t1") and not all(skill_confirmed(b.skills_t1.get(t)) for t in f["stack_t1"]):
            continue
        if f.get("stack_any"):
            have = b.stack_t0 | {k for k, v in b.skills_t1.items() if skill_confirmed(v)}
            if not all(t in have for t in f["stack_any"]):
                continue
        formats = f.get("work_formats") or ([f["work_format"]] if f.get("work_format") else [])
        if formats and p.work_format.value not in (*formats, "any"):
            continue
        if (f.get("city") and city_applies(p.work_format.value, formats)
                and (p.city or "").strip().lower() != f["city"].strip().lower() and not p.relocation):
            continue
        if f.get("experience_min") is not None and float(p.experience_years or 0) < float(f["experience_min"]):
            continue
        out.append(b)
    return out


def build_selection(db: Session, req: dict, filters: dict, limit: int = 30, include_refs: tuple = ()) -> dict:
    """include_refs: кандидаты, которые идут в results со своим настоящим местом, даже ниже limit (QR-демо жюри)."""
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    counts = category_counts(db)
    recs = recommended_categories(req, counts, cats)
    cat_ids = filters.get("categories") or [r["id"] for r in recs if r["relation"] in ("exact", "direction", "all")]
    pool = visible_pool(db, category_ids=cat_ids)
    ids = [p.user_id for p in pool]
    if not filters.get("confirmed_only"):
        # без подтверждённого грейда — по заявленной категории, отдельным ярусом ниже (видео №6: показывать, не скрывать)
        ids += [p.user_id for p, _, _ in unconfirmed_pool(db, category_ids=cat_ids)]
    bundles = list(load_bundles(db, ids, direction=req.get("direction"), category_ids=cat_ids).values())
    # Ф2: условия потребности (формат, город — T0) применяются по умолчанию, только сужают выдачу и не дают баллов;
    # сколько скрыто условиями — в ответе (чип «скрыто условиями: N», отмена — filters.conditions_off)
    effective = condition_filters(req, filters)
    before_conditions = len(apply_filters(bundles, {k: v for k, v in filters.items() if k != "conditions_off"}))
    bundles = apply_filters(bundles, effective)
    scored = []
    for b in bundles:
        s, comps, reasons = score_candidate(b, req)
        if filters.get("min_score") and s < float(filters["min_score"]):
            continue
        scored.append((s, b, comps, reasons))
    # Ф2: ярус статуса грейда → ярус обязательного (0, 1, ≥ 2 непокрытых; must_have) → балл → рейтинг → ref
    levels = must_have.declared_levels(db, [b.profile.user_id for _, b, _, _ in scored]) \
        if must_have.declared_counts() else {}
    must = must_have.tiers_for([b for _, b, _, _ in scored], req, levels)
    scored.sort(key=lambda x: (tier(x[1]), must[x[1].profile.user_id]["tier"], -x[0], -(x[1].rating or 0),
                               x[1].profile.public_ref or ""))
    results = []
    for rank, (s, b, comps, reasons) in enumerate(scored, start=1):
        if rank > limit and b.profile.public_ref not in include_refs:
            continue
        results.append({"ref": b.profile.public_ref, "rank": rank, "score": s, "components": comps,
                        "reasons": reasons, "category_id": b.category_id, "must": must[b.profile.user_id],
                        "grade_status": b.grade_status, "card": card(b, cats)})
    prov, unc = provisional_counts(db), unconfirmed_counts(db)
    for r in recs:
        r["provisional"] = prov.get(r["id"], 0)
        r["unconfirmed"] = unc.get(r["id"], 0)
    applied = {k: effective[k] for k in ("work_formats", "work_format", "city") if effective.get(k)}
    conditions = {"applied": applied, "text": conditions_text(applied), "off": bool(filters.get("conditions_off")),
                  "from_need": need_conditions(req)["work_formats"] is not None,
                  "hidden": max(0, before_conditions - len(bundles))}
    meta = {"categories": recs, "conditions": conditions, "must_first": must_have.enabled(),
            "total_matched": len(scored)}
    return {"categories": recs, "results": results, "total_matched": len(scored), "algorithm": algorithm(),
            "conditions": conditions, "must_first": must_have.enabled(), "meta": meta,
            "weights": WEIGHTS, "provisional_penalty": PROVISIONAL_PENALTY,
            "provisional_matched": sum(1 for _, b, _, _ in scored if b.provisional),
            "unconfirmed_matched": sum(1 for _, b, _, _ in scored if b.unconfirmed),
            "confirmed_matched": sum(1 for _, b, _, _ in scored if b.grade_status == "confirmed")}


def search(db: Session, *, direction=None, grade=None, category=None, stack: list[str] | None = None,
           stack_level: str = "any", fsp_only: bool = False, limit: int = 50, offset: int = 0,
           confirmed_only: bool = False) -> dict:
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    pool = visible_pool(db, direction=direction, grades=[grade] if grade else None,
                        category_ids=[category] if category else None)
    wanted = [category] if category else [c.id for c in cats.values() if c.grade_id == grade] if grade else None
    ids = [p.user_id for p in pool]
    if not confirmed_only:  # без подтверждённого грейда — по заявленному, ярусом ниже
        ids += [p.user_id for p, _, _ in unconfirmed_pool(db, direction=direction, grades=[grade] if grade else None,
                                                             category_ids=[category] if category else None)]
    bundles = list(load_bundles(db, ids, direction=direction, category_ids=wanted).values())
    f = {"fsp_only": fsp_only, "confirmed_only": confirmed_only}
    if stack:
        f["stack_t1" if stack_level == "t1" else "stack_any"] = stack
    bundles = apply_filters(bundles, f)
    bundles.sort(key=lambda b: (tier(b), -(b.rating or 0), b.profile.public_ref or ""))
    # Место в категории — по рейтингу среди видимых
    by_cat: dict[str, list[float]] = {}
    for b in load_bundles(db, [p.user_id for p in visible_pool(db)]).values():
        for r in b.specializations.values():
            if r.category_id:
                by_cat.setdefault(r.category_id, []).append(r.rating_score or 0)
    items = []
    for b in bundles[offset: offset + limit]:
        if b.unconfirmed:  # места в категории нет — категории нет
            items.append(card(b, cats))
            continue
        peers = by_cat.get(b.category_id, [])
        rank = 1 + sum(1 for r in peers if r > (b.rating or 0))
        items.append(card(b, cats, rank=rank, rank_total=len(peers)))
    return {"total": len(bundles), "items": items,
            "provisional": sum(1 for b in bundles if b.provisional),
            "unconfirmed": sum(1 for b in bundles if b.unconfirmed),
            "confirmed": sum(1 for b in bundles if b.grade_status == "confirmed")}
