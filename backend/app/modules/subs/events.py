"""Слушатель сессии: изменился кандидат (тест, грейд, навык, видимость) → строка в subs_dirty.

Подписки не пересчитываются при каждом изменении: слушатель только помечает кандидата (одна строка на кандидата,
повторные изменения обновляют время), а фоновый обход собирает пометки и пересчитывает лишь подписки его направления.
Сбой слушателя не должен ломать основную операцию: ошибки гасятся, а при отсутствии таблицы (миграция ещё не
применена) слушатель отключается на минуту.
"""
from __future__ import annotations

from itertools import chain
import logging
import time
import uuid

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.modules.assessment.models import GradeHistory
from app.modules.profiles.models import CandidateFact, CandidateProfile, CandidateSpecialization
from app.modules.subs.models import SubsDirty

log = logging.getLogger(__name__)
PROFILE_ATTRS = ("current_category_id", "current_grade_id", "current_direction_id", "grade_provisional",
                 "visible_to_employers", "onboarding_completed_at")
_off_until = 0.0
_table_ok = False
_installed = False


def _changed(session: Session) -> dict[uuid.UUID, str]:
    out: dict[uuid.UUID, str] = {}
    for obj in chain(session.new, session.dirty):
        new = obj in session.new
        if isinstance(obj, CandidateFact):
            if new or session.is_modified(obj, include_collections=False):
                out.setdefault(obj.user_id, "fact")
        elif isinstance(obj, GradeHistory):
            if new:
                out.setdefault(obj.user_id, "grade")
        elif isinstance(obj, CandidateSpecialization):
            if new or session.is_modified(obj, include_collections=False):
                out.setdefault(obj.user_id, "grade")
        elif isinstance(obj, CandidateProfile):
            st = inspect(obj)
            if new or any(st.attrs[a].history.has_changes() for a in PROFILE_ATTRS):
                out.setdefault(obj.user_id, "profile")
    return {k: v for k, v in out.items() if k is not None}


def _upsert(conn, rows: list[dict]) -> None:
    name = conn.dialect.name
    if name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:  # другой движок: отметки не ставим — страховочный полный пересчёт раз в сутки всё равно сработает
        return
    stmt = insert(SubsDirty.__table__).values(rows)
    conn.execute(stmt.on_conflict_do_update(index_elements=["user_id"],
                                            set_={"at": stmt.excluded.at, "reason": stmt.excluded.reason}))


def _after_flush(session: Session, _ctx) -> None:
    global _off_until, _table_ok
    if time.monotonic() < _off_until or session.info.get("subs_no_dirty"):
        return
    try:
        users = _changed(session)
        if not users:
            return
        conn = session.connection()
        if not _table_ok:
            if not inspect(conn).has_table(SubsDirty.__tablename__):
                _off_until = time.monotonic() + 60
                return
            _table_ok = True
        now = utcnow()
        _upsert(conn, [{"user_id": u, "at": now, "reason": r} for u, r in users.items()])
    except Exception:  # noqa: BLE001 — отметка не должна ронять основную операцию
        log.exception("subs: не удалось отметить изменение кандидата")


def install() -> None:
    global _installed
    if not _installed:
        event.listen(Session, "after_flush", _after_flush)
        _installed = True


install()
