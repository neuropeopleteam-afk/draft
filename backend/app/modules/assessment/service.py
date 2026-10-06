"""Сервис тестирования: хранение сессий, применение правил грейда, запись фактов T1.

С движком (заглушка или банк) общается только через протокол AssessmentEngine (engine.py).
"""
from __future__ import annotations

from datetime import timedelta
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
from app.modules.assessment.rules import GradeOutcome, apply_result, check_can_start
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


def _mode(ts: TestSession) -> str:
    return ((ts.result or {}).get("state") or {}).get("mode") or "full"


def start_session(db: Session, user_id: uuid.UUID, claimed_grade: str, engine_name: str | None = None, *,
                  integrity_ack: bool = False, enforce_sandbox_quota: bool = False, mode: str = "full") -> TestSession:
    """enforce_sandbox_quota — запрос кандидата через API (демо-сиды жюри проходят тест без лимита).

    mode="confirm" — короткое дотестирование у порога Junior для подтверждения «Junior (предварительно)»
    (provisional.py): ответы сессии, по которой стоит статус, переносятся, добавляется до 6 коротких заданий."""
    profile = db.get(CandidateProfile, user_id)
    survey = latest_survey(db, user_id)
    if profile is None or survey is None or profile.onboarding_completed_at is None:
        raise api_error(409, "onboarding_required", "Сначала пройдите опрос: направление, стек и опыт")
    now = utcnow()
    confirm_src = None
    if mode == "confirm":
        from app.modules.assessment import provisional

        opts = provisional.options(db, profile)
        if opts is None:
            raise api_error(409, "not_provisional", "Дотестирование нужно только для категории «Junior (предварительно)»")
        if profile.current_direction_id != survey.direction_id:
            raise api_error(409, "direction_changed", "Направление в опросе изменилось — пройдите тест на Junior заново")
        if not opts["can_confirm_test"]:
            raise api_error(409, "confirm_unavailable", opts["confirm_unavailable_reason"] or "Дотестирование недоступно")
        confirm_src = provisional.source_session(db, profile)
        claimed_grade = profile.current_grade_id or "junior"
    check = check_can_start(profile.current_grade_id, profile.grade_locked_until, claimed_grade, now,
                            is_sandbox(profile))
    if not check.allowed:
        raise api_error(409 if check.code == "grade_locked" else 422, check.code or "not_allowed", check.message or "")
    old = active_session(db, user_id)
    if (old is not None and old.claimed_grade_id == claimed_grade and old.direction_id == survey.direction_id
            and _mode(old) == mode):
        if integrity_ack and not (old.result or {}).get("integrity_ack"):
            old.result = {**old.result, "integrity_ack": {"at": now.isoformat()}}
            flag_modified(old, "result")
            db.commit()
        return old
    sandbox = is_sandbox(profile)
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
    engine = get_engine(engine_name or ("bank" if confirm_src is not None else None))
    seed = secrets.randbelow(2**31)
    stack = list((survey.answers or {}).get("stack", {}).keys())
    if confirm_src is not None:
        if not engine.name.startswith("bank"):
            raise api_error(409, "confirm_unavailable", "Дотестирование доступно только для теста банка заданий")
        prev_state = dict((confirm_src.result or {}).get("state") or {},
                          final_theta=confirm_src.theta, final_se=confirm_src.theta_se)
        past = [((t.result or {}).get("state") or {}) for t in db.scalars(
            select(TestSession).where(TestSession.user_id == user_id, TestSession.status == TestSessionStatus.finished)
            .order_by(TestSession.created_at.desc()).limit(5))]
        fams = sorted({i.get("family_id") for st in past for i in (st.get("items") or []) + (st.get("prior") or [])
                       if i.get("family_id")})
        state = engine.start(direction=survey.direction_id, claimed_grade=claimed_grade, stack_tags=stack, seed=seed,
                             previous_families=fams, confirm_from=prev_state)
        state["confirm"]["source_session_id"] = str(confirm_src.id)
    elif engine.name.startswith("bank"):
        # Повторная попытка — другой субпул, чем в прошлых сессиях этого кандидата (параллельная форма);
        # семейства последней попытки не попадают в дотестирование у порога (оно берёт задания и из другого субпула)
        past = [((t.result or {}).get("state") or {}) for t in db.scalars(
            select(TestSession).where(TestSession.user_id == user_id, TestSession.status == TestSessionStatus.finished)
            .order_by(TestSession.created_at.desc()).limit(5))]
        prev = [st.get("subpool") for st in past if st.get("subpool") is not None]
        last_families = [i.get("family_id") for i in (past[0].get("items") or []) if i.get("family_id")] if past else []
        state = engine.start(direction=survey.direction_id, claimed_grade=claimed_grade, stack_tags=stack, seed=seed,
                             previous_subpools=prev, previous_families=last_families)
    else:
        state = engine.start(direction=survey.direction_id, claimed_grade=claimed_grade, stack_tags=stack, seed=seed)
    # Адаптивный тест банка: до 60 минут (лимит CATConfig) + запас на дотестирование у порога (не меньше 30 минут,
    # как раньше); заглушка — 30 минут
    st_ = get_settings()
    minutes = (st_.assessment_max_minutes + max(30, st_.assessment_extension_minutes + 10)
               if engine.name.startswith("bank") else 30)
    if confirm_src is not None:  # только дотестирование: его лимит + запас
        minutes = st_.assessment_extension_minutes + 10
    ts = TestSession(
        user_id=user_id, survey_id=survey.id, direction_id=survey.direction_id, claimed_grade_id=claimed_grade,
        status=TestSessionStatus.in_progress, form_seed=seed, is_sandbox=sandbox, started_at=now,
        deadline_at=now + timedelta(minutes=minutes),
        result={"engine": engine.name, "state": state,
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
        if st.get("mode") == "confirm":  # дотестирование: только новые короткие задания
            return done, int(ext.get("n") or cfg.get("ext_items", 6)), bool(st.get("done"))
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
    ts.status = TestSessionStatus.finished
    ts.finished_at = now
    outcome = apply_engine_result(db, ts, res, profile, now)
    db.commit()
    return {
        "session_id": str(ts.id), "theta": res.theta, "se": res.se, "claimed_grade": ts.claimed_grade_id,
        "point_grade": res.point_grade, "confirmed": res.confirmed, "upgrade_available": res.upgrade_available,
        "retake_lower": res.retake_lower, "probabilities": res.probabilities, "correct": res.correct,
        "answered": res.answered, "explanation": res.explanation, "grade_changed": outcome.changed,
        "current_grade": profile.current_grade_id, "category_id": profile.current_category_id,
        "message": outcome.message, "engine": res.engine,
        # «Junior (предварительно)»: итог теста и статус профиля после него
        "provisional": res.provisional, "provisional_reason": res.provisional_reason, "p_claimed": res.p_claimed,
        "category_provisional": bool(profile.grade_provisional) and bool(profile.current_category_id),
        "status_changed": outcome.status_changed, "mode": _mode(ts),
        "locked_until": as_aware(profile.grade_locked_until).isoformat() if profile.grade_locked_until else None,
        # Кандидату — только ход теста; показатели детектора утечек видны в данных сессии, не в ответе
        "details": {k: res.details.get(k) for k in ("stop_reason", "n_scored", "n_canaries", "time_used_s",
                                                     "extension", "pending_review", "n_families_in_bank")},
    }


def apply_engine_result(db: Session, ts: TestSession, res, profile: CandidateProfile, now) -> GradeOutcome:
    """Итог движка → история грейда, профиль, факты T1, рейтинг (завершение теста и пересчёт после проверки).

    «Junior (предварительно)» (provisional.py): присвоение без 90 дней; подтверждение того же грейда — не смена
    грейда (причина confirmed, период 90 дней от даты попадания в категорию); любой следующий тест на Junior в том же
    направлении обновляет оценку в фактах (работодатель видит актуальную), но статус снимает только подтверждение.
    """
    from app.modules.assessment import provisional

    sandbox = is_sandbox(profile)
    same_dir = profile.current_direction_id == ts.direction_id
    # Тест в другом направлении: подтверждённый грейд считается «нет» для правил (категория — пара направление·грейд)
    current = profile.current_grade_id if same_dir else None
    cur_prov = bool(profile.grade_provisional) and current is not None
    elsewhere = (profile.current_category_id if profile.current_category_id and not same_dir
                 and not profile.grade_provisional else None)
    since_at = provisional.since(db, ts.user_id, ts.direction_id) if cur_prov else None
    outcome = apply_result(current, ts.claimed_grade_id, res.confirmed, now, sandbox,
                           get_settings().grade_change_interval_days, profile.grade_locked_until,
                           provisional=bool(getattr(res, "provisional", False)), current_provisional=cur_prov,
                           provisional_since=since_at, confirmed_elsewhere=elsewhere)
    mode = _mode(ts)
    ts.theta, ts.theta_se = res.theta, res.se
    ts.score = res.correct / res.answered if res.answered else 0.0
    ts.result_grade_id = ts.claimed_grade_id if res.confirmed else None
    ts.result = {**ts.result, "engine_result": res.to_dict(),
                 "outcome": {"changed": outcome.changed, "grade": outcome.new_grade, "message": outcome.message,
                             "provisional": outcome.provisional, "status_changed": outcome.status_changed}}
    flag_modified(ts, "result")
    write, extra = False, None
    if outcome.changed:
        db.add(GradeHistory(user_id=ts.user_id, direction_id=ts.direction_id, from_grade_id=current,
                            to_grade_id=outcome.new_grade, reason=GradeChangeReason(outcome.reason),
                            test_session_id=ts.id, locked_until=outcome.locked_until))
        profile.current_direction_id = ts.direction_id
        profile.current_grade_id = outcome.new_grade
        profile.current_category_id = f"{ts.direction_id}.{outcome.new_grade}"
        profile.grade_locked_until = outcome.locked_until
        profile.grade_provisional = outcome.provisional
        write = True
        if outcome.provisional:
            extra = provisional.fact_extra(ts, res, since_at=now, attempts=0)
    elif outcome.status_changed:  # предварительный → подтверждён тем же тестом на Junior: не смена грейда
        by = "sandbox" if sandbox else ("extension" if mode == "confirm" else "test")
        provisional.mark_confirmed(db, profile, by=by, session_id=ts.id, sandbox=sandbox)
        write = True
        extra = {"status": "confirmed", "confirmed_by": by, "confirmed_at": now.isoformat(),
                 "provisional_since": since_at.isoformat() if since_at else None}
    elif res.confirmed and outcome.new_grade == ts.claimed_grade_id:
        write = True
    elif cur_prov and ts.claimed_grade_id == current:
        # тест на Junior (дотестирование или полный) не подтвердил: статус сохраняется, оценка — актуальная
        write = True
        extra = provisional.fact_extra(ts, res, since_at=since_at,
                                       attempts=provisional.confirm_attempts(db, ts.user_id, since_at), now=now)
    if write:
        _write_t1_facts(db, ts, res, extra)
        db.flush()
        refresh_rating(db, ts.user_id)
    return outcome


def _write_t1_facts(db: Session, ts: TestSession, res, extra: dict | None = None) -> None:
    """Результат теста и навыки, проверенные заданиями, — факты T1 (заменяют прежние факты теста).
    extra — статус «Junior (предварительно)» / как подтверждён (provisional.fact_extra)."""
    db.execute(delete(CandidateFact).where(CandidateFact.user_id == ts.user_id, CandidateFact.source == FactSource.test))
    d = res.details or {}
    db.add(CandidateFact(
        user_id=ts.user_id, kind="test_result", key=f"{ts.direction_id}.{ts.claimed_grade_id}",
        title=f"Тест {ts.direction_id} · {ts.claimed_grade_id}",
        value={"theta": res.theta, "se": res.se, "grade": ts.claimed_grade_id, "confirmed": res.confirmed,
               "correct": res.correct, "answered": res.answered, "engine": res.engine, "session_id": str(ts.id),
               "pending_review": d.get("pending_review"), "extension": bool(d.get("extension")),
               "preknowledge_flagged": (d.get("preknowledge") or {}).get("flagged"),
               "integrity": d.get("integrity"), **(extra or {})},
        evidence_level=EvidenceLevel.T1, source=FactSource.test, source_ref=f"test_session:{ts.id}",
    ))
    for tag, s in res.skills.items():
        db.add(CandidateFact(
            user_id=ts.user_id, kind="skill", key=tag, title=STACK.get(tag, (tag,))[0],
            value={"score": s["score"], "correct": s["correct"], "total": s["total"]},
            evidence_level=EvidenceLevel.T1, source=FactSource.test, source_ref=f"test_session:{ts.id}",
        ))


def _confirmed_by(db: Session, user_id: uuid.UUID) -> dict | None:
    from app.modules.assessment import provisional

    f = db.scalar(select(CandidateFact).where(CandidateFact.user_id == user_id, CandidateFact.kind == "test_result",
                                              CandidateFact.source == FactSource.test)
                  .order_by(CandidateFact.created_at.desc()).limit(1))
    return provisional.confirmed_by(f.value if f else None)


def status(db: Session, user_id: uuid.UUID) -> dict:
    from app.modules.assessment import provisional
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
    jury_allowed = bool(get_settings().jury_mode_available and user is not None and user.is_demo)
    return {
        "onboarding_completed": profile.onboarding_completed_at is not None,
        "survey_direction": survey.direction_id if survey else None,
        "claimed_grade": survey.claimed_grade_id if survey else None,
        "current": {
            "direction": profile.current_direction_id, "grade": profile.current_grade_id,
            "category_id": profile.current_category_id,
            "category_title": provisional.title(cat.title, bool(profile.grade_provisional)) if cat else None,
            "provisional": bool(profile.grade_provisional) and cat is not None,
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
        "grade_change_interval_days": get_settings().grade_change_interval_days,
        "active_session_id": str(active.id) if active else None,
        "active_grade": active.claimed_grade_id if active else None,
        "active_mode": _mode(active) if active else None,
        # «Junior (предварительно)»: уровень доказанности и как подтвердить (provisional.options)
        "provisional": provisional.options(db, profile),
        "confirmed_by": _confirmed_by(db, user_id),
        "engine": get_engine().name,
        "sessions": [{
            "id": str(s.id), "direction": s.direction_id, "claimed_grade": s.claimed_grade_id, "status": s.status.value,
            "theta": s.theta, "se": s.theta_se, "confirmed": (s.result or {}).get("engine_result", {}).get("confirmed"),
            "provisional": (s.result or {}).get("engine_result", {}).get("provisional"), "mode": _mode(s),
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
