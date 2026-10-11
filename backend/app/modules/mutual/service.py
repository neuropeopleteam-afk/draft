"""Взаимный подбор: данные кандидатов для индикатора, отзывы по подборке, новые версии, ссылки для руководителя."""
from __future__ import annotations

from datetime import timedelta
import hashlib
import secrets
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import as_aware, utcnow
from app.core.errors import api_error
from app.modules.auth.models import User
from app.modules.catalog.seed_data import category_title, tag_title
from app.modules.invitations.models import Invitation
from app.modules.matching import ranking
from app.modules.matching.models import EmployerNeed, SelectionVersion
from app.modules.mutual import fit as fitm
from app.modules.mutual.models import (
    CandidatePreference,
    OfferFitCheck,
    SelectionFeedback,
    SelectionShare,
    ShareReaction,
)
from app.modules.profiles.facts import Bundle, load_bundles, skill_confirmed
from app.modules.profiles.models import CandidateProfile, Company

# Сравнений вилки со скрытым минимумом (корзины по 10 000 ₽) за сутки: на пару «компания — кандидат» в форме
# приглашения и на компанию по вилкам потребностей в подборках. Ограничивает подбор минимума перебором.
OFFER_CHECKS_PER_DAY = 5
SELECTION_BUCKETS_PER_DAY = 8
SHARE_TTL_DAYS = 7
SHARES_PER_NEED = 10
REASONS = {"skill": "навык", "grade": "грейд", "format": "формат", "salary": "зарплата", "other": "другое"}
VERDICTS = {"fit": "подходит", "unfit": "не подходит"}
REACTIONS = {"interesting": "интересно", "no": "нет"}


# ------------------------------------------------------------------ интересы кандидата

def prefs_dict(p: CandidatePreference | None) -> dict | None:
    if p is None:
        return None
    return {"offers_status": p.offers_status, "interest_tags": list(p.interest_tags or []),
            "interest_tasks": list(p.interest_tasks or []), "salary_signal": bool(p.salary_signal),
            "updated_at": p.updated_at.isoformat() if p.updated_at else None}


def prefs_of(db: Session, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    if not user_ids:
        return {}
    rows = db.scalars(select(CandidatePreference).where(CandidatePreference.user_id.in_(user_ids))).all()
    return {r.user_id: prefs_dict(r) for r in rows}


def save_prefs(db: Session, user_id: uuid.UUID, data: dict) -> dict:
    p = db.get(CandidatePreference, user_id)
    if p is None:
        p = CandidatePreference(user_id=user_id, interest_tags=[], interest_tasks=[], salary_signal=True)
        db.add(p)
    p.offers_status = data.get("offers_status")
    p.interest_tags = list(dict.fromkeys(data.get("interest_tags") or []))
    p.interest_tasks = list(dict.fromkeys(data.get("interest_tasks") or []))
    p.salary_signal = bool(data.get("salary_signal", True))
    p.updated_at = utcnow()
    db.commit()
    return prefs_dict(p)


def bundle_fit(b: Bundle, prefs: dict | None, req: dict, need_text: str | None, salary_to: int | None,
               audience: str = "employer", salary_limited: bool = False, salary_basis: str | None = "gross") -> dict:
    p = b.profile
    return fitm.offer_fit(work_format=p.work_format.value if p.work_format else "any", city=p.city,
                          relocation=bool(p.relocation), salary_min=p.salary_min_hidden, privacy=b.privacy,
                          declared_stack=b.stack_t0, prefs=prefs, req=req or {}, need_text=need_text,
                          salary_to=salary_to, audience=audience, salary_limited=salary_limited,
                          salary_basis=salary_basis)


def need_salary_basis(req: dict) -> str:
    """Основание вилки потребности: «на руки», если так сказано в тексте (need_parser.salary_net), иначе до вычета."""
    return "net" if req.get("salary_net") else "gross"


# ------------------------------------------------------------------ лимит сравнений вилки

def _since():
    return utcnow() - timedelta(days=1)


def salary_allowed(db: Session, company_id: uuid.UUID, candidate_id: uuid.UUID | None, salary_to: int | None,
                   limit: int) -> bool:
    """True — сравнение вилки разрешено (и записано). Повтор той же корзины — бесплатно."""
    if not salary_to:
        return True
    bucket = fitm.salary_bucket(salary_to)
    cond = [OfferFitCheck.company_id == company_id, OfferFitCheck.created_at > _since()]
    cond.append(OfferFitCheck.candidate_user_id == candidate_id if candidate_id else OfferFitCheck.candidate_user_id.is_(None))
    seen = set(db.scalars(select(OfferFitCheck.salary_bucket).where(*cond)).all())
    if bucket in seen:
        return True
    if len(seen) >= limit:
        return False
    db.add(OfferFitCheck(company_id=company_id, candidate_user_id=candidate_id, salary_bucket=bucket))
    db.commit()
    return True


# ------------------------------------------------------------------ подборка: индикатор, отзывы, порядок

def own_version(db: Session, need: EmployerNeed, version: int) -> SelectionVersion:
    v = db.scalar(select(SelectionVersion).where(SelectionVersion.need_id == need.id, SelectionVersion.version == version))
    if v is None:
        raise api_error(404, "version_not_found", "Версия подборки не найдена")
    return v


def _profiles_by_ref(db: Session, refs: list[str]) -> dict[str, CandidateProfile]:
    if not refs:
        return {}
    return {p.public_ref: p for p in db.scalars(select(CandidateProfile).where(CandidateProfile.public_ref.in_(refs))).all()}


def fits_for_results(db: Session, company_id: uuid.UUID, need: EmployerNeed, req: dict, results: list[dict]) -> dict:
    refs = [r["ref"] for r in results]
    profiles = _profiles_by_ref(db, refs)
    ids = [p.user_id for p in profiles.values()]
    bundles = load_bundles(db, ids, direction=req.get("direction")) if ids else {}
    prefs = prefs_of(db, ids)
    salary_to = req.get("salary_to") or req.get("salary_from")
    basis = need_salary_basis(req)
    allowed = salary_allowed(db, company_id, None, salary_to, SELECTION_BUCKETS_PER_DAY)  # корзины — по введённой вилке
    out = {}
    for ref, p in profiles.items():
        b = bundles.get(p.user_id)
        if b is not None:
            out[ref] = bundle_fit(b, prefs.get(p.user_id), req, need.raw_text, salary_to, salary_limited=not allowed,
                                  salary_basis=basis)
    return out


def feedback_out(f: SelectionFeedback) -> dict:
    return {"ref": f.candidate_ref, "version": f.version, "verdict": f.verdict, "verdict_title": VERDICTS[f.verdict],
            "reason": f.reason, "reason_title": REASONS.get(f.reason or ""), "comment": f.comment,
            "updated_at": f.updated_at.isoformat()}


def feedback_map(db: Session, need: EmployerNeed) -> dict[str, dict]:
    rows = db.scalars(select(SelectionFeedback).where(SelectionFeedback.need_id == need.id)).all()
    return {f.candidate_ref: feedback_out(f) for f in rows}


def reactions_map(db: Session, need: EmployerNeed) -> dict[str, list[dict]]:
    rows = db.execute(select(ShareReaction, SelectionShare).join(SelectionShare, SelectionShare.id == ShareReaction.share_id)
                      .where(SelectionShare.need_id == need.id).order_by(ShareReaction.updated_at.desc())).all()
    out: dict[str, list[dict]] = {}
    for r, s in rows:
        out.setdefault(r.candidate_ref, []).append(reaction_out(r, s))
    return out


def reaction_out(r: ShareReaction, s: SelectionShare | None = None) -> dict:
    return {"ref": r.candidate_ref, "verdict": r.verdict, "verdict_title": REACTIONS[r.verdict], "comment": r.comment,
            "author": r.author, "updated_at": r.updated_at.isoformat(),
            "share_label": s.label if s else None, "share_version": s.version if s else None}


def version_mutual(db: Session, company: Company, need: EmployerNeed, v: SelectionVersion) -> dict:
    fits = fits_for_results(db, company.id, need, v.requirements or {}, v.results)
    counts = {k: 0 for k in fitm.LEVELS}
    for f in fits.values():
        counts[f["level"]] += 1
    return {"version": v.version, "algorithm": fitm.ALGORITHM, "weights": fitm.WEIGHTS, "levels": fitm.LEVELS,
            "items": fits, "mutual_order": fitm.mutual_order(v.results, fits), "counts": counts,
            "feedback": feedback_map(db, need), "reactions": reactions_map(db, need),
            "tasks_detected": fitm.detect_tasks(need.raw_text),
            "note": "Индикатор — вторая сторона подбора: формат, город или удалёнка, вилка против скрытого минимума "
                    "(только «в ожиданиях / ниже ожиданий»), интерес к стеку и задачам, готовность к предложениям. "
                    "Всё это — самоописание кандидата (T0): в скор подбора не входит, порядок match-v1 по умолчанию "
                    "не меняется."}


def _ref_in(v: SelectionVersion, ref: str) -> dict:
    for r in v.results:
        if r.get("ref") == ref:
            return r
    raise api_error(404, "candidate_not_in_selection", "Кандидата нет в этой версии подборки")


def set_feedback(db: Session, user: User, need: EmployerNeed, v: SelectionVersion, ref: str, verdict: str,
                 reason: str | None, comment: str | None) -> dict:
    _ref_in(v, ref)
    if verdict == "unfit" and not reason:
        raise api_error(422, "reason_required", "Укажите причину: навык, грейд, формат, зарплата или другое")
    f = db.scalar(select(SelectionFeedback).where(SelectionFeedback.need_id == need.id,
                                                  SelectionFeedback.candidate_ref == ref))
    if f is None:
        f = SelectionFeedback(need_id=need.id, candidate_ref=ref, version=v.version, verdict=verdict)
        db.add(f)
    f.version, f.verdict, f.created_by = v.version, verdict, user.id
    f.reason = reason if verdict == "unfit" else None
    f.comment = (comment or "").strip()[:300] or None
    db.commit()
    return feedback_out(f)


def delete_feedback(db: Session, need: EmployerNeed, ref: str) -> None:
    f = db.scalar(select(SelectionFeedback).where(SelectionFeedback.need_id == need.id,
                                                  SelectionFeedback.candidate_ref == ref))
    if f is None:
        raise api_error(404, "feedback_not_found", "Отзыва о кандидате нет")
    db.delete(f)
    db.commit()


def _make_version(db: Session, need: EmployerNeed, user: User, filters: dict, parent: int, req: dict,
                  origin: dict) -> SelectionVersion:
    """Новая версия через тот же путь, что и уточнение фильтров (matching.router._make_version, match-v1)."""
    from app.modules.matching.router import _make_version as make

    v = make(db, need, user, {**filters, "origin": origin}, parent, req)
    return v


def _missing_required(results_by_ref: dict[str, dict], refs: list[str]) -> list[str]:
    """Обязательные навыки, которых не хватало (не T1) у отклонённых «по навыку»."""
    tags: dict[str, int] = {}
    for ref in refs:
        for x in (results_by_ref.get(ref) or {}).get("reasons") or []:
            req = x.get("requirement") or ""
            if req.startswith("Обязательно: ") and x.get("status") != "confirmed":
                tags[req.removeprefix("Обязательно: ")] = tags.get(req.removeprefix("Обязательно: "), 0) + 1
    return list(tags)


def refine_by_feedback(db: Session, user: User, need: EmployerNeed, v: SelectionVersion) -> SelectionVersion:
    """Новая версия по отзывам: отклонённые исключены; причины превращаются в фильтры (только сужают выдачу)."""
    fb = db.scalars(select(SelectionFeedback).where(SelectionFeedback.need_id == need.id)).all()
    unfit = [f for f in fb if f.verdict == "unfit"]
    if not unfit:
        raise api_error(409, "no_feedback", "Отметьте хотя бы одного кандидата «не подходит» — тогда будет что уточнять")
    req = dict(v.requirements or {})
    filters = {k: val for k, val in (v.filters or {}).items() if k not in ("origin", "_meta")}  # Ф2: снимок версии — свой
    filters["exclude_refs"] = sorted(set(filters.get("exclude_refs") or []) | {f.candidate_ref for f in unfit})
    reasons = {f.reason for f in unfit}
    notes = [f"исключены «не подходит»: {len(filters['exclude_refs'])}"]
    strict: dict = {}
    if "format" in reasons and fitm._formats(req):
        fm = fitm._formats(req)
        strict.update({"work_formats": fm} if len(fm) > 1 else {"work_format": fm[0]})
        if req.get("city") and any(x in ("office", "hybrid") for x in fm):
            strict["city"] = req["city"]
        notes.append("формат и город — из потребности")
    if "skill" in reasons:
        by_ref = {r["ref"]: r for r in v.results}
        titles = _missing_required(by_ref, [f.candidate_ref for f in unfit if f.reason == "skill"])
        title_to_tag = {tag_title(i["tag"]): i["tag"] for i in req.get("stack_required") or []}
        tags = [title_to_tag[t] for t in titles if t in title_to_tag]
        if tags:
            strict["stack_t1"] = sorted(set(filters.get("stack_t1") or []) | set(tags))
            notes.append("только с подтверждённым (T1): " + ", ".join(titles))
    if "grade" in reasons:
        strict["confirmed_only"] = True
        if req.get("direction") and req.get("grade"):
            strict["categories"] = [f"{req['direction']}.{req['grade']}"]
        notes.append("только подтверждённый грейд" + (f" {category_title(strict['categories'][0])}"
                                                       if strict.get("categories") else ""))
    if "salary" in reasons:
        notes.append("зарплата: фильтра по скрытому минимуму нет — включите порядок «с учётом интереса кандидата»")
    origin = {"kind": "feedback", "from": v.version, "unfit": len(unfit), "fit": sum(f.verdict == "fit" for f in fb)}
    nv = _make_version(db, need, user, {**filters, **strict}, v.version, req, {**origin, "note": "; ".join(notes)})
    if strict and not nv.results:  # строгие фильтры дали пустую выдачу — оставляем только исключение отклонённых
        db.delete(nv)
        db.commit()
        notes.append("строгие фильтры дали пустую выдачу — оставлено только исключение отклонённых")
        nv = _make_version(db, need, user, filters, v.version, req, {**origin, "note": "; ".join(notes)})
    return nv


def similar(db: Session, user: User, need: EmployerNeed, v: SelectionVersion, ref: str) -> SelectionVersion:
    """«Ещё похожих на этого»: та же категория, те же подтверждённые обязательные навыки; его сильные стороны (T1)
    добавлены в желательные. Порядок — match-v1 по уточнённым требованиям."""
    base = _ref_in(v, ref)
    p = db.scalar(select(CandidateProfile).where(CandidateProfile.public_ref == ref))
    if p is None:
        raise api_error(404, "candidate_not_found", "Кандидат не найден или скрыл профиль")
    req = {**(v.requirements or {})}
    b = load_bundles(db, [p.user_id], direction=req.get("direction"))[p.user_id]
    confirmed = {t: f.value.get("score", 0) for t, f in b.skills_t1.items() if skill_confirmed(f)}
    used = {i["tag"] for i in (req.get("stack_required") or []) + (req.get("stack_desired") or [])}
    extra = [t for t, _ in sorted(confirmed.items(), key=lambda x: -x[1]) if t not in used][:4]
    req["stack_desired"] = list(req.get("stack_desired") or []) + [{"tag": t, "weight": 0.5, "status": "manual"} for t in extra]
    filters = {k: val for k, val in (v.filters or {}).items() if k not in ("origin", "_meta")}  # Ф2: снимок версии — свой
    same_must = [i["tag"] for i in req.get("stack_required") or [] if i["tag"] in confirmed]
    strict = {}
    cat = base.get("category_id") or b.category_id
    if cat:
        strict["categories"] = [cat]
    if same_must:
        strict["stack_t1"] = same_must
    names = lambda tags: ", ".join(tag_title(t) for t in tags)  # noqa: E731
    note = [f"похожие на {ref}"] + ([f"категория {category_title(cat)}"] if cat else []) \
        + ([f"подтверждены те же обязательные: {names(same_must)}"] if same_must else []) \
        + ([f"в желательные добавлено его подтверждённое: {names(extra)}"] if extra else [])
    origin = {"kind": "similar", "ref": ref, "from": v.version}
    nv = _make_version(db, need, user, {**filters, **strict}, v.version, req, {**origin, "note": "; ".join(note)})
    if len(nv.results) <= 1 and "stack_t1" in strict:  # кроме него самого — никого: ослабляем до категории
        db.delete(nv)
        db.commit()
        strict.pop("stack_t1")
        note.append("с теми же подтверждёнными навыками больше никого — оставлена только категория")
        nv = _make_version(db, need, user, {**filters, **strict}, v.version, req, {**origin, "note": "; ".join(note)})
    return nv


# ------------------------------------------------------------------ форма приглашения: подсказка до отправки

def offer_hint(fit: dict) -> tuple[str, str | None]:
    """Заголовок подсказки формы приглашения и причина отказа. FIX7 В1 (замечание владельца): при «Вероятно, откажет»
    не из-за вилки (город без переезда, формат) заголовок — настоящая причина, а не «Вилка в ожиданиях кандидата»."""
    sal = next(f for f in fit["factors"] if f["key"] == "salary")
    veto = next((f for f in fit["factors"] if f["status"] == "bad" and f["key"] in ("location", "format")), None)
    if sal["status"] == "bad":
        return ("С такой вилкой кандидат, вероятно, откажет: верх вилки ниже его ожиданий. Минимум кандидата не "
                "раскрывается.", "salary")
    if veto is not None and fit["level"] == "low":
        return (f"{veto['text']} — кандидат, вероятно, откажет"
                + (". Вилка при этом в его ожиданиях." if sal["status"] == "ok" else "."), veto["key"])
    return ("Вилка в ожиданиях кандидата." if sal["status"] == "ok" else sal["text"]), None


def offer_check(db: Session, company: Company, p: CandidateProfile, salary_to: int, need: EmployerNeed | None,
                salary_basis: str = "gross") -> dict:
    req = dict(need.requirements or {}) if need else {}
    b = load_bundles(db, [p.user_id], direction=req.get("direction"))[p.user_id]
    allowed = salary_allowed(db, company.id, p.user_id, salary_to, OFFER_CHECKS_PER_DAY)
    out = bundle_fit(b, prefs_of(db, [p.user_id]).get(p.user_id), {**req, "salary_to": salary_to},
                     need.raw_text if need else None, salary_to, salary_limited=not allowed, salary_basis=salary_basis)
    sal = next(f for f in out["factors"] if f["key"] == "salary")
    out["hint"], out["decline_reason"] = offer_hint(out)
    out["salary_status"] = sal["status"]
    out["checks_left"] = None if not allowed else max(0, OFFER_CHECKS_PER_DAY - len(set(db.scalars(
        select(OfferFitCheck.salary_bucket).where(OfferFitCheck.company_id == company.id,
                                                  OfferFitCheck.candidate_user_id == p.user_id,
                                                  OfferFitCheck.created_at > _since())).all())))
    return out


# ------------------------------------------------------------------ ссылка для нанимающего руководителя

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def share_status(s: SelectionShare) -> str:
    if s.revoked_at:
        return "revoked"
    return "expired" if as_aware(s.expires_at) <= utcnow() else "active"


def share_out(db: Session, s: SelectionShare) -> dict:
    rs = db.scalars(select(ShareReaction).where(ShareReaction.share_id == s.id).order_by(ShareReaction.updated_at.desc())).all()
    return {"id": str(s.id), "version": s.version, "label": s.label, "status": share_status(s),
            "created_at": s.created_at.isoformat(), "expires_at": as_aware(s.expires_at).isoformat(),
            "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None, "views": s.views,
            "last_viewed_at": s.last_viewed_at.isoformat() if s.last_viewed_at else None,
            "reactions": [reaction_out(r, s) for r in rs]}


def create_share(db: Session, user: User, need: EmployerNeed, v: SelectionVersion, label: str | None) -> dict:
    active = db.scalar(select(func.count(SelectionShare.id)).where(
        SelectionShare.need_id == need.id, SelectionShare.revoked_at.is_(None), SelectionShare.expires_at > utcnow()))
    if (active or 0) >= SHARES_PER_NEED:
        raise api_error(409, "too_many_shares", f"Активных ссылок по потребности — не больше {SHARES_PER_NEED}: отзовите лишние")
    token = secrets.token_urlsafe(24)
    s = SelectionShare(need_id=need.id, version=v.version, token_hash=_hash(token), label=(label or "").strip()[:100] or None,
                       created_by=user.id, expires_at=utcnow() + timedelta(days=SHARE_TTL_DAYS))
    db.add(s)
    db.commit()
    return {**share_out(db, s), "token": token, "path": f"/share/{token}"}


def share_by_token(db: Session, token: str) -> SelectionShare:
    s = db.scalar(select(SelectionShare).where(SelectionShare.token_hash == _hash(token))) if 16 <= len(token) <= 64 else None
    if s is None:
        raise api_error(404, "share_not_found", "Ссылка не найдена")
    st = share_status(s)
    if st != "active":
        raise api_error(410, f"share_{st}", "Ссылка отозвана рекрутером" if st == "revoked" else
                        "Срок ссылки (7 дней) истёк — попросите рекрутера новую")
    return s


def _req_summary(req: dict) -> dict:
    title = lambda items: [tag_title(i["tag"]) for i in items or []]  # noqa: E731
    return {"category": category_title(f"{req['direction']}.{req['grade']}") if req.get("direction") and req.get("grade")
            else None, "direction": req.get("direction"), "grade": req.get("grade"),
            "stack_required": title(req.get("stack_required")), "stack_desired": title(req.get("stack_desired")),
            "work_format": req.get("work_format"), "work_formats": req.get("work_formats"), "city": req.get("city"),
            "salary_from": req.get("salary_from"), "salary_to": req.get("salary_to"),
            "experience_years_min": req.get("experience_years_min")}


def public_view(db: Session, s: SelectionShare) -> dict:
    """Только чтение, без ПДн: обезличенные карточки версии (как у работодателя), объяснения, индикатор взаимности."""
    need = db.get(EmployerNeed, s.need_id)
    v = own_version(db, need, s.version)
    company = db.get(Company, need.company_id)
    visible = {p.public_ref for p in _profiles_by_ref(db, [r["ref"] for r in v.results]).values() if p.visible_to_employers}
    results = [r for r in v.results if r["ref"] in visible]
    fits = fits_for_results(db, company.id, need, v.requirements or {}, results)
    mine = {r.candidate_ref: reaction_out(r) for r in db.scalars(select(ShareReaction).where(ShareReaction.share_id == s.id))}
    s.views = (s.views or 0) + 1
    s.last_viewed_at = utcnow()
    db.commit()
    return {"company": company.name if company else None, "need_title": need.title,
            "requirements": _req_summary(v.requirements or {}), "version": v.version,
            "created_at": v.created_at.isoformat(), "label": s.label, "expires_at": as_aware(s.expires_at).isoformat(),
            "hidden": len(v.results) - len(results),
            "candidates": [{"ref": r["ref"], "rank": r.get("rank"), "score": r.get("score"),
                            "grade_status": r.get("grade_status"), "card": r.get("card"), "reasons": r.get("reasons"),
                            "fit": {k: (fits.get(r["ref"]) or {}).get(k) for k in ("level", "title", "line")}}
                           for r in results],
            "reactions": mine,
            "note": "Обезличенная подборка: ФИО, контакты и минимум зарплаты не показываются. Отметки «интересно / "
                    "нет» увидит рекрутер."}


def react(db: Session, s: SelectionShare, ref: str, verdict: str, comment: str | None, author: str | None) -> dict:
    need = db.get(EmployerNeed, s.need_id)
    _ref_in(own_version(db, need, s.version), ref)
    r = db.scalar(select(ShareReaction).where(ShareReaction.share_id == s.id, ShareReaction.candidate_ref == ref))
    if r is None:
        r = ShareReaction(share_id=s.id, candidate_ref=ref, verdict=verdict)
        db.add(r)
    r.verdict = verdict
    r.comment = (comment or "").strip()[:500] or None
    r.author = (author or "").strip()[:80] or None
    db.commit()
    return reaction_out(r, s)


# ------------------------------------------------------------------ кандидат: почему выбрали

def why(db: Session, inv: Invitation) -> dict:
    """Почему кандидата выбрали: требования потребности с уровнем доказанности, место в подборке, совпадение условий
    предложения с его собственными (здесь — точные: это его данные)."""
    need = db.get(EmployerNeed, inv.need_id) if inv.need_id else None
    req = dict(need.requirements or {}) if need else {}
    uid = inv.candidate_user_id
    p = db.get(CandidateProfile, uid)
    b = load_bundles(db, [uid], direction=req.get("direction"))[uid]
    offer = bundle_fit(b, prefs_of(db, [uid]).get(uid), {**req, "salary_to": inv.salary_to},
                       need.raw_text if need else None, inv.salary_to, audience="candidate",
                       salary_basis=getattr(inv, "salary_basis", None) or "gross")
    out = {"need": None, "place": None, "matched": [], "counts": {}, "to_confirm": [], "offer": offer}
    if not need:
        return out
    _, _, reasons = ranking.score_candidate(b, req)
    skip = {"Формат работы", "Город присутствия"}  # условия — в блоке «условия предложения»
    matched = [{k: x.get(k) for k in ("requirement", "level", "status", "text")} for x in reasons
               if x.get("requirement") not in skip]
    place = None
    for v in db.scalars(select(SelectionVersion).where(SelectionVersion.need_id == need.id)
                        .order_by(SelectionVersion.version.desc())).all():
        hit = next((r for r in v.results if r.get("ref") == p.public_ref), None)
        if hit:
            place = {"version": v.version, "rank": hit.get("rank"), "total": len(v.results),
                     "score": hit.get("score")}
            break
    to_confirm = [x["requirement"].split(": ", 1)[1] for x in matched
                  if x["requirement"].startswith("Обязательно: ") and x["status"] != "confirmed"]
    out.update({"need": {"title": need.title, "category": category_title(f"{req['direction']}.{req['grade']}")
                         if req.get("direction") and req.get("grade") else None},
                "place": place, "matched": matched,
                "counts": {"confirmed": sum(1 for x in matched if x["status"] in ("confirmed", "partial")
                                            and x["level"] in ("T1", "T2")),
                           "declared": sum(1 for x in matched if x["status"] == "declared"),
                           "missing": sum(1 for x in matched if x["status"] == "missing")},
                "to_confirm": to_confirm})
    return out
