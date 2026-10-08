"""Демо переписки и встречного предложения в песочнице жюри (вызывается из jury.seed._create_jury).

Что видно сразу после входа:
* кандидат Илья — в приглашении «Backend-разработчик (платежи)» свой вопрос (номер телефона в тексте скрыт
  маской) и непрочитанный ответ работодателя;
* работодатель «Демо жюри: Северный платёж» — три приглашения общим демо-кандидатам: встречное предложение
  ждёт решения, принятое приглашение с чатом (одно непрочитанное от кандидата), приглашение с отозванным доступом
  к контактам;
* кандидат Мария — отклик на вакансию компании жюри «Backend-разработчик (платёжные сервисы)» (создаётся здесь
  же): вопрос работодателя, ответ Марии и уточнение работодателя, непрочитанное у Марии; работодатель видит тред в
  «Откликах» вакансии и в «Сообщениях». Вакансия работодателя песочницы видна только в его песочнице
  (vacancies.router.list_vacancies), поэтому общий список вакансий не засоряется копиями.

Общие демо-кандидаты выбираются детерминированно: backend, видимые работодателям, не из первой пятёрки подборок
песочницы — чтобы сравнение кандидатов и приглашение из подборки в путеводителе не упирались в «уже приглашён» —
и не из «backend.middle»: все десять участвуют в кубках песочницы (app.cup.demo.seed_jury_cups), а приглашение
по итогам кубка той же компании упёрлось бы в лимит «одно приглашение за 30 дней» (на PostgreSQL порядок по
public_ref другой, чем на SQLite, и пересечение выпадало бы случайно).
Приглашения компании жюри не попадают в аналитику ФСП (fsp.analytics исключает «Демо жюри…»); при сбросе
песочницы удаляются вместе с компанией (ON DELETE CASCADE), вакансия и отклик Марии — вместе с компанией.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.integrations.vacancies.models import Vacancy, VacancyApplication
from app.integrations.vacancies.router import STATUS_TITLES
from app.modules.auth.models import User
from app.modules.contact import service as svc
from app.modules.contact.masking import mask_contacts
from app.modules.contact.models import ContactMessage, InvitationCounter
from app.modules.invitations import service as inv_svc
from app.modules.invitations.models import Invitation, InvitationEvent
from app.modules.matching.models import SelectionVersion
from app.modules.profiles.models import CandidateProfile, Company

DEMO_VACANCY = "Backend-разработчик (платёжные сервисы)"
CUP_POOL_CATEGORY = "backend.middle"  # кубки песочницы берут всех десять демо-кандидатов этой категории


def _msg(db: Session, *, inv: Invitation | None = None, app: VacancyApplication | None = None, user_id, side: str,
         mode: str, body: str, at: datetime, read: bool) -> ContactMessage:
    text, n = mask_contacts(body) if mode == "qa" else (body, 0)
    m = ContactMessage(invitation_id=inv.id if inv else None, application_id=app.id if app else None,
                       sender_user_id=user_id, sender_side=side, mode=mode, body=text, masked=n, created_at=at,
                       read_at=at + timedelta(minutes=20) if read else None)
    db.add(m)
    return m


def _retime(db: Session, inv: Invitation, start: datetime, step: timedelta) -> None:
    """События и встречные приглашения — в прошлое по порядку создания: история в карточке выглядит живой."""
    inv.created_at = start
    evs = db.scalars(select(InvitationEvent).where(InvitationEvent.invitation_id == inv.id)
                     .order_by(InvitationEvent.created_at)).all()
    for k, e in enumerate(evs):
        e.created_at = start + step * k
    for c in db.scalars(select(InvitationCounter).where(InvitationCounter.invitation_id == inv.id)).all():
        c.created_at = start + step
    if inv.viewed_at:
        inv.viewed_at = start + step
    if inv.responded_at:
        inv.responded_at = start + step * 2
    if inv.contacts_revealed_at:
        inv.contacts_revealed_at = start + step * 2
    if inv.contacts_revoked_at:
        inv.contacts_revoked_at = start + step * 3  # как у события «Доступ к контактам отозван»


def shared_candidates(db: Session, needs: list, k: int = 3) -> list[CandidateProfile]:
    """k общих демо-кандидатов backend вне первой пятёрки подборок песочницы (детерминированно)."""
    top: set[str] = set()
    for n in needs:
        sv = db.scalar(select(SelectionVersion).where(SelectionVersion.need_id == n.id)
                       .order_by(SelectionVersion.version.desc()).limit(1))
        top |= {r.get("ref") for r in ((sv.results if sv else None) or [])[:5]}
    rows = db.scalars(
        select(CandidateProfile).join(User, User.id == CandidateProfile.user_id)
        .where(User.email.like("demo-candidate-%@demo.invalid"), CandidateProfile.visible_to_employers.is_(True),
               CandidateProfile.current_category_id.like("backend.%"),
               CandidateProfile.current_category_id != CUP_POOL_CATEGORY)
        .order_by(CandidateProfile.public_ref)).all()
    return [p for p in rows if p.public_ref not in top][:k]


def seed_jury_contact(db: Session, eu: User, c: Company, ilya: CandidateProfile, maria: CandidateProfile,
                      needs: list) -> dict:
    now = utcnow()
    out = {"qa": 0, "counter": None, "chat": None, "revoked": None, "application": None}
    # 1. Илья: вопрос до принятия (телефон скрыт) и непрочитанный ответ работодателя
    ii = db.scalar(select(Invitation).where(Invitation.company_id == c.id, Invitation.candidate_user_id == ilya.user_id))
    if ii is not None and ii.status in svc.OPEN:
        inv_svc.mark_viewed(db, ii, ilya.user_id)
        _retime(db, ii, now - timedelta(hours=5), timedelta(hours=1))  # отправлено и просмотрено до переписки
        _msg(db, inv=ii, user_id=ilya.user_id, side="candidate", mode="qa", at=now - timedelta(hours=3), read=True,
             body="Здравствуйте. Подскажите, сколько человек в команде платежей и есть ли дежурства? "
                  "Если удобнее голосом — мой номер +7 912 345-67-89.")
        _msg(db, inv=ii, user_id=eu.id, side="employer", mode="qa", at=now - timedelta(hours=1), read=False,
             body="Добрый день. В команде шесть разработчиков и тестировщик, дежурства раз в шесть недель, с "
                  "доплатой. Созвонимся, как только вы примете приглашение: тогда откроются контакты.")
        db.commit()
        out["qa"] = 2
    a, b, cc = (shared_candidates(db, needs) + [None, None, None])[:3]
    need_id = needs[0].id if needs else None
    # 2. Встречное предложение ждёт решения работодателя
    if a is not None:
        i = inv_svc.create_invitation(db, eu, c, a, position_title="Backend-разработчик (интеграции с банками)",
                                      offer_description="Интеграции с банками-партнёрами: FastAPI, PostgreSQL, Kafka. "
                                                        "Удалённо.", salary_from=250_000, salary_to=290_000,
                                      contact_method="Почта HR", need_id=need_id, probe_id=None)
        svc.create_counter(db, i, a.user_id, 290_000, 330_000, "gross",
                           "Последний год веду интеграции с банками на FastAPI и Kafka и могу выйти через две "
                           "недели. Прошу вилку ближе к верхней границе рынка.")
        _msg(db, inv=i, user_id=a.user_id, side="candidate", mode="qa", at=now - timedelta(hours=20), read=True,
             body="Здравствуйте. Отправил встречную вилку. Можно уточнить, сколько банков-партнёров сейчас в работе?")
        _msg(db, inv=i, user_id=eu.id, side="employer", mode="qa", at=now - timedelta(hours=18), read=True,
             body="Здравствуйте. Сейчас четыре банка, в планах ещё два до конца года.")
        _retime(db, i, now - timedelta(days=2), timedelta(hours=6))
        db.commit()
        out["counter"] = a.public_ref
    # 3. Принятое приглашение — обычный чат, одно непрочитанное от кандидата
    if b is not None:
        i = inv_svc.create_invitation(db, eu, c, b, position_title="Python-разработчик (платёжный шлюз)",
                                      offer_description="Платёжный шлюз: FastAPI, PostgreSQL, Redis. Гибрид.",
                                      salary_from=230_000, salary_to=270_000, contact_method="Звонок 20 минут",
                                      need_id=need_id, probe_id=None)
        inv_svc.respond(db, i, b.user_id, True, None)
        _retime(db, i, now - timedelta(days=3), timedelta(hours=5))
        _msg(db, inv=i, user_id=eu.id, side="employer", mode="chat", at=now - timedelta(hours=26), read=True,
             body="Спасибо, что приняли приглашение. Удобно созвониться в четверг в 11:00?")
        _msg(db, inv=i, user_id=b.user_id, side="candidate", mode="chat", at=now - timedelta(hours=2), read=False,
             body="Добрый день. Да, четверг в 11:00 подходит. Ссылку на встречу пришлите, пожалуйста, на почту.")
        db.commit()
        out["chat"] = b.public_ref
    # 4. Принято, затем кандидат отозвал доступ к контактам
    if cc is not None:
        i = inv_svc.create_invitation(db, eu, c, cc, position_title="Backend-разработчик (антифрод)",
                                      offer_description="Сервис антифрода: Python, PostgreSQL, ClickHouse. Удалённо.",
                                      salary_from=240_000, salary_to=280_000, contact_method="Почта HR",
                                      need_id=need_id, probe_id=None)
        inv_svc.respond(db, i, cc.user_id, True, None)
        svc.revoke_contacts(db, i, cc.user_id)
        _retime(db, i, now - timedelta(days=4), timedelta(hours=10))
        _msg(db, inv=i, user_id=cc.user_id, side="candidate", mode="qa", at=now - timedelta(hours=40), read=True,
             body="Спасибо за предложение. Я принял оффер в другой компании, поэтому закрыл контакты.")
        db.commit()
        out["revoked"] = cc.public_ref
    # 5. Мария: отклик на вакансию компании жюри и переписка по отклику (видна обеим сторонам)
    v = db.scalar(select(Vacancy).where(Vacancy.company_id == c.id, Vacancy.title == DEMO_VACANCY).limit(1))
    if v is None:
        v = Vacancy(company_id=c.id, created_by=eu.id, title=DEMO_VACANCY, category_id="backend.middle",
                    description="Сервисы платежей для малого бизнеса: API на FastAPI, PostgreSQL, очереди Kafka. "
                                "Код-ревью, тесты, дежурства по графику с доплатой. Удалённо или гибрид.",
                    stack=["python", "fastapi", "postgresql", "kafka"], salary_from=220_000, salary_to=280_000,
                    salary_basis="gross", work_format="remote", city="Санкт-Петербург", status="published",
                    published_at=now - timedelta(days=5), is_demo=True)
        db.add(v)
        db.flush()
    if db.scalar(select(VacancyApplication.id).where(VacancyApplication.vacancy_id == v.id,
                                                     VacancyApplication.candidate_user_id == maria.user_id)) is None:
        t0 = now - timedelta(hours=30)
        ap = VacancyApplication(vacancy_id=v.id, candidate_user_id=maria.user_id, status="viewed", viewed_at=t0 +
                                timedelta(hours=4), cover_letter="Делаю бэкенд на FastAPI и PostgreSQL, на "
                                "чемпионате отвечала за API и очереди.",
                                events=[{"at": t0.isoformat(), "status": "sent", "title": STATUS_TITLES["sent"],
                                         "by": "candidate"},
                                        {"at": (t0 + timedelta(hours=4)).isoformat(), "status": "viewed",
                                         "title": STATUS_TITLES["viewed"], "by": "employer"}])
        db.add(ap)
        db.flush()
        _msg(db, app=ap, user_id=eu.id, side="employer", mode="chat", at=t0 + timedelta(hours=5), read=True,
             body="Спасибо за отклик. Посмотрели паспорт ФСП: расскажите, какую часть решения на чемпионате делали "
                  "вы и сколько длился проект?")
        _msg(db, app=ap, user_id=maria.user_id, side="candidate", mode="chat", at=t0 + timedelta(hours=9), read=True,
             body="Проект шёл трое суток. Я делала API заказов на FastAPI и очередь на Kafka с повторами, напарник — "
                  "фронтенд. Код в репозитории команды, могу показать на созвоне.")
        _msg(db, app=ap, user_id=eu.id, side="employer", mode="chat", at=now - timedelta(hours=1, minutes=30),
             read=False, body="Отлично. Предлагаем созвон на 30 минут во вторник или среду после 15:00 — какой день "
                               "удобнее?")
        db.commit()
        out["application"] = str(ap.id)
    return out


__all__ = ["seed_jury_contact", "shared_candidates"]
