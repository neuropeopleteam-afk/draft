"""Демо-учётки для экспертов жюри: вход в один клик, исходное состояние, сброс.

Персоны (почты на зарезервированном домене example.com, RFC 2606 — письма туда не уходят; учётки is_demo):
* candidate — Мария Королёва, Backend · Middle: тест пройден НАСТОЯЩИМ движком банка заданий (адаптивная
  сессия, канарейки, детектор, сигналы интерфейса — как у живого кандидата; отвечает «демо-респондент» с
  заданным уровнем), паспорт ФСП из демо-реестра (T2); демо-режим жюри включён — правило 90 дней снято;
* candidate_nofsp — Илья Сергеев, Backend · Middle, тот же путь, но без истории ФСП (нейтральное состояние);
  один развёрнутый ответ оставлен «на проверке» — для экрана эксперта; есть входящее приглашение с вилкой;
* employer — HR компании «Демо жюри: Северный платёж»: профиль, три потребности текстом (третья — с
  дискриминационными фразами для показа фильтра ст. 64 ТК РФ), подборки с версиями;
* expert — эксперт (роль admin): очередь развёрнутых ответов, оценка по рубрике.

Сброс (POST /api/jury/reset) удаляет только эти учётки и компанию (каскадом — их сессии, подборки,
зонды, приглашения) и создаёт заново. Остальные демо-данные и учётки живых пользователей не затрагиваются.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
import logging
import time

import numpy as np
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.enums import FactSource, FspEventLevel, FspLinkSource, NeedStatus, UserRole, WorkFormat
from app.modules.assessment import service as assessment
from app.modules.assessment.bank_engine import BankEngine
from app.modules.assessment.models import SurveyResponse, SurveyStackTag
from app.modules.auth.models import User
from app.modules.fsp.models import FspAchievement, FspPassport
from app.modules.matching import ranking
from app.modules.matching.models import EmployerNeed, SelectionVersion
from app.modules.matching.need_parser import parse_need
from app.modules.profiles.facts import refresh_rating, set_t0_facts
from app.modules.profiles.models import CandidateProfile, Company, EmployerProfile
from app.modules.profiles.refs import new_public_ref

log = logging.getLogger("jury")
DOMAIN = "jury.example.com"
EMAILS = {"candidate": f"candidate@{DOMAIN}", "candidate_nofsp": f"candidate-nofsp@{DOMAIN}",
          "employer": f"employer@{DOMAIN}", "expert": f"expert@{DOMAIN}"}
COMPANY = "Демо жюри: Северный платёж"
PERSONAS = [
    {"id": "candidate", "role": "candidate", "title": "Кандидат с паспортом ФСП",
     "description": "Мария Королёва · Backend · Middle. Тест пройден, достижения ФСП (T2), есть место в рейтинге."},
    {"id": "candidate_nofsp", "role": "candidate", "title": "Кандидат без ФСП",
     "description": "Илья Сергеев · Backend · Middle. Истории ФСП нет — нейтрально. Ждёт входящее приглашение."},
    {"id": "employer", "role": "employer", "title": "Работодатель",
     "description": "«Северный платёж»: профиль компании, три потребности с цитатами и подборки с объяснениями, "
                    "сравнение кандидатов, фильтр ст. 64 ТК РФ."},
    {"id": "expert", "role": "expert", "title": "Эксперт",
     "description": "Проверка развёрнутых ответов по рубрике: очередь «на проверке» и выборочная проверка LLM."},
]
NEEDS = [
    "Backend-разработчик middle в команду платежей: обязательно Python, FastAPI и PostgreSQL, опыт с Redis. "
    "Будет плюсом Kafka и Docker. Удалённо. Зарплата 260 000 ₽ на руки.",
    "Frontend-разработчик middle для личного кабинета: React, TypeScript, HTML/CSS обязательно; "
    "желательно тестирование фронтенда. Гибрид, Санкт-Петербург, от 200 до 250 тыс.",
    # Демонстрация фильтра ст. 64 ТК РФ: фразы про пол, возраст, внешность и детей подсвечены, в требования
    # и в ранжирование не попадают, предложен текст через навыки
    "Python-разработчик middle в отдел интеграций: только мужчины до 35 лет, славянской внешности, без детей, "
    "в молодой коллектив. Нужны Python, Django и PostgreSQL, желательно Docker. Офис в Москве, 180–240 тыс.",
]
STACK = ["python", "fastapi", "postgresql", "redis", "docker", "sql", "git", "linux"]


class DemoRespondentEngine(BankEngine):
    """Движок банка, у которого развёрнутые ответы оценивает «демо-эксперт» (без LLM), а не модель.

    pending_left — сколько развёрнутых ответов оставить «на проверке» (для экрана эксперта).
    """

    def __init__(self, rng: np.random.Generator, theta: float, pending_left: int = 0):
        super().__init__()
        self.rng, self.theta, self.pending_left = rng, theta, pending_left
        self._pending_tokens: set[str] = set()

    def _grade_text(self, it: dict, part: int, text_: str, step_prompt: str | None) -> None:
        if it["token"] in self._pending_tokens or self.pending_left > 0:
            if it["token"] not in self._pending_tokens:
                self.pending_left -= 1
                self._pending_tokens.add(it["token"])
            it["grading"][part] = {"status": "pending", "method": "none", "error": "демо: оставлено эксперту"}
            it["x"][part] = None
            return
        b = float(np.mean(it["pool"]["b"]))
        score = float(np.clip(0.55 + 0.35 * (self.theta - b) + self.rng.normal(0, 0.1), 0.2, 1.0))
        it["grading"][part] = {"status": "scored", "method": "demo_expert", "score": round(score, 2),
                               "comment": "демо: оценка по эталонам рубрики"}
        it["x"][part] = round(score, 2)


def _answer_for(it: dict, step: int, correct: bool, rng: np.random.Generator):
    key = it["key"]
    fmt = it["format"]
    if fmt == "open_book_3step":
        if step == 3:
            rub = it.get("rubric") or {}
            return rub.get("strong" if correct else "medium") or "Объяснение причины дефекта и последствий изменения."
        right = (key.get("value") or {}).get(str(step))
        opts = [o["id"] for o in it["public"]["options"] or [] if o.get("step") == step]
    elif fmt in ("choose_fix", "mcq_concept"):
        right, opts = key["value"], [o["id"] for o in it["public"]["options"] or []]
    elif fmt == "find_bug":
        right, opts = int(key["value"]), list(range(1, max(2, it["public"]["code_lines"]) + 1))
    elif fmt == "predict_output":
        return str(key["value"]) if correct else "не знаю"
    else:  # open_answer
        rub = it.get("rubric") or {}
        return rub.get("strong" if correct else "medium") or "Развёрнутый ответ по существу вопроса."
    if correct or len(opts) < 2:
        return right
    wrong = [o for o in opts if o != right]
    return wrong[int(rng.integers(len(wrong)))]


def _p_correct(it: dict, theta: float, part: int) -> float:
    a = np.asarray(it["pool"]["a"], dtype=float)
    b = np.asarray(it["pool"]["b"], dtype=float)
    k = min(part, len(b) - 1)
    return float(1 / (1 + np.exp(-1.7 * a[k] * (theta - b[k]))))


def run_demo_test(db: Session, user_id, claimed: str, theta: float, seed: int, pending_left: int = 0,
                  away_items: tuple[int, ...] = ()) -> dict:
    """Проходит тест движком банка за «демо-респондента»: ответы по модели 2PL на уровне theta, время —
    обычное (40–90 % рекомендуемого), сигналы интерфейса без нарушений, кроме away_items — позиций, где
    «кандидат» уходил со вкладки (для демонстрации «достоверности результата»). Возвращает итог finish_session."""
    rng = np.random.default_rng(seed)
    eng = DemoRespondentEngine(rng, theta, pending_left)
    ts = assessment.start_session(db, user_id, claimed, engine_name="bank")
    st = ts.result["state"]
    for _ in range(60):
        item = eng.next_item(st)
        if item is None:
            break
        it = eng._current(st)
        it["issued_at"] = time.time() - float(rng.uniform(0.4, 0.9)) * it["time_limit_s"]
        away = it["position"] in away_items
        for step in range(1, it["parts"] + 1):
            ok = rng.random() < _p_correct(it, theta, step - 1)
            eng.answer(st, it["token"], _answer_for(it, step, ok, rng), None, step=step,
                       signals={"focus_lost": 1 if away and step == 1 else 0, "hidden_ms": 25_000 if away and step == 1 else 0,
                                "paste": 0, "paste_chars": 0})
    assessment._drain_outbox(db, ts)
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(ts, "result")
    db.commit()
    return assessment.finish_session(db, ts, engine=eng)


def _user(db: Session, persona: str, role: UserRole) -> User:
    from app.modules.demo.seed import _user as demo_user
    from app.core.security import hash_password
    import secrets

    return demo_user(db, EMAILS[persona], role, hash_password(secrets.token_urlsafe(24)))


def _candidate(db: Session, persona: str, name: str, with_fsp: bool, theta: float, seed: int, pending_left: int,
               away_items: tuple[int, ...] = ()):
    u = _user(db, persona, UserRole.candidate)
    p = CandidateProfile(user_id=u.id, full_name=name, phone="+7 900 000-00-00", telegram=f"@jury_{persona}",
                         city="Москва", work_format=WorkFormat.remote, relocation=False, experience_years=3.5,
                         salary_min_hidden=200_000, privacy={}, visible_to_employers=True,
                         public_ref=new_public_ref(db), onboarding_completed_at=utcnow(),
                         roles=["developer"], headline="backend · middle (демо жюри)", jury_mode=True)
    db.add(p)
    db.flush()
    sv = SurveyResponse(user_id=u.id, direction_id="backend", claimed_grade_id="middle", experience_years=3.5,
                        answers={"stack": {t: 3 for t in STACK}, "roles": ["developer"], "demo": True, "jury": True})
    db.add(sv)
    db.flush()
    for t in STACK:
        db.add(SurveyStackTag(survey_id=sv.id, stack_tag_id=t, self_level=3))
    set_t0_facts(db, u.id, FactSource.self_report, stack=STACK, roles=["developer"],
                 soft_skills=["communication", "teamwork"], experience_years=3.5)
    if with_fsp:
        pp = FspPassport(user_id=u.id, link_source=FspLinkSource.demo, synced_at=utcnow(), sport_rank="КМС",
                         raw={"demo": True, "jury": True, "note": "демо-реестр хакатона"})
        db.add(pp)
        db.flush()
        db.add(FspAchievement(passport_id=pp.id, discipline="product", event_level=FspEventLevel.national,
                              event_name="Чемпионат России по продуктовому программированию", event_date=date(2025, 11, 20),
                              place=2, result_title="призёр", team_name="Команда «Северный ветер» (демо)",
                              role_in_team="backend", verified=True, source_ref="demo-registry"))
        db.add(FspAchievement(passport_id=pp.id, discipline="algorithmic", event_level=FspEventLevel.interregional,
                              event_name="Кубок России по спортивному программированию", event_date=date(2026, 4, 12),
                              place=7, result_title="финалист", team_name="Команда «Северный ветер» (демо)",
                              verified=True, source_ref="demo-registry"))
    db.commit()
    res = {}
    for attempt in range(6):  # демо-респондент случаен: нужен подтверждённый грейд — иначе следующий seed
        res = run_demo_test(db, u.id, "middle", theta, seed + attempt, pending_left, away_items)
        if res.get("confirmed") or res.get("category_id"):
            break
    refresh_rating(db, u.id)
    db.commit()
    return u, p, res


def delete_jury(db: Session) -> int:
    from app.integrations.ats.models import AtsSettings, AtsStubRecord

    ids = db.scalars(select(User.id).where(User.email.in_(list(EMAILS.values())))).all()
    keys = db.scalars(select(AtsSettings.stub_key).join(Company, Company.id == AtsSettings.company_id)
                      .where(Company.name == COMPANY, Company.is_demo.is_(True), AtsSettings.stub_key.is_not(None))).all()
    if keys:  # «входящие» демо-ATS прежней демо-компании
        db.execute(delete(AtsStubRecord).where(AtsStubRecord.stub_key.in_(list(keys))))
    db.execute(delete(Company).where(Company.name == COMPANY, Company.is_demo.is_(True)))
    if ids:
        db.execute(delete(User).where(User.id.in_(ids)))
    db.commit()
    return len(ids)


def _connect_demo_ats(db: Session, company_id) -> None:
    """Демо-ATS у компании жюри: Хантфлоу, Talantix, «Поток» и вебхук на заглушках — принятие приглашения Ильёй
    сразу видно в журнале передач. Сбой интеграций не должен ломать сид жюри."""
    try:
        from app.integrations.ats.demo import connect_demo_all

        connect_demo_all(db, company_id)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("jury: demo ATS connect failed")


def create_jury(db: Session) -> dict:
    t0 = time.time()
    _, p1, r1 = _candidate(db, "candidate", "Мария Королёва", True, 1.05, 3101, 0)
    # у Ильи — два ухода со вкладки во время теста: достоверность «средняя» (видно работодателю с причиной)
    u2, p2, r2 = _candidate(db, "candidate_nofsp", "Илья Сергеев", False, 0.95, 4201, 1, away_items=(4, 8))
    eu = _user(db, "employer", UserRole.employer)
    c = Company(name=COMPANY, industry="Финансовые технологии", city="Санкт-Петербург", website="https://example.invalid",
                description="Платёжный сервис для малого бизнеса. Демо-компания для экспертов жюри.",
                contact_email=f"hr@{DOMAIN}", created_by=eu.id, is_demo=True)
    db.add(c)
    db.flush()
    db.add(EmployerProfile(user_id=eu.id, company_id=c.id, full_name="Ольга Миронова", position="HR-партнёр (демо)"))
    db.commit()
    _connect_demo_ats(db, c.id)
    needs = []
    for text_ in NEEDS:
        req = parse_need(text_, use_llm=False)
        n = EmployerNeed(company_id=c.id, created_by=eu.id, title=text_.split(":")[0][:200], raw_text=text_,
                         requirements=req, direction_id=req.get("direction"), grade_id=req.get("grade"),
                         salary_from=req.get("salary_from"), salary_to=req.get("salary_to"), status=NeedStatus.active)
        db.add(n)
        db.flush()
        sel = ranking.build_selection(db, req, {})
        db.add(SelectionVersion(need_id=n.id, version=1, parent_version=None, filters={}, requirements=req,
                                results=sel["results"], algorithm_version=sel["algorithm"], created_by=eu.id))
        needs.append(n)
    db.commit()
    from app.modules.invitations.service import create_invitation

    create_invitation(db, eu, c, p2, position_title="Backend-разработчик (платежи)",
                      offer_description="Команда платежей: FastAPI, PostgreSQL, Redis. Удалённо, гибкий график.",
                      salary_from=240_000, salary_to=270_000, contact_method="Почта HR и звонок 20 минут",
                      need_id=needs[0].id, probe_id=None)
    ex = _user(db, "expert", UserRole.expert)  # не admin: только /api/expert/*, только демо-кандидаты
    db.commit()
    return {"candidate": {"ref": p1.public_ref, "confirmed": r1.get("confirmed"), "theta": r1.get("theta")},
            "candidate_nofsp": {"ref": p2.public_ref, "confirmed": r2.get("confirmed"), "theta": r2.get("theta"),
                                "pending": (r2.get("details") or {}).get("pending_review")},
            "employer": {"company": c.name, "needs": len(needs)}, "expert": {"email": ex.email},
            "seconds": round(time.time() - t0, 1)}


@contextmanager
def _lock(db: Session):
    """Сброс и создание демо жюри — по очереди между воркерами uvicorn (advisory lock PostgreSQL на отдельном
    соединении: сессия внутри несколько раз фиксирует транзакции и может сменить соединение)."""
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        yield
        return
    with bind.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(20261006)"))
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(20261006)"))
            conn.commit()


def _complete(db: Session) -> bool:
    have = set(db.scalars(select(User.email).where(User.email.in_(list(EMAILS.values())))).all())
    db.commit()
    return have == set(EMAILS.values())


def reset(db: Session) -> dict:
    with _lock(db):
        n = delete_jury(db)
        out = create_jury(db)
    out["deleted_users"] = n
    log.info("Демо жюри пересоздано: %s", out)
    return out


def ensure(db: Session) -> bool:
    """Создаёт учётки жюри, если их нет (первый вход после выкладки). True — созданы сейчас."""
    if _complete(db):
        return False
    with _lock(db):
        if _complete(db):  # другой воркер уже создал, пока мы ждали
            return False
        delete_jury(db)
        create_jury(db)
    return True
