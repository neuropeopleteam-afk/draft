"""Демо-данные «Кубка работодателя» (поверх основных демо-данных app.modules.demo.seed).

* 5 кубков демо-компаний: 2 завершены (места, приглашения лучшим, записи в паспорт ФСП), 2 идут (в одном
  Backend · Middle можно поучаствовать демо-кандидатом жюри), 1 скоро начнётся;
* работодателю жюри при первом открытии раздела «Кубки» создаётся свой кубок: срок вышел, 5 решений оценены,
  2 ждут его оценки — после оценки итоги подводятся, лучшим уходят приглашения (ensure_jury_cup).

Ответы участников генерирует «демо-респондент»: вероятность верного ответа растёт с рейтингом кандидата.
Оценки открытых решений в демо — score_method="demo" (не LLM и не эксперт; так и показывается).

Запуск: python -m app.cup.demo [--reset | --delete]
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import random

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.db import SessionLocal, get_engine, utcnow
from app.cup import service as svc
from app.cup import tasks as auto
from app.cup.models import Cup, CupEntry
from app.modules.auth.models import User
from app.modules.fsp.models import FspAchievement
from app.modules.invitations import service as inv_svc
from app.modules.invitations.models import Invitation
from app.modules.profiles.models import CandidateFact, CandidateProfile, Company, EmployerProfile

JURY_EMPLOYER_EMAIL = "employer@jury.example.com"
ANSWERS = {
    "webhooks": {
        "strong": "Храню ключ идемпотентности (event_id провайдера) в таблице processed_events с уникальным индексом; "
                  "обработка в одной транзакции: INSERT ... ON CONFLICT DO NOTHING, если вставка не прошла — событие уже "
                  "обработано, отвечаю 200. Порядок событий не гарантирован, поэтому статус платежа меняю только вперёд "
                  "по конечному автомату. Повторы провайдера — с экспоненциальной задержкой, ответ быстрый, тяжёлую "
                  "работу — в очередь (outbox). Тесты: двойная доставка, перестановка событий, падение после коммита.",
        "medium": "Сохраняю id события в Redis с TTL сутки и перед обработкой проверяю, был ли он. Если был — пропускаю. "
                  "Обработку делаю в транзакции. Порядок событий может быть разным, это надо учитывать.",
        "weak": "Добавлю проверку, что такой платёж уже есть в базе, и не буду создавать второй. Можно ещё логировать.",
    },
    "a11y": {
        "strong": "Каждое поле с видимым label и связкой for/id, ошибки — текстом рядом с полем и в aria-describedby, "
                  "фокус переводится на первую ошибку, сводка ошибок в role=alert. Номер карты — inputmode=numeric, "
                  "autocomplete=cc-number, без маски, ломающей экранные дикторы. Контраст 4.5:1, состояние :focus-visible. "
                  "Проверка: клавиатура без мыши, NVDA и VoiceOver, axe в CI, тест на 200 % масштаба.",
        "medium": "Поставлю label к полям, ошибки красным под полем, добавлю aria-invalid. Проверю контраст и что "
                  "форма проходится табом. Можно прогнать Lighthouse.",
        "weak": "Сделаю поля побольше и подсказки placeholder внутри полей, ошибки покажу всплывающим окном.",
    },
    "traffic": {
        "strong": "Базовая модель — сезонная наивная по дню недели и часу, затем градиентный бустинг на лагах 1/7/14 дней, "
                  "календаре, погоде и событиях; валидация по времени (rolling origin), метрика MAPE и WAPE по станциям. "
                  "Отдельно — иерархическая согласованность сумм по линиям. Аномалии (праздники, перекрытия) — флагами.",
        "medium": "Возьму историю пассажиропотока, сделаю признаки по дню недели и часу, обучу случайный лес. "
                  "Проверю качество на последнем месяце по MAE.",
        "weak": "Посчитаю среднее за прошлые недели и буду использовать его как прогноз.",
    },
}


def _cands(db: Session, category: str, n: int, rnd: random.Random) -> list[CandidateProfile]:
    rows = db.scalars(select(CandidateProfile).join(User, User.id == CandidateProfile.user_id).where(
        CandidateProfile.current_category_id == category, CandidateProfile.visible_to_employers.is_(True),
        User.is_demo.is_(True), User.email.like("%@demo.invalid"))).all()
    rows = sorted(rows, key=lambda p: str(p.user_id))
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
         task_text: str | None = None, n_tasks: int = 5, rnd: random.Random) -> Cup:
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
              is_demo=True)
    db.add(cup)
    db.flush()
    return cup


def _play(db: Session, cup: Cup, p: CandidateProfile, rnd: random.Random, alias_n: int, *, state: str,
          text_key: str | None = None, demo_score: bool = True) -> CupEntry:
    """Демо-участие: state = joined | scored | submitted (ждёт оценки)."""
    skill = min(0.95, max(0.25, (p.rating_score or 0.5) + rnd.uniform(-0.15, 0.2)))
    e = CupEntry(cup_id=cup.id, candidate_user_id=p.user_id, alias=f"Участник {alias_n:02d}", status="joined", tasks=[])
    db.add(e)
    if state == "joined":
        return e
    st = cup.starts_at + timedelta(hours=rnd.uniform(1, 30))
    spent = int(rnd.uniform(0.45, 0.95) * cup.time_limit_min * 60)
    e.started_at, e.submitted_at = st, st + timedelta(seconds=spent)
    e.deadline_at, e.time_spent_s = st + timedelta(minutes=cup.time_limit_min), spent
    if cup.mode == "auto":
        items = auto.issue(cup.task_families)
        answers = {}
        for it in items:
            k = it["key"]["value"]
            if rnd.random() < skill:
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
    body = ANSWERS[text_key][lvl]
    e.answer = {"text": body, "link": None, "text_redacted": body, "redacted": []}
    e.status = "submitted"
    if demo_score:
        base = {"strong": 0.88, "medium": 0.62, "weak": 0.3}[lvl]
        e.score = round(min(1.0, max(0.0, base + rnd.uniform(-0.08, 0.08))), 3)
        e.score_method, e.status = "demo", "scored"
        e.grading = {"demo": {"level": lvl, "note": "демо: оценка выставлена генератором демо-данных"}}
    return e


def _finish(db: Session, cup: Cup, statuses: list[str]) -> None:
    """Итоги демо-кубка: штатный finalize, затем ответы кандидатов на приглашения и даты задним числом."""
    ends = cup.ends_at
    cup.ends_at = utcnow() - timedelta(seconds=1)
    db.commit()
    inv_ids = svc.finalize(db, cup, None)
    cup = db.get(Cup, cup.id)
    cup.ends_at = ends
    cup.finalized_at = ends + timedelta(hours=2)
    for iid, st in zip(inv_ids, statuses, strict=False):
        inv = db.get(Invitation, iid)
        inv.created_at = ends + timedelta(hours=3)
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
        _finish(db, cup, ["accepted", "viewed", "accepted"])
        made.append(cup.title)
    if (x := comp("Демо: Студия Интерфейсов")):
        c, u = x
        cup = _cup(db, c, u, title="Доступная форма оплаты", category="frontend.middle", mode="rubric",
                   start_days=-32, end_days=-25, salary=(190_000, 240_000), top=2, position="Frontend-разработчик",
                   description="Спроектировать форму оплаты, удобную для клавиатуры и экранных дикторов. Оценка по "
                               "рубрике: корректность, компромиссы, проверяемость.",
                   task_text="Опишите, как сделать форму оплаты картой доступной (WCAG 2.2 AA): разметка полей, ошибки, "
                             "фокус, маски ввода, проверка. Код — по желанию.", rnd=rnd)
        for i, p in enumerate(_cands(db, "frontend.middle", 6, rnd), start=1):
            _play(db, cup, p, rnd, i, state="scored", text_key="a11y")
        db.commit()
        _finish(db, cup, ["accepted", "declined"])
        made.append(cup.title)
    if (x := comp("Демо: ЛогистикПро")):
        c, u = x
        cup = _cup(db, c, u, title="Маршрутизация заказов", category="backend.middle", mode="auto", start_days=-2,
                   end_days=5, salary=(220_000, 280_000), top=3, position="Backend-разработчик (маршрутизация)",
                   description="Кубок идёт: пять заданий банка с автопроверкой на 15 минут. Лучшим трём — приглашение "
                               "с зарплатой 220–280 тыс. ₽.", rnd=rnd)
        for i, p in enumerate(_cands(db, "backend.middle", 5, rnd), start=1):
            _play(db, cup, p, rnd, i, state="scored")
        made.append(cup.title)
    if (x := comp("Демо: ГородДанные")):
        c, u = x
        cup = _cup(db, c, u, title="Прогноз пассажиропотока", category="data_ml.middle", mode="employer",
                   start_days=-3, end_days=4, salary=(200_000, 270_000), top=2, position="Data Scientist",
                   description="Предложить подход к прогнозу пассажиропотока метро на неделю вперёд. Решения "
                               "оценивает работодатель вслепую — под псевдонимами, без ссылок и контактов.",
                   task_text="Есть почасовые данные входов по станциям за 3 года, погода и календарь событий. Опишите "
                             "модель прогноза на 7 дней, валидацию и метрики.", rnd=rnd)
        for i, p in enumerate(_cands(db, "data_ml.middle", 5, rnd), start=1):
            _play(db, cup, p, rnd, i, state="submitted", text_key="traffic", demo_score=False)
        made.append(cup.title)
    if (x := comp("Демо: КиберЩит")):
        c, u = x
        cup = _cup(db, c, u, title="Разбор веб-уязвимостей", category="security.middle", mode="auto", start_days=2,
                   end_days=9, salary=(180_000, 250_000), top=2, position="Специалист по безопасности приложений",
                   description="Скоро старт: задания банка на OWASP, криптографию и сетевую безопасность, 15 минут.",
                   rnd=rnd)
        for i, p in enumerate(_cands(db, "security.middle", 2, rnd), start=1):
            _play(db, cup, p, rnd, i, state="joined")
        made.append(cup.title)
    db.commit()
    return {"cups": made}


def ensure_jury_cup(db: Session, user: User, company: Company) -> Cup | None:
    """Работодателю жюри — свой кубок «на оценке» (создаётся один раз; сброс жюри удаляет его вместе с компанией)."""
    if user.email != JURY_EMPLOYER_EMAIL or not user.is_demo:
        return None
    if db.scalar(select(Cup.id).where(Cup.company_id == company.id).limit(1)) is not None:
        return None
    rnd = random.Random(7)
    cup = _cup(db, company, user, title="Вебхуки без дублей", category="backend.middle", mode="rubric",
               start_days=-6, end_days=-0.05, salary=(240_000, 290_000), top=3,
               position="Backend-разработчик в команду платежей",
               description="Платёжный провайдер присылает вебхуки повторно и не по порядку. Нужно спроектировать "
                           "обработку без двойных списаний. Оценка по рубрике.",
               task_text="Провайдер доставляет вебхук «платёж прошёл» как минимум один раз, иногда повторно и в другом "
                         "порядке. Как обработать события так, чтобы не было двойных зачислений и потерь? Опишите "
                         "хранение, транзакции, повторы и тесты.", rnd=rnd)
    for i, p in enumerate(_cands(db, "backend.middle", 7, rnd), start=1):
        _play(db, cup, p, rnd, i, state="submitted" if i in (2, 5) else "scored", text_key="webhooks",
              demo_score=i not in (2, 5))
    db.commit()
    return cup


def delete_cups(db: Session) -> int:
    ids = db.scalars(select(Cup.id).where(Cup.is_demo.is_(True))).all()
    if not ids:
        return 0
    inv = [i for i in db.scalars(select(CupEntry.invitation_id).where(CupEntry.cup_id.in_(ids))).all() if i]
    refs = [f"cup:{i}" for i in ids]
    db.execute(delete(CandidateFact).where(CandidateFact.source_ref.in_(refs)))
    db.execute(delete(FspAchievement).where(FspAchievement.source_ref.in_(refs)))
    db.execute(delete(CupEntry).where(CupEntry.cup_id.in_(ids)))
    if inv:
        from app.modules.invitations.models import InvitationEvent

        db.execute(delete(InvitationEvent).where(InvitationEvent.invitation_id.in_(inv)))
        db.execute(delete(Invitation).where(Invitation.id.in_(inv)))
    db.execute(delete(Cup).where(Cup.id.in_(ids)))
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
        if db.scalar(select(Cup.id).where(Cup.is_demo.is_(True), Cup.company_id.in_(
                select(Company.id).where(Company.name.like("Демо: %")))).limit(1)):
            print("Демо-кубки уже есть. Для пересоздания: --reset")
            return
        print(seed_cups(db))


if __name__ == "__main__":
    main()
