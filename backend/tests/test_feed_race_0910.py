"""Лента заданий: гонка двух процессов за одну пару (задание, кандидат) — стенд 09.10 13:42 МСК.

У api два воркера uvicorn, в каждом свой фоновый обход ленты (feed.start_background), плюс обход при обращении к ленте.
Оба видят «попытки ещё нет» и вставляют её; второй получает UniqueViolation uq_assignment_attempts_pair. Раньше в обработчике
исключения run_once обращался к u.id до db.rollback() — после сбоя flush объекты сессии протухшие, поэтому вылетал
PendingRollbackError и падал весь обход («лента заданий: обход не удался»).

Теперь: вставка в service.offer — под SAVEPOINT (проигравший просто получает None, сессия остаётся рабочей), а в run_once
сначала откат, потом запись в журнал; обход продолжается со следующего кандидата.
"""
from datetime import timedelta
import uuid

from sqlalchemy import func, select

from app.core.db import SessionLocal, utcnow
from tests.test_assignments_targeted import open_assignment
from tests.test_day2_rules import H, candidate_with_category, employer


def _login(db, email):
    from app.modules.auth.models import User

    u = db.scalar(select(User).where(User.email == email))
    u.last_login_at = utcnow()
    db.commit()
    return u


def _n_attempts(db, aid, uid):
    from app.modules.assignments.models import AssignmentAttempt

    return db.scalar(select(func.count()).select_from(AssignmentAttempt).where(AssignmentAttempt.assignment_id == aid,
                                                                                AssignmentAttempt.candidate_user_id == uid))


def test_offer_parallel_duplicate_is_idempotent(client, monkeypatch):
    """Параллельный процесс вставил ту же пару между проверкой и вставкой: offer возвращает None, одна попытка, сессия жива."""
    from app.modules.assignments import service as svc
    from app.modules.assignments.models import Assignment

    te = employer(client)
    a = open_assignment(client, te, ["python", "postgresql"])
    candidate_with_category(client, "race1@example.com")
    with SessionLocal() as db:
        u = _login(db, "race1@example.com")
        asg = db.get(Assignment, uuid.UUID(a["id"]))
        first = svc.offer(db, asg, u, "feed", send=False)
        db.commit()
        assert first is not None and _n_attempts(db, asg.id, u.id) == 1
        monkeypatch.setattr(svc, "existing_attempt", lambda *_a, **_k: None)  # «проверка не увидела» — как при гонке
        assert svc.offer(db, asg, u, "feed", send=False) is None
        # транзакция и сессия рабочие: запрос и фиксация проходят без PendingRollbackError
        assert _n_attempts(db, asg.id, u.id) == 1
        db.commit()
        assert db.get(Assignment, asg.id).status == "active"


def test_run_once_survives_unique_violation_and_continues(client, monkeypatch):
    """Падение flush у одного кандидата (сырой UniqueViolation без SAVEPOINT) не роняет обход: откат, следующий кандидат получает предложение."""
    from app.modules.assignments import feed
    from app.modules.assignments import service as svc
    from app.modules.assignments.models import Assignment, AssignmentAttempt

    te = employer(client)
    a = open_assignment(client, te, ["python"])
    candidate_with_category(client, "race2@example.com")
    candidate_with_category(client, "race3@example.com")
    with SessionLocal() as db:
        u2, u3 = _login(db, "race2@example.com"), _login(db, "race3@example.com")
        asg = db.get(Assignment, uuid.UUID(a["id"]))
        # у race2 попытка уже есть (её вставил «другой воркер»), но подбор её не увидел
        db.add(AssignmentAttempt(assignment_id=asg.id, candidate_user_id=u2.id, source="feed", status="offered", offered_at=utcnow()))
        db.commit()
        monkeypatch.setattr(feed, "rank_for", lambda db_, user: [(1.0, asg, {"have": ["python"]})])
        monkeypatch.setattr(feed, "schedule", lambda db_, user: {"due": True, "frequency_days": 7})
        real_offer = svc.offer

        def racing_offer(db_, asg_, cand, source, **kw):
            if cand.email == "race2@example.com":  # вставка без точки сохранения — как до исправления
                db_.add(AssignmentAttempt(assignment_id=asg_.id, candidate_user_id=cand.id, source=source, status="offered",
                                          offered_at=utcnow()))
                db_.flush()
            return real_offer(db_, asg_, cand, source, send=False, **kw)

        monkeypatch.setattr(feed.svc, "offer", racing_offer)
        users_before = _n_attempts(db, asg.id, u3.id)
        assert users_before == 0
        n = feed.run_once(db)  # не бросает PendingRollbackError
        assert n == 1 and _n_attempts(db, asg.id, u3.id) == 1 and _n_attempts(db, asg.id, u2.id) == 1
        db.commit()
        for u in (u2, u3):
            u.last_login_at = utcnow() - timedelta(days=60)
        db.commit()
