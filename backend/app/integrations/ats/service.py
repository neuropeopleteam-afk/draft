"""Передача кандидата в ATS работодателя: Хантфлоу (API v2), вебхук, экспорт карточки в JSON.

Когда: автоматически при принятии приглашения (если включено ``auto_push``) и вручную — по кнопке у принятого
приглашения или у отклика на вакансию. Контакты уходят в ATS только когда они уже раскрыты работодателю
(приглашение принято / кандидат откликнулся сам) — правило ТЗ сохраняется и за пределами платформы.
Попытки: до ATS_MAX_ATTEMPTS с паузой 0,5 → 2 с; результат и ошибка — в журнале ats_deliveries (без ПДн).
"""
from __future__ import annotations

import logging
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, utcnow
from app.core.enums import InvitationStatus
from app.integrations.ats.clients import AtsError, HuntflowClient, post_webhook
from app.integrations.ats.models import AtsDelivery, AtsSettings
from app.integrations.crypto import decrypt
from app.integrations.settings import get_isettings
from app.integrations.vacancies.models import Vacancy, VacancyApplication
from app.modules.auth.models import User
from app.modules.catalog.seed_data import category_title
from app.modules.invitations.models import Invitation
from app.modules.invitations.service import candidate_contacts
from app.modules.profiles.candidate_router import candidate_card_for
from app.modules.profiles.models import CandidateProfile, Company

log = logging.getLogger(__name__)
SCHEMA = "vstrechny.candidate.v1"


def _rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₽"


def export_payload(db: Session, company: Company, *, invitation: Invitation | None = None,
                   application: VacancyApplication | None = None) -> dict:
    """Карточка кандидата для ATS / экспорта: обезличенная карточка + контакты (уже раскрытые) + контекст."""
    cand_id = invitation.candidate_user_id if invitation else application.candidate_user_id
    card = candidate_card_for(db, cand_id, include_hidden=False)
    contacts = candidate_contacts(db, cand_id)
    cp = db.get(CandidateProfile, cand_id)
    ctx: dict = {}
    if invitation is not None:
        ctx = {"type": "invitation", "id": str(invitation.id), "status": invitation.status.value,
               "position_title": invitation.position_title, "salary_from": invitation.salary_from,
               "salary_to": invitation.salary_to, "accepted_at": invitation.responded_at.isoformat()
               if invitation.responded_at else None, "evidence": invitation.evidence}
    else:
        v = db.get(Vacancy, application.vacancy_id)
        ctx = {"type": "vacancy_application", "id": str(application.id), "status": application.status,
               "vacancy_id": str(v.id), "position_title": v.title, "salary_from": v.salary_from,
               "salary_to": v.salary_to, "applied_at": application.created_at.isoformat(),
               "cover_letter": application.cover_letter}
    return {
        "schema": SCHEMA, "exported_at": utcnow().isoformat(),
        "source": {"platform": "Встречный (спецтрек ФСП)", "url": get_isettings().public_base_url},
        "company": {"id": str(company.id), "name": company.name, "inn": company.inn},
        "candidate": {"ref": cp.public_ref, "category_id": cp.current_category_id,
                      "category_title": category_title(cp.current_category_id) if cp.current_category_id else None,
                      "contacts": contacts, "card": card},
        "context": ctx,
        "evidence_levels": {"T0": "заявлено кандидатом", "T1": "подтверждено тестом/зондом",
                            "T2": "подтверждено реестром ФСП"},
    }


def _resume_text(p: dict) -> str:
    c, ctx = p["candidate"], p["context"]
    card = c.get("card") or {}
    lines = [f"Кандидат {c['ref']} с платформы «Встречный» (спецтрек ФСП).",
             f"Категория: {c.get('category_title') or 'не присвоена'}.",
             f"Позиция: {ctx.get('position_title')}; вилка {_rub(ctx['salary_from'])} – {_rub(ctx['salary_to'])}."]
    for e in ctx.get("evidence") or []:
        lines.append(f"[{e.get('level')}] {e.get('text')}")
    test = card.get("test") or {}
    if test.get("theta") is not None:
        lines.append(f"[T1] Тест: {test.get('correct')} из {test.get('answered')} верно, θ = {test['theta']:+.2f}")
    for s in (card.get("skills_confirmed") or [])[:8]:
        lines.append(f"[T1] Навык подтверждён заданиями: {s.get('title')}")
    for a in ((card.get("fsp") or {}).get("achievements") or [])[:5]:
        lines.append(f"[T2] ФСП: {a.get('text')}")
    if ctx.get("cover_letter"):
        lines.append(f"Сопроводительное письмо: {ctx['cover_letter']}")
    lines.append(f"Карточка: {p['source']['url']}/employer/candidates/{c['ref']}")
    return "\n".join(lines)


PATRONYMIC = ("вич", "вна", "ична", "чна", "оглы", "кызы")
SURNAME = ("ов", "ев", "ёв", "ин", "ын", "ова", "ева", "ёва", "ина", "ына", "ский", "цкий", "ская", "цкая", "ко", "ук",
           "юк", "дзе", "швили", "ян", "их", "ых")


def split_fio(full_name: str | None) -> tuple[str | None, str | None, str | None]:
    """(фамилия, имя, отчество) из свободной строки: «Петров Иван Сергеевич», «Иван Сергеевич Петров», «Иван Петров»."""
    parts = (full_name or "").split()
    if not parts:
        return None, None, None
    if len(parts) == 1:
        return parts[0], "—", None
    low = [x.lower() for x in parts]
    if len(parts) >= 3:
        if low[2].endswith(PATRONYMIC):
            return parts[0], parts[1], " ".join(parts[2:])
        if low[1].endswith(PATRONYMIC):
            return parts[-1], parts[0], parts[1]
        return parts[0], parts[1], " ".join(parts[2:])
    if low[1].endswith(SURNAME) and not low[0].endswith(SURNAME):
        return parts[1], parts[0], None
    return parts[0], parts[1], None


def huntflow_applicant(p: dict) -> dict:
    ct = p["candidate"]["contacts"]
    last, first, middle = split_fio(ct.get("full_name"))
    if not last:
        last, first = p["candidate"]["ref"], "Кандидат"
    ctx = p["context"]
    body = {"last_name": last, "first_name": first, "email": ct.get("email"), "phone": ct.get("phone"),
            "position": p["candidate"].get("category_title"),
            "money": f"{ctx['salary_from']}–{ctx['salary_to']} ₽ (вилка предложения)",
            "externals": [{"auth_type": "NATIVE", "data": {"body": _resume_text(p)}}]}
    if middle:
        body["middle_name"] = middle
    if ct.get("telegram"):
        body["social"] = [{"social_type": "TELEGRAM", "value": ct["telegram"].lstrip("@")}]
    return {k: v for k, v in body.items() if v not in (None, "")}


def _run_huntflow(st: AtsSettings, p: dict) -> dict:
    token = decrypt(st.huntflow_token_enc)
    if not token or not st.huntflow_account_id:
        raise AtsError("Хантфлоу: не заданы токен или id организации")
    cl = HuntflowClient(st.huntflow_base_url or get_isettings().huntflow_default_base_url, token)
    created = cl.create_applicant(st.huntflow_account_id, huntflow_applicant(p))
    res = {"applicant_id": created.get("id")}
    if st.huntflow_vacancy_id and created.get("id"):
        status_id = st.huntflow_status_id
        if not status_id:
            items = sorted(cl.statuses(st.huntflow_account_id), key=lambda s: s.get("order", 0))
            status_id = next((s["id"] for s in items if not s.get("removed")), None)
        if status_id:
            link = cl.add_to_vacancy(st.huntflow_account_id, created["id"], st.huntflow_vacancy_id, status_id,
                                     f"Принял приглашение на платформе «Встречный»: {p['context']['position_title']}")
            res.update({"vacancy_id": st.huntflow_vacancy_id, "status_id": status_id, "link_id": link.get("id")})
    return res


def _run_webhook(st: AtsSettings, p: dict, delivery_id: str, event: str) -> dict:
    secret = decrypt(st.webhook_secret_enc)
    if not st.webhook_url or not secret:
        raise AtsError("Вебхук: не заданы адрес или секрет")
    code = post_webhook(st.webhook_url, secret, event, delivery_id, {"event": event, "delivery_id": delivery_id, **p})
    return {"http_status": code}


def deliver(db: Session, company_id: uuid.UUID, *, invitation_id: uuid.UUID | None = None,
            application_id: uuid.UUID | None = None, trigger: str = "invitation_accepted",
            only: str | None = None) -> list[AtsDelivery]:
    """Отправить кандидата во все включённые ATS компании. Возвращает записи журнала."""
    st = db.get(AtsSettings, company_id)
    company = db.get(Company, company_id)
    if st is None or company is None:
        return []
    inv = db.get(Invitation, invitation_id) if invitation_id else None
    app_ = db.get(VacancyApplication, application_id) if application_id else None
    if inv is not None and (inv.status != InvitationStatus.accepted or inv.company_id != company_id):
        return []
    if inv is None and app_ is None:
        return []
    payload = export_payload(db, company, invitation=inv, application=app_)
    event = "candidate.accepted_invitation" if inv else "candidate.applied"
    targets = [t for t, on in (("huntflow", st.huntflow_enabled), ("webhook", st.webhook_enabled)) if on]
    if only:
        targets = [t for t in targets if t == only]
    out = []
    max_attempts = get_isettings().ats_max_attempts
    for target in targets:
        d = AtsDelivery(company_id=company_id, candidate_user_id=(inv or app_).candidate_user_id,
                        invitation_id=inv.id if inv else None, application_id=app_.id if app_ else None,
                        target=target, status="pending", trigger=trigger, result={})
        db.add(d)
        db.commit()  # не держим транзакцию открытой во время внешних HTTP-вызовов
        for attempt in range(1, max_attempts + 1):
            d.attempts = attempt
            try:
                d.result = _run_huntflow(st, payload) if target == "huntflow" else \
                    _run_webhook(st, payload, str(d.id), event)
                d.status, d.error, d.http_status = "ok", None, d.result.get("http_status", 200)
                break
            except AtsError as e:
                d.status, d.error, d.http_status = "error", str(e)[:500], e.status
                if e.status in (400, 401, 403, 404, 422) or attempt == max_attempts:
                    break
                time.sleep(0.5 if attempt == 1 else 2.0)
        db.commit()
        out.append(d)
    return out


def deliver_bg(company_id: uuid.UUID, **kw) -> None:
    db = SessionLocal()
    try:
        deliver(db, company_id, **kw)
    except Exception:  # noqa: BLE001 — фоновая задача не должна падать молча без лога
        log.exception("ATS delivery failed")
    finally:
        db.close()


def delivery_out(db: Session, d: AtsDelivery) -> dict:
    cp = db.get(CandidateProfile, d.candidate_user_id)
    title = None
    if d.invitation_id:
        i = db.get(Invitation, d.invitation_id)
        title = i.position_title if i else None
    elif d.application_id:
        a = db.get(VacancyApplication, d.application_id)
        v = db.get(Vacancy, a.vacancy_id) if a else None
        title = v.title if v else None
    return {"id": str(d.id), "target": d.target, "status": d.status, "attempts": d.attempts,
            "http_status": d.http_status, "result": d.result, "error": d.error, "trigger": d.trigger,
            "candidate_ref": cp.public_ref if cp else None, "position_title": title,
            "invitation_id": str(d.invitation_id) if d.invitation_id else None,
            "application_id": str(d.application_id) if d.application_id else None,
            "created_at": d.created_at.isoformat(), "updated_at": d.updated_at.isoformat()}


def company_settings(db: Session, company_id: uuid.UUID) -> AtsSettings:
    st = db.get(AtsSettings, company_id)
    if st is None:
        st = AtsSettings(company_id=company_id, auto_push=True)
        db.add(st)
        db.flush()
    return st


def employer_users(db: Session, company_id: uuid.UUID) -> list[User]:
    from app.modules.profiles.models import EmployerProfile

    return list(db.scalars(select(User).join(EmployerProfile, EmployerProfile.user_id == User.id)
                           .where(EmployerProfile.company_id == company_id)).all())
