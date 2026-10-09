"""Лента «Задания для вас» (К5): адресные предложения раз в неделю, с причиной, лимитом и напоминаниями.

Что и кому предлагается. Открытые активные задания (mode=open) того же направления, стек которых пересекается со
стеком кандидата (заявленный T0 плюс подтверждённые T1 навыки), ещё не предлагавшиеся ему. Выбор — по весу из
assignments.why: слабо подтверждённый навык (1,0) > навык, давно не подтверждавшийся (0,6 / 0,9 после 180 дней) > заявленный,
но не подтверждённый (0,5) > свежий сильный (0,1); плюс совпадение с обязательными требованиями работодателя и свой грейд.
Причина сохраняется в попытке («почему вам») и видна кандидату и работодателю. Задания из песочниц жюри видны только
кандидатам той же песочницы.

Периодичность и лимиты (настройки config — assignments_*):
* раз в 7 дней (кандидат выбирает 7 / 14 дней или «не предлагать»); после двух подряд отказов или истёкших предложений
  интервал удваивается — система не настаивает;
* одно активное предложение: пока оно не решено, не отклонено и не истекло, новое не приходит;
* не больше 4 предложений за скользящие 30 дней;
* без ответа предложение истекает через 14 дней; кандидату напоминание через 2 дня после предложения и ещё раз
  через 2 дня (не больше двух); работодателю — напоминание оценить подход по рубрике через 3 дня (не больше двух).

Запуск: лениво при обращении к ленте, фоновым потоком раз в час (app.main, lifespan) и из консоли:
    python -m app.modules.assignments.feed
"""
from __future__ import annotations

from datetime import timedelta
import logging
import threading
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal, as_aware, utcnow
from app.core.enums import UserRole
from app.modules.assignments import service as svc
from app.modules.assignments import why as why_mod
from app.modules.assignments.models import Assignment, AssignmentAttempt, AssignmentPrefs
from app.modules.auth.models import User
from app.modules.jury import scope as jury_scope
from app.modules.profiles.facts import load_bundles
from app.modules.profiles.models import CandidateProfile

log = logging.getLogger(__name__)
ACTIVE_DAYS = 30  # фоновый обход — только кандидатам, заходившим за последние N дней
WINDOW_DAYS = 30  # окно лимита предложений
FREQUENCIES = (7, 14, 0)  # дней между предложениями; 0 — не предлагать
MAX_REMINDS = 2


def _cfg(name: str, default: int) -> int:
    v = getattr(get_settings(), name, default)
    return default if v is None else int(v)


def feed_days() -> int:
    return _cfg("assignments_feed_days", 7) or 7


def get_freq(db: Session, user_id: uuid.UUID) -> int:
    p = db.get(AssignmentPrefs, user_id)
    return feed_days() if p is None else int(p.frequency_days)


def set_freq(db: Session, user_id: uuid.UUID, days: int) -> int:
    p = db.get(AssignmentPrefs, user_id)
    if p is None:
        p = AssignmentPrefs(user_id=user_id, frequency_days=days)
        db.add(p)
    p.frequency_days = days
    db.flush()
    return days


def candidate_tags(db: Session, user_id: uuid.UUID) -> set[str]:
    b = load_bundles(db, [user_id]).get(user_id)
    if b is None:
        return set()
    return set(b.stack_t0) | set(b.skills_t1)


def visible_open(db: Session, user: User, p: CandidateProfile) -> list[Assignment]:
    key = jury_scope.key_of(user.email)
    q = select(Assignment).where(Assignment.mode == "open", Assignment.status == "active")
    if p.current_direction_id:
        q = q.where(Assignment.direction_id == p.current_direction_id)
    q = q.where(Assignment.jury_scope.is_(None)) if key is None else \
        q.where((Assignment.jury_scope.is_(None)) | (Assignment.jury_scope == key))
    return list(db.scalars(q.order_by(Assignment.created_at.desc())).all())


def rank_for(db: Session, user: User) -> list[tuple[float, Assignment, dict]]:
    """Подходящие кандидату открытые задания по убыванию веса: [(вес, задание, разбор причин)]."""
    p = db.get(CandidateProfile, user.id)
    if p is None or not p.current_category_id:
        return []  # лента — после первичного теста: категория нужна, чтобы подобрать направление и грейд
    seen = set(db.scalars(select(AssignmentAttempt.assignment_id).where(AssignmentAttempt.candidate_user_id == user.id)).all())
    bundle = load_bundles(db, [user.id], direction=p.current_direction_id).get(user.id)
    out = []
    for a in visible_open(db, user, p):
        if a.id in seen:
            continue
        an = why_mod.analyse(db, a, user.id, bundle=bundle)
        if not an["have"]:
            continue  # стек задания не пересекается со стеком кандидата
        out.append((why_mod.target_score(an, a, p.current_grade_id), a, an))
    out.sort(key=lambda x: (x[0], as_aware(x[1].created_at)), reverse=True)
    return out


def pick_for(db: Session, user: User) -> Assignment | None:
    r = rank_for(db, user)
    return r[0][1] if r else None


def schedule(db: Session, user: User) -> dict:
    """Когда и почему кандидату предлагают (или не предлагают) следующее задание — для ленты и для решения «пора ли»."""
    now = utcnow()
    freq = get_freq(db, user.id)
    rows = list(db.scalars(select(AssignmentAttempt).where(AssignmentAttempt.candidate_user_id == user.id,
                                                           AssignmentAttempt.source == "feed")
                           .order_by(AssignmentAttempt.offered_at.desc())).all())
    pending = any(r.status in ("offered", "in_progress") for r in rows)
    last = as_aware(rows[0].offered_at) if rows else None
    backoff = len(rows) >= 2 and all(r.status in ("declined", "expired") for r in rows[:2])
    days = freq * (2 if backoff else 1) if freq else 0
    next_at = (last + timedelta(days=days)) if (last and days) else None
    limit = _cfg("assignments_feed_monthly_limit", 4)
    used = sum(1 for r in rows if as_aware(r.offered_at) >= now - timedelta(days=WINDOW_DAYS))
    blocked = ("paused" if not freq else "pending" if pending else "limit" if used >= limit
               else "wait" if next_at and now < next_at else None)
    return {"frequency_days": freq, "effective_days": days, "backoff": backoff, "paused": not freq, "pending": pending,
            "last_offer_at": last, "next_at": next_at, "limit": limit, "used": used, "window_days": WINDOW_DAYS,
            "blocked": blocked, "due": blocked is None, "options": list(FREQUENCIES),
            "remind_days": _cfg("assignments_remind_days", 2), "ttl_days": _cfg("assignments_offer_ttl_days", 14)}


def due(db: Session, user_id: uuid.UUID) -> bool:
    u = db.get(User, user_id)
    return bool(u and schedule(db, u)["due"])


def offer_if_due(db: Session, user: User) -> AssignmentAttempt | None:
    if user.role != UserRole.candidate:
        return None
    sch = schedule(db, user)
    if not sch["due"]:
        return None
    ranked = rank_for(db, user)
    if not ranked:
        return None
    at = svc.offer(db, ranked[0][1], user, "feed", why_days=sch["frequency_days"])
    db.commit()
    return at


# ------------------------------------------------------------------ истечение и напоминания

def maintenance(db: Session, *, user_id: uuid.UUID | None = None, company_id: uuid.UUID | None = None) -> dict:
    """Истекают предложения ленты без ответа; кандидатам — напоминания о неначатых заданиях; работодателям — о заданиях,
    ждущих оценки по рубрике. Идемпотентно: каждое напоминание — один раз за период, не больше двух на попытку."""
    now = utcnow()
    ttl, rd, rrd = (_cfg("assignments_offer_ttl_days", 14), _cfg("assignments_remind_days", 2),
                    _cfg("assignments_review_remind_days", 3))
    q = select(AssignmentAttempt, Assignment).join(Assignment, Assignment.id == AssignmentAttempt.assignment_id)
    if user_id is not None:
        q = q.where(AssignmentAttempt.candidate_user_id == user_id)
    if company_id is not None:
        q = q.where(Assignment.company_id == company_id)
    done = {"expired": 0, "reminded": 0, "review_reminded": 0}
    for at, a in db.execute(q.where((AssignmentAttempt.status == "offered") |
                                    ((AssignmentAttempt.status == "scored") & (AssignmentAttempt.review_status == "pending")))).all():
        if at.status == "offered":
            age = now - as_aware(at.offered_at)
            if at.source == "feed" and age >= timedelta(days=ttl):
                at.status = "expired"
                done["expired"] += 1
            elif a.status == "active" and at.remind_count < MAX_REMINDS and now - as_aware(at.remind_at or at.offered_at) >= timedelta(days=rd):
                svc.remind_candidate(db, at, a, ttl_days=ttl if at.source == "feed" else None)
                at.remind_at, at.remind_count = now, at.remind_count + 1
                done["reminded"] += 1
        elif at.review_remind_count < MAX_REMINDS and now - as_aware(at.review_remind_at or at.submitted_at or at.offered_at) >= timedelta(days=rrd):
            svc.remind_employer(db, at, a)
            at.review_remind_at, at.review_remind_count = now, at.review_remind_count + 1
            done["review_reminded"] += 1
    if any(done.values()):
        db.flush()
    return done


def run_once(db: Session | None = None) -> int:
    """Фоновый обход: напоминания и истечение для всех, затем новые предложения кандидатам, заходившим за последние
    30 дней. Возвращает число новых предложений."""
    own = db is None
    db = db or SessionLocal()
    n = 0
    try:
        try:
            maintenance(db)
            db.commit()
        except Exception:  # noqa: BLE001
            log.exception("лента заданий: напоминания")
            db.rollback()
        since = utcnow() - timedelta(days=ACTIVE_DAYS)
        users = db.scalars(select(User).where(User.role == UserRole.candidate, User.is_active.is_(True),
                                              User.last_login_at.is_not(None), User.last_login_at >= since)).all()
        for u in users:
            uid = u.id  # до try: после сбоя flush объекты сессии протухают, и обращение к u.id до отката — PendingRollbackError
            try:
                if offer_if_due(db, u) is not None:
                    n += 1
            except Exception:  # noqa: BLE001
                db.rollback()  # сначала откат — сессия снова рабочая, обход продолжается со следующего кандидата
                log.exception("лента заданий: кандидат %s", uid)
    finally:
        if own:
            db.close()
    return n


def demo_fast_forward(db: Session, user: User) -> dict:
    """Только песочница жюри: «прошла неделя» — даты ленты сдвигаются на период назад и выполняется обычный цикл
    (напоминание → истечение → новое предложение). Само расписание и причины считаются настоящим кодом."""
    shift = timedelta(days=get_freq(db, user.id) or feed_days())
    for at in db.scalars(select(AssignmentAttempt).where(AssignmentAttempt.candidate_user_id == user.id,
                                                         AssignmentAttempt.source == "feed")).all():
        at.offered_at = as_aware(at.offered_at) - shift
        if at.remind_at:
            at.remind_at = as_aware(at.remind_at) - shift
    db.flush()
    done = maintenance(db, user_id=user.id)
    offered = offer_if_due(db, user)
    db.commit()
    return {**done, "offered": str(offered.id) if offered else None}


_started: list[threading.Thread] = []


def start_background(interval_s: int = 3600) -> threading.Thread | None:
    """Один фоновый поток на процесс; interval_s <= 0 — выключено (тесты)."""
    if interval_s <= 0 or _started:
        return None

    def loop() -> None:
        import random
        import time

        # разброс старта: у api два воркера uvicorn, каждый со своим потоком — иначе их обходы идут секунда в секунду
        # и соревнуются за одну и ту же пару (задание, кандидат); гонка и так безопасна (SAVEPOINT в service.offer)
        time.sleep(min(60, interval_s) + random.uniform(0, min(120, interval_s / 4)))
        while True:
            try:
                n = run_once()
                if n:
                    log.info("лента заданий: предложено %d", n)
            except Exception:  # noqa: BLE001
                log.exception("лента заданий: обход не удался")
            time.sleep(interval_s)

    t = threading.Thread(target=loop, name="assignments-feed", daemon=True)
    _started.append(t)
    t.start()
    return t


if __name__ == "__main__":
    print(f"предложено заданий: {run_once()}")
