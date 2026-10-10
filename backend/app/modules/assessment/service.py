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
from app.modules.assessment import second_opinion as second_op
from app.modules.assessment.bank_engine import express_params
from app.modules.assessment.engine import get_engine
from app.modules.assessment.integrity import NOTICE_VERSION, candidate_view
from app.modules.assessment.models import (GradeHistory, SandboxTestStart, SurveyResponse, TaskFamily, TaskVariant,
                                           TestAnswer, TestSession, TestSessionItem)
from app.modules.auth.models import User
from app.modules.assessment.rules import (GRADE_LEVEL, GradeOutcome, accept_lower_allowed, apply_result,
                                          check_can_start, retake_locks)
from app.modules.catalog.seed_data import GRADES, tag_title
from app.modules.profiles.facts import refresh_rating
from app.modules.profiles.models import CandidateFact, CandidateProfile
from app.modules.profiles.models import CandidateSpecialization
from app.modules.profiles.specializations import ensure_specialization, summary, sync_primary


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


def latest_survey(db: Session, user_id: uuid.UUID, direction: str | None = None) -> SurveyResponse | None:
    if direction is None:
        direction = db.scalar(select(CandidateSpecialization.direction_id).where(
            CandidateSpecialization.user_id == user_id, CandidateSpecialization.is_primary.is_(True)))
    q = select(SurveyResponse).where(SurveyResponse.user_id == user_id)
    if direction:
        q = q.where(SurveyResponse.direction_id == direction)
    return db.scalar(q
                     .order_by(SurveyResponse.created_at.desc()).limit(1))


def active_session(db: Session, user_id: uuid.UUID, direction: str | None = None) -> TestSession | None:
    q = select(TestSession).where(
        TestSession.user_id == user_id,
        TestSession.status.in_([TestSessionStatus.created, TestSessionStatus.in_progress]),
    )
    if direction:
        q = q.where(TestSession.direction_id == direction)
    return db.scalar(q.order_by(TestSession.created_at.desc()).limit(1))


def _mode(ts: TestSession) -> str:
    """full | express (экспресс жюри, И2) | confirm (дотестирование «Junior (предварительно)», И1)."""
    r = ts.result or {}
    return r.get("mode") or (r.get("state") or {}).get("mode") or "full"


def recent_failed(db: Session, user_id: uuid.UUID, direction_id: str, now, retake_days: int) -> dict[str, datetime]:
    """Неподтверждённые завершённые попытки в направлении за последние retake_days дней: {грейд: время последней}.
    Исход «Junior (предварительно)» — не неудача (консилиум 07.10, 7.3а): категория присвоена, её подтверждают
    дотестированием; такие сессии не закрывают повтор."""
    since = now - timedelta(days=retake_days)
    rows = db.scalars(select(TestSession).where(
        TestSession.user_id == user_id, TestSession.direction_id == direction_id,
        TestSession.status == TestSessionStatus.finished, TestSession.finished_at >= since,
    ).order_by(TestSession.finished_at.desc())).all()
    out: dict[str, datetime] = {}
    for t in rows:
        er = (t.result or {}).get("engine_result") or {}
        if er.get("provisional"):
            continue
        if er.get("confirmed") is False and t.claimed_grade_id not in out:
            # принятый по этому тесту уровень ниже — не неудача на этом уровне, а присвоение; попытка на заявленный
            # грейд всё равно считается неподтверждённой
            out[t.claimed_grade_id] = as_aware(t.finished_at)
    return out


def seen_families(db: Session, user_id, direction: str | None = None) -> tuple[dict[str, int], dict[str, list[int]]]:
    """Семейства всех завершённых попыток кандидата (по направлению; None — по всем) с «возрастом»: 0 — последняя
    попытка, 1 — предпоследняя, … (для LRU), и их seed — чтобы повтор семейства шёл только с новым вариантом.
    Контрольные задания (канарейки) не входят: они опубликованы и идут отдельным пулом."""
    q = select(TestSession).where(TestSession.user_id == user_id, TestSession.status == TestSessionStatus.finished)
    if direction is not None:
        q = q.where(TestSession.direction_id == direction)
    seen: dict[str, int] = {}
    seeds: dict[str, list[int]] = {}
    for age, t in enumerate(db.scalars(q.order_by(TestSession.created_at.desc()))):
        st = (t.result or {}).get("state") or {}
        for it in (st.get("items") or []) + (st.get("prior") or []):
            f = it.get("family_id")
            if not f or it.get("canary"):
                continue
            seen.setdefault(f, age)
            if it.get("seed") is not None and int(it["seed"]) not in seeds.setdefault(f, []):
                seeds[f].append(int(it["seed"]))
    return seen, seeds


def start_session(db: Session, user_id: uuid.UUID, claimed_grade: str, engine_name: str | None = None, *,
                  integrity_ack: bool = False, enforce_sandbox_quota: bool = False,
                  direction: str | None = None, mode: str = "full") -> TestSession:
    """enforce_sandbox_quota — запрос кандидата через API (демо-сиды жюри проходят тест без лимита).

    direction — направление теста (основное или дополнительное, И14).
    mode: full — обычный адаптивный тест; express — экспресс-тест для жюри (только в демо-режиме, И2);
    confirm — короткое дотестирование у порога Junior для подтверждения «Junior (предварительно)» этого направления
    (provisional.py): ответы сессии, по которой стоит статус, переносятся, добавляется до 6 коротких заданий."""
    profile = db.get(CandidateProfile, user_id)
    survey = latest_survey(db, user_id, direction)
    if profile is None or survey is None or profile.onboarding_completed_at is None:
        raise api_error(409, "onboarding_required", "Сначала пройдите опрос: направление, стек и опыт")
    now = utcnow()
    st_ = get_settings()
    sandbox = is_sandbox(profile)
    specialization = ensure_specialization(db, profile, survey.direction_id)
    confirm_src = None
    if mode == "express" and not sandbox:
        raise api_error(409, "express_sandbox_only",
                        "Экспресс-тест доступен только в демо-режиме жюри: категорию живым кандидатам присваивает полный тест")
    if mode == "confirm":
        from app.modules.assessment import provisional

        opts = provisional.options(db, profile, specialization)
        if opts is None:
            raise api_error(409, "not_provisional", "Дотестирование нужно только для категории «Junior (предварительно)»")
        if not opts["can_confirm_test"]:
            raise api_error(409, "confirm_unavailable", opts["confirm_unavailable_reason"] or "Дотестирование недоступно")
        confirm_src = provisional.source_session(db, profile, specialization)
        claimed_grade = specialization.grade_id or "junior"
    old = active_session(db, user_id, survey.direction_id)
    # Продолжение уже начатого теста не расходует повтор/лимит.
    # Дотестирование — не новая попытка: правило 30 дней после неподтверждённой попытки на него не действует
    # (консилиум 07.10, 7.3а); число дотестирований ограничивает provisional.options.
    failed = (recent_failed(db, user_id, survey.direction_id, now, st_.retake_same_grade_days)
              if not sandbox and mode != "confirm" else None)
    check = check_can_start(specialization.grade_id, specialization.locked_until, claimed_grade, now, sandbox,
                            failed, st_.retake_same_grade_days)
    if not check.allowed:
        raise api_error(409 if check.code in ("grade_locked", "retake_cooldown") else 422,
                        check.code or "not_allowed", check.message or "")
    if (old is not None and old.claimed_grade_id == claimed_grade and old.direction_id == survey.direction_id
            and _mode(old) == mode):
        if integrity_ack and not (old.result or {}).get("integrity_ack"):
            old.result = {**old.result, "integrity_ack": {"at": now.isoformat(), "notice": NOTICE_VERSION}}
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
        seen, seen_seeds = seen_families(db, user_id)
        state = engine.start(direction=survey.direction_id, claimed_grade=claimed_grade, stack_tags=stack, seed=seed,
                             previous_families=fams, confirm_from=prev_state, seen=seen, seen_seeds=seen_seeds)
        state["confirm"]["source_session_id"] = str(confirm_src.id)
    elif engine.name.startswith("bank"):
        # Повторная попытка — другой субпул, чем в прошлых сессиях этого кандидата (параллельная форма);
        # семейства всех прошлых попыток по направлению не берутся ни в основную часть, ни в дотестирование
        # (И26; запасной путь при исчерпании — семейства, виденные давнее всего, с новым вариантом)
        past = [((t.result or {}).get("state") or {}) for t in db.scalars(
            select(TestSession).where(TestSession.user_id == user_id, TestSession.direction_id == survey.direction_id,
                                      TestSession.status == TestSessionStatus.finished)
            .order_by(TestSession.created_at.desc()).limit(5))]
        prev = [st.get("subpool") for st in past if st.get("subpool") is not None]
        last_families = [i.get("family_id") for i in (past[0].get("items") or []) if i.get("family_id")] if past else []
        seen, seen_seeds = seen_families(db, user_id, survey.direction_id)
        state = engine.start(direction=survey.direction_id, claimed_grade=claimed_grade, stack_tags=stack, seed=seed,
                             previous_subpools=prev, previous_families=last_families, mode=mode,
                             seen=seen, seen_seeds=seen_seeds)
    else:
        state = engine.start(direction=survey.direction_id, claimed_grade=claimed_grade, stack_tags=stack, seed=seed)
    # демо-режим жюри: быстрые верные ответы без других сигналов — мягкая пометка, не понижение достоверности (Ф3)
    state["sandbox"] = bool(sandbox)
    # Адаптивный тест банка: до 60 минут (лимит CATConfig) + запас на дотестирование у порога (не меньше 30 минут,
    # как раньше); экспресс — 20 минут (за Senior — длиннее, см. express_params); дотестирование — его лимит + запас;
    # заглушка — 30 минут
    if not engine.name.startswith("bank"):
        minutes = 30
    elif confirm_src is not None:
        minutes = st_.assessment_extension_minutes + 10
    elif mode == "express":
        minutes = express_params(st_, claimed_grade)["max_minutes"]
    else:
        minutes = st_.assessment_max_minutes + max(30, st_.assessment_extension_minutes + 10)
    ts = TestSession(
        user_id=user_id, survey_id=survey.id, direction_id=survey.direction_id, claimed_grade_id=claimed_grade,
        status=TestSessionStatus.in_progress, form_seed=seed, is_sandbox=sandbox, started_at=now,
        deadline_at=now + timedelta(minutes=minutes),
        result={"engine": engine.name, "state": state, "mode": mode,
                # согласие с проверкой самостоятельности до начала теста (текст — версия NOTICE_VERSION, Р27)
                "integrity_ack": {"at": now.isoformat(), "notice": NOTICE_VERSION} if integrity_ack else None},
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
    second_todo = []
    if _engine_key(ts) == "bank":
        _drain_outbox(db, ts)
        second_todo = second_op.take_new(state)  # И27: вторая оценка спорных ответов — в фоне, после commit
    flag_modified(ts, "result")
    db.commit()
    second_op.schedule(ts.id, second_todo)
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
    from app.modules.proctor.service import apply_to_result  # камера по согласию (И16): итог — в достоверность

    apply_to_result(db, ts, res.details)
    now = utcnow()
    ts.status = TestSessionStatus.finished
    ts.finished_at = now
    outcome = apply_engine_result(db, ts, res, profile, now)
    specialization = ensure_specialization(db, profile, ts.direction_id)
    result = {
        "changed": outcome.changed, "grade": outcome.new_grade,
        "session_id": str(ts.id), "theta": res.theta, "se": res.se, "claimed_grade": ts.claimed_grade_id,
        "point_grade": res.point_grade, "confirmed": res.confirmed, "upgrade_available": res.upgrade_available,
        "retake_lower": res.retake_lower, "probabilities": res.probabilities, "correct": res.correct,
        "answered": res.answered, "explanation": res.explanation, "grade_changed": outcome.changed,
        "direction": ts.direction_id, "current_grade": specialization.grade_id, "category_id": specialization.category_id,
        "is_primary": specialization.is_primary, "category_status": specialization.status,
        "message": outcome.message, "engine": res.engine,
        # «Junior (предварительно)»: итог теста и статус категории этого направления после него
        "provisional": res.provisional, "provisional_reason": res.provisional_reason, "p_claimed": res.p_claimed,
        "category_provisional": specialization.status == "provisional" and bool(specialization.category_id),
        "status_changed": outcome.status_changed, "mode": _mode(ts),
        "locked_until": as_aware(specialization.locked_until).isoformat() if specialization.locked_until else None,
        # уровень ниже доказан уверенно (P ≥ 0,8): кандидат может принять его одним действием, без нового теста (И2);
        # в демо-режиме жюри правило 30 дней не действует — фронт не обещает ожидание
        **_accept_lower_fields(ts, specialization, res.to_dict() if hasattr(res, "to_dict") else {}),
        "sandbox": is_sandbox(profile), "retake_same_grade_days": get_settings().retake_same_grade_days,
        # Кандидату — только ход теста; показатели детектора утечек и контрольные задания видны в данных сессии,
        # не в ответе. Достоверность — уровень и общая причина (Р27), подробности — работодателю
        "details": {k: res.details.get(k) for k in ("stop_reason", "n_scored", "time_used_s",
                                                     "extension", "pending_review", "n_families_in_bank", "mode")},
        "integrity": candidate_view((res.details or {}).get("integrity")),
    }
    second_todo = second_op.take_new(ts.result["state"]) if _engine_key(ts) == "bank" else []
    result["second_opinions"] = second_op.summary(ts.result["state"])  # И27: итог не ждёт вторую оценку
    _add_level_position(result, ts)
    ts.result = {**ts.result, "outcome": {**ts.result["outcome"], **result}}
    flag_modified(ts, "result")
    db.commit()
    second_op.schedule(ts.id, second_todo)
    return result


def _add_level_position(out: dict, ts: TestSession) -> None:
    """Я22 (флаг GRADE_POSITION_ENABLED): позиция внутри уровня, присвоенного этим тестом, — без чисел θ."""
    if not get_settings().grade_position_enabled:
        return
    from app.modules.assessment.grades import level_position

    er = (ts.result or {}).get("engine_result") or {}
    grade = ts.result_grade_id or ("junior" if er.get("provisional") else None)
    out["level_position"] = level_position(er.get("theta"), er.get("se"), grade)


def store_confirmed(db, profile, specialization, ts, res, outcome, current):
    """Единый путь записи категории направления из полного теста и экспертного пересчёта.
    outcome.provisional — категория «Junior (предварительно)» (статус специализации provisional, 90 дней не идут)."""
    if outcome.changed:
        db.add(GradeHistory(user_id=ts.user_id, direction_id=ts.direction_id, from_grade_id=current,
                            to_grade_id=outcome.new_grade, reason=GradeChangeReason(outcome.reason),
                            test_session_id=ts.id, locked_until=outcome.locked_until))
    specialization.grade_id = outcome.new_grade
    specialization.category_id = f"{ts.direction_id}.{outcome.new_grade}"
    specialization.status = "provisional" if outcome.provisional else "confirmed"
    specialization.theta, specialization.theta_se = res.theta, res.se
    specialization.test_session_id = ts.id
    specialization.confirmed_at = None if outcome.provisional else utcnow()
    specialization.locked_until = outcome.locked_until
    sync_primary(profile, specialization)


def apply_engine_result(db: Session, ts: TestSession, res, profile: CandidateProfile, now, *,
                        after_review: bool = False) -> GradeOutcome:
    """Итог движка → история грейда, специализация направления, факты T1, рейтинг (завершение теста и пересчёт
    после проверки). Правила применяются к специализации направления теста (И14), не к глобальному профилю.

    «Junior (предварительно)» (provisional.py): присвоение без 90 дней; подтверждение того же грейда — не смена
    грейда (причина confirmed, период 90 дней от даты попадания в категорию); любой следующий тест на Junior в том же
    направлении обновляет оценку в фактах (работодатель видит актуальную), но статус снимает только подтверждение.
    """
    from app.modules.assessment import provisional

    sandbox = is_sandbox(profile)
    specialization = ensure_specialization(db, profile, ts.direction_id)
    current = specialization.grade_id
    cur_prov = specialization.status == "provisional" and current is not None
    since_at = provisional.since(db, ts.user_id, ts.direction_id) if cur_prov else None
    outcome = apply_result(current, ts.claimed_grade_id, res.confirmed, now, sandbox,
                           get_settings().grade_change_interval_days, specialization.locked_until,
                           provisional=bool(getattr(res, "provisional", False)), current_provisional=cur_prov,
                           provisional_since=since_at)
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
        store_confirmed(db, profile, specialization, ts, res, outcome, current)
        write = True
        if outcome.provisional:
            extra = provisional.fact_extra(ts, res, since_at=now, attempts=0)
    elif outcome.status_changed:  # предварительный → подтверждён тем же тестом на Junior: не смена грейда
        by = "sandbox" if sandbox else ("extension" if mode == "confirm" else "test")
        provisional.mark_confirmed(db, profile, specialization, by=by, session_id=ts.id, sandbox=sandbox)
        specialization.theta, specialization.theta_se = res.theta, res.se
        specialization.test_session_id = ts.id
        specialization.confirmed_at = now
        sync_primary(profile, specialization)
        write = True
        extra = {"status": "confirmed", "confirmed_by": by, "confirmed_at": now.isoformat(),
                 "provisional_since": since_at.isoformat() if since_at else None}
    elif res.confirmed and outcome.new_grade == ts.claimed_grade_id:
        store_confirmed(db, profile, specialization, ts, res, outcome, current)  # повторное подтверждение: оценка обновлена
        write = True
    elif cur_prov and ts.claimed_grade_id == current:
        # тест на Junior (дотестирование или полный) не подтвердил: статус сохраняется, оценка — актуальная
        write = True
        extra = provisional.fact_extra(ts, res, since_at=since_at,
                                       attempts=provisional.confirm_attempts(db, ts.user_id, since_at, ts.direction_id),
                                       now=now)
    if write:
        _write_t1_facts(db, ts, res, extra)
        db.flush()
        refresh_rating(db, ts.user_id)
        # подписанный паспорт грейда (app/passport): выпуск или перевыпуск по актуальному составу (при понижении старый
        # отзывается; after_review — пересчёт той же сессии экспертом: «заменён после экспертной проверки»).
        # Сбой ключа или сборки состава не роняет тест.
        from app.passport.service import on_test_finished

        on_test_finished(db, ts.user_id, ts, previous_grade=current, previous_direction=ts.direction_id,
                         after_review=after_review)
    return outcome




def _accept_lower_fields(ts: TestSession, specialization, er: dict) -> dict:
    """Поля «принять уровень ниже» для итога теста (И2): доказанный уровень ниже заявленного (P ≥ 0,8), который выше
    текущего подтверждённого; у «Junior (предварительно)» доказанный Стажёр принимается (консилиум 07.10, 7.3в)."""
    current = specialization.grade_id if specialization is not None else None
    cur_prov = bool(specialization is not None and specialization.status == "provisional" and current)
    probs = er.get("probabilities") or {}
    can_lower, _ = accept_lower_allowed(current, ts.claimed_grade_id, bool(er.get("confirmed")), probs,
                                        provisional=cur_prov)
    accepted = ((ts.result or {}).get("outcome") or {}).get("accepted_lower")
    avail = bool(can_lower and not accepted)
    return {
        "accept_lower_available": avail,
        "accept_lower_grade": can_lower if avail else None,
        "accept_lower_p": (round(sum(float(v) for g, v in probs.items()
                                     if GRADE_LEVEL.get(g, -1) >= GRADE_LEVEL[can_lower]), 3) if avail else None),
        "accepted_lower": accepted,
    }


def result(db: Session, ts: TestSession) -> dict:
    """Итог завершённого теста для кандидата (повторные запросы): сохранённый итог + актуальные поля принятия уровня."""
    if ts.status != TestSessionStatus.finished:
        raise api_error(409, "test_not_finished", "Тест ещё не завершён")
    profile = db.get(CandidateProfile, ts.user_id)
    specialization = ensure_specialization(db, profile, ts.direction_id)
    er = ts.result.get("engine_result") or {}
    out = dict(ts.result.get("outcome") or {})
    out.update(_accept_lower_fields(ts, specialization, er))
    out["second_opinions"] = second_op.summary(ts.result.get("state") or {})  # И27: текущее состояние фона
    _add_level_position(out, ts)
    out.update({"current_grade": specialization.grade_id, "category_id": specialization.category_id,
                "category_status": specialization.status, "mode": _mode(ts),
                "sandbox": is_sandbox(profile), "retake_same_grade_days": get_settings().retake_same_grade_days,
                "locked_until": (as_aware(specialization.locked_until).isoformat()
                                 if specialization.locked_until else None)})
    return out


def accept_lower_grade(db: Session, ts: TestSession) -> dict:
    """Принять уровень ниже по уже пройденному тесту (видео организаторов №7): заявленный грейд не подтверждён,
    но P(θ ≥ порог уровня ниже) ≥ 0,8 — категория направления присваивается без нового теста. Только по действию
    кандидата. У «Junior (предварительно)» так принимается доказанный Стажёр (консилиум 07.10, 7.3в)."""
    from app.modules.assessment import provisional

    if ts.status != TestSessionStatus.finished:
        raise api_error(409, "test_not_finished", "Тест ещё не завершён")
    er = ts.result.get("engine_result") or {}
    outcome = dict(ts.result.get("outcome") or {})
    if outcome.get("accepted_lower"):
        raise api_error(409, "already_accepted", "Уровень по этому тесту уже принят")
    profile = db.get(CandidateProfile, ts.user_id)
    specialization = ensure_specialization(db, profile, ts.direction_id)
    current = specialization.grade_id
    cur_prov = bool(specialization.status == "provisional" and current)
    lower, why = accept_lower_allowed(current, ts.claimed_grade_id, bool(er.get("confirmed")), er.get("probabilities"),
                                      provisional=cur_prov)
    if lower is None:
        msg = {"confirmed": "Заявленный грейд подтверждён — принимать уровень ниже незачем",
               "no_lower_proved": "Тест не доказал уверенно ни один уровень ниже заявленного (нужно P ≥ 80 %)",
               "not_above_current": "Доказанный уровень не выше текущего подтверждённого грейда"}[why]
        raise api_error(409, "accept_lower_unavailable", msg)
    now = utcnow()
    sandbox = is_sandbox(profile)
    since_at = provisional.since(db, ts.user_id, ts.direction_id) if cur_prov else None
    res = apply_result(current, lower, True, now, sandbox, get_settings().grade_change_interval_days,
                       specialization.locked_until, current_provisional=cur_prov, provisional_since=since_at)
    ts.result_grade_id = lower
    p_lower = round(100 * sum(v for g, v in (er.get("probabilities") or {}).items()
                              if GRADE_LEVEL.get(g, -1) >= GRADE_LEVEL[lower]))
    outcome.update({"changed": res.changed, "grade": res.new_grade, "accepted_lower": lower, "accepted_at": now.isoformat(),
                    "grade_changed": res.changed, "category_provisional": False, "status_changed": res.status_changed,
                    "message": f"Принят уровень {GRADES.get(lower, lower)} по результату теста на "
                               f"{GRADES.get(ts.claimed_grade_id, ts.claimed_grade_id)}: вероятность уровня не ниже "
                               f"{GRADES.get(lower, lower)} — {p_lower} %."})
    ts.result = {**ts.result, "outcome": outcome}
    flag_modified(ts, "result")
    if res.changed:

        class _R:  # EngineResult-подобный объект для фактов T1 и специализации
            pass

        r = _R()
        for k in ("theta", "se", "confirmed", "correct", "answered", "engine", "skills", "details"):
            setattr(r, k, er.get(k))
        r.skills = r.skills or {}
        r.details = r.details or {}
        store_confirmed(db, profile, specialization, ts, r, res, current)
        _write_t1_facts(db, ts, r, grade=lower, accepted_lower=True)
        db.flush()
        refresh_rating(db, ts.user_id)
    db.commit()
    return result(db, ts)

def _write_t1_facts(db: Session, ts: TestSession, res, extra: dict | None = None, *, grade: str | None = None,
                    accepted_lower: bool = False) -> None:
    """Результат теста и навыки, проверенные заданиями, — факты T1 (заменяют прежние факты теста этого направления).
    extra — статус «Junior (предварительно)» / как подтверждён (provisional.fact_extra);
    grade — присвоенный грейд (по умолчанию заявленный; при принятии уровня ниже — он, И2)."""
    rows = db.scalars(select(CandidateFact).where(
        CandidateFact.user_id == ts.user_id, CandidateFact.source == FactSource.test)).all()
    past = {f"test_session:{s.id}": s.direction_id for s in db.scalars(
        select(TestSession).where(TestSession.user_id == ts.user_id))}
    profile = db.get(CandidateProfile, ts.user_id)
    for fact in rows:
        direction = fact.value.get("direction") or past.get(fact.source_ref) or (
            fact.key.split(".")[0] if fact.kind == "test_result" else profile.current_direction_id)
        if direction == ts.direction_id:
            db.delete(fact)
    d = res.details or {}
    grade = grade or ts.claimed_grade_id
    db.add(CandidateFact(
        user_id=ts.user_id, kind="test_result", key=f"{ts.direction_id}.{grade}",
        title=f"Тест {ts.direction_id} · {grade}",
        value={"direction": ts.direction_id, "theta": res.theta, "se": res.se, "grade": grade, "confirmed": res.confirmed,
               "claimed_grade": ts.claimed_grade_id, "accepted_lower": accepted_lower, "mode": _mode(ts),
               "correct": res.correct, "answered": res.answered, "engine": res.engine, "session_id": str(ts.id),
               "pending_review": d.get("pending_review"), "extension": bool(d.get("extension")),
               "preknowledge_flagged": (d.get("preknowledge") or {}).get("flagged"),
               "integrity": d.get("integrity"), **(extra or {})},
        evidence_level=EvidenceLevel.T1, source=FactSource.test, source_ref=f"test_session:{ts.id}",
    ))
    for tag, s in res.skills.items():
        db.add(CandidateFact(
            user_id=ts.user_id, kind="skill", key=tag, title=tag_title(tag),
            value={"direction": ts.direction_id, "score": s["score"], "correct": s["correct"], "total": s["total"]},
            evidence_level=EvidenceLevel.T1, source=FactSource.test, source_ref=f"test_session:{ts.id}",
        ))


def status(db: Session, user_id: uuid.UUID, direction: str | None = None) -> dict:
    from app.modules.assessment import provisional
    from app.modules.profiles.facts import grade_status
    from app.modules.catalog.models import Category

    profile = db.get(CandidateProfile, user_id)
    survey = latest_survey(db, user_id, direction)
    now = utcnow()
    sandbox = is_sandbox(profile)
    from app.modules.profiles.facts import load_bundles
    from app.modules.matching.ranking import visible_pool
    bundle = load_bundles(db, [user_id], direction=direction)[user_id]
    selected = direction or (survey.direction_id if survey else None) or bundle.direction
    specialization = bundle.specializations.get(selected)
    lock = as_aware(specialization.locked_until) if specialization else None
    sessions = db.scalars(select(TestSession).where(TestSession.user_id == user_id)
                          .order_by(TestSession.created_at.desc()).limit(20)).all()
    history = db.scalars(select(GradeHistory).where(GradeHistory.user_id == user_id)
                         .order_by(GradeHistory.created_at.desc())).all()
    surveys = db.scalars(select(SurveyResponse).where(SurveyResponse.user_id == user_id)
                         .order_by(SurveyResponse.created_at.desc()).limit(10)).all()
    cat_id = specialization.category_id if specialization else None
    cat = db.get(Category, cat_id) if cat_id else None
    rank = total = None
    if cat is not None:
        pool = visible_pool(db, category_ids=[cat.id])
        peers = [b.rating for b in load_bundles(db, [p.user_id for p in pool], category_ids=[cat.id]).values()]
        total = len(peers) + (0 if profile.visible_to_employers else 1)
        mine = specialization.rating_score or 0
        rank = 1 + sum(1 for r in peers if (r or 0) > mine)
    active = active_session(db, user_id, selected)
    user = db.get(User, user_id)
    st_ = get_settings()
    jury_allowed = bool(st_.jury_mode_available and user is not None and user.is_demo)
    is_prov = bool(specialization is not None and specialization.status == "provisional" and cat is not None)
    selected_bundle = bundle.for_direction(selected) if selected else bundle
    failed = (recent_failed(db, user_id, survey.direction_id, now, st_.retake_same_grade_days)
              if survey is not None and not sandbox else {})
    r_locks = retake_locks(failed, now, st_.retake_same_grade_days)
    return {
        "onboarding_completed": profile.onboarding_completed_at is not None,
        "survey_direction": survey.direction_id if survey else None,
        "claimed_grade": survey.claimed_grade_id if survey else None,
        "current": {
            "direction": selected, "grade": specialization.grade_id if specialization else None,
            "category_id": cat_id, "category_title": provisional.title(cat.title, is_prov) if cat else None,
            "provisional": is_prov,
            "rating_score": specialization.rating_score if specialization else None, "rank": rank, "category_size": total,
            "market_range": {"from": cat.market_salary_from, "to": cat.market_salary_to,
                             "median": cat.market_salary_median} if cat else None,
        },
        "specializations": [
            {**summary(r, bundle.tests_by_direction.get(r.direction_id)),
             "lock_active": bool(r.locked_until and now < as_aware(r.locked_until)),
             "can_retest_now": not (r.locked_until and now < as_aware(r.locked_until)) or sandbox,
             "grade_history": [{"from": h.from_grade_id, "to": h.to_grade_id, "reason": h.reason.value,
                                "at": h.created_at.isoformat()} for h in history if h.direction_id == r.direction_id],
             "active_session_id": str(a.id) if (a := active_session(db, user_id, r.direction_id)) else None,
             "active_grade": a.claimed_grade_id if a else None, "active_mode": _mode(a) if a else None}
            for r in sorted(bundle.specializations.values(), key=lambda r: (not r.is_primary, r.direction_id))],
        "selected_direction": selected,
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
        # экспресс-тест (5–7 заданий, ≈ 5 минут, интервал шире; за Senior — 8–12 заданий) — только в демо-режиме жюри;
        # min_items/max_items — для Junior/Middle (как раньше), by_grade — по каждому грейду
        "express_available": sandbox and get_engine().name.startswith("bank"),
        "express": {"min_items": st_.assessment_express_min_items, "max_items": st_.assessment_express_max_items,
                    "by_grade": {g: express_params(st_, g) for g in ("intern", "junior", "middle", "senior")}},
        "active_session_id": str(active.id) if active else None,
        "active_grade": active.claimed_grade_id if active else None,
        "active_mode": _mode(active) if active else None,
        # «Junior (предварительно)»: уровень доказанности и как подтвердить (provisional.options) — для направления
        "provisional": provisional.options(db, profile, specialization) if specialization is not None else None,
        # единая модель статуса грейда (та же, что видит работодатель): подтверждён / предварительно / не подтверждён
        "grade_status": grade_status(selected_bundle),
        "confirmed_by": provisional.confirmed_by(selected_bundle.test.value if selected_bundle.test else None),
        "engine": get_engine().name,
        "sessions": [{
            "id": str(s.id), "direction": s.direction_id, "claimed_grade": s.claimed_grade_id, "status": s.status.value,
            "theta": s.theta, "se": s.theta_se, "confirmed": (s.result or {}).get("engine_result", {}).get("confirmed"),
            "provisional": (s.result or {}).get("engine_result", {}).get("provisional"), "mode": _mode(s),
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
