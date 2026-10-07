"""Лента «Задания для вас»: раз в N дней система предлагает кандидату открытое задание работодателя по его стеку.

Подбор: открытые активные задания (mode=open) того же направления, стек которых пересекается со стеком кандидата
(заявленный T0 плюс подтверждённые T1 навыки), ещё не предлагавшиеся ему; предпочтение — своему грейду и
большему пересечению по стеку. Задания из песочниц жюри видны только кандидатам той же песочницы.

Запуск: лениво при обращении кандидата к ленте, фоновым потоком раз в час (app.main, lifespan) и из консоли:
    python -m app.modules.assignments.feed
Интервал N дней — настройка assignments_feed_days (по умолчанию 3).
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
from app.modules.assignments.models import Assignment, AssignmentAttempt
from app.modules.auth.models import User
from app.modules.jury import scope as jury_scope
from app.modules.profiles.facts import load_bundles
from app.modules.profiles.models import CandidateProfile

log = logging.getLogger(__name__)
ACTIVE_DAYS = 30  # фоновый обход — только кандидатам, заходившим за последние N дней


def feed_days() -> int:
    return int(getattr(get_settings(), "assignments_feed_days", 3) or 3)


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


def pick_for(db: Session, user: User) -> Assignment | None:
    p = db.get(CandidateProfile, user.id)
    if p is None or not p.current_category_id:
        return None  # лента — после первичного теста: категория нужна, чтобы подобрать направление и грейд
    tags = candidate_tags(db, user.id)
    seen = set(db.scalars(select(AssignmentAttempt.assignment_id)
                          .where(AssignmentAttempt.candidate_user_id == user.id)).all())
    best, best_key = None, None
    for a in visible_open(db, user, p):
        if a.id in seen:
            continue
        overlap = len(tags & set(a.stack_tags or []))
        if overlap == 0:
            continue
        k = (a.grade_id == p.current_grade_id, overlap, as_aware(a.created_at))
        if best_key is None or k > best_key:
            best, best_key = a, k
    return best


def due(db: Session, user_id: uuid.UUID) -> bool:
    """Пора ли предлагать: нет ожидающего предложения из ленты и прошлое было не раньше N дней назад."""
    rows = db.scalars(select(AssignmentAttempt).where(AssignmentAttempt.candidate_user_id == user_id,
                                                      AssignmentAttempt.source == "feed")).all()
    if any(r.status in ("offered", "in_progress") for r in rows):
        return False
    last = max((as_aware(r.offered_at) for r in rows), default=None)
    return last is None or utcnow() - last >= timedelta(days=feed_days())


def offer_if_due(db: Session, user: User) -> AssignmentAttempt | None:
    if user.role != UserRole.candidate or not due(db, user.id):
        return None
    a = pick_for(db, user)
    if a is None:
        return None
    at = svc.offer(db, a, user, "feed")
    db.commit()
    return at


def run_once(db: Session | None = None) -> int:
    """Фоновый обход: кандидаты, заходившие за последние 30 дней. Возвращает число новых предложений."""
    own = db is None
    db = db or SessionLocal()
    n = 0
    try:
        since = utcnow() - timedelta(days=ACTIVE_DAYS)
        users = db.scalars(select(User).where(User.role == UserRole.candidate, User.is_active.is_(True),
                                              User.last_login_at.is_not(None), User.last_login_at >= since)).all()
        for u in users:
            try:
                if offer_if_due(db, u) is not None:
                    n += 1
            except Exception:  # noqa: BLE001
                log.exception("лента заданий: кандидат %s", u.id)
                db.rollback()
    finally:
        if own:
            db.close()
    return n


_started: list[threading.Thread] = []


def start_background(interval_s: int = 3600) -> threading.Thread | None:
    """Один фоновый поток на процесс; interval_s <= 0 — выключено (тесты)."""
    if interval_s <= 0 or _started:
        return None

    def loop() -> None:
        import time

        time.sleep(min(60, interval_s))
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
