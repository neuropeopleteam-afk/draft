"""Правила «Кубка работодателя» (покрыты tests/test_cup.py).

* Участвовать могут только кандидаты категории кубка с опубликованным профилем; одно участие на кубок.
* Время на решение — time_limit_min с момента старта, но не позже окончания кубка; ответ после срока (+ 2 мин
  на сеть) не принимается, начатое и не отправленное участие — «время вышло», без места.
* Таблица результатов — под псевдонимами. Работодатель видит обезличенный номер кандидата только у тех, кого
  пригласил; имя и контакты — по общему правилу, после принятия приглашения.
* Итоги: места по баллу (при равенстве — по времени), лучшим invite_top_n с баллом не ниже min_score —
  приглашения с вилкой кубка через общий сервис приглашений (лимит «одно приглашение за 30 дней» действует).
* Каждый участник с местом получает факт T1 «Кубок …» с вердиктом «N место из M» (входит в рейтинг как зонд,
  не штрафует) и запись в паспорт ФСП: мероприятие уровня «platform», verified=False (подтверждено платформой,
  не реестром).
  Нет паспорта — запись ждёт связки с ФСП ID (pending_link) и дописывается при первом обращении после связки.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.db import as_aware, utcnow
from app.core.enums import EvidenceLevel, FactSource, FspEventLevel
from app.core.errors import api_error
from app.cup import tasks as auto
from app.cup.models import Cup, CupEntry
from app.modules.auth.models import User
from app.modules.catalog.seed_data import category_title
from app.modules.fsp.models import FspAchievement, FspPassport
from app.modules.invitations import service as inv_svc
from app.modules.invitations.models import Invitation
from app.modules.jury import scope as jury_scope
from app.modules.profiles.facts import refresh_rating
from app.modules.profiles.models import CandidateFact, CandidateProfile, Company

GRACE_S = 120
MODES = {"auto": "Автопроверка: задания банка, у каждого свой вариант",
         "rubric": "Открытая задача, оценка по рубрике (LLM, при сбое — работодатель)",
         "employer": "Открытая задача, оценивает работодатель вслепую"}
DEFAULT_RUBRIC = [
    {"id": "correctness", "title": "Решение верное и работает в заданных условиях", "weight": 0.5},
    {"id": "tradeoffs", "title": "Обоснованы выбор и компромиссы, учтены крайние случаи", "weight": 0.3},
    {"id": "clarity", "title": "Изложение ясное и проверяемое: шаги, код, тесты", "weight": 0.2},
]
DISCIPLINE_BY_DIRECTION = {"security": "security"}  # остальное — продуктовое программирование


def phase(cup: Cup, now: datetime | None = None) -> str:
    if cup.status in ("finished", "cancelled"):
        return cup.status
    now = now or utcnow()
    if now < as_aware(cup.starts_at):
        return "upcoming"
    if now < as_aware(cup.ends_at):
        return "active"
    return "judging"


def rubric_of(cup: Cup) -> list[dict]:
    return (cup.rubric or {}).get("criteria") or DEFAULT_RUBRIC


def llm_rubric(cup: Cup) -> dict:
    """Рубрика в формате банка для grader.grade_open."""
    r = cup.rubric or {}
    crit = [{"id": c["id"], "weight": c["weight"], "description": c["title"]} for c in rubric_of(cup)]
    return {"criteria": crit, "strong": r.get("strong") or "Полное верное решение, все критерии выполнены.",
            "medium": r.get("medium") or "Решение в целом верное, часть критериев выполнена частично.",
            "weak": r.get("weak") or "Решение неверное или по существу отсутствует.",
            "scoring_notes": "Оценивай по критериям работодателя."}


def normalize_rubric(criteria: list[dict] | None) -> list[dict]:
    if not criteria:
        return [dict(c) for c in DEFAULT_RUBRIC]
    total = sum(max(0.0, float(c["weight"])) for c in criteria) or 1.0
    out = [{"id": f"c{i}", "title": c["title"].strip(), "weight": round(max(0.0, float(c["weight"])) / total, 3)}
           for i, c in enumerate(criteria, start=1)]
    out[-1]["weight"] = round(1.0 - sum(c["weight"] for c in out[:-1]), 3)
    return out


# ------------------------------------------------------------------ создание

def create_cup(db: Session, user: User, company: Company, data: dict) -> Cup:
    inv_svc.check_salary(data["salary_from"], data["salary_to"])
    cat = data["category_id"]
    direction, grade = cat.split(".", 1)
    now = utcnow()
    starts = as_aware(data.get("starts_at")) or now
    ends = as_aware(data.get("ends_at")) or starts + timedelta(days=int(data.get("duration_days") or 7))
    if ends <= starts:
        raise api_error(422, "cup_period_invalid", "Окончание кубка должно быть позже начала")
    if ends <= now:
        raise api_error(422, "cup_period_past", "Кубок должен закончиться в будущем")
    mode = data["mode"]
    families: list[str] = []
    if mode == "auto":
        families = auto.pick_families(direction, grade, int(data.get("n_tasks") or 5))
        if len(families) < 3:
            raise api_error(422, "cup_bank_too_small", "В банке мало заданий с автопроверкой для этой категории")
    elif not (data.get("task_text") or "").strip():
        raise api_error(422, "cup_task_required", "Опишите задачу кубка")
    cup = Cup(company_id=company.id, created_by=user.id, title=data["title"].strip(),
              description=data["description"].strip(), category_id=cat, direction_id=direction, grade_id=grade,
              mode=mode, task_text=(data.get("task_text") or "").strip() or None,
              rubric={"criteria": normalize_rubric(data.get("rubric"))} if mode == "rubric" else None,
              task_families=families, time_limit_min=int(data.get("time_limit_min") or 15), starts_at=starts,
              ends_at=ends, salary_from=data["salary_from"], salary_to=data["salary_to"],
              salary_basis=data.get("salary_basis") or "gross",
              invite_top_n=int(data.get("invite_top_n") or 3), min_score=float(data.get("min_score", 0.5)),
              position_title=data["position_title"].strip(), offer_description=data["offer_description"].strip(),
              contact_method=data["contact_method"].strip(), status="active", summary={},
              is_demo=bool(company.is_demo),
              # кубок работодателя песочницы жюри виден только кандидатам этой песочницы (как и засеянные кубки)
              jury_scope=jury_scope.key_of(user.email))
    db.add(cup)
    db.commit()
    return cup


# ------------------------------------------------------------------ участие

def _profile(db: Session, user_id: uuid.UUID) -> CandidateProfile:
    p = db.get(CandidateProfile, user_id)
    if p is None or not p.current_category_id:
        raise api_error(409, "category_required", "Участвовать могут кандидаты с подтверждённой категорией")
    return p


def entry_of(db: Session, cup_id: uuid.UUID, user_id: uuid.UUID) -> CupEntry | None:
    return db.scalar(select(CupEntry).where(CupEntry.cup_id == cup_id, CupEntry.candidate_user_id == user_id))


def join(db: Session, cup: Cup, user: User) -> CupEntry:
    if phase(cup) not in ("upcoming", "active"):
        raise api_error(409, "cup_closed", "Приём участников в этот кубок закрыт")
    e = entry_of(db, cup.id, user.id)
    if e is not None:
        return e
    p = _profile(db, user.id)
    if p.current_category_id != cup.category_id:
        raise api_error(403, "cup_other_category",
                        f"Кубок проходит в категории {category_title(cup.category_id)}, ваша — "
                        f"{category_title(p.current_category_id)}")
    if not p.visible_to_employers:
        raise api_error(409, "profile_hidden",
                        "Чтобы получить приглашение по итогам, включите публикацию профиля в настройках")
    n = db.scalar(select(func.count()).select_from(CupEntry).where(CupEntry.cup_id == cup.id)) or 0
    e = CupEntry(cup_id=cup.id, candidate_user_id=user.id, alias=f"Участник {n + 1:02d}", status="joined", tasks=[])
    db.add(e)
    db.commit()
    return e


def leave(db: Session, cup: Cup, e: CupEntry) -> None:
    if e.status != "joined":
        raise api_error(409, "cup_entry_started", "Начатое участие отменить нельзя")
    db.delete(e)
    db.commit()


def start(db: Session, cup: Cup, e: CupEntry) -> CupEntry:
    if phase(cup) != "active":
        raise api_error(409, "cup_not_active", "Кубок ещё не начался или уже закончился")
    if e.status != "joined":
        raise api_error(409, "cup_entry_started", "Участие уже начато")
    now = utcnow()
    e.started_at = now
    e.deadline_at = min(now + timedelta(minutes=cup.time_limit_min), as_aware(cup.ends_at))
    if cup.mode == "auto":
        e.tasks = auto.issue(cup.task_families)
        flag_modified(e, "tasks")
    e.status = "in_progress"
    db.commit()
    return e


def expire_if_late(db: Session, e: CupEntry, now: datetime | None = None) -> bool:
    now = now or utcnow()
    if e.status == "in_progress" and e.deadline_at and now > as_aware(e.deadline_at) + timedelta(seconds=GRACE_S):
        e.status = "expired"
        return True
    return False


def submit(db: Session, cup: Cup, e: CupEntry, *, answers: dict | None = None, text: str | None = None,
           link: str | None = None) -> CupEntry:
    if e.status != "in_progress":
        raise api_error(409, "cup_entry_not_in_progress", "Решение уже отправлено или участие не начато")
    now = utcnow()
    if expire_if_late(db, e, now):
        db.commit()
        raise api_error(409, "cup_time_over", "Время на решение вышло — ответ не принят")
    e.submitted_at = now
    e.time_spent_s = max(1, int((now - as_aware(e.started_at)).total_seconds()))
    if cup.mode == "auto":
        items = list(e.tasks or [])
        e.score = auto.score(items, {str(k): v for k, v in (answers or {}).items()})
        e.tasks = items
        flag_modified(e, "tasks")
        e.score_method, e.status = "auto", "scored"
        e.grading = {"correct": sum(1 for it in items if it["correct"]), "total": len(items)}
    else:
        body = (text or "").strip()
        if len(body) < 20:
            raise api_error(422, "cup_answer_too_short", "Опишите решение подробнее (не короче 20 символов)")
        from app.modules.resume.pii import redact

        red = redact(body, use_ner=True, header=False)
        e.answer = {"text": body[:10000], "link": (link or "").strip()[:500] or None, "text_redacted": red.text[:10000],
                    "redacted": sorted(red.found)}
        e.status = "submitted"
        if cup.mode == "rubric":
            from app.modules.assessment.grader import grade_open

            g = grade_open(stem=f"{cup.title}\n\n{cup.task_text or ''}", code=None, step_prompt=None,
                           rubric=llm_rubric(cup), answer=body)
            e.grading = {"llm": g.to_dict()}
            if g.status == "scored" and g.score is not None:
                e.score, e.score_method, e.status = g.score, "llm" if g.method in ("llm", "llm2") else "rule", "scored"
    db.commit()
    return e


def score_by_employer(db: Session, cup: Cup, e: CupEntry, *, score_pct: float | None,
                      criteria: dict[str, float] | None, comment: str | None) -> CupEntry:
    if cup.status != "active":
        raise api_error(409, "cup_finished", "Итоги кубка уже подведены")
    if cup.mode == "auto":
        raise api_error(409, "cup_auto_scored", "В кубке с автопроверкой балл ставит система")
    if e.status not in ("submitted", "scored"):
        raise api_error(409, "cup_entry_not_submitted", "Оценить можно только присланное решение")
    if criteria:
        crit = rubric_of(cup)
        missing = [c["id"] for c in crit if c["id"] not in criteria]
        if missing:
            raise api_error(422, "cup_criteria_missing", "Оцените все критерии рубрики")
        val = sum(c["weight"] * min(1.0, max(0.0, float(criteria[c["id"]]))) for c in crit)
    elif score_pct is not None:
        val = min(100.0, max(0.0, float(score_pct))) / 100
    else:
        raise api_error(422, "cup_score_required", "Поставьте балл или оцените критерии")
    e.score = round(val, 4)
    e.score_method = "employer"
    e.status = "scored"
    e.grading = {**(e.grading or {}), "employer": {"criteria": criteria, "score_pct": score_pct, "comment": comment,
                                                    "at": utcnow().isoformat()}}
    flag_modified(e, "grading")
    db.commit()
    return e


# ------------------------------------------------------------------ таблица результатов и итоги

def entries(db: Session, cup_id: uuid.UUID) -> list[CupEntry]:
    return list(db.scalars(select(CupEntry).where(CupEntry.cup_id == cup_id).order_by(CupEntry.created_at)).all())


def ranked(rows: list[CupEntry]) -> list[CupEntry]:
    far = datetime.max.replace(tzinfo=None)
    sc = [e for e in rows if e.status == "scored" and e.score is not None]
    return sorted(sc, key=lambda e: (-e.score, e.time_spent_s or 10**9,
                                     (as_aware(e.submitted_at).replace(tzinfo=None) if e.submitted_at else far)))


def close_expired(db: Session, cup: Cup) -> None:
    changed = False
    for e in entries(db, cup.id):
        changed |= expire_if_late(db, e)
    if changed:
        db.commit()


def result_title(place: int) -> str:
    return "победитель" if place == 1 else "призёр" if place <= 3 else "участник"


def credits(db: Session, cup: Cup, user_id: uuid.UUID) -> bool:
    """Получает ли участник за место факт T1 и запись в паспорт ФСП.

    Кубок платформы — да, все. Кубок демо жюри (cup.jury_scope) — только учётки этой песочницы: демо-кандидаты
    платформы там «статисты» (место и приглашение — да, факты — нет), иначе каждая копия демо жюри меняла бы
    их рейтинг и паспорт, а с ними — общую аналитику Кабинета ФСП."""
    if cup.jury_scope is None:
        return True
    u = db.get(User, user_id)
    return u is not None and jury_scope.key_of(u.email) == cup.jury_scope


def write_passport(db: Session, cup: Cup, e: CupEntry, total: int, company_name: str) -> str:
    """Запись участия в паспорт ФСП (идемпотентно). Нет паспорта — pending_link."""
    pp = db.scalar(select(FspPassport).where(FspPassport.user_id == e.candidate_user_id))
    if pp is None:
        e.passport_status = "pending_link"
        return e.passport_status
    ref = f"cup:{cup.id}"
    a = db.scalar(select(FspAchievement).where(FspAchievement.passport_id == pp.id, FspAchievement.source_ref == ref))
    if a is None:
        a = FspAchievement(passport_id=pp.id, source_ref=ref, discipline="product", event_name="",
                           event_level=FspEventLevel.platform)
        db.add(a)
    a.discipline = DISCIPLINE_BY_DIRECTION.get(cup.direction_id, "product")
    a.event_name = f"Кубок работодателя «{cup.title}» — {company_name}"[:255]
    a.event_level = FspEventLevel.platform
    a.event_date = as_aware(cup.ends_at).date()
    a.place = e.place
    a.result_title = f"{result_title(e.place)}, {e.place} из {total}"[:100]
    a.team_name = None
    a.role_in_team = "индивидуально"
    a.verified = False  # подтверждено платформой (T1), а не реестром ФСП (T2)
    e.passport_status = "written"
    e.passport_written_at = e.passport_written_at or utcnow()
    return e.passport_status


def sync_passport(db: Session, user_id: uuid.UUID) -> int:
    """Дописывает в паспорт ФСП места из кубков, если паспорт появился (связка ФСП ID) или был пересобран."""
    rows = db.scalars(select(CupEntry).where(CupEntry.candidate_user_id == user_id, CupEntry.place.is_not(None))).all()
    if not rows:
        return 0
    pp = db.scalar(select(FspPassport).where(FspPassport.user_id == user_id))
    if pp is None:
        return 0
    have = set(db.scalars(select(FspAchievement.source_ref).where(FspAchievement.passport_id == pp.id)).all())
    n = 0
    for e in rows:
        cup = db.get(Cup, e.cup_id)
        if cup is None or f"cup:{cup.id}" in have or not credits(db, cup, user_id):
            continue
        comp = db.get(Company, cup.company_id)
        write_passport(db, cup, e, int((cup.summary or {}).get("placed") or e.place), comp.name if comp else "")
        n += 1
    if n:
        db.commit()
    return n


def finalize(db: Session, cup: Cup, actor: User | None, *, early: bool = False) -> list[uuid.UUID]:
    """Подводит итоги: места, факты T1, паспорт ФСП, приглашения лучшим. Возвращает id новых приглашений."""
    ph = phase(cup)
    if ph in ("finished", "cancelled"):
        raise api_error(409, "cup_finished", "Итоги кубка уже подведены")
    now = utcnow()
    if ph in ("upcoming", "active"):
        if not early:
            raise api_error(409, "cup_running", "Кубок ещё идёт — подвести итоги можно после окончания")
        if ph == "upcoming":
            raise api_error(409, "cup_not_started", "Кубок ещё не начался")
    rows = entries(db, cup.id)
    pending = [e for e in rows if e.status == "submitted"]
    if pending:
        raise api_error(409, "cup_unscored", f"Оцените присланные решения: осталось {len(pending)}")
    if ph == "active":
        cup.ends_at = now
    for e in rows:
        if e.status == "in_progress":
            e.status = "expired"
    order = ranked(rows)
    total = len(order)
    company = db.get(Company, cup.company_id)
    employer = actor or (db.get(User, cup.created_by) if cup.created_by else None)
    credited = [e for e in order if credits(db, cup, e.candidate_user_id)]
    for i, e in enumerate(order, start=1):
        e.place = i
        if e not in credited:
            continue
        # место — только в verdict: интерфейс, ATS и PDF показывают факт как «название — вердикт»
        title = f"Кубок «{cup.title}»"
        fact = db.scalar(select(CandidateFact).where(CandidateFact.user_id == e.candidate_user_id,
                                                     CandidateFact.source_ref == f"cup:{cup.id}"))
        if fact is None:
            db.add(CandidateFact(user_id=e.candidate_user_id, kind="probe", key=f"cup:{cup.id}"[:100], title=title[:255],
                                 value={"score": round(e.score, 3), "verdict": f"{i} место из {total}", "place": i,
                                        "of": total, "cup_id": str(cup.id)},
                                 evidence_level=EvidenceLevel.T1, source=FactSource.probe, source_ref=f"cup:{cup.id}"))
        write_passport(db, cup, e, total, company.name if company else "")
    db.flush()
    for e in credited:
        refresh_rating(db, e.candidate_user_id)
    # «Junior (предварительно)»: кубок своего направления с результатом ≥ 70 % подтверждает грейд (не смена грейда)
    from app.modules.assessment import provisional

    for e in credited:
        provisional.confirm_by_work(db, e.candidate_user_id, source="cup", ref=f"cup:{cup.id}",
                                    ref_title=f"Кубок «{cup.title}»", score=float(e.score or 0),
                                    direction=getattr(cup, "direction_id", None))
    cup.status = "finished"
    cup.finalized_at = now
    db.commit()

    invited: list[uuid.UUID] = []
    notes = []
    for e in order[: cup.invite_top_n]:
        if e.invitation_id:  # Н5: уже приглашён «в один клик» во время турнира — второе приглашение не нужно
            continue
        if e.score < cup.min_score:
            e.invite_note = f"балл ниже порога приглашения {round(cup.min_score * 100)} %"
            db.commit()
            continue
        prof = db.get(CandidateProfile, e.candidate_user_id)
        if prof is None or not prof.visible_to_employers or employer is None:
            e.invite_note = "кандидат скрыл профиль"
            db.commit()
            continue
        text = (f"{cup.offer_description}\n\nПо итогам Кубка работодателя «{cup.title}»: {e.place} место из {total}, "
                f"балл {round(e.score * 100)} %.")
        try:
            inv = inv_svc.create_invitation(db, employer, company, prof, position_title=cup.position_title,
                                            offer_description=text[:5000], salary_from=cup.salary_from,
                                            salary_to=cup.salary_to, contact_method=cup.contact_method,
                                            need_id=None, probe_id=None, salary_basis=cup.salary_basis or "gross")
        except Exception as ex:  # noqa: BLE001 — например, лимит «одно приглашение за 30 дней»
            db.rollback()
            e = db.get(CupEntry, e.id)
            e.invite_note = (getattr(ex, "detail", None) or {}).get("message", "приглашение не отправлено")[:255]
            notes.append(e.invite_note)
            db.commit()
            continue
        inv.evidence = [{"level": "T1", "kind": "cup",
                         "text": f"Кубок работодателя «{cup.title}»: {e.place} место из {total}, балл "
                                 f"{round(e.score * 100)} %"}, *(inv.evidence or [])]
        flag_modified(inv, "evidence")
        e = db.get(CupEntry, e.id)
        e.invitation_id = inv.id
        e.invite_note = None
        invited.append(inv.id)
        db.commit()
    cup = db.get(Cup, cup.id)
    keep = {k: v for k, v in (cup.summary or {}).items() if k == "tournament"}  # Н5: паспорт турнира ФСП остаётся
    cup.summary = {**keep, "joined": len(rows), "placed": total, "expired": sum(1 for e in rows if e.status == "expired"),
                   "invited": sum(1 for e in order[: cup.invite_top_n] if db.get(CupEntry, e.id).invitation_id),
                   "invite_top_n": cup.invite_top_n,
                   "best_pct": round(order[0].score * 100) if order else None, "finalized_at": now.isoformat(),
                   "early": bool(early and ph == "active")}
    flag_modified(cup, "summary")
    db.commit()
    return invited


def maybe_auto_finalize(db: Session, cup: Cup) -> list[uuid.UUID]:
    """По окончании кубка итоги подводятся сами, если все решения оценены (автопроверка — всегда)."""
    if phase(cup) != "judging":
        return []
    rows = entries(db, cup.id)
    if any(e.status == "submitted" for e in rows):
        return []
    return finalize(db, cup, None)


def invitation_status(db: Session, e: CupEntry) -> str | None:
    if not e.invitation_id:
        return None
    inv = db.get(Invitation, e.invitation_id)
    return inv.status.value if inv else None
