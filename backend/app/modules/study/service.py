"""Обезличенная статистика прохождения: включение, отказ, события экранов и ошибок, необязательная анкета, сброс."""
from __future__ import annotations

import re
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.db import as_aware, utcnow
from app.core.errors import api_error
from app.modules.auth.models import User
from app.modules.matching.models import EmployerNeed, SelectionVersion
from app.modules.study import exclude
from app.modules.study import path as P
from app.modules.study import stats, texts
from app.modules.study.models import StudyAnswer, StudyEvent, StudyParticipant

EVENT_CAP = 3000  # событий на участника: защита базы от зацикленного клиента
TOP_K = 5


# ----------------------------------------------------------------------------- участник

def participant_of(db: Session, user: User) -> StudyParticipant | None:
    return db.scalar(select(StudyParticipant).where(StudyParticipant.user_id == user.id))


def active_of(db: Session, user: User) -> StudyParticipant | None:
    p = participant_of(db, user)
    return p if p is not None and p.declined_at is None else None


def enroll(db: Session, user: User, *, ua: str | None = None, automation: bool = False, again: bool = False) -> dict:
    """Включить сбор (показано уведомление). Отказавшего повторно не включаем сами: только по его явной просьбе (again)."""
    why = exclude.reason(user, ua=ua, automation=automation)
    if why is not None:
        return {"state": "excluded", "reason": why}
    p = participant_of(db, user)
    if p is not None and p.declined_at is not None:
        if not again:
            return {"state": "declined"}
        p.declined_at, p.enrolled_at, p.prompted_at = None, utcnow(), None  # свежее начало: прошлый отказ — не «путь»
    if p is None:
        p = StudyParticipant(user_id=user.id, role=user.role.value, enrolled_at=utcnow())
        db.add(p)
    db.commit()
    return me(db, user)


def decline(db: Session, user: User) -> dict:
    """«Не участвовать»: события и анкета удаляются, сбор больше не ведётся. Работает и до первого включения."""
    p = participant_of(db, user)
    if p is None:
        if exclude.reason(user) in ("role", "disabled"):
            return {"state": "excluded"}
        p = StudyParticipant(user_id=user.id, role=user.role.value if user.role.value in texts.ROLES else "candidate",
                             enrolled_at=utcnow())
        db.add(p)
        db.flush()
    db.execute(delete(StudyEvent).where(StudyEvent.participant_id == p.id))
    db.execute(delete(StudyAnswer).where(StudyAnswer.participant_id == p.id))
    p.declined_at = utcnow()
    db.commit()
    return {"state": "declined"}


def me(db: Session, user: User, *, ua: str | None = None) -> dict:
    """Состояние для интерфейса: new (уведомление ещё не показано) | on | declined | excluded."""
    p = participant_of(db, user)
    if p is not None and p.declined_at is not None:
        return {"state": "declined"}
    if p is None:
        why = exclude.reason(user, ua=ua)
        return {"state": "excluded", "reason": why} if why else {"state": "new"}
    if exclude.reason(user, ua=ua) in ("automation",):
        return {"state": "excluded", "reason": "automation"}
    d = P.derive(db, p)
    ans = P.answered(db, p)
    rows = []
    defs = {k: (t, link) for k, t, link in texts.PATH[p.role]}
    for k in d["keys"]:
        s = d["steps"][k]
        rows.append({"key": k, "title": defs[k][0], "link": defs[k][1], "done": s["at"] is not None, "skipped": s["skipped"],
                     "at": s["at"].isoformat() if s["at"] else None})
    return {"state": "on", "role": p.role, "steps": rows, "current": d["current"], "path_done": d["path_done"],
            "answered": ans is not None,
            "prompt": bool(d["path_done"] and ans is None and p.prompted_at is None),  # анкету предложить один раз
            "survey_url": "/study/survey"}


def mark_prompted(db: Session, user: User) -> dict:
    p = active_of(db, user)
    if p is not None and p.prompted_at is None:
        p.prompted_at = utcnow()
        db.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------- события экранов и ошибок

def record_event(db: Session, user: User, kind: str, key: str, status: int | None = None, code: str | None = None,
                 ua: str | None = None) -> bool:
    p = active_of(db, user)
    if p is None or exclude.automation_ua(ua):
        return False  # не включено или отказ: ничего не пишем
    k = P.norm_key(key)
    if k is None or k.startswith("/study"):
        return False
    n = db.scalar(select(func.count()).select_from(StudyEvent).where(StudyEvent.participant_id == p.id)) or 0
    if n >= EVENT_CAP:
        return False
    now = utcnow()
    last = db.scalar(select(StudyEvent).where(StudyEvent.participant_id == p.id).order_by(StudyEvent.at.desc()).limit(1))
    if last is not None and last.kind == kind and last.key == k and last.status == status \
            and (now - as_aware(last.at)).total_seconds() < 1.0:
        return False
    db.add(StudyEvent(participant_id=p.id, kind=kind, key=k, status=status if kind == "error" else None,
                      code=(re.sub(r"[^A-Za-z0-9_.\-]", "", code or "")[:64] or None) if kind == "error" else None, at=now))
    p.last_seen_at = now
    db.commit()
    return True


# ----------------------------------------------------------------------------- анкета (необязательная)

def top5(db: Session, user: User, need_id: str | None = None, version: int | None = None) -> dict | None:
    """Первые пять кандидатов подборки, которую работодатель смотрел (need_id и version — из адреса экрана; без них — последняя
    подборка его потребностей): то, что он оценивает в анкете, в порядке выдачи."""
    q = (select(SelectionVersion).join(EmployerNeed, EmployerNeed.id == SelectionVersion.need_id)
         .where(EmployerNeed.created_by == user.id))
    if need_id:
        try:
            q = q.where(SelectionVersion.need_id == uuid.UUID(str(need_id)))
        except ValueError:
            return None
        if version:
            q = q.where(SelectionVersion.version == version)
    v = db.scalar(q.order_by(SelectionVersion.created_at.desc(), SelectionVersion.version.desc()).limit(1))
    if v is None or not v.results:
        return None
    shown = []
    for r in v.results[:TOP_K]:
        c = r.get("card") or {}
        cat = (c.get("category") or {}).get("title") or ((c.get("claimed") or {}).get("title"))
        reasons = [str(x.get("text")) for x in (r.get("reasons") or []) if isinstance(x, dict) and x.get("text")][:3]
        shown.append({"ref": r.get("ref"), "rank": r.get("rank") or len(shown) + 1, "category": cat,
                      "status": r.get("grade_status") or (c.get("status") or {}).get("status"), "reasons": reasons})
    return {"need_id": str(v.need_id), "version": v.version, "algorithm": v.algorithm_version, "shown": shown}


def form(db: Session, user: User, need_id: str | None = None, version: int | None = None) -> dict:
    p = active_of(db, user)
    if p is None:
        raise api_error(404, "not_participant", "Статистика прохождения для этой учётной записи не ведётся")
    d = P.derive(db, p)
    ans = P.answered(db, p)
    exposed = d["steps"].get("result" if p.role == "candidate" else "selection", {}).get("at") is not None
    sel = top5(db, user, need_id, version) if p.role == "employer" and exposed else None
    return {"role": p.role, "path_done": d["path_done"], "exposed": exposed,
            "sus": {"items": list(texts.SUS_ITEMS), "scale": list(texts.SUS_SCALE)},
            "rel": {"scale": list(texts.REL_SCALE), "threshold": texts.REL_THRESHOLD, "selection": sel},
            "belief": {"q": texts.BELIEF_Q[p.role]} if exposed else None,
            "grade_fit": ({"q": texts.GRADE_FIT_Q, "options": texts.GRADE_FIT} if p.role == "candidate" and exposed else None),
            "tags": texts.BLOCKER_TAGS, "text_max": texts.TEXT_MAX,
            "answers": ({"sus": ans.sus, "ratings": ans.ratings, "belief": ans.belief, "grade_fit": ans.grade_fit,
                         "tags": ans.tags, "comment": ans.comment} if ans else None)}


def clean_comment(text: str | None) -> str | None:
    """Комментарий — только по делу: контакты (почта, телефон, ссылки, ники) убираются до сохранения; исходный текст не хранится."""
    t = (text or "").strip()[:texts.TEXT_MAX]
    if not t:
        return None
    from app.modules.contact.masking import mask_contacts
    from app.modules.resume.pii import redact

    t, _ = mask_contacts(t)
    t = redact(t, use_ner=False).text
    return t.strip() or None


def submit(db: Session, user: User, *, sus: list[int] | None, ratings: list[dict] | None, belief: int | None,
           grade_fit: str | None, tags: list[str] | None, comment: str | None, need_id: str | None = None,
           version: int | None = None) -> dict:
    """Анкета необязательна, любая её часть — тоже: SUS целиком (10 ответов) или не вовсе; оценки топ-5 — всех пятерых или не вовсе."""
    p = active_of(db, user)
    if p is None:
        raise api_error(404, "not_participant", "Статистика прохождения для этой учётной записи не ведётся")
    sus_list: list[int] = []
    if sus:
        try:
            stats.sus_score(sus)
        except ValueError:
            raise api_error(422, "bad_sus", "Ответьте на все 10 вопросов шкалы: от 1 до 5") from None
        sus_list = list(sus)
    d = P.derive(db, p)
    exposed = d["steps"].get("result" if p.role == "candidate" else "selection", {}).get("at") is not None
    sel, rated = None, []
    if ratings:
        if p.role != "employer" or not exposed:
            raise api_error(422, "bad_rating", "Оценивать кандидатов можно после того, как открыта подборка")
        sel = top5(db, user, need_id, version)
        by_ref = {x["ref"]: x for x in (sel or {}).get("shown", [])}
        got = {}
        for r in ratings:
            ref, val = r.get("ref"), r.get("rating")
            if ref not in by_ref or isinstance(val, bool) or not isinstance(val, int) or not 1 <= val <= 5 or ref in got:
                raise api_error(422, "bad_rating", "Оценка — число от 1 до 5 для каждого из показанных кандидатов")
            got[ref] = val
        if set(got) != set(by_ref):
            raise api_error(422, "ratings_incomplete", "Оцените всех показанных кандидатов или не оценивайте никого")
        rated = [{"ref": ref, "rank": by_ref[ref]["rank"], "rating": got[ref]} for ref in by_ref]
    if belief is not None and (isinstance(belief, bool) or not 1 <= belief <= 5):
        raise api_error(422, "bad_belief", "Доверие к грейду — число от 1 до 5")
    if grade_fit is not None and grade_fit not in texts.GRADE_FIT:
        raise api_error(422, "bad_grade_fit", "Допустимо: занижен, соответствует, завышен")
    if not exposed:  # вопросов о грейде и подборке человек не видел — ответов нет
        belief, grade_fit = None, None
    if p.role != "candidate":
        grade_fit = None
    tag_list = [t for t in dict.fromkeys(tags or []) if t in texts.BLOCKER_TAGS]
    text = clean_comment(comment)
    if not (sus_list or rated or belief is not None or grade_fit or tag_list or text):
        raise api_error(422, "empty_survey", "Анкета пуста: ответьте хотя бы на один вопрос или закройте окно")
    row = P.answered(db, p)
    if row is None:
        row = StudyAnswer(participant_id=p.id)
        db.add(row)
    row.sus, row.ratings, row.belief, row.grade_fit, row.tags = sus_list, rated, belief, grade_fit, tag_list
    row.selection = ({"need_id": sel["need_id"], "version": sel["version"], "algorithm": sel["algorithm"],
                      "shown": len(sel["shown"])} if sel and rated else None)
    row.comment, row.path_done, row.submitted_at = text, d["path_done"], utcnow()
    p.prompted_at = p.prompted_at or utcnow()
    db.commit()
    return {"ok": True, "sus_score": stats.sus_score(sus_list) if sus_list else None, "path_done": d["path_done"]}


def reset_all(db: Session, *, keep_declined: bool = True) -> dict:
    """Сброс собранной статистики (данные, не код): события, анкеты, участники. Отказавшие остаются отказавшими —
    это их выбор, а не статистика — если не указано иное."""
    ev = db.execute(delete(StudyEvent)).rowcount
    an = db.execute(delete(StudyAnswer)).rowcount
    q = delete(StudyParticipant)
    if keep_declined:
        q = q.where(StudyParticipant.declined_at.is_(None))
    pa = db.execute(q).rowcount
    left = db.scalar(select(func.count()).select_from(StudyParticipant)) or 0
    db.commit()
    return {"participants": pa, "events": ev, "answers": an, "declined_kept": left}
