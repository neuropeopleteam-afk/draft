"""Готовые примеры устной защиты для песочниц жюри — «пример, модельный кандидат».

Разговор не вёлся: реплики «кандидата» — модельные (начало его же письменного ответа или нарочно чужой текст), оценка —
правилом заглушки. Сеется всегда (дёшево, без моделей); показывается только при INTERVIEW_ENABLED. Живой запуск жюри —
отдельно, с лимитом 1 в час на песочницу и не длиннее INTERVIEW_JURY_MINUTES.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.modules.assessment.models import TestSession
from app.modules.interview import context as cx
from app.modules.interview import port as pt
from app.modules.interview import service as svc
from app.modules.interview.models import InterviewSession

log = logging.getLogger("interview.demo")

OFFTOPIC = ("Честно говоря, здесь я бы просто взял готовое решение из интернета, точно не помню, как оно устроено "
            "внутри, но обычно всё работает и так.")


def _attempt(db: Session, user_id) -> TestSession | None:
    from app.modules.profiles.models import CandidateFact

    f = db.scalar(select(CandidateFact).where(CandidateFact.user_id == user_id, CandidateFact.kind == "test_result")
                  .order_by(CandidateFact.created_at.desc()).limit(1))
    if f is None or not (f.source_ref or "").startswith("test_session:"):
        return None
    return db.get(TestSession, uuid.UUID(f.source_ref.split(":", 1)[1]))


def _example(db: Session, user_id, honest: bool) -> InterviewSession | None:
    from app.modules.auth.models import User
    from app.modules.jury import scope

    ts = _attempt(db, user_id)
    if ts is None:
        return None
    good, reason = cx.eligible(ts)
    if reason:
        return None
    ctx, meta = cx.defense_context(ts, good[:2])
    port = pt.StubPort()
    est, _, _ = port.start("defense", ctx, max_questions=3, minutes=3, name="Мария")
    plan = est["plan"]
    by_task = {t["id"]: t for t in ctx["tasks"]}
    transcript = []
    for q in plan:
        transcript.append({"who": "interviewer", "text": q["question"], "n": q["n"]})
        written = (by_task.get(q["task_id"]) or {}).get("answer") or ""
        said = (written[:260].rsplit(" ", 1)[0] + ". Поэтому я так и написал.") if honest else OFFTOPIC
        transcript.append({"who": "candidate", "text": said, "n": q["n"], "channel": "voice"})
    raw = port.evaluate(est, transcript)
    raw["summary"] = ("Пример, модельный кандидат: реплики модельные, разговор не вёлся — так результат выглядит на "
                      "карточке. Оценка — правилом заглушки, не моделью.")
    raw["stub"] = False
    row = InterviewSession(id=uuid.uuid4(), mode="defense", candidate_user_id=user_id, test_session_id=ts.id,
                           status="in_progress", engine="example", is_example=True, minutes=3, max_questions=3,
                           jury_scope=scope.key_of((db.get(User, user_id) or User()).email),
                           context_meta=meta, transcript=transcript, consent_version=svc.CONSENT_VERSION,
                           started_at=utcnow(), duration_s=150, channel="voice", result={},
                           state={"channels_log": ["avatar", "voice"]})
    db.add(row)
    db.flush()
    svc.apply_result(db, row, raw)
    row.cost = {"usd": 0.0, "estimated": False}
    return row


def seed_jury_defense(db: Session, maria, ilya=None) -> None:
    """Мария — «ответ подтверждён устно», Илья (если в попытке есть развёрнутые ответы) — «есть расхождения».
    Сбой не ломает сид песочницы."""
    try:
        with db.begin_nested():
            _example(db, maria.user_id, honest=True)
            if ilya is not None:
                _example(db, ilya.user_id, honest=False)
    except Exception:  # noqa: BLE001
        log.exception("interview: пример устной защиты не создан")
