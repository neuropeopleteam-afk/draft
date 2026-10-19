"""Сценарии «устной защиты» и «ИИ-интервью»: правила, лимиты, опрос сервиса, вид для кандидата и работодателя.

Честно: грейд защита не меняет (FTT.4 — официально грейд даёт только тест); вердикт — модель сервиса (в заглушке —
правило), решение — за человеком. Результат защиты — сигнал доверия на карточке («ответ подтверждён устно / есть
расхождения / мало данных / не проходил»).
"""
from __future__ import annotations

from datetime import timedelta
import logging
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.core.db import as_aware, utcnow
from app.core.errors import api_error
from app.modules.assessment.models import TestSession
from app.modules.auth.models import User
from app.modules.interview import port as pt
from app.modules.interview import context as cx
from app.modules.interview.models import ACTIVE, FINAL, InterviewSession

log = logging.getLogger("interview")

CONSENT_VERSION = "2026-10-10.2"
EXAMPLE_LABEL = "пример, модельный кандидат"
VERDICT_TITLES = {"confirmed": "Ответ подтверждён устно", "discrepancies": "Есть расхождения",
                  "insufficient": "Мало данных", "strong": "Сильный результат", "medium": "Средний результат",
                  "weak": "Слабый результат", None: "Устную защиту не проходил"}
LEVEL_TITLES = {"confirmed": "подтверждено", "partial": "частично", "discrepancy": "расхождение", "no_data": "нет данных",
                "strong": "уверенно", "medium": "в целом", "weak": "слабо"}
STATUS_TITLES = {"invited": "Приглашение отправлено", "created": "Можно начинать", "in_progress": "Идёт разговор",
                 "evaluating": "Оценивается моделью", "completed": "Готово", "failed": "Не удалось", "expired": "Срок ссылки истёк", "cancelled": "Прервано",
                 "deleted": "Запись удалена по просьбе кандидата"}


def enabled() -> bool:
    return bool(get_settings().interview_enabled)


def meta() -> dict:
    s = get_settings()
    # avatar — свой образ интервьюера (сгенерированный портрет) на экране разговора (INTERVIEW_AVATAR_ENABLED, только при включённом интервью)
    return {"enabled": enabled(), "stub": pt.is_stub(), "defense_minutes": s.interview_defense_minutes,
            "avatar": enabled() and bool(s.interview_avatar_enabled)}


def require_enabled() -> None:
    if not enabled():
        raise api_error(409, "interview_disabled", "Устная защита и ИИ-интервью выключены")


def jury_key(user: User) -> str | None:
    from app.modules.jury import scope

    return scope.key_of(user.email) if user.is_demo else None


def consent_text(mode: str) -> dict:
    from app.core.legal import OPERATOR

    what = ("подтверждение ваших развёрнутых ответов теста" if mode == "defense" else "первое интервью по приглашению")
    return {"version": CONSENT_VERSION, "items": [
        f"Оператор — {OPERATOR['short_name']}; цель — {what}.",
        "Разговор ведёт ИИ-интервьюер (модель); решение принимают люди. Грейд по тесту не меняется.",
        "Речь и текст передаются сервисам распознавания речи и языковых моделей, в том числе за пределами России; "
        "фамилию, контакты и резюме мы им не передаём.",
        "Хранится только текстовая расшифровка и результат — без видео и звука; срок — как у попытки теста, "
        "удалить запись можно в любой момент.",
        "Результат, подтверждённые цитаты и текст разговора (без имени) видят работодатели, которые откроют вашу карточку." if mode == "defense" else
        "Результат и расшифровку видит только пригласившая компания."]}


# ------------------------------------------------------------------ лимиты

def _limits(db: Session, user: User, jkey: str | None) -> None:
    s, now = get_settings(), utcnow()
    live = (InterviewSession.is_example.is_(False), InterviewSession.status != "invited")
    day = db.scalar(select(func.count()).select_from(InterviewSession).where(
        *live, InterviewSession.created_at >= now - timedelta(days=1)))
    if day >= s.interview_total_day:
        raise api_error(429, "interview_daily_cap", "Дневной лимит сессий исчерпан — попробуйте завтра")
    recent = db.execute(select(InterviewSession.created_at, InterviewSession.status).where(
        *live, InterviewSession.jury_scope == jkey, InterviewSession.created_at >= now - timedelta(hours=1))).all() if jkey else []
    hour = len(recent)
    spent = sum(float((c or {}).get("usd") or 0) for c in db.scalars(select(InterviewSession.cost).where(
        InterviewSession.created_at >= now - timedelta(days=1), InterviewSession.cost.is_not(None)).limit(5000)))
    port = pt.get_port()
    try:
        # лимиты движка (контракт, раздел 4): жюри — 1 сессия в час на песочницу, дневной потолок расходов. На заглушке
        # денег нет — действуют только лимиты продукта ниже (INTERVIEW_JURY_PER_HOUR и др.)
        if not port.is_stub():
            port.check_limits(bool(jkey), [{"created_at": as_aware(c), "active": st in ("created", "in_progress")}
                                           for c, st in recent], spent)
    except Exception as e:  # noqa: BLE001 — EngineError движка
        code = getattr(e, "code", "interview_busy")
        raise api_error(429, code if code in ("jury_limit", "daily_cap") else "interview_busy",
                        "Дневной потолок расходов на интервью исчерпан — попробуйте завтра" if code == "daily_cap"
                        else "В песочнице жюри — один живой запуск в час; готовый пример — ниже") from None
    if jkey:
        if hour >= s.interview_jury_per_hour:
            raise api_error(429, "jury_limit", "В песочнице жюри — один живой запуск в час; готовый пример — ниже")
        return
    mine = db.scalar(select(func.count()).select_from(InterviewSession).where(
        *live, InterviewSession.candidate_user_id == user.id, InterviewSession.created_at >= now - timedelta(days=1)))
    if mine >= s.interview_per_user_day:
        raise api_error(429, "interview_user_limit", "Не больше нескольких сессий в сутки — попробуйте завтра")


def _clean_name(name: str | None) -> str:
    n = re.sub(r"[^\w\- ]", "", (name or "").strip(), flags=re.U)[:60].strip()
    return n.split()[0] if n else ""


def name_hint(db: Session, user: User) -> str:
    from app.modules.profiles.models import CandidateProfile

    p = db.get(CandidateProfile, user.id)
    return _clean_name(p.full_name if p else "") or ""


# ------------------------------------------------------------------ разговор

def _scrub(db: Session, user_id: uuid.UUID, text: str) -> str:
    """ПДн → плейсхолдеры в том, что сказал кандидат (до отправки в модели): имя и фамилия из профиля, контакты, имена."""
    from app.modules.profiles.models import CandidateProfile

    p = db.get(CandidateProfile, user_id)
    t = re.sub(r"\s+", " ", text or "").strip()
    for w in sorted({x for x in re.split(r"\s+", (p.full_name or "") if p else "") if len(x) >= 3}, key=len, reverse=True):
        t = re.sub(rf"\b{re.escape(w)}\w*", "[имя]", t, flags=re.I | re.U)
    return cx.redact(t) if t else t


def _deadline(row: InterviewSession):
    return as_aware(row.started_at) + timedelta(minutes=row.minutes, seconds=60) if row.started_at else None


def _expire(db: Session, row: InterviewSession) -> None:
    """Срок ссылки (не начат за сутки) — expired; разговор брошен — оценить сказанное или expired."""
    now = utcnow()
    if row.status == "created" and row.expires_at and as_aware(row.expires_at) < now:
        row.status = "expired"
        db.commit()
    elif row.status == "in_progress" and _deadline(row) and _deadline(row) + timedelta(minutes=15) < now:
        _close(db, row, inline=True)


def conversation(row: InterviewSession) -> dict | None:
    """Текущий шаг разговора для экрана кандидата."""
    if row.status not in ("created", "in_progress"):
        return None
    st = row.state or {}
    port = pt.get_port()
    stub = port.is_stub()
    return {"n": st.get("n"), "question": st.get("q"), "asked": len([r for r in row.transcript or []
                                                                      if r.get("who") == "interviewer"]),
            "max_questions": row.max_questions, "deadline": _deadline(row), "channels": port.channels(),
            "engine": "stub" if stub else "engine",
            # заглушка: начало письменного ответа на задание текущего вопроса — «подставить» в e2e
            "hint": port.hint(st.get("engine") or {}, int(st.get("n") or 0)) if stub and st.get("engine") else None,
            # защита: «Ваш ответ в тесте: «…»» под вопросом — 1–2 строки собственного ответа, по которому вопрос
            "context": _answer_excerpt(port, st) if row.mode == "defense" and row.status == "in_progress" else None}


def _answer_excerpt(port, st: dict, limit: int = 160) -> str | None:
    try:
        a = " ".join((port.hint(st.get("engine") or {}, int(st.get("n") or 0)) or "").split())
    except Exception:  # noqa: BLE001 — контекст необязателен
        return None
    if not a:
        return None
    return a if len(a) <= limit else a[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"


# Прощание ведущей, если разговор закрыт не её репликой (время вышло, «Закончить»): не тишина, а понятный итог.
CLOSING = {
    "defense": "Спасибо, я всё записала. Объяснения увидит работодатель, результат теста не меняется.",
    "interview": "Спасибо, я всё записала. Итог увидит работодатель, решение принимает человек.",
}
CLOSING_LATE = "Время вышло, на этом закончим. "


def add_cost(row: InterviewSession, kind: str, usd: float) -> None:
    """Доли стоимости, которые считает продукт (распознавание, голос), — к итогу движка."""
    if not usd:
        return
    st = dict(row.state or {})
    extra = dict(st.get("cost_extra") or {})
    extra[kind] = round(float(extra.get(kind) or 0) + float(usd), 6)
    st["cost_extra"] = extra
    row.state = st


def begin(db: Session, row: InterviewSession, channel: str) -> InterviewSession:
    if row.status == "in_progress":
        return row
    if row.status != "created":
        raise api_error(409, "interview_closed", "Сессия уже завершена")
    st = dict(row.state or {})
    port = pt.get_port()
    try:
        est, q, _ = port.start(row.mode, st.get("ctx") or {}, max_questions=row.max_questions, minutes=row.minutes,
                               name=st.pop("name", "") or "кандидат", jury=bool(row.jury_scope), channel=channel)
    except pt.EngineUnavailable as e:
        if str(e) == "insufficient_context":
            raise api_error(422, "insufficient_context", "Защищать нечего: нет развёрнутых ответов от 120 знаков") from None
        raise api_error(503, "interview_unavailable", "Интервьюер сейчас недоступен — попробуйте позже") from None
    row.state = {**st, "engine": est, "n": 1, "q": q, "port": port.name, "channels_log": [channel]}
    row.engine = "stub" if port.is_stub() else port.name  # движок без ключа модели — тоже заглушка
    row.transcript = [{"who": "interviewer", "text": q, "n": 1}]
    row.status, row.started_at, row.channel = "in_progress", utcnow(), channel
    db.commit()
    return row


def answer(db: Session, row: InterviewSession, text: str, channel: str) -> InterviewSession:
    if row.status != "in_progress":
        raise api_error(409, "interview_closed", "Разговор не идёт")
    t = _scrub(db, row.candidate_user_id, text)[:3000]
    if not t:
        raise api_error(422, "empty_answer", "Пустой ответ")
    st = dict(row.state or {})
    n = int(st.get("n") or 1)
    tr = list(row.transcript or []) + [{"who": "candidate", "text": t, "n": n, "channel": channel}]
    row.transcript, row.channel = tr, channel
    log_ = list(st.get("channels_log") or [])
    if not log_ or log_[-1] != channel:
        st["channels_log"] = log_ + [channel]
    late = _deadline(row) is not None and utcnow() > _deadline(row)
    q, fin = None, True
    if not late and n < row.max_questions + 2:
        try:
            est, q, fin = pt.get_port().reply(st.get("engine") or {}, t, channel)
            st["engine"] = est
        except pt.EngineUnavailable:
            q, fin = None, True
    if q and not fin:
        st.update(n=n + 1, q=q)
        row.transcript = tr + [{"who": "interviewer", "text": q, "n": n + 1}]
        row.state = st
        db.commit()
        return row
    if q:  # прощание ведущего — в расшифровку
        tr = tr + [{"who": "interviewer", "text": q, "n": None}]
        row.transcript = tr
    row.state = {**st, "q": None}
    _close(db, row, inline=pt.get_port().name == "stub")
    return row


def _close(db: Session, row: InterviewSession, *, inline: bool) -> None:
    """Разговор окончен: есть ответы — оценка (заглушка — сразу, движок — в фоне), нет — cancelled.
    Последняя реплика не прощание ведущей — добавляется короткое прощание (его же озвучивает /speech после закрытия)."""
    tr = list(row.transcript or [])
    last = tr[-1] if tr else None
    if not (last and last.get("who") == "interviewer" and last.get("n") is None):
        late = _deadline(row) is not None and utcnow() >= _deadline(row) - timedelta(seconds=5)
        bye = (CLOSING_LATE if late else "") + CLOSING.get(row.mode, CLOSING["defense"])
        row.transcript = tr + [{"who": "interviewer", "text": bye, "n": None}]
    else:
        bye = last.get("text") or ""
    row.state = {**(row.state or {}), "q": None, "closing": bye}
    if not any(r.get("who") == "candidate" for r in row.transcript or []):
        row.status = "cancelled"
        db.commit()
        return
    row.status = "evaluating"
    row.duration_s = int((utcnow() - as_aware(row.started_at)).total_seconds()) if row.started_at else None
    db.commit()
    if inline:
        evaluate(db, row)


def evaluate(db: Session, row: InterviewSession) -> None:
    try:
        raw = pt.get_port().evaluate((row.state or {}).get("engine") or {}, list(row.transcript or []))
    except Exception as e:  # noqa: BLE001
        log.warning("interview: оценка не удалась (%s)", type(e).__name__)
        row.status, row.error = "failed", "Оценка не удалась — можно пройти ещё раз"
        db.commit()
        return
    apply_result(db, row, raw)
    db.commit()


def evaluate_bg(row_id: uuid.UUID) -> None:
    """Оценка движком в фоне (BackgroundTasks) — своя сессия БД."""
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        row = db.get(InterviewSession, row_id)
        if row is not None and row.status == "evaluating":
            evaluate(db, row)


def _norm(t: str) -> str:
    return re.sub(r"[^\w]+", " ", (t or "").lower().replace("ё", "е")).strip()


def apply_result(db: Session, row: InterviewSession, raw: dict) -> None:
    """Итог движка → строка. Цитаты ещё раз сверяются кодом с ответами кандидата: чего нет в расшифровке — отбрасывается."""
    said = " | ".join(_norm(r.get("text") or "") for r in row.transcript or [] if r.get("who") == "candidate")
    qs, dropped = [], 0
    for i, q in enumerate(raw.get("questions") or []):
        if not isinstance(q, dict):
            continue
        quotes = []
        for c in q.get("quotes") or []:
            txt = str((c or {}).get("text") if isinstance(c, dict) else c or "").strip()[:400]
            if txt and _norm(txt) and _norm(txt) in said:
                quotes.append({"text": txt})
            elif txt:
                dropped += 1
        qs.append({"n": q.get("n") or i + 1, "task_id": q.get("task_id"), "skill": q.get("skill"),
                   "question": str(q.get("question") or "")[:600], "level": str(q.get("level") or "no_data")[:20],
                   "quotes": quotes[:4], "reasoning": str(q.get("reasoning") or "")[:600],
                   "lowered": bool(q.get("lowered"))})
    verdict = str(raw.get("verdict") or "insufficient")[:16]
    if verdict not in VERDICT_TITLES:
        verdict = "insufficient"
    score = raw.get("score")
    row.verdict, row.score = verdict, float(score) if isinstance(score, (int, float)) else None
    cost = dict(raw.get("cost") or {}) if isinstance(raw.get("cost"), dict) else {}
    for k, v in ((row.state or {}).get("cost_extra") or {}).items():
        cost[k] = round(float(cost.get(k) or 0) + float(v), 6)
    if cost:
        cost["usd"] = round(sum(float(cost.get(k) or 0) for k in ("llm_usd", "tts_usd", "stt_usd", "avatar_usd"))
                            or float(cost.get("usd") or 0), 6)
    row.cost = cost or None
    row.result = {"summary": str(raw.get("summary") or "")[:1200], "questions": qs,
                  "flags": [str(f)[:600] for f in raw.get("flags") or [] if f][:8], "coverage": raw.get("coverage"),
                  "stub": bool(raw.get("stub")), "quotes_dropped": dropped,
                  "quotes_removed_by_engine": int(raw.get("removed_quotes") or 0), "source": raw.get("source"),
                  "channels": (row.state or {}).get("channels_log") or []}
    bye = (row.state or {}).get("closing")
    row.state = {"closing": bye} if bye else {}  # контекст и состояние движка не нужны; прощание — для /speech после итога
    row.status, row.completed_at, row.error = "completed", utcnow(), None
    if row.mode == "defense":
        sync_fact(db, row)


# ------------------------------------------------------------------ устная защита

def _defense_rows(db: Session, ts_id: uuid.UUID) -> list[InterviewSession]:
    return list(db.scalars(select(InterviewSession).where(
        InterviewSession.test_session_id == ts_id, InterviewSession.mode == "defense")
        .order_by(InterviewSession.created_at.desc())))


def latest_defense(db: Session, ts_id: uuid.UUID) -> tuple[InterviewSession | None, InterviewSession | None]:
    """(последняя живая сессия, готовый пример) для попытки."""
    rows = _defense_rows(db, ts_id)
    return next((r for r in rows if not r.is_example), None), next((r for r in rows if r.is_example), None)


def own_attempt(db: Session, user: User, ts_id: uuid.UUID) -> TestSession:
    ts = db.get(TestSession, ts_id)
    if ts is None or ts.user_id != user.id:
        raise api_error(404, "test_session_not_found", "Попытка не найдена")
    return ts


def _jury_example(db: Session, jkey: str) -> InterviewSession | None:
    return db.scalar(select(InterviewSession).where(InterviewSession.is_example.is_(True),
                                                    InterviewSession.jury_scope == jkey)
                     .order_by(InterviewSession.created_at).limit(1))


def jury_fallback(db: Session, ts: TestSession, example: InterviewSession | None) -> dict | None:
    """Д2: в попытке жюри нечего защищать (экспресс-тест: 7 коротких заданий без развёрнутых ответов) — всё равно даём
    живой разговор с ИИ-интервьюером: по защищаемому примеру песочницы (развёрнутые ответы модельного кандидата), иначе —
    по последнему заданию попытки. {source, title, ctx, meta} или None, если опереться не на что."""
    from app.core.enums import TestSessionStatus

    if ts.status != TestSessionStatus.finished:
        return None
    if example is not None and example.test_session_id:
        ets = db.get(TestSession, example.test_session_id)
        good, why = cx.eligible(ets) if ets is not None else ([], "нет")
        if good and not why:
            ctx, meta = cx.defense_context(ets, good[:2])
            titles = [t["title"] for t in ctx["tasks"]]
            meta = {**meta, "source": "example", "example_id": str(example.id)}
            return {"source": "example", "title": "по защищаемому примеру" + (f": «{titles[0]}»" if titles else ""),
                    "ctx": ctx, "meta": meta}
    last = cx.last_task(ts)
    if last is not None:
        ctx, meta = cx.defense_context(ts, [last])
        meta = {**meta, "source": "last_task"}
        return {"source": "last_task", "title": f"по последнему заданию попытки: «{ctx['tasks'][0]['title']}»",
                "ctx": ctx, "meta": meta}
    return None


def defense_state(db: Session, user: User, ts: TestSession) -> dict:
    s = get_settings()
    good, reason = cx.eligible(ts)
    live, example = latest_defense(db, ts.id)
    if live is not None:
        _expire(db, live)
    jkey = jury_key(user)
    if example is None and jkey:  # жюри без своего примера (экспресс-тест без развёрнутых ответов) — пример песочницы
        example = _jury_example(db, jkey)
    fb = jury_fallback(db, ts, example) if (reason and jkey) else None
    used = sum(1 for r in _defense_rows(db, ts.id) if not r.is_example)
    # итог уже был (в том числе удалённый кандидатом) — повторной защиты этой попытки нет
    done = any(r.status == "completed" or (r.status == "deleted" and r.completed_at) for r in _defense_rows(db, ts.id)
               if not r.is_example)
    can = enabled() and (not reason or fb is not None) and not (live is not None and live.status in ACTIVE) and \
        (bool(jkey) or (not done and used < s.interview_defense_attempts))
    minutes = min(s.interview_defense_minutes, s.interview_jury_minutes) if jkey else s.interview_defense_minutes
    return {"enabled": enabled(), "stub": pt.is_stub(), "eligible": not reason, "reason": reason,
            "answers_n": len(good), "minutes": minutes, "max_questions": s.interview_defense_max_questions,
            "attempts_left": None if jkey else max(0, s.interview_defense_attempts - used), "can_start": can,
            "jury": {"live_per_hour": s.interview_jury_per_hour, "max_minutes": s.interview_jury_minutes} if jkey else None,
            "name_hint": name_hint(db, user), "consent": consent_text("defense"),
            "session": view(live, "candidate") if live else None,
            "example": view(example, "candidate") if example else None,
            # Д2: жюри без развёрнутых ответов — живой запуск по примеру или последнему заданию (title — о чём разговор)
            "fallback": {"source": fb["source"], "title": fb["title"]} if fb else None}


def start_defense(db: Session, user: User, ts: TestSession, name: str, consent: bool) -> InterviewSession:
    require_enabled()
    if not consent:
        raise api_error(422, "consent_required", "Нужно согласие на обработку ответов")
    nm = _clean_name(name)
    if not nm:
        raise api_error(422, "name_required", "Как к вам обращаться — одно слово, без фамилии")
    st = defense_state(db, user, ts)
    if st["reason"] and not st.get("fallback"):
        raise api_error(422, "insufficient_context", st["reason"])
    if st["session"] and st["session"]["status"] in ACTIVE:
        return db.get(InterviewSession, uuid.UUID(st["session"]["id"]))
    if not st["can_start"]:
        raise api_error(409, "defense_done", "Устная защита этой попытки уже пройдена или попытки закончились")
    jkey = jury_key(user)
    _limits(db, user, jkey)
    good, why = cx.eligible(ts)
    if why:  # Д2: жюри — разговор по защищаемому примеру или последнему заданию попытки
        fb = jury_fallback(db, ts, latest_defense(db, ts.id)[1] or (_jury_example(db, jkey) if jkey else None))
        if fb is None:
            raise api_error(422, "insufficient_context", why)
        ctx, meta_ = fb["ctx"], fb["meta"]
    else:
        ctx, meta_ = cx.defense_context(ts, good)
    s = get_settings()
    row = InterviewSession(id=uuid.uuid4(), mode="defense", candidate_user_id=user.id, test_session_id=ts.id,
                           created_by=user.id, status="created", jury_scope=jkey, minutes=st["minutes"],
                           max_questions=s.interview_defense_max_questions, context_meta=meta_,
                           consent_version=CONSENT_VERSION, result={})
    row.state, row.expires_at = {"ctx": ctx, "name": nm}, utcnow() + timedelta(hours=24)
    db.add(row)
    db.commit()
    return row


def summary(row: InterviewSession) -> dict:
    qs = (row.result or {}).get("questions") or []
    return {"verdict": row.verdict, "label": VERDICT_TITLES.get(row.verdict), "session_id": str(row.id),
            "date": as_aware(row.completed_at or row.created_at).date().isoformat(), "questions": len(qs),
            "quotes": sum(len(q.get("quotes") or []) for q in qs), "example": row.is_example,
            "stub": bool((row.result or {}).get("stub"))}


def sync_fact(db: Session, row: InterviewSession) -> None:
    """Сводка последней завершённой защиты → факт теста (value.defense) — значок на карточке без лишних запросов."""
    from app.modules.profiles.models import CandidateFact

    if not row.test_session_id:
        return
    f = db.scalar(select(CandidateFact).where(CandidateFact.kind == "test_result",
                                              CandidateFact.source_ref == f"test_session:{row.test_session_id}"))
    if f is None:
        return
    rows = [r for r in _defense_rows(db, row.test_session_id) if r.status == "completed"] or [row]
    best = next((r for r in rows if not r.is_example), rows[0])
    if best.status != "completed":
        return
    if (f.value or {}).get("defense") != summary(best):
        f.value = {**(f.value or {}), "defense": summary(best)}
        flag_modified(f, "value")


def badge(test_value: dict | None) -> dict | None:
    """Значок для карточки (facts.card): None — флаг выключен или теста нет."""
    if not enabled() or test_value is None:
        return None
    d = test_value.get("defense")
    if not d:
        return {"verdict": None, "title": VERDICT_TITLES[None], "example": False, "stub": False}
    return {"verdict": d.get("verdict"), "title": VERDICT_TITLES.get(d.get("verdict"), "Мало данных"),
            "session_id": d.get("session_id"), "date": d.get("date"), "questions": d.get("questions"),
            "quotes": d.get("quotes"), "example": bool(d.get("example")), "stub": bool(d.get("stub"))}


COMPARE_HINT = "Подтвердил ли кандидат развёрнутые ответы теста в коротком разговоре. Оценивает модель; грейд не меняет"


def compare_cell(b: dict | None) -> dict:
    """Ячейка сравнения по значку карточки."""
    if not b or not b.get("verdict"):
        return {"level": "none", "status": "neutral", "text": VERDICT_TITLES[None]}
    st = {"confirmed": "confirmed", "discrepancies": "mismatch"}.get(b["verdict"], "partial")
    extra = f"; цитат подтверждено — {b['quotes']}" if b.get("quotes") else ""
    tail = " (пример, модельный кандидат)" if b.get("example") else " (заглушка)" if b.get("stub") else ""
    return {"level": "T1", "status": st, "text": f"{b['title']}{extra}{tail}", "defense": b["verdict"]}


# ------------------------------------------------------------------ вид

def _clean_title(t: str | None) -> str | None:
    """Заголовок задания без хвостового «:», «;», «,» — в строке «Задание: … · подтверждено» не было «: ·»."""
    return t.rstrip(" :;,—-") or t if t else t


def view(row: InterviewSession, audience: str, *, transcript: bool = False) -> dict:
    r = row.result or {}
    meta_ = row.context_meta or {}
    titles = {t["id"]: t.get("title") for t in meta_.get("tasks") or []}
    # ИИ-интервью компании: итог и разбор видит только она (кандидату — статус); устную защиту кандидат видит сам
    done = row.status == "completed" and not (audience == "candidate" and row.mode == "interview")
    if row.is_example and done:  # примеры, засеянные до Д3: «(правило примера)», проценты ≤ 100
        from app.modules.interview.demo import example_wording

        r = example_wording(r)
    qs = [{"n": q.get("n"), "question": q.get("question") or "", "task_id": q.get("task_id"),
           "task_title": _clean_title(titles.get(q.get("task_id"))), "skill": q.get("skill"),
           "level": q.get("level") or "no_data", "level_title": LEVEL_TITLES.get(q.get("level"), "нет данных"),
           "quotes": [{"text": c["text"]} for c in q.get("quotes") or []], "reasoning": q.get("reasoning") or None,
           "lowered": bool(q.get("lowered"))} for q in (r.get("questions") or [])] if done else []
    return {"id": str(row.id), "mode": row.mode, "status": row.status,
            "status_title": STATUS_TITLES[row.status],
            "verdict": row.verdict if done else None,
            "verdict_title": VERDICT_TITLES.get(row.verdict) if done else None,
            "score": row.score if done else None, "summary": r.get("summary") if done else None,
            "questions": qs, "flags": r.get("flags") or [] if done else [], "coverage": r.get("coverage") if done else None,
            "duration_s": row.duration_s, "minutes": row.minutes, "max_questions": row.max_questions,
            "conversation": conversation(row) if audience == "candidate" else None,
            "created_at": row.created_at, "completed_at": row.completed_at, "expires_at": row.expires_at,
            "example": row.is_example, "example_label": EXAMPLE_LABEL if row.is_example else None,
            "stub": row.engine == "stub" or bool(r.get("stub")), "jury": bool(row.jury_scope),
            "tasks": [{"id": t["id"], "title": _clean_title(t.get("title"))} for t in meta_.get("tasks") or []],
            "skills": [s_["name"] for s_ in meta_.get("skills") or []], "note": row.note if audience == "employer" else None,
            "transcript": row.transcript if transcript and done and audience == "employer" else None,
            "result_hidden": row.status == "completed" and not done,
            "return_to": "/candidate/category#defense" if row.mode == "defense" else "/candidate/invitations",
            "error": row.error if row.status == "failed" else None}


# ------------------------------------------------------------------ работодатель: карточка кандидата

def for_candidate_card(db: Session, user_id: uuid.UUID, ts_id: uuid.UUID | None, company_id: uuid.UUID | None) -> dict:
    """Защита (последняя завершённая по попытке из карточки) + ИИ-интервью этой компании с кандидатом."""
    out: dict = {"enabled": enabled(), "defense": None, "interviews": []}
    if not enabled():
        return out
    if ts_id:
        rows = [r for r in _defense_rows(db, ts_id) if r.status == "completed"]
        best = next((r for r in rows if not r.is_example), rows[0] if rows else None)
        if best:
            sync_fact(db, best)
            db.commit()
            out["defense"] = view(best, "employer", transcript=True)
    if company_id:
        for r in db.scalars(select(InterviewSession).where(
                InterviewSession.candidate_user_id == user_id, InterviewSession.company_id == company_id,
                InterviewSession.mode == "interview").order_by(InterviewSession.created_at.desc()).limit(5)):
            _expire(db, r)
            out["interviews"].append(view(r, "employer", transcript=True))
    return out


# ------------------------------------------------------------------ ИИ-интервью — этап найма

def _hiring_row(db: Session, inv_id: uuid.UUID) -> InterviewSession | None:
    return db.scalar(select(InterviewSession).where(InterviewSession.invitation_id == inv_id,
                                                    InterviewSession.mode == "interview")
                     .order_by(InterviewSession.created_at.desc()).limit(1))


def _need_req(db: Session, inv) -> dict:
    from app.modules.matching.models import EmployerNeed

    n = db.get(EmployerNeed, inv.need_id) if inv.need_id else None
    return (n.requirements or {}) if n else {}


def _bundle(db: Session, user_id: uuid.UUID):
    from app.modules.profiles.facts import load_bundles

    return load_bundles(db, [user_id]).get(user_id)


def hiring_skills(db: Session, inv, extra: list[str] | None = None) -> tuple[dict, dict, str | None]:
    ctx, meta_, reason = cx.interview_context(db, inv, _bundle(db, inv.candidate_user_id), _need_req(db, inv))
    extra = [re.sub(r"\s+", " ", x).strip()[:80] for x in extra or [] if x and x.strip()][:8]
    if extra:
        if reason:
            ctx = {"need_title": (inv.position_title or "Вакансия")[:200],
                   "need_summary": cx.redact(re.sub(r"\s+", " ", inv.offer_description or ""))[:600],
                   "confirmed_skills": [], "unconfirmed_skills": []}
            meta_, reason = {"skills": [], "confirmed": [], "need_id": None}, None
        have = {u["name"].lower() for u in ctx["unconfirmed_skills"]}
        for x in extra:
            if x.lower() not in have and len(ctx["unconfirmed_skills"]) < 8:
                ctx["unconfirmed_skills"].append({"name": x, "why": "указал работодатель", "level": "базовый"})
                meta_["skills"].append({"tag": None, "name": x, "why": "указал работодатель"})
    return ctx, meta_, reason


def stage_state(db: Session, inv, side: str) -> dict:
    from app.core.enums import InvitationStatus

    row = _hiring_row(db, inv.id)
    if row is not None:
        _expire(db, row)
    ok = inv.status == InvitationStatus.accepted
    _, meta_, reason = hiring_skills(db, inv) if side == "employer" and enabled() else ({}, {}, None)
    return {"enabled": enabled(), "stub": pt.is_stub(), "minutes": get_settings().interview_hiring_minutes,
            "can_invite": enabled() and ok and (row is None or row.status in ("failed", "expired", "cancelled")),
            "reason": None if ok else "Этап доступен после того, как кандидат принял приглашение",
            "skills": [s_["name"] for s_ in meta_.get("skills") or []], "skills_reason": reason,
            "name_hint": name_hint(db, db.get(User, inv.candidate_user_id)) if side == "candidate" else None,
            "consent": consent_text("interview") if side == "candidate" else None,
            "session": view(row, side, transcript=side == "employer") if row else None}


def invite_interview(db: Session, employer: User, inv, note: str | None, skills: list[str] | None) -> InterviewSession:
    from app.core.enums import InvitationStatus

    require_enabled()
    if inv.status != InvitationStatus.accepted:
        raise api_error(409, "invitation_not_accepted", "Этап доступен после того, как кандидат принял приглашение")
    row = _hiring_row(db, inv.id)
    if row is not None and row.status not in ("failed", "expired", "cancelled"):
        raise api_error(409, "interview_exists", "ИИ-интервью по этому приглашению уже назначено")
    ctx, meta_, reason = hiring_skills(db, inv, skills)
    if reason:
        raise api_error(422, "insufficient_context", reason + " — добавьте навыки вручную")
    s = get_settings()
    row = InterviewSession(id=uuid.uuid4(), mode="interview", candidate_user_id=inv.candidate_user_id,
                           invitation_id=inv.id, company_id=inv.company_id, created_by=employer.id, status="invited",
                           minutes=s.interview_hiring_minutes, max_questions=s.interview_hiring_max_questions,
                           context_meta={**meta_, "extra": [x for x in (skills or []) if x][:8]},
                           note=(note or "").strip()[:500] or None, result={})
    db.add(row)
    db.commit()
    return row


def start_interview(db: Session, user: User, inv, name: str, consent: bool) -> InterviewSession:
    require_enabled()
    row = _hiring_row(db, inv.id)
    if row is None:
        raise api_error(404, "interview_not_found", "Компания не приглашала на ИИ-интервью")
    if row.status in ACTIVE:
        return row
    if row.status != "invited":
        raise api_error(409, "interview_done", "ИИ-интервью уже пройдено или прервано")
    if not consent:
        raise api_error(422, "consent_required", "Нужно согласие на обработку ответов")
    nm = _clean_name(name)
    if not nm:
        raise api_error(422, "name_required", "Как к вам обращаться — одно слово, без фамилии")
    jkey = jury_key(user)
    _limits(db, user, jkey)
    ctx, meta_, reason = hiring_skills(db, inv, (row.context_meta or {}).get("extra"))
    if reason:
        raise api_error(422, "insufficient_context", reason)
    row.jury_scope = jkey
    if jkey:
        row.minutes = min(row.minutes, get_settings().interview_jury_minutes)
    row.context_meta = {**meta_, "extra": (row.context_meta or {}).get("extra") or []}
    row.consent_version = CONSENT_VERSION
    row.created_at = utcnow()  # лимиты считаются от начала разговора, а не от приглашения
    row.state, row.expires_at = {"ctx": ctx, "name": nm}, utcnow() + timedelta(hours=24)
    row.status = "created"
    db.commit()
    return row


def own_session(db: Session, user: User, sid: uuid.UUID) -> InterviewSession:
    row = db.get(InterviewSession, sid)
    if row is None or row.candidate_user_id != user.id:
        raise api_error(404, "interview_not_found", "Сессия не найдена")
    return row


def delete_session(db: Session, row: InterviewSession) -> None:
    """Удалить запись по просьбе кандидата (ПДн): текст разговора, результат, контекст и сводку в факте теста.
    Остаётся отметка о факте сессии (статус deleted, без содержимого): иначе удаление «расхождений» давало бы повторную
    защиту той же попытки, а лимиты считались бы заново."""
    from app.modules.profiles.models import CandidateFact

    ts_id = row.test_session_id
    was_done = row.status == "completed"
    row.status, row.verdict, row.score, row.transcript, row.result = "deleted", None, None, None, {}
    row.state, row.context_meta, row.note, row.error = {}, {}, None, None
    if not was_done:
        row.completed_at = None
    db.flush()
    if ts_id:
        f = db.scalar(select(CandidateFact).where(CandidateFact.kind == "test_result",
                                                  CandidateFact.source_ref == f"test_session:{ts_id}"))
        rest = [r for r in _defense_rows(db, ts_id) if r.status == "completed"]
        if f is not None and (f.value or {}).get("defense"):
            v = {k: x for k, x in f.value.items() if k != "defense"}
            if rest:
                best = next((r for r in rest if not r.is_example), rest[0])
                v["defense"] = summary(best)
            f.value = v
            flag_modified(f, "value")
    db.commit()
