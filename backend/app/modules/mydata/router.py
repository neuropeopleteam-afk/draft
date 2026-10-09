"""API «Мои данные» кандидата: что хранится, выгрузка одним файлом, отзыв доступа к контактам, удаление учётной записи,
обезличенная отметка интереса. Только роль candidate; чужие данные недоступны (всё считается по ``user.id`` из токена)."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db, utcnow
from app.core.deps import require_role
from app.core.enums import ConsentKind, InvitationStatus, UserRole
from app.core.errors import api_error, err
from app.core.legal import CONSENT_VERSION, OPERATOR
from app.core.ratelimit import SlidingWindow, hit
from app.modules.auth import twofa
from app.modules.auth.models import Consent, User
from app.modules.mydata import erase, export, interest
from app.modules.profiles.models import CandidateProfile

log = logging.getLogger("mydata")
router = APIRouter(prefix="/api/me", tags=["my-data"])
AUTH = {401: err("Не выполнен вход"), 403: err("Только для кандидата")}
candidate = require_role(UserRole.candidate)

# Подтверждение удаления: неверные попытки — не больше 8 за 15 минут на учётную запись (перебор пароля)
_delete_attempts = SlidingWindow(8, 900)
# Выгрузка собирает много таблиц — не чаще 10 раз в час
_exports = SlidingWindow(10, 3600)

BACKUPS = ("Резервные копии базы данных хранятся в закрытом контуре оператора; копии перезаписываются по кругу — "
           "хранятся не более 14 последних. Ваши данные остаются в них до вытеснения новыми копиями (при ежедневном "
           "графике — около двух недель). В работе копии не используются; восстановление из копии — только при аварии.")
NOT_IN_OUR_POWER = [
    "Контакты, которые вы открыли работодателю, принимая приглашение: он уже получил их по вашему согласию, и копии "
    "у него мы удалить не можем. Чтобы такого не повторилось, до удаления отзовите доступ к контактам.",
    "Записи работодателя о вас в его собственных системах (ATS, почта, заметки): они вне платформы.",
]


# ------------------------------------------------------------------ обзор

def _count(db: Session, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


def _consents(db: Session, uid) -> list[dict]:
    titles = {"processing": "Обработка персональных данных", "publication": "Показ обезличенного профиля работодателям",
              "proctoring": "Анализ камеры во время теста"}
    out = []
    for kind in ConsentKind:
        last = db.scalar(select(Consent).where(Consent.user_id == uid, Consent.kind == kind)
                         .order_by(Consent.granted_at.desc()).limit(1))
        active = bool(last and last.revoked_at is None)
        out.append({"kind": kind.value, "title": titles[kind.value], "active": active,
                    "granted_at": last.granted_at.isoformat() if last else None,
                    "revoked_at": last.revoked_at.isoformat() if last and last.revoked_at else None,
                    "version": last.document_version if last else None,
                    # согласие на обработку отзывается удалением учётной записи, остальные — кнопкой «Отозвать»
                    "revoke": "delete_account" if kind.value == "processing" else "button" if active else None})
    return out


def _contacts_open(db: Session, uid) -> list[dict]:
    from app.modules.invitations.models import Invitation
    from app.modules.profiles.models import Company

    rows = db.execute(select(Invitation, Company.name).join(Company, Company.id == Invitation.company_id).where(
        Invitation.candidate_user_id == uid, Invitation.status == InvitationStatus.accepted,
        Invitation.contacts_revealed_at.is_not(None)).order_by(Invitation.contacts_revealed_at.desc())).all()
    return [{"invitation_id": str(i.id), "company": name, "position_title": i.position_title,
             "since": i.contacts_revealed_at.isoformat(),
             "what": "телефон, Telegram и почта из профиля"} for i, name in rows]


def overview(db: Session, user: User) -> dict:
    from app.integrations.vacancies.models import VacancyApplication
    from app.modules.assessment.models import GradeHistory, SurveyResponse, TestAnswer, TestSession
    from app.modules.contact.models import ContactMessage, InvitationCounter
    from app.modules.invitations.models import Invitation, Probe
    from app.modules.proctor.models import ProctorSession
    from app.modules.profiles.models import CandidateFact, CandidateResume, CandidateSpecialization

    uid = user.id
    p = db.get(CandidateProfile, uid)
    n_tests = _count(db, TestSession, TestSession.user_id == uid)
    owned = erase.owned_tables(uid)
    n_prefs = sum(db.scalar(select(func.count()).select_from(t).where(c)) or 0
                  for name, (t, c) in owned.items() if name in ("candidate_preferences", "assignment_prefs", "notify_prefs", "user_notifications"))
    n_msgs = _count(db, ContactMessage, ContactMessage.invitation_id.in_(
        select(Invitation.id).where(Invitation.candidate_user_id == uid)))
    from app.modules.hiring.models import HiringInterview, HiringOffer, HiringOutcome
    from app.modules.study.models import StudyEvent, StudyParticipant

    n_hiring = sum(_count(db, m, m.candidate_user_id == uid) for m in (HiringInterview, HiringOffer, HiringOutcome))
    n_study = _count(db, StudyEvent, StudyEvent.participant_id.in_(
        select(StudyParticipant.id).where(StudyParticipant.user_id == uid)))
    stored = [
        {"key": "account", "title": "Учётная запись", "count": 1, "kept": "пока вы не удалите учётную запись",
         "what": "почта, роль, даты регистрации и входа; пароль хранится только в виде хеша"},
        {"key": "profile", "title": "Профиль", "count": 1 if p else 0, "kept": "пока вы не удалите учётную запись",
         "what": "имя, телефон, Telegram, город, формат работы, скрытый минимум зарплаты, настройки приватности"},
        {"key": "specializations", "title": "Направления и категории", "count": _count(db, CandidateSpecialization, CandidateSpecialization.user_id == uid),
         "what": "направление, грейд, категория, статус подтверждения"},
        {"key": "survey", "title": "Опросы", "count": _count(db, SurveyResponse, SurveyResponse.user_id == uid),
         "what": "ответы опроса после регистрации и стек с вашей оценкой уровня"},
        {"key": "facts", "title": "Факты и навыки", "count": _count(db, CandidateFact, CandidateFact.user_id == uid),
         "what": "то, что вы указали или подтвердили тестом, и уровень доказанности"},
        {"key": "resumes", "title": "Резюме", "count": _count(db, CandidateResume, CandidateResume.user_id == uid),
         "what": "текст резюме без ФИО и контактов и извлечённые поля; исходный файл не сохраняется"},
        {"key": "tests", "title": "Попытки теста и ответы", "count": n_tests,
         "what": "ваши ответы (сейчас — "
                 f"{_count(db, TestAnswer, TestAnswer.session_id.in_(select(TestSession.id).where(TestSession.user_id == uid)))}), "
                 "время, итог и достоверность результата"},
        {"key": "grade_history", "title": "История грейда", "count": _count(db, GradeHistory, GradeHistory.user_id == uid),
         "what": "смены грейда и их причины"},
        {"key": "camera", "title": "Камера во время теста (по согласию)", "count": _count(db, ProctorSession, ProctorSession.user_id == uid),
         "what": "только события и время наблюдения; кадры, лицо и звук не хранятся"},
        {"key": "consents", "title": "Согласия", "count": _count(db, Consent, Consent.user_id == uid),
         "what": "какое согласие, какая редакция текста, когда дано и отозвано"},
        {"key": "invitations", "title": "Приглашения работодателей", "count": _count(db, Invitation, Invitation.candidate_user_id == uid),
         "what": "приглашение, ваш ответ, причина отказа, встречные предложения, доступ к контактам"},
        {"key": "probes", "title": "Зонды (короткие задачи)", "count": _count(db, Probe, Probe.candidate_user_id == uid),
         "what": "задача от работодателя и ваш ответ"},
        {"key": "applications", "title": "Отклики на вакансии", "count": _count(db, VacancyApplication, VacancyApplication.candidate_user_id == uid),
         "what": "отклик, сопроводительное письмо, статус"},
        {"key": "messages", "title": "Переписка с работодателями", "count": n_msgs,
         "what": "сообщения по приглашениям и откликам"},
        {"key": "counters", "title": "Встречные предложения", "count": _count(db, InvitationCounter, InvitationCounter.candidate_user_id == uid),
         "what": "ваша вилка в ответ на приглашение"},
        {"key": "prefs", "title": "Предпочтения и уведомления", "count": n_prefs,
         "what": "готовность к предложениям и интересы, настройки уведомлений и ленты заданий, сами уведомления"},
        {"key": "hiring", "title": "Этапы найма", "count": n_hiring,
         "what": "собеседования, офферы и исход по принятым приглашениям; у работодателя остаются как история без ваших текстов"},
        {"key": "study", "title": "Статистика прохождения", "count": n_study,
         "what": "роль, время шагов, адреса экранов и коды ошибок без содержимого — пока вы не нажали «Не участвовать» на /study; "
                 "привязана к учётной записи, после удаления учётной записи — отвязывается"},
    ]
    inter = interest.summary(db, uid)
    return {
        "stored": [s for s in stored],
        "interest": {k: inter[k] for k in ("employers_viewed", "selections", "probes")},
        "consents": _consents(db, uid),
        "contacts_open_to": _contacts_open(db, uid),
        "delete": {"phrase": "УДАЛИТЬ", "needs_password": erase.uses_password(user), "needs_email": not erase.uses_password(user),
                   "needs_code": twofa.enabled(db, user), "demo": bool(user.is_demo)},
        "retention": [
            {"what": "Данные учётной записи", "term": "пока вы пользуетесь платформой; после удаления — сразу"},
            {"what": "Попытки теста, ответы, события камеры", "term": "пока не удалите учётную запись; камера — вместе с попыткой"},
            {"what": "События интереса работодателей (без названий)", "term": f"{interest.KEEP_DAYS} дней"},
            {"what": "Резервные копии базы", "term": "до 14 последних копий"},
        ],
        "backups": BACKUPS, "not_in_our_power": NOT_IN_OUR_POWER,
        "operator": {"name": OPERATOR["short_name"], "email": OPERATOR["email"], "storage": OPERATOR["storage"]},
        "consent_version": CONSENT_VERSION,
    }


@router.get("/data", summary="Мои данные: что о вас хранится, согласия, кому открыты контакты, правила удаления",
            responses=AUTH)
def my_data(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return overview(db, user)


# ------------------------------------------------------------------ выгрузка

@router.get("/data/export", summary="Скачать все данные одним JSON-файлом (152-ФЗ, ст. 14)",
            description="Только ваши данные: без почт и имён работодателей, без других кандидатов, без текстов заданий и "
                        "ключей. Достоверность результата — в том виде, как её видит кандидат. Секреты не выгружаются.",
            responses={**AUTH, 429: err("Слишком часто")})
def my_data_export(user: User = Depends(candidate), db: Session = Depends(get_db)) -> Response:
    if not user.is_demo:
        hit(_exports, f"export:{user.id}", "export_rate", "Выгрузка уже запрашивалась несколько раз подряд")
    data = export.build(db, user)
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    name = f"moi-dannye-{utcnow().strftime('%Y%m%d')}.json"
    return Response(body, media_type="application/json; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


# ------------------------------------------------------------------ отзыв доступа к контактам

@router.post("/data/contacts/revoke", summary="Отозвать доступ к контактам у всех работодателей сразу",
             description="Для каждого принятого приглашения с открытыми контактами: карточка снова обезличена. Уже "
                         "полученные работодателем контакты вернуть нельзя. Доступ можно вернуть по каждому приглашению.",
             responses=AUTH)
def revoke_all_contacts(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    from app.modules.contact import service as contact_svc
    from app.modules.invitations.models import Invitation

    rows = db.scalars(select(Invitation).where(
        Invitation.candidate_user_id == user.id, Invitation.status == InvitationStatus.accepted,
        Invitation.contacts_revealed_at.is_not(None))).all()
    for inv in rows:
        contact_svc.revoke_contacts(db, inv, user.id)
    return {"revoked": len(rows), "contacts_open_to": _contacts_open(db, user.id)}


# ------------------------------------------------------------------ удаление

class DeleteIn(BaseModel):
    confirm: str = Field(description="Слово УДАЛИТЬ")
    password: str | None = Field(None, max_length=200, description="Пароль (для учётных записей с паролем)")
    email: str | None = Field(None, max_length=254, description="Своя почта (демо-учётки и вход через ФСП ID)")
    code: str | None = Field(None, max_length=32, description="Код второго фактора, если он подключён")


@router.get("/data/delete/preview", summary="Что будет удалено сразу и что обезличено — до подтверждения",
            responses=AUTH)
def delete_preview(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return {**erase.preview(db, user), "not_in_our_power": NOT_IN_OUR_POWER, "backups": BACKUPS,
            "contacts_open_to": _contacts_open(db, user.id),
            "confirm": {"phrase": "УДАЛИТЬ", "needs_password": erase.uses_password(user),
                        "needs_email": not erase.uses_password(user), "needs_code": twofa.enabled(db, user)}}


@router.post("/data/delete", summary="Удалить учётную запись (отзыв согласия на обработку): сразу и необратимо",
             description="Подтверждение: слово УДАЛИТЬ + пароль (демо-учётка и вход через ФСП ID — своя почта) + код "
                         "второго фактора, если он подключён. Профиль, тесты, ответы, резюме, согласия и остальное "
                         "стираются сразу; записи работодателей остаются без привязки к вам (docs/MY_DATA.md).",
             responses={**AUTH, 403: err("Неверный пароль, почта или код"), 422: err("Не введено слово УДАЛИТЬ"),
                        429: err("Слишком много неверных попыток")})
def delete_account(data: DeleteIn, user: User = Depends(candidate),
                   db: Session = Depends(get_db)) -> dict:
    from app.modules.jury import scope

    persona, sid = scope.parse(user.email)
    if user.is_demo and persona is not None and not sid:
        raise api_error(403, "jury_shared", "Общее демо одно на всех экспертов жюри и не удаляется — войдите в свою песочницу")
    key = f"del:{user.id}"
    hit(_delete_attempts, key, "too_many_attempts", "Слишком много попыток подтверждения удаления")
    erase.confirm(db, user, password=data.password, email=data.email, phrase=data.confirm, code=data.code)
    res = erase.erase(db, user)
    if res.notify_email:
        _notify(res.notify_email)
    return {"ok": True, "deleted": res.deleted, "anonymized": res.anonymized, "not_in_our_power": NOT_IN_OUR_POWER,
            "backups": BACKUPS}


def _notify(to: str) -> None:
    """Письмо-подтверждение удаления на прежнюю почту (без ПДн в тексте). Сбой отправки удаление не отменяет."""
    try:
        from app.modules.notifications.mailer import Message, get_mailer

        text = ("Учётная запись удалена по вашему запросу.\n\nЛичные данные, тесты, ответы, резюме и согласия стёрты. "
                "Записи работодателей (приглашения, зонды, отклики) остались без привязки к вам. Копии баз "
                "перезаписываются по кругу и не используются в работе.\n\nЕсли это были не вы, напишите оператору: "
                f"{OPERATOR['email']}.")
        get_mailer().send(Message(to=to, subject="Учётная запись удалена", text=text, html=None))
    except Exception:  # noqa: BLE001
        log.warning("Письмо об удалении не отправлено", exc_info=True)


# ------------------------------------------------------------------ интерес

@router.get("/interest", summary="Отметка интереса за неделю: сколько работодателей смотрели карточку, в скольких подборках, "
                                 "сколько зондов — без названий компаний", responses=AUTH)
def my_interest(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return {**interest.summary(db, user.id), "demo": bool(user.is_demo)}  # demo: цифры песочницы жюри — модельные
