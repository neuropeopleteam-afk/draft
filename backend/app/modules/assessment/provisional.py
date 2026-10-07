"""«Junior (предварительно)» — статус категории у нижнего порога (решение владельца 06.10).

Правило (психометрика — ``assessment_bank.psychometrics.grading.provisional_status``):
* тест на Junior не подтвердил грейд (P(θ ≥ порога Junior) < 0,80), но уровень ниже порога не доказан:
  P(θ ≥ порога) ≥ 0,10 ⇔ θ̂ + 1,28·SE ≥ порога (верхняя граница одностороннего 90 % интервала достаёт до порога).
  Две причины: «uncertain» — θ̂ ниже порога, интервал его пересекает; «precision» — θ̂ у порога или выше, но
  точности не хватило до 80 %;
* только тест на нижний грейд: заявившему Middle/Senior Junior не присваивается даже предварительно (грейд не
  понижается принудительно, тест на грейд ниже — выбор кандидата);
* только если подтверждённой категории нет: предварительный результат её не заменяет.

Что видит работодатель: категория «Junior (предварительно)», вероятность уровня не ниже Junior, причина, сколько
попыток подтверждения сделано. В ранжировании предварительный ниже подтверждённого при прочих равных: −0,05 к скору
подбора и к рейтингу в категории (вес одного зонда; задан до бенчмарка, на нём не подбирался).

Как подтвердить (кандидату): короткое дотестирование у порога Junior (до 6 коротких заданий, до 20 минут, ответы
прошлой попытки учитываются; не больше 2 попыток), повторный тест на Junior, зонд работодателя с оценкой «хорошее»
или «сильное решение» или кубок работодателя своего направления с результатом ≥ 70 %. Подтверждение — не смена
грейда: в истории причина confirmed, период 90 дней не начинается заново (отсчёт — от даты попадания в категорию).
Неудачная попытка статус не снимает (принудительного понижения нет), но работодатель видит актуальную оценку.
"""
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.core.db import as_aware, utcnow
from app.core.enums import EvidenceLevel, FactSource, GradeChangeReason, TestSessionStatus
from app.modules.assessment.models import GradeHistory, TestSession
from app.modules.assessment.rules import confirmation_lock
from app.modules.profiles.facts import PROVISIONAL_PENALTY

LEVEL = 0.10  # P(θ ≥ порога Junior) — «не доказанно ниже»
CONFIRM_LEVEL = 0.80  # подтверждение (как в движке банка)
CONFIRM_ATTEMPTS = 2  # коротких дотестирований на один предварительный статус (больше — банк утекает быстрее)
RANK_PENALTY = PROVISIONAL_PENALTY  # −0,05 к скору подбора и рейтингу в категории
WORK_MIN_SCORE = 0.7  # зонд «хорошее решение» и выше; кубок — результат ≥ 70 %
REASON_TITLES = {
    "uncertain": "оценка ниже порога Junior, но интервал неопределённости его пересекает",
    "precision": "оценка у порога Junior или выше, но точности не хватило для подтверждения",
    "below": "последняя попытка подтверждения не подтвердила Junior; статус сохраняется — принудительного понижения нет",
}
BY_TITLES = {"test": "тестом", "extension": "дотестированием у порога", "probe": "зондом работодателя",
             "cup": "кубком работодателя", "sandbox": "тестом (демо-режим)"}
HINT = ("Категория Junior присвоена предварительно: тест не подтвердил грейд, но и не показал, что уровень ниже. "
        "Работодатели видят её с пометкой «предварительно» и ставят чуть ниже подтверждённых при прочих равных. "
        "Подтвердите коротким дотестированием у порога — до 6 коротких заданий, до 20 минут, ответы прошлой попытки "
        "учитываются — или работой: зонд работодателя с оценкой «хорошее решение» и выше либо кубок работодателя "
        "в вашем направлении с результатом от 70 %. Подтверждение — не смена грейда: правило 90 дней не "
        "начинается заново.")


def title(grade_title: str | None, provisional: bool) -> str | None:
    if not grade_title:
        return grade_title
    return f"{grade_title} (предварительно)" if provisional else grade_title


def fact_extra(ts, res, *, since_at: datetime | None, attempts: int, now: datetime | None = None) -> dict:
    """Поля факта test_result для предварительного статуса (карточка, сравнение, PDF, подбор)."""
    mode = ((ts.result or {}).get("state") or {}).get("mode") or "full"
    last = None
    if now is not None:
        n_new = sum(1 for i in ((ts.result or {}).get("state") or {}).get("items") or [] if i.get("done")
                    and not i.get("canary"))
        last = {"at": now.isoformat(), "mode": mode, "theta": res.theta, "se": res.se, "p": res.p_claimed,
                "new_items": n_new if mode == "confirm" else None, "confirmed": False}
    return {"status": "provisional",
            "provisional": {"reason": getattr(res, "provisional_reason", None) or "below", "p": res.p_claimed,
                            "cut": -1.0, "level": LEVEL, "since": since_at.isoformat() if since_at else None,
                            "attempts": attempts, "attempts_max": CONFIRM_ATTEMPTS, "session_id": str(ts.id),
                            "last_confirm": last}}


def info(value: dict | None) -> dict | None:
    """Предварительный статус из факта test_result (для карточки, сравнения, PDF, подбора)."""
    pv = (value or {}).get("provisional")
    if not pv or (value or {}).get("status") == "confirmed":
        return None
    p = pv.get("p")
    return {"reason": pv.get("reason"), "reason_title": REASON_TITLES.get(pv.get("reason") or "", ""),
            "p": p, "p_pct": None if p is None else round(100 * float(p)), "level_pct": round(100 * LEVEL),
            "confirm_pct": round(100 * CONFIRM_LEVEL), "since": pv.get("since"),
            "attempts": int(pv.get("attempts") or 0), "attempts_max": CONFIRM_ATTEMPTS,
            "last_confirm": pv.get("last_confirm"),
            "text": (f"Junior предварительно: вероятность уровня не ниже Junior — {round(100 * float(p or 0))} % "
                     f"(подтверждение — от {round(100 * CONFIRM_LEVEL)} %, «не доказанно ниже» — от "
                     f"{round(100 * LEVEL)} %)")}


def confirmed_by(value: dict | None) -> dict | None:
    """Как был подтверждён бывший предварительный грейд (для карточки): способ и дата попадания в категорию."""
    v = value or {}
    if v.get("status") != "confirmed" or not v.get("confirmed_by"):
        return None
    by = v["confirmed_by"]
    return {"by": by, "title": BY_TITLES.get(by, by), "ref_title": v.get("confirmed_ref_title"),
            "provisional_since": v.get("provisional_since")}


def since(db: Session, user_id: uuid.UUID, direction: str | None) -> datetime | None:
    """Когда кандидат попал в категорию предварительно (последняя запись истории с причиной provisional)."""
    q = select(GradeHistory.created_at).where(GradeHistory.user_id == user_id,
                                               GradeHistory.reason == GradeChangeReason.provisional)
    if direction:
        q = q.where(GradeHistory.direction_id == direction)
    return as_aware(db.scalar(q.order_by(GradeHistory.created_at.desc()).limit(1)))


def confirm_attempts(db: Session, user_id: uuid.UUID, since_at: datetime | None) -> int:
    """Число коротких дотестирований (завершённых или начатых) после попадания в категорию предварительно."""
    rows = db.scalars(select(TestSession).where(TestSession.user_id == user_id)
                      .order_by(TestSession.created_at.desc()).limit(30)).all()
    n = 0
    for t in rows:
        if ((t.result or {}).get("state") or {}).get("mode") != "confirm":
            continue
        if t.status in (TestSessionStatus.aborted, TestSessionStatus.created):
            continue
        if since_at is None or (as_aware(t.created_at) or utcnow()) >= since_at:
            n += 1
    return n


def source_session(db: Session, profile) -> TestSession | None:
    """Сессия, по которой стоит предварительный статус (из факта test_result), — основа дотестирования."""
    from app.modules.profiles.models import CandidateFact

    f = db.scalar(select(CandidateFact).where(CandidateFact.user_id == profile.user_id,
                                              CandidateFact.kind == "test_result",
                                              CandidateFact.source == FactSource.test)
                  .order_by(CandidateFact.created_at.desc()).limit(1))
    sid = (f.value or {}).get("session_id") if f else None
    if not sid:
        return None
    try:
        ts = db.get(TestSession, uuid.UUID(str(sid)))
    except ValueError:
        return None
    if ts is None or ts.status != TestSessionStatus.finished or ts.user_id != profile.user_id:
        return None
    if not str((ts.result or {}).get("engine", "")).startswith("bank"):
        return None
    return ts


def options(db: Session, profile) -> dict | None:
    """Подсказка кандидату и доступные способы подтверждения (экран «Категория и грейд»)."""
    if not profile.grade_provisional or not profile.current_category_id:
        return None
    from app.modules.profiles.facts import load_bundles

    b = load_bundles(db, [profile.user_id]).get(profile.user_id)
    inf = info(b.test.value if b and b.test else None) or {}
    st = since(db, profile.user_id, profile.current_direction_id)
    used = confirm_attempts(db, profile.user_id, st)
    src = source_session(db, profile)
    can = src is not None and used < CONFIRM_ATTEMPTS
    return {**inf, "since": st.isoformat() if st else inf.get("since"), "attempts": used,
            "attempts_left": max(0, CONFIRM_ATTEMPTS - used), "can_confirm_test": can,
            "confirm_unavailable_reason": (None if can else
                                           "Попытки дотестирования использованы — подтвердите работой или пройдите тест на Junior заново."
                                           if used >= CONFIRM_ATTEMPTS else
                                           "Дотестирование доступно для теста банка заданий — пройдите тест на Junior заново."),
            "hint": HINT,
            "routes": [
                {"id": "extension", "title": "Короткое дотестирование у порога",
                 "text": "До 6 коротких заданий у порога Junior, до 20 минут. Ответы прошлой попытки учитываются: "
                         "оценка — по всем ответам, тем же правилом (подтверждение — от 80 %)."},
                {"id": "probe", "title": "Зонд работодателя",
                 "text": "Работодатель присылает короткую задачу; оценка «хорошее решение» или «сильное решение» "
                         "подтверждает Junior. Зонды приходят в «Приглашения»."},
                {"id": "cup", "title": "Кубок работодателя",
                 "text": "Участие в кубке своего направления; результат от 70 % подтверждает Junior."},
            ]}


def _latest_test_fact(db: Session, user_id: uuid.UUID):
    from app.modules.profiles.models import CandidateFact

    return db.scalar(select(CandidateFact).where(CandidateFact.user_id == user_id, CandidateFact.kind == "test_result",
                                                 CandidateFact.source == FactSource.test,
                                                 CandidateFact.evidence_level == EvidenceLevel.T1)
                     .order_by(CandidateFact.created_at.desc()).limit(1))


def mark_confirmed(db: Session, profile, *, by: str, ref: str | None = None, ref_title: str | None = None,
                   session_id: uuid.UUID | None = None, sandbox: bool = False) -> GradeHistory:
    """Предварительный грейд → подтверждён. Не смена грейда: тот же грейд, период 90 дней — от даты попадания
    в категорию (если он ещё идёт), новый не начинается."""
    now = utcnow()
    st = since(db, profile.user_id, profile.current_direction_id)
    until = None if sandbox else confirmation_lock(st, now, get_settings().grade_change_interval_days)
    h = GradeHistory(user_id=profile.user_id, direction_id=profile.current_direction_id,
                     from_grade_id=profile.current_grade_id, to_grade_id=profile.current_grade_id,
                     reason=GradeChangeReason.sandbox if sandbox else GradeChangeReason.confirmed,
                     test_session_id=session_id, locked_until=until)
    db.add(h)
    profile.grade_provisional = False
    profile.grade_locked_until = until
    f = _latest_test_fact(db, profile.user_id)
    if f is not None and by in ("probe", "cup"):
        v = dict(f.value or {})
        v.update({"status": "confirmed", "confirmed_by": by, "confirmed_ref": ref, "confirmed_ref_title": ref_title,
                  "provisional_since": st.isoformat() if st else (v.get("provisional") or {}).get("since"),
                  "confirmed_at": now.isoformat()})
        f.value = v
        flag_modified(f, "value")
    return h


def confirm_by_work(db: Session, user_id: uuid.UUID, *, source: str, ref: str, ref_title: str, score: float,
                    direction: str | None = None) -> bool:
    """Зонд работодателя («хорошее решение» и выше) или кубок своего направления (≥ 70 %) подтверждают
    предварительный Junior. True — подтверждён сейчас."""
    from app.modules.profiles.facts import refresh_rating
    from app.modules.profiles.models import CandidateProfile

    p = db.get(CandidateProfile, user_id)
    if p is None or not p.grade_provisional or not p.current_category_id or score < WORK_MIN_SCORE:
        return False
    if direction and direction != p.current_direction_id:
        return False
    mark_confirmed(db, p, by=source, ref=ref, ref_title=ref_title)
    db.flush()
    refresh_rating(db, user_id)
    return True
