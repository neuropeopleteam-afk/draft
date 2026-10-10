"""Демо-учётки для экспертов жюри: вход в один клик, исходное состояние, сброс.

Персоны (почты на зарезервированном домене example.com, RFC 2606 — письма туда не уходят; учётки is_demo):
* candidate — Мария Королёва, Backend · Middle: тест пройден НАСТОЯЩИМ движком банка заданий (адаптивная
  сессия, канарейки, детектор, сигналы интерфейса — как у живого кандидата; отвечает «демо-респондент» с
  заданным уровнем), паспорт ФСП из демо-реестра (T2); демо-режим жюри включён — правило 90 дней снято;
* candidate_nofsp — Илья Сергеев, Backend · Middle, тот же путь, но без истории ФСП (нейтральное состояние);
  один развёрнутый ответ оставлен «на проверке» — для экрана эксперта; есть входящее приглашение с вилкой;
* employer — HR компании «Демо жюри: Северный платёж»: профиль, четыре потребности текстом (третья — с
  дискриминационными фразами для показа фильтра ст. 64 ТК РФ), подборки с версиями;
* expert — эксперт (роль admin): очередь развёрнутых ответов, оценка по рубрике;
* fsp — аналитик ФСП (роль fsp_analyst): Кабинет ФСП — обезличенная аналитика платформы (общая, без копий жюри).

У работодателя каждой копии — два своих кубка (app.cup.demo.seed_jury_cups): завершённый, где Мария этой копии на
2-м месте (запись в паспорте ФСП; приглашение — только победителю, Марию работодатель приглашает в сценарии сам),
и кубок с двумя решениями на оценке. У Марии на старте — приглашение от второй компании песочницы (COMPANY2) и
общие демо-вакансии платформы (_maria_extras). Общее демо кубков
и Кабинета ФСП (кубки демо-компаний, история приглашений) — одно на платформу: ensure_ideas.

Песочницы (scope.py): у каждого эксперта жюри свой набор этих персон (почты ``candidate+<sid>@…``), чтобы жюри
не мешали друг другу. Сброс (POST /api/jury/reset) удаляет только учётки, компанию и кубки СВОЕЙ песочницы
(каскадом — их сессии, подборки, зонды, приглашения) и создаёт заново. Другие песочницы, остальные демо-данные и учётки живых
пользователей не затрагиваются.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from datetime import date, timedelta
import logging
import time

import numpy as np
from sqlalchemy import and_, delete, false, or_, select, text, update
from sqlalchemy.orm import Session

from app.core.db import as_aware, utcnow
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
from app.modules.jury import scope

log = logging.getLogger("jury")
DOMAIN = scope.DOMAIN
EMAILS = scope.emails("")  # общее демо; песочница — scope.emails(sid)
COMPANY = "Демо жюри: Северный платёж"
COMPANY2 = "Демо жюри: Логистика Онлайн"  # второй работодатель песочницы: приглашение Марии на старте (fx01)
COMPANY3 = "Демо жюри: Быстрый заработок"  # «плохой» работодатель (Ф4): низкий индекс доверия, неправдоподобная вилка
PERSONAS = [
    {"id": "candidate", "role": "candidate", "title": "Кандидат с паспортом ФСП",
     "description": "Мария Королёва · Backend · Middle и Frontend · Junior. Два отдельных теста, достижения ФСП (T2)."},
    {"id": "candidate_nofsp", "role": "candidate", "title": "Кандидат без ФСП",
     "description": "Илья Сергеев · Backend · Middle. Истории ФСП нет — нейтрально. Ждёт входящее приглашение."},
    {"id": "candidate_junior", "role": "candidate", "title": "Кандидат «Junior (предварительно)»",
     "description": "Артём Лебедев · Backend · Junior (предварительно). Тест у порога Junior: грейд не подтверждён, но и "
                    "не доказанно ниже — вероятность уровня, короткое дотестирование у порога, статус у работодателя."},
    {"id": "candidate_new", "role": "candidate", "title": "Пройдите тест сами",
     "description": "Антон Лебедев · Backend · категории нет. Опрос и резюме есть, теста нет: экспресс-тест ≈ 5 минут "
                    "или полный, подсказка грейда, путь до категории и подборки."},
    {"id": "employer", "role": "employer", "title": "Работодатель",
     "description": "«Северный платёж»: профиль компании, четыре потребности с цитатами и подборки с объяснениями, "
                    "сравнение кандидатов, фильтр ст. 64 ТК РФ."},
    {"id": "expert", "role": "expert", "title": "Эксперт",
     "description": "Проверка развёрнутых ответов по рубрике: очередь «на проверке» и выборочная проверка LLM."},
    {"id": "fsp", "role": "fsp_analyst", "title": "Федерация (ФСП)",
     "description": "Кабинет ФСП: спрос работодателей, эффект соревнований ФСП, зарплаты из офферов, кубки и воронки."},
]
NEEDS = [
    "Backend-разработчик middle в команду платежей: обязательно Python, FastAPI и PostgreSQL, опыт с Redis. "
    "Будет плюсом Kafka и Docker. Удалённо. Зарплата 260 000 ₽ на руки.",
    "Frontend-разработчик middle для личного кабинета: React, TypeScript, HTML/CSS обязательно; "
    "желательно тестирование фронтенда. Гибрид, Санкт-Петербург, от 200 до 250 тыс.",
    # Демонстрация фильтра ст. 64 ТК РФ: фразы про пол, возраст, внешность и детей подсвечены, в требования
    # и в ранжирование не попадают, предложен текст через навыки. «Офис в Москве или удалённо»: условия потребности
    # применяются сразу (Ф2) — персоны песочницы (удалённо, Москва) должны проходить условия своих демо-потребностей
    "Python-разработчик middle в отдел интеграций: только мужчины до 35 лет, славянской внешности, без детей, "
    "в молодой коллектив. Нужны Python, Django и PostgreSQL, желательно Docker. Офис в Москве или удалённо, 180–240 тыс.",
    # И18: подборка мала — «Что если» показывает, какое требование отсекает больше всего подтверждённых
    "Backend-разработчик senior для платёжного шлюза: обязательно PostgreSQL, Kafka и Linux. Удалённо, от 350 тыс. ₽.",
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
                  away_items: tuple[int, ...] = (), copy_items: tuple[int, ...] = (), *,
                  direction: str | None = None, camera: bool = False) -> dict:
    """Проходит тест движком банка за «демо-респондента»: ответы по модели 2PL на уровне theta, время —
    обычное (40–90 % рекомендуемого), сигналы интерфейса без нарушений, кроме away_items — позиций, где
    «кандидат» уходил со вкладки (для демонстрации «достоверности результата»). Возвращает итог finish_session."""
    rng = np.random.default_rng(seed)
    eng = DemoRespondentEngine(rng, theta, pending_left)
    ts = assessment.start_session(db, user_id, claimed, engine_name="bank", direction=direction)
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
                                "paste": 0, "paste_chars": 0,
                                # лёгкий прокторинг (И9): тест во весь экран; copy_items — попытка скопировать задание
                                "copy": 1 if it["position"] in copy_items and step == 1 else 0,
                                "fs_ms": 60_000, "fs_out_ms": 0, "fs_exit": 0, "fs_na": 0})
            if step < it["parts"] and str(step) in it["answers"]:  # шаги тоже занимают время (часы сервера)
                it["answers"][str(step)]["at"] = it["issued_at"] + (time.time() - it["issued_at"]) * step / it["parts"]
    assessment._drain_outbox(db, ts)
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(ts, "result")
    db.commit()
    from app.modules.proctor.service import seed_demo  # камера по согласию (И16): с камерой без замечаний / без камеры

    seed_demo(db, ts, camera)
    return assessment.finish_session(db, ts, engine=eng)


def _user(db: Session, persona: str, role: UserRole, sid: str = "") -> User:
    from app.modules.demo.seed import _user as demo_user
    from app.core.security import hash_password
    import secrets

    u = demo_user(db, scope.emails(sid)[persona], role, hash_password(secrets.token_urlsafe(24)))
    if sid and not _SPARE.get():
        # песочница уже чья-то (вход, сброс, пересоздание): отметка входа — сразу при создании, чтобы её
        # не выдали другому эксперту как запасную ни на миг
        u.last_login_at = utcnow()
    return u


def _candidate(db: Session, persona: str, name: str, with_fsp: bool, theta: float, seed: int, pending_left: int,
               away_items: tuple[int, ...] = (), sid: str = "", claimed: str = "middle", experience: float = 3.5,
               salary: int = 200_000, want: str = "category", copy_items: tuple[int, ...] = (), camera: bool = False):
    """Демо-кандидат жюри. want — какой исход теста нужен: category — любая категория (подтверждённая или
    предварительная), provisional — «Junior (предварительно)»; демо-респондент случаен, поэтому до 6 попыток
    с разными seed, затем остаётся последний исход. copy_items — позиции заданий с попыткой копирования (И9);
    camera — тест с камерой по согласию (И16)."""
    u = _user(db, persona, UserRole.candidate, sid)
    stack = STACK if claimed != "junior" else STACK[:5]
    level = 3 if claimed != "junior" else 2
    p = CandidateProfile(user_id=u.id, full_name=name, phone="+7 900 000-00-00", telegram=f"@jury_{persona}",
                         city="Москва", work_format=WorkFormat.remote, relocation=False, experience_years=experience,
                         salary_min_hidden=salary, privacy={}, visible_to_employers=True,
                         public_ref=new_public_ref(db), onboarding_completed_at=utcnow(),
                         roles=["developer"], headline=f"backend · {claimed} (демо жюри)", jury_mode=True)
    db.add(p)
    db.flush()
    sv = SurveyResponse(user_id=u.id, direction_id="backend", claimed_grade_id=claimed, experience_years=experience,
                        answers={"stack": {t: level for t in stack}, "roles": ["developer"], "demo": True, "jury": True})
    db.add(sv)
    db.flush()
    for t in stack:
        db.add(SurveyStackTag(survey_id=sv.id, stack_tag_id=t, self_level=level))
    set_t0_facts(db, u.id, FactSource.self_report, stack=stack, roles=["developer"],
                 soft_skills=["communication", "teamwork"], experience_years=experience)
    if with_fsp:
        pp = FspPassport(user_id=u.id, link_source=FspLinkSource.demo, synced_at=utcnow(), sport_rank="КМС",
                         raw={"demo": True, "jury": True, "fsp_id": "FSP-770012", "note": "демо-реестр хакатона"})
        p.fsp_id_claimed = "FSP-770012"
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
    for attempt in range(6):  # демо-респондент случаен: нужен заданный исход — иначе следующий seed
        res = run_demo_test(db, u.id, claimed, theta, seed + attempt, pending_left, away_items, copy_items,
                            camera=camera)
        if want == "provisional" and res.get("category_provisional"):
            break
        if want == "category" and (res.get("confirmed") or res.get("category_id")):
            break
    refresh_rating(db, u.id)
    db.commit()
    return u, p, res


NEW_STACK = ["python", "fastapi", "postgresql", "sql", "git"]
# Текст резюме персоны «Пройдите тест сами» — без ФИО и контактов (их вырезал бы загрузчик), только опыт и стек
NEW_RESUME = (
    "Backend-разработчик. Опыт коммерческой разработки 2 года.\n"
    "2024 — настоящее время: разработчик, сервис онлайн-записи. Python, FastAPI, PostgreSQL, SQL, Git. "
    "Писал REST API, миграции, покрывал код тестами, участвовал в код-ревью.\n"
    "2023–2024: стажёр-разработчик, интернет-магазин. Python, Django, PostgreSQL.\n"
    "Образование: бакалавр прикладной информатики. Участник регионального этапа чемпионата по программированию."
)


def _candidate_new(db: Session, sid: str = ""):
    """Персона «Пройдите тест сами» (видео организаторов №5, №52): опрос пройден, резюме загружено, небольшой паспорт
    ФСП (участие, без призовых мест), ТЕСТА НЕТ — эксперт жюри сам проходит экспресс- или полный тест, видит подсказку
    грейда и путь до категории и подборки. Лёгкая: без прогона теста движком."""
    from app.modules.profiles.models import CandidateResume
    from app.modules.resume.extract import extract_rules

    u = _user(db, "candidate_new", UserRole.candidate, sid)
    p = CandidateProfile(user_id=u.id, full_name="Антон Лебедев", phone="+7 900 000-00-01", telegram="@jury_candidate_new",
                         city="Нижний Новгород", work_format=WorkFormat.remote, relocation=False, experience_years=2.0,
                         salary_min_hidden=150_000, privacy={}, visible_to_employers=True,
                         public_ref=new_public_ref(db), onboarding_completed_at=utcnow(),
                         roles=["developer"], headline="backend · без категории (демо жюри)", jury_mode=True)
    db.add(p)
    db.flush()
    sv = SurveyResponse(user_id=u.id, direction_id="backend", claimed_grade_id="middle", experience_years=2.0,
                        answers={"stack": {t: 2 for t in NEW_STACK}, "roles": ["developer"], "demo": True, "jury": True})
    db.add(sv)
    db.flush()
    for t in NEW_STACK:
        db.add(SurveyStackTag(survey_id=sv.id, stack_tag_id=t, self_level=2))
    set_t0_facts(db, u.id, FactSource.self_report, stack=NEW_STACK, roles=["developer"], soft_skills=["teamwork"],
                 experience_years=2.0)
    fields = extract_rules(NEW_RESUME)
    db.add(CandidateResume(user_id=u.id, filename="resume_demo.pdf", size_bytes=len(NEW_RESUME.encode()), page_count=1,
                           text_redacted=NEW_RESUME, pii_summary={"demo": True}, extracted=fields,
                           method=fields.get("method", "rules")))
    pp = FspPassport(user_id=u.id, link_source=FspLinkSource.demo, synced_at=utcnow(), sport_rank=None,
                     raw={"demo": True, "jury": True, "note": "демо-реестр хакатона"})
    db.add(pp)
    db.flush()
    db.add(FspAchievement(passport_id=pp.id, discipline="algorithmic", event_level=FspEventLevel.regional,
                          event_name="Региональный этап чемпионата по алгоритмическому программированию",
                          event_date=date(2025, 3, 15), place=12, result_title="участник", verified=True,
                          source_ref="demo-registry"))
    db.commit()
    return u, p


def delete_jury(db: Session, sid: str = "") -> int:
    """Удаляет учётки и компанию одной песочницы (sid "" — общее демо). Чужие песочницы не трогает."""
    from app.integrations.ats.models import AtsSettings, AtsStubRecord

    from app.cup.demo import delete_cups
    from app.cup.models import CupEntry

    delete_cups(db, jury_scope=sid or scope.SHARED)  # кубки песочницы — с приглашениями по итогам и фактами T1
    if sid:  # гости живой демонстрации (QR → мини-тест, app.jury_live); зал и его код остаются — QR на слайде рабочий
        from app.jury_live import service as live

        live.delete_guests(db, list(db.scalars(select(User.id).where(User.email.like(live.guest_emails_like(sid)))).all()))
        live.bump_sid(db, sid)
    # учётка, удалённая кандидатом сама («Мои данные»): почта обезличена, но «+sid@домен» сохранён — убираем вместе
    gone = User.email.like(f"deleted-%+{sid}@{scope.DOMAIN}") if sid else false()
    ids = db.scalars(select(User.id).where(or_(User.email.in_(list(scope.emails(sid).values())), gone))).all()
    if sid:  # И25: подписки, лента уведомлений и смоделированные кандидаты песочницы
        from app.modules.subs import demo as subs_demo

        subs_demo.purge(db, sid, list(ids))
    if ids:  # участия её кандидатов в общих кубках платформы
        db.execute(delete(CupEntry).where(CupEntry.candidate_user_id.in_(ids)))
    own = Company.created_by.in_(ids) if ids else Company.id.is_(None)
    # компания без автора (автор удалён раньше) — только для общего демо, как было до песочниц
    cond = and_(Company.name.in_([COMPANY, COMPANY2, COMPANY3]), Company.is_demo.is_(True),
                or_(own, and_(Company.created_by.is_(None), not sid)))
    keys = db.scalars(select(AtsSettings.stub_key).join(Company, Company.id == AtsSettings.company_id)
                      .where(cond, AtsSettings.stub_key.is_not(None))).all()
    if keys:  # «входящие» демо-ATS удаляемой демо-компании
        db.execute(delete(AtsStubRecord).where(AtsStubRecord.stub_key.in_(list(keys))))
    db.execute(delete(Company).where(cond))
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


def create_jury(db: Session, sid: str = "") -> dict:
    with scope.use(sid):  # подборки песочницы строятся по её кандидатам, без чужих песочниц
        return _create_jury(db, sid)


def _create_jury(db: Session, sid: str) -> dict:
    t0 = time.time()
    # у Марии тест пройден с камерой по согласию (замечаний нет); у Ильи — «тест без камеры» (нейтрально)
    _, p1, r1 = _candidate(db, "candidate", "Мария Королёва", True, 1.05, 3101, 0, sid=sid, camera=True)
    # И26: готовая пара попыток Backend · Middle — «Две попытки рядом» видно без прохождения. Повтор в демо-режиме
    # сразу (правило 30/90 дней снято), из другого субпула банка; повторное подтверждение обновляет оценку в фактах.
    for attempt in range(4):
        r1b = run_demo_test(db, p1.user_id, "middle", 1.05, 3201 + attempt, camera=True)
        if r1b.get("confirmed"):
            r1 = r1b
            break
    # Вторая специализация — реальный отдельный тест банка, не ручная пометка в профиле.
    from app.modules.profiles.specializations import ensure_specialization
    ensure_specialization(db, p1, "frontend")
    sv = SurveyResponse(user_id=p1.user_id, direction_id="frontend", claimed_grade_id="junior",
                        experience_years=3.5,
                        answers={"stack": {"javascript": 2, "typescript": 2, "react": 2}, "demo": True, "jury": True})
    db.add(sv)
    db.flush()
    for tag in ("javascript", "typescript", "react"):
        db.add(SurveyStackTag(survey_id=sv.id, stack_tag_id=tag, self_level=2))
    db.commit()
    for attempt in range(6):
        extra_result = run_demo_test(db, p1.user_id, "junior", 1.6, 5301 + attempt, direction="frontend", camera=True)
        if extra_result.get("confirmed"):
            break
    # у Ильи — два ухода со вкладки и попытка скопировать текст задания: достоверность «средняя» (видно
    # работодателю и Илье с причинами)
    u2, p2, r2 = _candidate(db, "candidate_nofsp", "Илья Сергеев", False, 0.95, 4201, 1, away_items=(4, 8), sid=sid,
                            copy_items=(8,))
    # у порога Junior: тест не подтвердил грейд, но и не доказал уровень ниже — «Junior (предварительно)»
    _, p3, r3 = _candidate(db, "candidate_junior", "Артём Лебедев", False, -1.05, 5301, 0, sid=sid, claimed="junior",
                           experience=0.5, salary=80_000, want="provisional")
    _, p4 = _candidate_new(db, sid)  # «Пройдите тест сами»: без теста, категории нет — в подборки не попадает
    eu = _user(db, "employer", UserRole.employer, sid)
    c = Company(name=COMPANY, industry="Финансовые технологии", city="Санкт-Петербург",
                website=f"https://severny-platezh.{DOMAIN}",  # сайт на домене почты: демо-сведения, высокий индекс (Ф4)
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
        db.add(SelectionVersion(need_id=n.id, version=1, parent_version=None, filters={"_meta": sel["meta"]},
                                requirements=req, results=sel["results"], algorithm_version=sel["algorithm"],
                                created_by=eu.id))  # Ф2: снимок версии — открытие без пересчёта
        needs.append(n)
    db.commit()
    from app.modules.invitations.service import create_invitation

    create_invitation(db, eu, c, p2, position_title="Backend-разработчик (платежи)",
                      offer_description="Команда платежей: FastAPI, PostgreSQL, Redis. Удалённо, гибкий график.",
                      salary_from=240_000, salary_to=270_000, contact_method="Почта HR и звонок 20 минут",
                      need_id=needs[0].id, probe_id=None)
    _jury_contact(db, eu, c, p2, p1, needs)  # переписка и встречное предложение (app.modules.contact, И4)
    from app.modules.hiring.demo import seed_jury_hiring

    seed_jury_hiring(db, c)  # найм: назначенное собеседование у принятого приглашения (Н8); сбой не ломает сид
    cups = _jury_cups(db, sid, eu, c, p1)
    tasks = _jury_assignments(db, sid, eu, c, needs[0], p1, p2, p3)  # задания работодателя с автопроверкой (И7)
    _maria_extras(db, eu, p1)
    from app.modules.interview.demo import seed_jury_defense  # устная защита: «пример, модельный кандидат» (Я15)
    seed_jury_defense(db, p1, p2)
    from app.modules.mydata.demo import seed_jury_interest  # «Мои данные»: отметка интереса у персон жюри (md01)

    seed_jury_interest(db, eu, c, p1, p2, p3)
    from app.modules.mutual.demo import seed_jury_mutual  # взаимный подбор, отзывы, ссылка руководителю (Н9, Н2, Н3)
    seed_jury_mutual(db, eu, needs, p1, p2, p3)
    _user(db, "fsp", UserRole.fsp_analyst, sid)  # только агрегаты /api/fsp-cabinet/* — общие для платформы
    # эксперт — последним: набор почт песочницы полон (_complete) только когда всё создано — запасную не выдадут раньше
    ex = _user(db, "expert", UserRole.expert, sid)  # не admin: только /api/expert/*, только демо-кандидаты
    db.commit()
    return {"candidate": {"ref": p1.public_ref, "confirmed": r1.get("confirmed"), "theta": r1.get("theta")},
            "candidate_nofsp": {"ref": p2.public_ref, "confirmed": r2.get("confirmed"), "theta": r2.get("theta"),
                                "pending": (r2.get("details") or {}).get("pending_review")},
            "candidate_junior": {"ref": p3.public_ref, "provisional": r3.get("category_provisional"),
                                 "theta": r3.get("theta"), "category_id": r3.get("category_id")},
            "candidate_new": {"ref": p4.public_ref},
            "employer": {"company": c.name, "needs": len(needs), "cups": cups, "assignments": tasks},
            "expert": {"email": ex.email},
            "scenario": sid or None, "seconds": round(time.time() - t0, 1)}


def _jury_contact(db: Session, eu: User, c: Company, ilya: CandidateProfile, maria: CandidateProfile, needs) -> None:
    """Демо переписки, встречного предложения и отзыва контактов. Сбой не должен ломать сид жюри."""
    from app.modules.contact.demo import seed_jury_contact

    try:
        seed_jury_contact(db, eu, c, ilya, maria, needs)
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("jury: demo contact failed")


def _jury_cups(db: Session, sid: str, eu: User, c: Company, maria: CandidateProfile) -> list[str]:
    """Кубки работодателя песочницы (app.cup.demo.seed_jury_cups). Сбой кубков не должен ломать сид жюри: кубки
    досоздадутся при открытии раздела «Кубки» работодателем (ensure_jury_cups)."""
    from app.cup.demo import seed_jury_cups

    try:
        return seed_jury_cups(db, sid or scope.SHARED, eu, c, maria)
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("jury: demo cups failed")
        return []


def _jury_assignments(db: Session, sid: str, eu: User, c: Company, need, maria: CandidateProfile,
                      ilya: CandidateProfile, artem: CandidateProfile | None = None) -> list[str]:
    """Задания работодателя песочницы (И7, app.modules.assignments.demo); сбой не ломает сид жюри."""
    from app.modules.assignments.demo import seed_jury_assignments

    try:
        return seed_jury_assignments(db, sid or scope.SHARED, eu, c, need, maria, ilya, artem)
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("jury: demo assignments failed")
        return []


def _maria_extras(db: Session, eu: User, maria: CandidateProfile) -> None:
    """Чтобы у Марии на старте были приглашение и вакансии (fx01): приглашение от второй компании песочницы
    (COMPANY2 — не от «Северного платежа»: его приглашение Марии — шаг сценария, лимит 30 дней не мешает) и общие
    демо-вакансии платформы (если их ещё не посеяли). Жалоба на это приглашение меняет индекс только COMPANY2
    своей песочницы. Сбой не ломает сид жюри."""
    from app.integrations.vacancies.demo import ensure as ensure_vacancies
    from app.modules.invitations.service import create_invitation

    try:
        c2 = Company(name=COMPANY2, industry="Логистика", city="Казань", website=f"https://logistika-online.{DOMAIN}",
                     description="Сервис доставки для интернет-магазинов. Демо-компания для экспертов жюри.",
                     contact_email=f"hr-logistics@{DOMAIN}", created_by=eu.id, is_demo=True)
        db.add(c2)
        db.flush()
        create_invitation(db, eu, c2, maria, position_title="Python-разработчик (сервис маршрутов)",
                          offer_description="Расчёт маршрутов и слотов доставки: FastAPI, PostgreSQL, Redis. "
                                            "Гибрид в Казани или удалённо.",
                          salary_from=230_000, salary_to=270_000, contact_method="Звонок HR 15 минут",
                          need_id=None, probe_id=None)
        # «плохой» работодатель (Ф4): индекс доверия низкий — записи в реестре нет, почта на бесплатном сервисе,
        # вилка втрое выше рынка. Приглашение видно в списке рядом с хорошими: функция показывает, как предупреждает
        c3 = Company(name=COMPANY3, industry="Сетевой маркетинг", city="Москва", website="https://bystry-zarabotok.example.com",
                     description="Демо-компания для экспертов жюри: неправдоподобное предложение, чтобы показать "
                                 "предупреждение индекса доверия.",
                     contact_email="bystry.zarabotok@gmail.com", created_by=eu.id, is_demo=True)
        db.add(c3)
        db.flush()
        create_invitation(db, eu, c3, maria, position_title="Backend-разработчик: доход от 600 000 ₽, опыт не важен",
                          offer_description="Срочно! Высокий доход с первого дня, оформление после оплаты обучения. "
                                            "(Демо: намеренно неправдоподобная вилка и условия — индекс доверия "
                                            "предупреждает кандидата.)",
                          salary_from=600_000, salary_to=850_000, contact_method="Телеграм-чат менеджера",
                          need_id=None, probe_id=None)
        ensure_vacancies(db)
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("jury: Maria extras failed")


def ensure_ideas(db: Session) -> None:
    """Общее демо кубков и Кабинета ФСП (одно на платформу): кубки демо-компаний и история приглашений для
    аналитики. Дёшево, если всё на месте; пересев — если демо нет или идущий кубок подходит к концу."""
    from app.cup.demo import is_stale
    from app.fsp_cabinet.demo import has_demo_invitations, prepare

    try:
        if not is_stale(db) and has_demo_invitations(db):
            return
        with _lock(db):
            if is_stale(db) or not has_demo_invitations(db):  # другой воркер мог уже пересеять, пока мы ждали
                prepare(db)
    except Exception:  # noqa: BLE001 — демо кубков не должно ломать вход жюри
        db.rollback()
        log.exception("jury: ideas demo failed")


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


def _complete(db: Session, sid: str = "") -> bool:
    want = set(scope.emails(sid).values())
    have = set(db.scalars(select(User.email).where(User.email.in_(list(want)))).all())
    db.commit()
    return have == want


def reset(db: Session, sid: str = "") -> dict:
    with _lock(db):
        n = delete_jury(db, sid)
        out = create_jury(db, sid)
    out["deleted_users"] = n
    log.info("Демо жюри пересоздано: %s", out)
    return out


def ensure(db: Session, sid: str = "") -> bool:
    """Создаёт учётки песочницы (sid "" — общее демо), если их нет. True — созданы сейчас."""
    if _complete(db, sid):
        return False
    with _lock(db):
        if _complete(db, sid):  # другой воркер уже создал, пока мы ждали
            return False
        delete_jury(db, sid)
        create_jury(db, sid)
    return True


def sandboxes(db: Session) -> dict[str, float]:
    """Песочницы жюри → время последней активности (вход или создание), секунды эпохи."""
    rows = db.execute(select(User.email, User.last_login_at, User.created_at)
                      .where(User.email.like(f"%+%@{DOMAIN}"))).all()
    out: dict[str, float] = {}
    for email, last, created in rows:
        _, sid = scope.parse(email)
        if sid:
            t = max(x.timestamp() for x in (last, created) if x is not None) if (last or created) else 0.0
            out[sid] = max(out.get(sid, 0.0), t)
    return out


def created_last_hour(db: Session) -> int:
    """Сколько песочниц выдано за последний час (по учёткам работодателя песочниц: создание или выдача запасной).
    Считается по БД — одинаково для всех воркеров uvicorn."""
    since = utcnow() - timedelta(hours=1)
    rows = db.execute(select(User.created_at, User.last_login_at).where(User.email.like(f"employer+%@{DOMAIN}"))).all()
    n = 0
    for created, last in rows:
        if created is not None and as_aware(created) >= since:
            n += 1
    return n


_SPARE: contextvars.ContextVar[bool] = contextvars.ContextVar("jury_spare", default=False)


@contextmanager
def as_spare():
    """Создаваемая песочница — запасная: ещё ничья, отметок входа нет (см. spares, claim)."""
    tok = _SPARE.set(True)
    try:
        yield
    finally:
        _SPARE.reset(tok)


def spares(db: Session) -> list[str]:
    """Запасные песочницы: полностью созданы, но ещё не выданы (у кандидата песочницы нет отметки входа)."""
    rows = db.execute(select(User.email, User.last_login_at).where(User.email.like(f"candidate+%@{DOMAIN}"))).all()
    out = []
    for email, last in rows:
        persona, sid = scope.parse(email)
        if persona == "candidate" and sid and last is None and _complete(db, sid):
            out.append(sid)
    return sorted(out)


def claim(db: Session, sid: str) -> bool:
    """Атомарно выдать запасную песочницу одному эксперту: отметка входа у её кандидата ставится одним UPDATE
    с условием «ещё не было входа» — из двух одновременных входов песочницу получит только один."""
    r = db.execute(update(User).where(User.email == scope.emails(sid)["candidate"], User.last_login_at.is_(None))
                   .values(last_login_at=utcnow()))
    db.commit()
    return r.rowcount == 1


def evict(db: Session, keep: int, protect: str | None = None) -> list[str]:
    """Удаляет самые давние песочницы сверх keep (кроме protect). Возвращает удалённые sid."""
    boxes = sorted((t, s) for s, t in sandboxes(db).items() if s != protect)
    gone = [s for _, s in boxes[: max(0, len(boxes) - keep)]]
    if gone:
        with _lock(db):
            for s in gone:
                delete_jury(db, s)
        log.info("Песочницы жюри удалены по лимиту: %s", gone)
    return gone
