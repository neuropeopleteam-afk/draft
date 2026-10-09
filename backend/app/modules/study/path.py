"""Путь участника: шаги берутся из фактов платформы (время создания записей), а не из того, что сообщил браузер.

* Кандидат: регистрация (почта подтверждена) → опрос → тест начат → результат (тест завершён).
* Работодатель: регистрация → потребность создана → подборка открыта → вопрос или приглашение отправлены.
Браузер добавляет только то, чего в базе нет: открытие экрана подборки, экраны и ошибки (study_events).
Факты до согласия на участие (старая учётная запись) не засчитываются.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import as_aware, utcnow
from app.core.enums import TestSessionStatus
from app.modules.assessment.models import SurveyResponse, TestSession
from app.modules.auth.models import User
from app.modules.invitations.models import Invitation, Probe
from app.modules.matching.models import EmployerNeed, SelectionVersion
from app.modules.study import texts
from app.modules.study.models import StudyAnswer, StudyEvent, StudyParticipant

STALL_AFTER = timedelta(minutes=30)  # нет событий дольше — считаем, что человек остановился
NEW_ACCOUNT_SLACK = timedelta(minutes=3)  # учётная запись создана не раньше согласия (с запасом на часы)
SELECTION_VIEW = re.compile(r"^/employer/needs/:id(/|$)")

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_REF = re.compile(r"^[A-Z]-[A-Z0-9]{4,10}$")


def norm_key(path: str) -> str | None:
    """Путь экрана или API без идентификаторов, кодов и параметров: «/employer/needs/:id/v/:n». None — не годится."""
    p = (path or "").split("?", 1)[0].split("#", 1)[0].strip()
    if p.startswith("/api/"):
        p = p[4:]
    if not p.startswith("/"):
        return None
    out = []
    for seg in p.split("/")[1:]:
        if not seg:
            continue
        if _UUID.match(seg):
            seg = ":id"
        elif _REF.match(seg):
            seg = ":ref"
        elif seg.isdigit():
            seg = ":n"
        elif len(seg) > 24 or not re.fullmatch(r"[A-Za-z0-9_.\-:]+", seg):
            seg = ":t"
        out.append(seg)
    key = "/" + "/".join(out)
    return key[:120] if len(key) > 1 else "/"


def _first(db: Session, col, *where):
    return as_aware(db.scalar(select(func.min(col)).where(*where)))


def _after(dt: datetime | None, since: datetime | None) -> datetime | None:
    return dt if dt and since and dt >= since else None


def derive(db: Session, p: StudyParticipant) -> dict:
    """{steps: {ключ: {at, skipped}}, path_done, done_at, current, last_activity, errors, views}. Только факты после согласия."""
    steps_def = texts.PATH[p.role]
    started = as_aware(p.started_at)
    user = db.get(User, p.user_id) if p.user_id else None
    at: dict[str, datetime | None] = {k: None for k, _, _ in steps_def}
    skipped: dict[str, bool] = {k: False for k, _, _ in steps_def}
    events = list(db.scalars(select(StudyEvent).where(StudyEvent.participant_id == p.id).order_by(StudyEvent.at))) if p.id else []
    views = [e for e in events if e.kind == "view"]
    errors = [e for e in events if e.kind == "error"]

    if user is not None and started is not None:
        # регистрация: учётная запись создана после согласия и почта подтверждена; иначе — «уже был аккаунт» / вход по ссылке
        fresh = as_aware(user.created_at) >= started - NEW_ACCOUNT_SLACK
        if p.mode == "quick" or not fresh:
            at["register"], skipped["register"] = as_aware(p.joined_at), True
        elif user.is_email_verified:
            at["register"] = as_aware(user.email_verified_at) or as_aware(p.joined_at)
        if p.role == "candidate":
            at["survey"] = _after(_first(db, SurveyResponse.created_at, SurveyResponse.user_id == user.id), started)
            ts_where = (TestSession.user_id == user.id, TestSession.is_sandbox.is_(False), TestSession.created_at >= started)
            at["test"] = _first(db, func.coalesce(TestSession.started_at, TestSession.created_at), *ts_where)
            at["result"] = _first(db, TestSession.finished_at, *ts_where, TestSession.status == TestSessionStatus.finished,
                                  TestSession.finished_at.is_not(None))
        else:
            need_where = (EmployerNeed.created_by == user.id, EmployerNeed.created_at >= started)
            at["need"] = _first(db, EmployerNeed.created_at, *need_where)
            if at["need"]:
                seen = [as_aware(v.at) for v in views if SELECTION_VIEW.match(v.key) and as_aware(v.at) >= at["need"]]
                if seen:
                    at["selection"] = min(seen)
                elif not views:  # браузер ничего не сообщал (нет экранов вообще): версия подборки создана вместе с потребностью
                    at["selection"] = _first(db, SelectionVersion.created_at, SelectionVersion.created_by == user.id,
                                             SelectionVersion.created_at >= started)
            cand = [_first(db, Probe.created_at, Probe.employer_user_id == user.id, Probe.created_at >= started),
                    _first(db, Invitation.created_at, Invitation.employer_user_id == user.id, Invitation.created_at >= started)]
            cand = [c for c in cand if c]
            at["contact"] = min(cand) if cand else None

    keys = [k for k, _, _ in steps_def]
    # путь строго по порядку: шаг без предыдущих не засчитывается как «пройденный» (кроме пропущенной регистрации)
    path_done = all(at[k] is not None for k in keys)
    current = next((k for k in keys if at[k] is None), None)
    times = [t for t in list(at.values()) + [as_aware(e.at) for e in events] + [as_aware(p.joined_at), started] if t]
    last_activity = max(times) if times else None
    done_at = max(at[k] for k in keys) if path_done else None
    return {"steps": {k: {"at": at[k], "skipped": skipped[k]} for k in keys}, "keys": keys, "path_done": path_done,
            "done_at": done_at, "current": current, "last_activity": last_activity, "errors": errors, "views": views}


def status_of(p: StudyParticipant, d: dict, answered: bool, now: datetime | None = None) -> str:
    """withdrawn | not_started | done | stopped | active — состояние участника для сводок."""
    now = now or utcnow()
    if p.withdrawn_at:
        return "withdrawn"
    if not p.started_at:
        return "not_started"
    if d["path_done"]:
        return "done"
    last = d["last_activity"]
    if answered or (last is not None and now - last >= STALL_AFTER):
        return "stopped"
    return "active"


def answered(db: Session, p: StudyParticipant) -> StudyAnswer | None:
    return db.scalar(select(StudyAnswer).where(StudyAnswer.participant_id == p.id))
