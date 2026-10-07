"""Демо-данные «Кубка работодателя» (поверх основных демо-данных app.modules.demo.seed).

* 6 кубков демо-компаний «Демо: …» — общие для всей платформы: 3 завершены (места, приглашения лучшим, записи в
  паспорт ФСП), 2 идут (в Backend · Middle может поучаствовать и демо-кандидат жюри), 1 скоро начнётся. На них
  строится аналитика Кабинета ФСП;
* у каждой копии демо жюри (песочницы, app.modules.jury.scope) — свои два кубка её работодателя
  (seed_jury_cups): завершённый «Платёжный шлюз» — Мария Королёва этой песочницы на 2-м месте, запись в паспорте
  ФСП (приглашение — только победителю); «Вебхуки без дублей» — срок вышел, 3 решения оценены, 2 ждут оценки
  работодателя, после оценки итоги подводятся сами. Кубки песочницы видны только её кандидатам (Cup.jury_scope),
  демо-кандидаты платформы в них — «статисты»: места и приглашения есть, фактов T1 и записей паспорта нет
  (app.cup.service.credits) — поэтому число песочниц не меняет ни их рейтинг, ни аналитику ФСП.

Ответы участников генерирует «демо-респондент»: вероятность верного ответа растёт с рейтингом кандидата.
Оценки открытых решений в демо — score_method="demo" (не LLM и не эксперт; так и показывается).

Даты относительные (от момента посева). Когда идущий кубок подходит к концу или «скоро» начинается, демо
устаревает (is_stale) — вход жюри и сброс демо пересевают кубки демо-компаний (app.fsp_cabinet.demo.prepare).

Запуск: python -m app.cup.demo [--reset | --delete]
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import random

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.db import SessionLocal, as_aware, get_engine, utcnow
from app.cup import service as svc
from app.cup import tasks as auto
from app.cup.models import Cup, CupEntry
from app.modules.auth.models import User
from app.modules.fsp.models import FspAchievement
from app.modules.invitations import service as inv_svc
from app.modules.invitations.models import Invitation
from app.modules.jury import scope
from app.modules.profiles.facts import refresh_rating
from app.modules.profiles.models import CandidateFact, CandidateProfile, Company, EmployerProfile

JURY_DOMAIN = scope.DOMAIN
# Разные тексты для одного уровня: в слепой оценке у работодателя не должно быть одинаковых решений.
ANSWERS: dict[str, dict[str, list[str]]] = {
    "webhooks": {
        "strong": [
            "Храню ключ идемпотентности (event_id провайдера) в таблице processed_events с уникальным индексом; "
            "обработка в одной транзакции: INSERT ... ON CONFLICT DO NOTHING, если вставка не прошла — событие уже "
            "обработано, отвечаю 200. Порядок событий не гарантирован, поэтому статус платежа меняю только вперёд "
            "по конечному автомату. Повторы провайдера — с экспоненциальной задержкой, ответ быстрый, тяжёлую "
            "работу — в очередь (outbox). Тесты: двойная доставка, перестановка событий, падение после коммита.",
            "Уникальное ограничение на (provider, event_id) в PostgreSQL. В одной транзакции — вставка ключа, "
            "UPDATE платежа с условием на текущий статус и запись в outbox; повтор с тем же ключом получает 200 без "
            "побочных эффектов. Запоздавшее событие сравниваю по версии провайдера и не откатываю статус назад. "
            "Раз в сутки — сверка с API провайдера, она ловит потерянные вебхуки. Тесты: две копии параллельно, "
            "обратный порядок, таймаут после коммита.",
            "Подпись вебхука проверяю до любой записи. Дальше журнал входящих событий с уникальным id и состоянием "
            "«принято → применено»; применение — идемпотентная операция над платежом с оптимистичной блокировкой "
            "по version. Ответ провайдеру сразу после записи в журнал, применение — воркером, повтор при сбое "
            "безопасен. Метрики: доля дублей, задержка применения, расхождения сверки.",
        ],
        "medium": [
            "Сохраняю id события в Redis с TTL сутки и перед обработкой проверяю, был ли он. Если был — пропускаю. "
            "Обработку делаю в транзакции. Порядок событий может быть разным, это надо учитывать.",
            "Перед зачислением ищу платёж по id провайдера: если он уже «оплачен» — выхожу, иначе меняю статус и "
            "баланс. От гонок — SELECT FOR UPDATE на строку платежа. Повторы провайдера тогда не страшны. "
            "Тест — на повторный вебхук.",
            "Кладу вебхук в Kafka с ключом партиции payment_id, чтобы события одного платежа шли по порядку. "
            "Консьюмер отсекает дубли по таблице обработанных id. Если консьюмер упал, Kafka передоставит.",
        ],
        "weak": [
            "Добавлю проверку, что такой платёж уже есть в базе, и не буду создавать второй. Можно ещё логировать.",
            "Буду отвечать провайдеру 200 сразу, а обработку запускать в фоне — тогда он не станет присылать "
            "повторы и дублей не будет.",
            "Сделаю флаг processed у платежа и буду ставить его после обработки. Если пришёл второй раз и флаг "
            "стоит — ничего не делаю.",
        ],
    },
    "a11y": {
        "strong": [
            "Каждое поле с видимым label и связкой for/id, ошибки — текстом рядом с полем и в aria-describedby, "
            "фокус переводится на первую ошибку, сводка ошибок в role=alert. Номер карты — inputmode=numeric, "
            "autocomplete=cc-number, без маски, ломающей экранные дикторы. Контраст 4.5:1, состояние :focus-visible. "
            "Проверка: клавиатура без мыши, NVDA и VoiceOver, axe в CI, тест на 200 % масштаба.",
            "Нативные input и button вместо div, группа «срок действия» в fieldset с legend. Ошибки не только "
            "цветом: текст и значок, связка aria-describedby, при отправке — сводка со ссылками на поля. "
            "Автозаполнение cc-name, cc-exp, cc-csc, таймаут сессии с предупреждением и продлением. Проверяю "
            "клавиатурой, экранным диктором и автотестами axe-core в Playwright.",
        ],
        "medium": [
            "Поставлю label к полям, ошибки красным под полем, добавлю aria-invalid. Проверю контраст и что "
            "форма проходится табом. Можно прогнать Lighthouse.",
            "Сделаю порядок табуляции по смыслу, подписи к полям и понятные тексты ошибок. Маску для номера "
            "карты возьму готовую библиотеку. Проверю расширением axe.",
        ],
        "weak": [
            "Сделаю поля побольше и подсказки placeholder внутри полей, ошибки покажу всплывающим окном.",
            "Добавлю атрибуты alt и title ко всем элементам формы, ошибки подсвечу красной рамкой.",
        ],
    },
    "traffic": {
        "strong": [
            "Базовая модель — сезонная наивная по дню недели и часу, затем градиентный бустинг на лагах 1/7/14 дней, "
            "календаре, погоде и событиях; валидация по времени (rolling origin), метрика MAPE и WAPE по станциям. "
            "Отдельно — иерархическая согласованность сумм по линиям. Аномалии (праздники, перекрытия) — флагами.",
            "Глобальная модель на все станции: LightGBM с эмбеддингом станции, лаги и скользящие средние, "
            "признаки праздников и погоды из прогноза, а не факта, чтобы не было утечки. Прогноз на 7 дней — "
            "прямой, отдельная модель на горизонт. Бэктест на 12 неделях, WAPE и квантильная потеря для "
            "интервалов; сравнение с наивной сезонной.",
        ],
        "medium": [
            "Возьму историю пассажиропотока, сделаю признаки по дню недели и часу, обучу случайный лес. "
            "Проверю качество на последнем месяце по MAE.",
            "Попробую Prophet для каждой станции с праздниками РФ, погоду добавлю регрессором. Качество — "
            "по MAPE на отложенном месяце.",
        ],
        "weak": [
            "Посчитаю среднее за прошлые недели и буду использовать его как прогноз.",
            "Обучу нейросеть LSTM на всех данных и проверю на тех же данных, насколько точно она предсказывает.",
        ],
    },
}


# Уровни решений по порядку участников (strong > 0.72 > medium > 0.45 > weak): тексты не повторяются.
SPREAD = {"webhooks": [0.85, 0.6, 0.3, 0.8, 0.55, 0.65, 0.4], "a11y": [0.85, 0.6, 0.35, 0.8, 0.55, 0.3],
          "traffic": [0.8, 0.6, 0.85, 0.55, 0.35]}


def _cands(db: Session, category: str, n: int, rnd: random.Random, exclude: set | None = None) -> list[CandidateProfile]:
    rows = db.scalars(select(CandidateProfile).join(User, User.id == CandidateProfile.user_id).where(
        CandidateProfile.current_category_id == category, CandidateProfile.visible_to_employers.is_(True),
        User.is_demo.is_(True), User.email.like("%@demo.invalid"))).all()
    rows = sorted((p for p in rows if p.user_id not in (exclude or set())), key=lambda p: str(p.user_id))
    return rnd.sample(rows, min(n, len(rows)))


def _company(db: Session, name: str) -> tuple[Company, User] | None:
    c = db.scalar(select(Company).where(Company.name == name, Company.is_demo.is_(True)))
    if c is None:
        return None
    ep = db.scalar(select(EmployerProfile).where(EmployerProfile.company_id == c.id))
    u = db.get(User, ep.user_id) if ep else None
    return (c, u) if u else None


def _cup(db: Session, c: Company, u: User, *, title: str, description: str, category: str, mode: str,
         start_days: float, end_days: float, salary: tuple[int, int], top: int, position: str,
         task_text: str | None = None, n_tasks: int = 5, rnd: random.Random, jury_scope: str | None = None) -> Cup:
    now = utcnow()
    d, g = category.split(".")
    cup = Cup(company_id=c.id, created_by=u.id, title=title, description=description, category_id=category,
              direction_id=d, grade_id=g, mode=mode, task_text=task_text,
              rubric={"criteria": [dict(x) for x in svc.DEFAULT_RUBRIC]} if mode == "rubric" else None,
              task_families=auto.pick_families(d, g, n_tasks, seed=rnd.randint(1, 10**6)) if mode == "auto" else [],
              time_limit_min=15 if mode == "auto" else 40, starts_at=now + timedelta(days=start_days),
              ends_at=now + timedelta(days=end_days), salary_from=salary[0], salary_to=salary[1], invite_top_n=top,
              min_score=0.5, position_title=position,
              offer_description=f"{position} в компании {c.name}. Команда, задачи и условия обсудим на встрече (демо).",
              contact_method=f"{c.contact_email or 'hr@demo.invalid'} (демо)", status="active", summary={},
              is_demo=True, jury_scope=jury_scope)
    db.add(cup)
    db.flush()
    return cup


def _play(db: Session, cup: Cup, p: CandidateProfile, rnd: random.Random, alias_n: int, *, state: str,
          text_key: str | None = None, demo_score: bool = True, skill: float | None = None,
          correct_n: int | None = None, spent_s: int | None = None) -> CupEntry:
    """Демо-участие: state = joined | scored | submitted (ждёт оценки). correct_n — ровно столько верных ответов
    в автопроверке (детерминированные места), spent_s — время решения."""
    if skill is None and text_key in SPREAD:  # открытая задача: сильные, средние и слабые решения вперемешку
        skill = SPREAD[text_key][(alias_n - 1) % len(SPREAD[text_key])]
    skill = skill if skill is not None else min(0.95, max(0.25, (p.rating_score or 0.5) + rnd.uniform(-0.15, 0.2)))
    e = CupEntry(cup_id=cup.id, candidate_user_id=p.user_id, alias=f"Участник {alias_n:02d}", status="joined", tasks=[])
    db.add(e)
    if state == "joined":
        return e
    st = cup.starts_at + timedelta(hours=rnd.uniform(1, 30))
    spent = spent_s or int(rnd.uniform(0.45, 0.95) * cup.time_limit_min * 60)
    e.started_at, e.submitted_at = st, st + timedelta(seconds=spent)
    e.deadline_at, e.time_spent_s = st + timedelta(minutes=cup.time_limit_min), spent
    if cup.mode == "auto":
        items = auto.issue(cup.task_families)
        answers = {}
        for j, it in enumerate(items):
            k = it["key"]["value"]
            if (j < correct_n) if correct_n is not None else (rnd.random() < skill):
                answers[it["token"]] = k
            elif it["kind"] == "option":
                answers[it["token"]] = next(o["id"] for o in it["public"]["options"] if o["id"] != k)
            elif it["kind"] == "line":
                answers[it["token"]] = int(k) % max(2, it["public"]["code_lines"]) + 1
            else:
                answers[it["token"]] = "не знаю"
        e.score = auto.score(items, answers)
        e.tasks = items
        e.grading = {"correct": sum(1 for it in items if it["correct"]), "total": len(items)}
        e.score_method, e.status = "auto", "scored"
        return e
    lvl = "strong" if skill > 0.72 else "medium" if skill > 0.45 else "weak"
    variants = ANSWERS[text_key][lvl]
    mine = [x for x in db.new if isinstance(x, CupEntry) and x.cup_id == cup.id]  # ещё не записанные (autoflush выключен)
    mine += db.scalars(select(CupEntry).where(CupEntry.cup_id == cup.id)).all()
    used = {x.answer.get("text") for x in mine if x.answer}
    body = next((v for v in variants if v not in used), variants[alias_n % len(variants)])
    e.answer = {"text": body, "link": None, "text_redacted": body, "redacted": []}
    e.status = "submitted"
    if demo_score:
        base = {"strong": 0.88, "medium": 0.62, "weak": 0.3}[lvl]
        e.score = round(min(1.0, max(0.0, base + rnd.uniform(-0.08, 0.08))), 3)
        e.score_method, e.status = "demo", "scored"
        e.grading = {"demo": {"level": lvl, "note": "демо: оценка выставлена генератором демо-данных"}}
    return e


def _finish(db: Session, cup: Cup, statuses: list[str]) -> None:
    """Итоги демо-кубка: штатный finalize, затем ответы кандидатов на приглашения и даты задним числом.

    На приглашение демо-кандидату жюри никто не отвечает за него — оно ждёт ответа в его кабинете."""
    ends = cup.ends_at
    cup.ends_at = utcnow() - timedelta(seconds=1)
    db.commit()
    inv_ids = svc.finalize(db, cup, None)
    cup = db.get(Cup, cup.id)
    cup.ends_at = ends
    cup.finalized_at = ends + timedelta(hours=2)
    invs = [db.get(Invitation, iid) for iid in inv_ids]
    jury = {i.candidate_user_id for i in invs if scope.key_of(db.get(User, i.candidate_user_id).email) is not None}
    for inv in invs:
        inv.created_at = ends + timedelta(hours=3)
    # статусы — только демо-кандидатам по порядку мест; кандидат жюри отвечает сам и слот не занимает
    for inv, st in zip([i for i in invs if i.candidate_user_id not in jury], statuses, strict=False):
        if st in ("accepted", "declined"):
            inv_svc.respond(db, inv, inv.candidate_user_id, st == "accepted", None)
        elif st == "viewed":
            inv_svc.mark_viewed(db, inv, inv.candidate_user_id)
    db.commit()


def seed_cups(db: Session, rng_seed: int = 20261010) -> dict:
    rnd = random.Random(rng_seed)
    made = []

    def comp(name):
        return _company(db, name)

    if (x := comp("Демо: ФинТех Север")):
        c, u = x
        cup = _cup(db, c, u, title="Надёжные платежи", category="backend.middle", mode="auto", start_days=-19,
                   end_days=-12, salary=(230_000, 290_000), top=3, position="Backend-разработчик (платёжное ядро)",
                   description="Пять заданий из банка платформы на транзакции, идемпотентность и работу с БД. "
                               "У каждого участника свой вариант, проверка автоматическая, 15 минут.", rnd=rnd)
        ps = _cands(db, "backend.middle", 8, rnd)
        for i, p in enumerate(ps, start=1):
            _play(db, cup, p, rnd, i, state="joined" if i == len(ps) else "scored")
        db.commit()
        _finish(db, cup, ["accepted", "accepted", "viewed"])
        made.append(cup.title)
    if (x := comp("Демо: Студия Интерфейсов")):
        c, u = x
        cup = _cup(db, c, u, title="Доступная форма оплаты", category="frontend.middle", mode="rubric",
                   start_days=-32, end_days=-25, salary=(190_000, 240_000), top=3, position="Frontend-разработчик",
                   description="Спроектировать форму оплаты, удобную для клавиатуры и экранных дикторов. Оценка по "
                               "рубрике: корректность, компромиссы, проверяемость.",
                   task_text="Опишите, как сделать форму оплаты картой доступной (WCAG 2.2 AA): разметка полей, ошибки, "
                             "фокус, маски ввода, проверка. Код — по желанию.", rnd=rnd)
        for i, p in enumerate(_cands(db, "frontend.middle", 6, rnd), start=1):
            _play(db, cup, p, rnd, i, state="scored", text_key="a11y")
        db.commit()
        _finish(db, cup, ["accepted", "declined", "accepted"])
        made.append(cup.title)
    if (x := comp("Демо: Тест-Качество")):
        c, u = x
        cup = _cup(db, c, u, title="Дефекты в API", category="qa.middle", mode="auto", start_days=-45, end_days=-38,
                   salary=(150_000, 200_000), top=4, position="QA-инженер (тестирование API)",
                   description="Пять заданий банка: найти дефект, предсказать вывод, выбрать исправление. Своя вариация "
                               "у каждого участника, автопроверка, 15 минут.", rnd=rnd)
        for i, p in enumerate(_cands(db, "qa.middle", 7, rnd), start=1):
            _play(db, cup, p, rnd, i, state="scored")
        db.commit()
        _finish(db, cup, ["accepted", "accepted", "declined", "accepted"])
        made.append(cup.title)
    if (x := comp("Демо: ЛогистикПро")):
        c, u = x
        cup = _cup(db, c, u, title="Маршрутизация заказов", category="backend.middle", mode="auto", start_days=-2,
                   end_days=6, salary=(220_000, 280_000), top=3, position="Backend-разработчик (маршрутизация)",
                   description="Кубок идёт: пять заданий банка с автопроверкой на 15 минут. Лучшим трём — приглашение "
                               "с зарплатой 220–280\u00a0тыс.\u00a0₽.", rnd=rnd)
        for i, p in enumerate(_cands(db, "backend.middle", 5, rnd), start=1):
            _play(db, cup, p, rnd, i, state="scored")
        made.append(cup.title)
    if (x := comp("Демо: ГородДанные")):
        c, u = x
        cup = _cup(db, c, u, title="Прогноз пассажиропотока", category="data_ml.middle", mode="employer",
                   start_days=-3, end_days=6, salary=(200_000, 270_000), top=2, position="Data Scientist",
                   description="Предложить подход к прогнозу пассажиропотока метро на неделю вперёд. Решения "
                               "оценивает работодатель вслепую — под псевдонимами, без ссылок и контактов.",
                   task_text="Есть почасовые данные входов по станциям за 3 года, погода и календарь событий. Опишите "
                             "модель прогноза на 7 дней, валидацию и метрики.", rnd=rnd)
        for i, p in enumerate(_cands(db, "data_ml.middle", 5, rnd), start=1):
            _play(db, cup, p, rnd, i, state="submitted", text_key="traffic", demo_score=False)
        made.append(cup.title)
    if (x := comp("Демо: КиберЩит")):
        c, u = x
        cup = _cup(db, c, u, title="Разбор веб-уязвимостей", category="security.middle", mode="auto", start_days=5,
                   end_days=12, salary=(180_000, 250_000), top=2, position="Специалист по безопасности приложений",
                   description="Скоро старт: задания банка на OWASP, криптографию и сетевую безопасность, 15 минут.",
                   rnd=rnd)
        for i, p in enumerate(_cands(db, "security.middle", 2, rnd), start=1):
            _play(db, cup, p, rnd, i, state="joined")
        made.append(cup.title)
    db.commit()
    return {"cups": made}


def _seeded(db: Session) -> list[Cup]:
    """Кубки демо-компаний «Демо: …» — общие для платформы (кубки песочниц жюри живут вместе с ними)."""
    return list(db.scalars(select(Cup).join(Company, Company.id == Cup.company_id).where(
        Cup.is_demo.is_(True), Cup.jury_scope.is_(None), Company.is_demo.is_(True), Company.name.like("Демо: %"))).all())


def is_stale(db: Session, margin_h: float = 12) -> bool:
    """Демо-кубки надо пересеять: их нет, идущий скоро закончится или «скоро старт» вот-вот начнётся."""
    rows = _seeded(db)
    if not rows:
        return True
    now = utcnow()
    for cup in rows:
        if cup.status != "active":
            continue
        ph = svc.phase(cup, now)
        if ph == "judging":
            return True
        edge = as_aware(cup.starts_at) if ph == "upcoming" else as_aware(cup.ends_at)
        if edge - now < timedelta(hours=margin_h):
            return True
    return False


def seed_jury_cups(db: Session, key: str, employer: User, company: Company, maria: CandidateProfile | None) -> list[str]:
    """Два кубка работодателя одной копии демо жюри (key — sid песочницы или scope.SHARED), см. docstring модуля."""
    rnd = random.Random(31)
    used: set = set()
    cup = _cup(db, company, employer, title="Платёжный шлюз", category="backend.middle", mode="auto", start_days=-16,
               end_days=-9, salary=(230_000, 290_000), top=1, position="Backend-разработчик (платёжный шлюз)",
               description="Пять заданий из банка платформы на транзакции, идемпотентность и работу с БД. У каждого "
                           "участника свой вариант, проверка автоматическая, 15 минут.", rnd=rnd, jury_scope=key)
    # места детерминированы: первый — 5 из 5 быстрее Марии, Мария — 5 из 5 (2-е место), дальше — меньше верных
    # демо-кандидатов Backend · Middle — 10: по 5 на кубок, без пересечений (см. ниже)
    ps = _cands(db, "backend.middle", 5, rnd)
    for i, (p, n) in enumerate(zip(ps, [5, 4, 3, 2, 1]), start=1):
        _play(db, cup, p, rnd, i, state="scored", correct_n=n, spent_s=480 if i == 1 else None)
        used.add(p.user_id)
    if maria is not None and maria.current_category_id == "backend.middle" and maria.visible_to_employers:
        _play(db, cup, maria, rnd, len(ps) + 1, state="scored", correct_n=5, spent_s=660)
    db.commit()
    # приглашение — только победителю: Марию эта компания приглашает в основном сценарии жюри, а повторное
    # приглашение от той же компании упёрлось бы в лимит 30 дней
    _finish(db, cup, ["accepted"])
    cup2 = _cup(db, company, employer, title="Вебхуки без дублей", category="backend.middle", mode="rubric",
                start_days=-6, end_days=-0.05, salary=(240_000, 290_000), top=3,
                position="Backend-разработчик в команду платежей",
                description="Платёжный провайдер присылает вебхуки повторно и не по порядку. Нужно спроектировать "
                            "обработку без двойных списаний. Оценка по рубрике.",
                task_text="Провайдер доставляет вебхук «платёж прошёл» как минимум один раз, иногда повторно и в "
                          "другом порядке. Как обработать события так, чтобы не было двойных зачислений и потерь? "
                          "Опишите хранение, транзакции, повторы и тесты.", rnd=rnd, jury_scope=key)
    # другие участники, чем в «Платёжном шлюзе»: повторное приглашение той же компанией упёрлось бы в лимит 30 дней
    for i, p in enumerate(_cands(db, "backend.middle", 5, rnd, exclude=used), start=1):
        _play(db, cup2, p, rnd, i, state="submitted" if i in (2, 5) else "scored", text_key="webhooks",
              demo_score=i not in (2, 5))
    db.commit()
    return [cup.title, cup2.title]


def ensure_jury_cups(db: Session, user: User, company: Company) -> bool:
    """Работодателю демо жюри — его кубки, если их ещё нет (копия демо создана до появления кубков)."""
    persona, sid = scope.parse(user.email)
    if persona != "employer" or not user.is_demo:
        return False
    if db.scalar(select(Cup.id).where(Cup.company_id == company.id).limit(1)) is not None:
        return False
    mu = db.scalar(select(User).where(User.email == scope.emails(sid)["candidate"]))
    seed_jury_cups(db, sid or scope.SHARED, user, company, db.get(CandidateProfile, mu.id) if mu else None)
    return True


def delete_cups(db: Session, seeded_only: bool = False, jury_scope: str | None = None) -> int:
    """Удаляет демо-кубки с участиями, фактами T1, записями паспорта и приглашениями по итогам; пересчитывает
    рейтинг кандидатов, у которых были факты. seeded_only — только кубки демо-компаний «Демо: …»; jury_scope —
    только кубки одной копии демо жюри; иначе — все демо-кубки."""
    if jury_scope is not None:
        ids = list(db.scalars(select(Cup.id).where(Cup.jury_scope == jury_scope)).all())
    elif seeded_only:
        ids = [c.id for c in _seeded(db)]
    else:
        ids = list(db.scalars(select(Cup.id).where(Cup.is_demo.is_(True))).all())
    if not ids:
        return 0
    inv = [i for i in db.scalars(select(CupEntry.invitation_id).where(CupEntry.cup_id.in_(ids))).all() if i]
    refs = [f"cup:{i}" for i in ids]
    users = set(db.scalars(select(CandidateFact.user_id).where(CandidateFact.source_ref.in_(refs))).all())
    db.execute(delete(CandidateFact).where(CandidateFact.source_ref.in_(refs)))
    db.execute(delete(FspAchievement).where(FspAchievement.source_ref.in_(refs)))
    db.execute(delete(CupEntry).where(CupEntry.cup_id.in_(ids)))
    if inv:
        from app.modules.invitations.models import InvitationEvent

        db.execute(delete(InvitationEvent).where(InvitationEvent.invitation_id.in_(inv)))
        db.execute(delete(Invitation).where(Invitation.id.in_(inv)))
    db.execute(delete(Cup).where(Cup.id.in_(ids)))
    db.flush()
    for uid in users:
        refresh_rating(db, uid)
    db.commit()
    return len(ids)


def main() -> None:
    ap = argparse.ArgumentParser(description="Демо-данные «Кубка работодателя»")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--delete", action="store_true")
    a = ap.parse_args()
    get_engine()
    with SessionLocal() as db:
        if a.reset or a.delete:
            print(f"Удалено демо-кубков: {delete_cups(db)}")
        if a.delete:
            return
        if _seeded(db):
            print("Демо-кубки уже есть. Для пересоздания: --reset")
            return
        print(seed_cups(db))


if __name__ == "__main__":
    main()
