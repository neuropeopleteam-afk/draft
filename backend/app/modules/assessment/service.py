"""Сервис тестирования: хранение сессий, применение правил грейда, запись фактов T1.

С движком (заглушка или банк) общается только через протокол AssessmentEngine (engine.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta
import secrets
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, object_session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.core.db import as_aware, utcnow
from app.core.enums import EvidenceLevel, FactSource, GradeChangeReason, TestSessionStatus
from app.core.errors import api_error
from app.modules.assessment.engine import get_engine
from app.modules.assessment.models import (GradeHistory, SandboxTestStart, SurveyResponse, TaskFamily, TaskVariant,
                                           TestAnswer, TestSession, TestSessionItem)
from app.modules.auth.models import User
from app.modules.assessment.rules import (GRADE_LEVEL, accept_lower_allowed, apply_result, check_can_start,
                                          retake_locks)
from app.modules.catalog.seed_data import STACK
from app.modules.profiles.facts import refresh_rating
from app.modules.profiles.models import CandidateFact, CandidateProfile


def is_sandbox(profile: CandidateProfile) -> bool:
    """Правило 90 дней снято: глобальная песочница или демо-режим жюри — только у демо-учёток (users.is_demo)."""
    s = get_settings()
    if s.demo_sandbox:
        return True
    if not (s.jury_mode_available and profile.jury_mode):
        return False
    db = object_session(profile)
    user = db.get(User, profile.user_id) if db is not None else None
    return bool(user and user.is_demo)


def sandbox_quota(db: Session, email: str) -> dict:
    """Сколько тестов ещё можно начать в демо-режиме за скользящие 24 часа (лимит JURY_MAX_TEST_STARTS_PER_DAY).

    Без лимита демо-режим (правило 90 дней снято, вход под жюри — в один клик) позволял бы перезапусками
    выкачать банк заданий: каждая новая сессия выдаёт новые варианты.
    """
    limit = get_settings().jury_max_test_starts_per_day
    since = utcnow() - timedelta(hours=24)
    rows = db.scalars(select(SandboxTestStart.created_at).where(SandboxTestStart.email == email,
                                                                SandboxTestStart.created_at >= since)
                      .order_by(SandboxTestStart.created_at)).all()
    used = len(rows)
    reset_at = as_aware(rows[0]) + timedelta(hours=24) if rows and used >= limit else None
    return {"limit": limit, "used": used, "left": max(0, limit - used),
            "next_at": reset_at.isoformat() if reset_at else None}


def latest_survey(db: Session, user_id: uuid.UUID) -> SurveyResponse | None:
    return db.scalar(select(SurveyResponse).where(SurveyResponse.user_id == user_id)
                     .order_by(SurveyResponse.created_at.desc()).limit(1))


def active_session(db: Session, user_id: uuid.UUID) -> TestSession | None:
    return db.scalar(select(TestSession).where(
        TestSession.user_id == user_id,
        TestSession.status.in_([TestSessionStatus.created, TestSessionStatus.in_progress]),
    ).order_by(TestSession.created_at.desc()).limit(1))


def recent_failed(db: Session, user_id: uuid.UUID, direction_id: str, now, retake_days: int) -> dict[str, datetime]:
    """Неподтверждённые завершённые попытки в направлении за последние retake_days дней: {грейд: время последней}."""
    since = now - timedelta(days=retake_days)
    rows = db.scalars(select(TestSession).where(
        TestSession.user_id == user_id, TestSession.direction_id == direction_id,
        TestSession.status == TestSessionStatus.finished, TestSession.finished_at >= since,
    ).order_by(TestSession.finished_at.desc())).all()
    out: dict[str, datetime] = {}
    for t in rows:
        er = (t.result or {}).get("engine_result") or {}
        if er.get("confirmed") is False and t.claimed_grade_id not in out:
            # принятый по этому тесту уровень ниже — не неудача на этом уровне, а присвоение; попытка на заявленный
            # грейд всё равно считается неподтверждённой
            out[t.claimed_grade_id] = as_aware(t.finished_at)
    return out


def start_session(db: Session, user_id: uuid.UUID, claimed_grade: str, engine_name: str | None = None, *,
                  integrity_ack: bool = False, enforce_sandbox_quota: bool = False, mode: str = "full") -> TestSession:
    """enforce_sandbox_quota — запрос кандидата через API (демо-сиды жюри проходят тест без лимита).
    mode: full — обычный адаптивный тест; express — экспресс-тест для жюри (только в демо-режиме)."""
    profile = db.get(CandidateProfile, user_id)
    survey = latest_survey(db, user_id)
    if profile is None or survey is None or profile.onboarding_completed_at is None:
        raise api_error(409, "onboarding_required", "Сначала пройдите опрос: направление, стек и опыт")
    now = utcnow()
    st_ = get_settings()
    sandbox = is_sandbox(profile)
    if mode == "express" and not sandbox:
        raise api_error(409, "express_sandbox_only",
                        "Экспресс-тест доступен только в демо-режиме жюри: категорию живым кандидатам присваивает полный тест")
    failed = recent_failed(db, user_id, survey.direction_id, now, st_.retake_same_grade_days) if not sandbox else None
    check = check_can_start(profile.current_grade_id, profile.grade_locked_until, claimed_grade, now, sandbox,
                            failed, st_.retake_same_grade_days)
    if not check.allowed:
        raise api_error(409 if check.code in ("grade_locked", "retake_cooldown") else 422,
                        check.code or "not_allowed", check.message or "")
    old = active_session(db, user_id)
    if (old is not None and old.claimed_grade_id == claimed_grade and old.direction_id == survey.direction_id
            and (old.result or {}).get("mode", "full") == mode):
        if integrity_ack and not (old.result or {}).get("integrity_ack"):
            old.result = {**old.result, "integrity_ack": {"at": now.isoformat()}}
            flag_modified(old, "result")
            db.commit()
        return old
    if enforce_sandbox_quota and sandbox:
        user = db.get(User, user_id)
        q = sandbox_quota(db, user.email)
        if q["left"] <= 0:
            when = f" Следующая попытка — после {q['next_at'][:16].replace('T', ' ')} UTC." if q["next_at"] else ""
            raise api_error(429, "sandbox_restarts_exhausted",
                            f"В демо-режиме можно начать не больше {q['limit']} тестов за 24 часа — так банк заданий "
                            f"нельзя выкачать перезапусками.{when}")
        db.add(SandboxTestStart(email=user.email, user_id=user_id))
    if old is not None:
        old.status = TestSessionStatus.aborted
        old.finished_at = now
    engine = get_engine(engine_name)
    seed = secrets.randbelow(2**31)
    stack = list((survey.answers or {}).get("stack", {}).keys())
    if engine.name.startswith("bank"):
        # Повторная попытка — другой субпул, чем в прошлых сессиях этого кандидата (параллельная форма);
        # семейства последней попытки не попадают в дотестирование у порога (оно берёт задания и из другого субпула)
        past = [((t.result or {}).get("state") or {}) for t in db.scalars(
            select(TestSession).where(TestSession.user_id == user_id, TestSession.status == TestSessionStatus.finished)
            .order_by(TestSession.created_at.desc()).limit(5))]
        prev = [st.get("subpool") for st in past if st.get("subpool") is not None]
        last_families = [i.get("family_id") for i in (past[0].get("items") or []) if i.get("family_id")] if past else []
        state = engine.start(direction=survey.direction_id, claimed_grade=claimed_grade, stack_tags=stack, seed=seed,
                             previous_subpools=prev, previous_families=last_families, mode=mode)
    else:
        state = engine.start(direction=survey.direction_id, claimed_grade=claimed_grade, stack_tags=stack, seed=seed)
    # Адаптивный тест банка: до 60 минут (лимит CATConfig) + запас на дотестирование у порога (не меньше 30 минут,
    # как раньше); экспресс — 20 минут; заглушка — 30 минут
    if not engine.name.startswith("bank"):
        minutes = 30
    elif mode == "express":
        minutes = st_.assessment_express_max_minutes
    else:
        minutes = st_.assessment_max_minutes + max(30, st_.assessment_extension_minutes + 10)
    ts = TestSession(
        user_id=user_id, survey_id=survey.id, direction_id=survey.direction_id, claimed_grade_id=claimed_grade,
        status=TestSessionStatus.in_progress, form_seed=seed, is_sandbox=sandbox, started_at=now,
        deadline_at=now + timedelta(minutes=minutes),
        result={"engine": engine.name, "state": state, "mode": mode,
                # кандидат прочитал экран «что отслеживается» (прозрачный античит) до начала теста
                "integrity_ack": {"at": now.isoformat()} if integrity_ack else None},
    )
    db.add(ts)
    db.commit()
    return ts


def get_own_session(db: Session, user_id: uuid.UUID, session_id: uuid.UUID, lock: bool = False) -> TestSession:
    # lock: строка сессии блокируется до конца транзакции (два параллельных запроса не выдадут два задания)
    ts = db.get(TestSession, session_id, with_for_update=lock)
    if ts is None or ts.user_id != user_id:
        raise api_error(404, "session_not_found", "Сессия теста не найдена")
    return ts


def next_item(db: Session, ts: TestSession):
    """Текущее или следующее задание. Движок банка при выдаче меняет состояние — сохраняем его сразу."""
    if ts.status != TestSessionStatus.in_progress:
        return None
    item = get_engine(_engine_key(ts)).next_item(ts.result["state"])
    if _engine_key(ts) == "bank":
        _drain_outbox(db, ts)
        flag_modified(ts, "result")
        db.commit()
    return item


def progress(ts: TestSession) -> tuple[int, int, bool]:
    """(отвечено заданий, ориентир общего числа, можно завершать)."""
    st = ts.result.get("state", {})
    if _engine_key(ts) == "bank":
        done = sum(1 for i in st.get("items", []) if i.get("done"))
        cfg = st.get("cfg", {})
        ext = st.get("ext") or {}
        return done, int(cfg.get("max_items", 20)) + 3 + int(ext.get("n", 0)), bool(st.get("done"))
    total = len(st.get("item_ids", []))
    answered = len(st.get("answers", {}))
    return answered, total, answered >= total > 0


def _drain_outbox(db: Session, ts: TestSession) -> None:
    """Выданные задания и ответы — в таблицы task_families/task_variants/test_session_items/test_answers.

    Это нормализованная копия для калибровки банка (матрица «кандидат × задание», время ответов) и аудита;
    сам движок работает по состоянию сессии. Ключи и рубрики хранятся только в БД, кандидату не отдаются.
    """
    st = ts.result.get("state", {})
    box = st.get("outbox") or []
    if not box:
        return
    from assessment_bank import get_spec

    by_token = {i["token"]: i for i in st.get("items", [])}
    for ev in box:
        it = by_token.get(ev.get("token"))
        if it is None:
            continue
        if ev["type"] == "issue":
            fam = db.get(TaskFamily, it["family_id"])
            if fam is None:
                spec = get_spec(it["family_id"])
                fam = TaskFamily(id=spec.family_id, direction=spec.direction, skills=spec.skills,
                                 target_grades=list(spec.target_grades), format=spec.format,
                                 invariants=spec.invariants.model_dump(mode="json"), time_limit_s=spec.time_limit_s,
                                 canary=spec.canary, prior_difficulty=spec.prior_difficulty.b, version=spec.version,
                                 exposure_count=0)
                db.add(fam)
                db.flush()
            fam.exposure_count = (fam.exposure_count or 0) + 1
            var = db.get(TaskVariant, it["variant_id"])
            if var is None:
                pub = it["public"]
                var = TaskVariant(id=it["variant_id"], family_id=it["family_id"], seed=it["seed"], stem=pub["stem"],
                                  code=pub["code"], code_language=it.get("language"), options=pub["options"],
                                  answer_key=it["key"], rubric=it["rubric"],
                                  meta={"steps": pub.get("steps"), "format": it["format"], "bank": st.get("engine")},
                                  exposure_count=0)
                db.add(var)
                db.flush()
            var.exposure_count = (var.exposure_count or 0) + 1
            row = TestSessionItem(session_id=ts.id, variant_id=it["variant_id"], position=it["position"],
                                  shown_at=utcnow())
            db.add(row)
            db.flush()
            it["row_id"] = str(row.id)
        elif ev["type"] == "review" and it.get("row_id"):
            row = db.scalar(select(TestAnswer).where(TestAnswer.item_id == uuid.UUID(it["row_id"])))
            if row is not None:
                xs = [v for v in it["x"] if v is not None]
                row.score = sum(xs) / len(xs) if xs else None
                row.is_correct = all(v == 1.0 for v in it["x"]) if len(xs) == len(it["x"]) else None
                row.grading = {**(row.grading or {}), "x": it["x"], "parts": it["grading"],
                               "expert_reviews": it.get("expert_reviews")}
                flag_modified(row, "grading")
        elif ev["type"] == "answer" and it.get("row_id"):
            xs = [v for v in it["x"] if v is not None]
            db.add(TestAnswer(
                session_id=ts.id, item_id=uuid.UUID(it["row_id"]),
                answer={k: {"value": a["value"], "client_ms": a.get("client_ms"), "server_ms": a.get("server_ms")}
                        for k, a in it["answers"].items()},
                is_correct=(all(v == 1.0 for v in it["x"]) if len(xs) == len(it["x"]) else None),
                score=(sum(xs) / len(xs) if xs else None),
                grading={"x": it["x"], "parts": it["grading"], "canary": it["canary"], "log_t": it.get("log_t"),
                         "overtime": it.get("overtime")},
                time_spent_ms=int(it.get("time_s", 0) * 1000),
            ))
    st["outbox"] = []


def _engine_key(ts: TestSession) -> str:
    return "bank" if str(ts.result.get("engine", "")).startswith("bank") else "stub"


def submit_answer(db: Session, ts: TestSession, item_id: str, answer, time_spent_ms: int | None,
                  step: int | None = None, signals: dict | None = None):
    if ts.status != TestSessionStatus.in_progress:
        raise api_error(409, "session_closed", "Сессия теста уже завершена")
    if ts.deadline_at and utcnow() > as_aware(ts.deadline_at):
        ts.status = TestSessionStatus.expired
        db.commit()
        raise api_error(409, "session_expired", "Время на тест истекло — начните заново")
    state = ts.result["state"]
    eng = get_engine(_engine_key(ts))
    if _engine_key(ts) == "bank":
        fb = eng.answer(state, item_id, answer, time_spent_ms, step=step, signals=signals)
    else:
        fb = eng.answer(state, item_id, answer, time_spent_ms, step=step)
    if not fb.accepted:
        raise api_error(422, "answer_rejected", "Ответ не принят: задание уже отвечено, шаг не текущий "
                                                "или ответ не подходит к формату задания")
    if _engine_key(ts) == "bank":
        _drain_outbox(db, ts)
    flag_modified(ts, "result")
    db.commit()
    return fb


def finish_session(db: Session, ts: TestSession, engine=None) -> dict:
    if ts.status == TestSessionStatus.finished:
        return ts.result.get("outcome", {})
    if ts.status != TestSessionStatus.in_progress:
        raise api_error(409, "session_closed", "Сессия теста уже закрыта")
    if _engine_key(ts) == "bank" and not ts.result["state"].get("done"):
        # Досрочное завершение запрещено: иначе можно ответить на 2–3 удачных задания и подтвердить грейд
        raise api_error(409, "test_not_complete", "Тест ещё не закончен: ответьте на текущее задание")
    profile = db.get(CandidateProfile, ts.user_id)
    res = (engine or get_engine(_engine_key(ts))).finish(ts.result["state"])
    now = utcnow()
    sandbox = is_sandbox(profile)
    # Тест в другом направлении: подтверждённый грейд считается «нет» для правил (категория — пара направление·грейд)
    current = profile.current_grade_id if profile.current_direction_id == ts.direction_id else None
    outcome = apply_result(current, ts.claimed_grade_id, res.confirmed, now, sandbox,
                           get_settings().grade_change_interval_days, profile.grade_locked_until)
    ts.status = TestSessionStatus.finished
    ts.finished_at = now
    ts.theta, ts.theta_se = res.theta, res.se
    ts.score = res.correct / res.answered if res.answered else 0.0
    ts.result_grade_id = ts.claimed_grade_id if res.confirmed else None
    ts.result = {**ts.result, "engine_result": res.to_dict(),
                 "outcome": {"changed": outcome.changed, "grade": outcome.new_grade, "message": outcome.message}}
    flag_modified(ts, "result")

    if outcome.changed or (res.confirmed and outcome.new_grade == ts.claimed_grade_id):
        if outcome.changed:
            db.add(GradeHistory(user_id=ts.user_id, direction_id=ts.direction_id, from_grade_id=current,
                                to_grade_id=outcome.new_grade, reason=GradeChangeReason(outcome.reason),
                                test_session_id=ts.id, locked_until=outcome.locked_until))
            profile.current_direction_id = ts.direction_id
            profile.current_grade_id = outcome.new_grade
            profile.current_category_id = f"{ts.direction_id}.{outcome.new_grade}"
            profile.grade_locked_until = outcome.locked_until
        _write_t1_facts(db, ts, res)
        db.flush()
        refresh_rating(db, ts.user_id)
    db.commit()
    return _result_payload(db, ts, profile)


def _result_payload(db: Session, ts: TestSession, profile: CandidateProfile) -> dict:
    """Итог завершённого теста для кандидата (finish и повторные запросы результата)."""
    er = ts.result.get("engine_result") or {}
    outcome = ts.result.get("outcome") or {}
    details = er.get("details") or {}
    current = profile.current_grade_id if profile.current_direction_id == ts.direction_id else None
    can_lower, _ = accept_lower_allowed(current, ts.claimed_grade_id, bool(er.get("confirmed")), er.get("probabilities"))
    accepted = outcome.get("accepted_lower")
    return {
        "session_id": str(ts.id), "theta": er.get("theta"), "se": er.get("se"), "claimed_grade": ts.claimed_grade_id,
        "point_grade": er.get("point_grade"), "confirmed": er.get("confirmed"),
        "upgrade_available": er.get("upgrade_available"), "retake_lower": er.get("retake_lower"),
        "probabilities": er.get("probabilities"), "correct": er.get("correct"),
        "answered": er.get("answered"), "explanation": er.get("explanation"), "grade_changed": outcome.get("changed"),
        "current_grade": profile.current_grade_id, "category_id": profile.current_category_id,
        "message": outcome.get("message"), "engine": er.get("engine"),
        "mode": ts.result.get("mode", "full"),
        "locked_until": as_aware(profile.grade_locked_until).isoformat() if profile.grade_locked_until else None,
        # уровень ниже доказан уверенно (P ≥ 0,8): кандидат может принять его одним действием, без нового теста
        "accept_lower_available": bool(can_lower and not accepted),
        "accept_lower_grade": can_lower if not accepted else None,
        "accept_lower_p": (round(sum(float(v) for g, v in (er.get("probabilities") or {}).items()
                                     if GRADE_LEVEL.get(g, 0) >= GRADE_LEVEL[can_lower]), 3) if can_lower and not accepted else None),
        "accepted_lower": accepted,
        # Кандидату — только ход теста; показатели детектора утечек видны в данных сессии, не в ответе
        "details": {k: details.get(k) for k in ("stop_reason", "n_scored", "n_canaries", "time_used_s",
                                                "extension", "pending_review", "n_families_in_bank", "mode")},
    }


def result(db: Session, ts: TestSession) -> dict:
    if ts.status != TestSessionStatus.finished:
        raise api_error(409, "test_not_finished", "Тест ещё не завершён")
    return _result_payload(db, ts, db.get(CandidateProfile, ts.user_id))


def accept_lower_grade(db: Session, ts: TestSession) -> dict:
    """Принять уровень ниже по уже пройденному тесту (видео организаторов №7): заявленный грейд не подтверждён,
    но P(θ ≥ порог уровня ниже) ≥ 0,8 — категория присваивается без нового теста. Только по действию кандидата."""
    if ts.status != TestSessionStatus.finished:
        raise api_error(409, "test_not_finished", "Тест ещё не завершён")
    er = ts.result.get("engine_result") or {}
    outcome = dict(ts.result.get("outcome") or {})
    if outcome.get("accepted_lower"):
        raise api_error(409, "already_accepted", "Уровень по этому тесту уже принят")
    profile = db.get(CandidateProfile, ts.user_id)
    current = profile.current_grade_id if profile.current_direction_id == ts.direction_id else None
    lower, why = accept_lower_allowed(current, ts.claimed_grade_id, bool(er.get("confirmed")), er.get("probabilities"))
    if lower is None:
        msg = {"confirmed": "Заявленный грейд подтверждён — принимать уровень ниже незачем",
               "no_lower_proved": "Тест не доказал уверенно ни один уровень ниже заявленного (нужно P ≥ 80 %)",
               "not_above_current": "Доказанный уровень не выше текущего подтверждённого грейда"}[why]
        raise api_error(409, "accept_lower_unavailable", msg)
    now = utcnow()
    sandbox = is_sandbox(profile)
    res = apply_result(current, lower, True, now, sandbox, get_settings().grade_change_interval_days,
                       profile.grade_locked_until)
    ts.result_grade_id = lower
    outcome.update({"changed": res.changed, "grade": res.new_grade, "accepted_lower": lower, "accepted_at": now.isoformat(),
                    "message": f"Принят уровень {lower.capitalize()} по результату теста на {ts.claimed_grade_id.capitalize()}: "
                               f"вероятность уровня не ниже {lower.capitalize()} — "
                               f"{round(100 * sum(v for g, v in (er.get('probabilities') or {}).items() if GRADE_LEVEL.get(g, 0) >= GRADE_LEVEL[lower]))} %."})
    ts.result = {**ts.result, "outcome": outcome}
    flag_modified(ts, "result")
    if res.changed:
        db.add(GradeHistory(user_id=ts.user_id, direction_id=ts.direction_id, from_grade_id=current,
                            to_grade_id=res.new_grade, reason=GradeChangeReason(res.reason),
                            test_session_id=ts.id, locked_until=res.locked_until))
        profile.current_direction_id = ts.direction_id
        profile.current_grade_id = res.new_grade
        profile.current_category_id = f"{ts.direction_id}.{res.new_grade}"
        profile.grade_locked_until = res.locked_until

        class _R:  # EngineResult-подобный объект для фактов T1
            pass

        r = _R()
        for k in ("theta", "se", "confirmed", "correct", "answered", "engine", "skills", "details"):
            setattr(r, k, er.get(k))
        r.skills = r.skills or {}
        r.details = r.details or {}
        _write_t1_facts(db, ts, r, grade=lower, accepted_lower=True)
        db.flush()
        refresh_rating(db, ts.user_id)
    db.commit()
    return _result_payload(db, ts, profile)


def _write_t1_facts(db: Session, ts: TestSession, res, grade: str | None = None, accepted_lower: bool = False) -> None:
    """Результат теста и навыки, проверенные заданиями, — факты T1 (заменяют прежние факты теста).
    grade — присвоенный грейд (по умолчанию заявленный; при принятии уровня ниже — он)."""
    db.execute(delete(CandidateFact).where(CandidateFact.user_id == ts.user_id, CandidateFact.source == FactSource.test))
    d = res.details or {}
    grade = grade or ts.claimed_grade_id
    db.add(CandidateFact(
        user_id=ts.user_id, kind="test_result", key=f"{ts.direction_id}.{grade}",
        title=f"Тест {ts.direction_id} · {grade}",
        value={"theta": res.theta, "se": res.se, "grade": grade, "confirmed": res.confirmed,
               "claimed_grade": ts.claimed_grade_id, "accepted_lower": accepted_lower,
               "mode": ts.result.get("mode", "full"),
               "correct": res.correct, "answered": res.answered, "engine": res.engine, "session_id": str(ts.id),
               "pending_review": d.get("pending_review"), "extension": bool(d.get("extension")),
               "preknowledge_flagged": (d.get("preknowledge") or {}).get("flagged"),
               "integrity": d.get("integrity")},
        evidence_level=EvidenceLevel.T1, source=FactSource.test, source_ref=f"test_session:{ts.id}",
    ))
    for tag, s in res.skills.items():
        db.add(CandidateFact(
            user_id=ts.user_id, kind="skill", key=tag, title=STACK.get(tag, (tag,))[0],
            value={"score": s["score"], "correct": s["correct"], "total": s["total"]},
            evidence_level=EvidenceLevel.T1, source=FactSource.test, source_ref=f"test_session:{ts.id}",
        ))


def status(db: Session, user_id: uuid.UUID) -> dict:
    from app.modules.catalog.models import Category

    profile = db.get(CandidateProfile, user_id)
    survey = latest_survey(db, user_id)
    now = utcnow()
    sandbox = is_sandbox(profile)
    lock = as_aware(profile.grade_locked_until)
    sessions = db.scalars(select(TestSession).where(TestSession.user_id == user_id)
                          .order_by(TestSession.created_at.desc()).limit(20)).all()
    history = db.scalars(select(GradeHistory).where(GradeHistory.user_id == user_id)
                         .order_by(GradeHistory.created_at.desc())).all()
    surveys = db.scalars(select(SurveyResponse).where(SurveyResponse.user_id == user_id)
                         .order_by(SurveyResponse.created_at.desc()).limit(10)).all()
    cat = db.get(Category, profile.current_category_id) if profile.current_category_id else None
    rank = total = None
    if cat is not None:
        peers = db.scalars(select(CandidateProfile.rating_score).where(
            CandidateProfile.current_category_id == cat.id, CandidateProfile.visible_to_employers.is_(True))).all()
        total = len(peers) + (0 if profile.visible_to_employers else 1)
        mine = profile.rating_score or 0
        rank = 1 + sum(1 for r in peers if (r or 0) > mine)
    active = active_session(db, user_id)
    user = db.get(User, user_id)
    st_ = get_settings()
    jury_allowed = bool(st_.jury_mode_available and user is not None and user.is_demo)
    failed = (recent_failed(db, user_id, survey.direction_id, now, st_.retake_same_grade_days)
              if survey is not None and not sandbox else {})
    r_locks = retake_locks(failed, now, st_.retake_same_grade_days)
    return {
        "onboarding_completed": profile.onboarding_completed_at is not None,
        "survey_direction": survey.direction_id if survey else None,
        "claimed_grade": survey.claimed_grade_id if survey else None,
        "current": {
            "direction": profile.current_direction_id, "grade": profile.current_grade_id,
            "category_id": profile.current_category_id, "category_title": cat.title if cat else None,
            "rating_score": profile.rating_score, "rank": rank, "category_size": total,
            "market_range": {"from": cat.market_salary_from, "to": cat.market_salary_to,
                             "median": cat.market_salary_median} if cat else None,
        },
        "locked_until": lock.isoformat() if lock else None,
        "lock_active": bool(lock and now < lock),
        "can_retest_now": not (lock and now < lock) or sandbox,
        "jury_mode": profile.jury_mode and jury_allowed, "jury_mode_available": get_settings().jury_mode_available,
        # демо-режим жюри доступен только демо-учёткам (вход жюри в один клик); живым кандидатам — нет
        "jury_mode_allowed": jury_allowed,
        "sandbox_active": sandbox,
        "sandbox_starts": sandbox_quota(db, user.email) if sandbox and user is not None else None,
        "grade_change_interval_days": st_.grade_change_interval_days,
        # неподтверждённая попытка: повтор на тот же грейд и выше — через retake_same_grade_days, ниже — сразу
        "retake_same_grade_days": st_.retake_same_grade_days,
        "retake_locks": {g: t.isoformat() for g, t in r_locks.items()},
        # экспресс-тест (5–7 заданий, ≈ 5 минут, интервал шире) — только в демо-режиме жюри
        "express_available": sandbox and get_engine().name.startswith("bank"),
        "express": {"min_items": st_.assessment_express_min_items, "max_items": st_.assessment_express_max_items},
        "active_session_id": str(active.id) if active else None,
        "active_grade": active.claimed_grade_id if active else None,
        "active_mode": (active.result or {}).get("mode", "full") if active else None,
        "engine": get_engine().name,
        "sessions": [{
            "id": str(s.id), "direction": s.direction_id, "claimed_grade": s.claimed_grade_id, "status": s.status.value,
            "theta": s.theta, "se": s.theta_se, "confirmed": (s.result or {}).get("engine_result", {}).get("confirmed"),
            "mode": (s.result or {}).get("mode", "full"),
            "accepted_lower": ((s.result or {}).get("outcome") or {}).get("accepted_lower"),
            "message": (s.result or {}).get("outcome", {}).get("message"), "is_sandbox": s.is_sandbox,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        } for s in sessions],
        "grade_history": [{
            "from": h.from_grade_id, "to": h.to_grade_id, "direction": h.direction_id, "reason": h.reason.value,
            "at": h.created_at.isoformat(), "locked_until": h.locked_until.isoformat() if h.locked_until else None,
        } for h in history],
        "surveys": [{"id": str(s.id), "direction": s.direction_id, "claimed_grade": s.claimed_grade_id,
                     "at": s.created_at.isoformat()} for s in surveys],
    }
