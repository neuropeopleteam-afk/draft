"""Передача кандидата в ATS работодателя: Хантфлоу (API v2), Talantix (GraphQL), «Поток» (REST v3), вебхук,
экспорт карточки в JSON. Провайдеры — общий интерфейс providers/base.Provider.

Когда: автоматически при принятии приглашения (если включено ``auto_push``) и вручную — по кнопке у принятого
приглашения или у отклика на вакансию. Контакты уходят в ATS только когда они уже раскрыты работодателю
(приглашение принято / кандидат откликнулся сам) — правило ТЗ сохраняется и за пределами платформы.
Попытки: до ATS_MAX_ATTEMPTS с паузой 0,5 → 2 с; результат и ошибка — в журнале ats_deliveries (без ПДн).
Идемпотентность: ats_links (кандидат платформы → id в ATS и вакансии) — повтор не создаёт дубликат,
короткая блокировка строки связи защищает от гонки двух воркеров (авто-передача и кнопка одновременно).
"""
from __future__ import annotations

from datetime import timedelta
import logging
import time
import uuid

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, as_aware, utcnow
from app.core.enums import InvitationStatus
from app.integrations.ats import profile as prof
from app.integrations.ats import providers
from app.integrations.ats.clients import AtsError, post_webhook
from app.integrations.ats.models import AtsDelivery, AtsLink, AtsSettings
from app.integrations.ats.profile import split_fio  # noqa: F401 — совместимость импорта
from app.integrations.ats.providers.base import LinkState, Target
from app.integrations.ats.providers.huntflow import applicant_body as hf_body
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
SCHEMA = "draft.candidate.v1"
LOCK_S = 90
TARGET_TITLES = {"huntflow": "Хантфлоу", "talantix": "Talantix", "potok": "Поток", "webhook": "Вебхук"}
NO_RETRY = (400, 401, 402, 403, 404, 422)


def export_payload(db: Session, company: Company, *, invitation: Invitation | None = None,
                   application: VacancyApplication | None = None) -> dict:
    """Карточка кандидата для ATS / экспорта / вебхука:
    - до согласия кандидата (приглашение ещё не принято или отозвано, либо чужая компания) — только ``candidate_ref``,
      ``consent=False``, ``consent_at=None``, ``contacts=None`` (без ПДн);
    - после принятия приглашения этой компании (или при самостоятельном отклике на её вакансию) — раскрытые кандидатом
      контакты (``name``/``full_name``, ``email``, ``phone``, ``telegram`` с учётом ``shared_contacts``),
      ``consent=True`` и ``consent_at`` (ISO-время согласия).
    """
    cand_id = invitation.candidate_user_id if invitation else application.candidate_user_id
    cp = db.get(CandidateProfile, cand_id)
    ref = cp.public_ref if cp else None
    base = get_isettings().public_base_url.rstrip("/")

    if invitation is not None:
        has_consent = bool(
            invitation.company_id == company.id
            and invitation.status == InvitationStatus.accepted
            and invitation.contacts_revealed_at is not None
            and cp is not None
            and cp.deleted_at is None
        )
        if not has_consent:
            status_val = invitation.status.value if hasattr(invitation.status, "value") else str(invitation.status)
            return {
                "schema": SCHEMA,
                "exported_at": utcnow().isoformat(),
                "source": {"platform": "Драфт (спецтрек ФСП)", "url": base},
                "company": {"id": str(company.id), "name": company.name, "inn": company.inn},
                "candidate_ref": ref,
                "consent": False,
                "consent_at": None,
                "contacts": None,
                "candidate": {
                    "ref": ref,
                    "consent": False,
                    "consent_at": None,
                    "contacts": None,
                },
                "context": {
                    "type": "invitation",
                    "id": str(invitation.id),
                    "status": status_val,
                    "position_title": invitation.position_title,
                    "consent": False,
                    "consent_at": None,
                },
            }
        consent_dt = as_aware(invitation.contacts_revealed_at or invitation.responded_at)
        consent_at = consent_dt.isoformat() if consent_dt is not None else utcnow().isoformat()
        contacts = candidate_contacts(db, cand_id, invitation)
        ctx = {
            "type": "invitation",
            "id": str(invitation.id),
            "status": invitation.status.value,
            "position_title": invitation.position_title,
            "salary_from": invitation.salary_from,
            "salary_to": invitation.salary_to,
            "accepted_at": invitation.responded_at.isoformat() if invitation.responded_at else consent_at,
            "consent": True,
            "consent_at": consent_at,
            "evidence": invitation.evidence,
        }
    else:
        v = db.get(Vacancy, application.vacancy_id)
        if v is None or v.company_id != company.id or cp is None or cp.deleted_at is not None:
            return {
                "schema": SCHEMA,
                "exported_at": utcnow().isoformat(),
                "source": {"platform": "Драфт (спецтрек ФСП)", "url": base},
                "company": {"id": str(company.id), "name": company.name, "inn": company.inn},
                "candidate_ref": ref,
                "consent": False,
                "consent_at": None,
                "contacts": None,
                "candidate": {"ref": ref, "consent": False, "consent_at": None, "contacts": None},
                "context": {"type": "vacancy_application", "id": str(application.id), "consent": False, "consent_at": None},
            }
        consent_dt = as_aware(application.created_at)
        consent_at = consent_dt.isoformat() if consent_dt is not None else utcnow().isoformat()
        contacts = candidate_contacts(db, cand_id)
        ctx = {
            "type": "vacancy_application",
            "id": str(application.id),
            "status": application.status,
            "vacancy_id": str(v.id),
            "position_title": v.title,
            "salary_from": v.salary_from,
            "salary_to": v.salary_to,
            "applied_at": application.created_at.isoformat(),
            "consent": True,
            "consent_at": consent_at,
            "cover_letter": application.cover_letter,
        }

    card = candidate_card_for(db, cand_id, include_hidden=False)
    return {
        "schema": SCHEMA,
        "exported_at": utcnow().isoformat(),
        "source": {"platform": "Драфт (спецтрек ФСП)", "url": base},
        "company": {"id": str(company.id), "name": company.name, "inn": company.inn},
        "candidate_ref": ref,
        "consent": True,
        "consent_at": consent_at,
        "contacts": contacts,
        "candidate": {
            "ref": ref,
            "fsp_id": cp.fsp_id_claimed,
            "category_id": cp.current_category_id,
            "category_title": category_title(cp.current_category_id) if cp.current_category_id else None,
            "consent": True,
            "consent_at": consent_at,
            "contacts": contacts,
            "card": card,
        },
        "context": ctx,
        "links": {
            "pdf": prof.pdf_url(str(company.id), str(cand_id)),
            "card": f"{base}/employer/candidates/{ref}",
        },
        "evidence_levels": {
            "T0": "заявлено кандидатом",
            "T1": "подтверждено тестом/зондом",
            "T2": "подтверждено реестром ФСП",
        },
    }


def huntflow_applicant(p: dict) -> dict:
    """Тело POST /accounts/{id}/applicants Хантфлоу из карточки ``draft.candidate.v1``."""
    return hf_body(prof.build(p))


def _target(db: Session, company_id: uuid.UUID, code: str, st: AtsSettings, *,
            application: VacancyApplication | None, override: int | None) -> Target:
    """Вакансия в ATS: явно выбранная при передаче → сопоставление вакансии платформы → вакансия по умолчанию."""
    if code == "huntflow":
        return Target(vacancy_id=override or st.huntflow_vacancy_id, stage_id=st.huntflow_status_id)
    conn = providers.connection(db, company_id, code, create=False)
    if override:
        return Target(vacancy_id=override)
    if application is not None:
        m = (conn.vacancy_map or {}).get(str(application.vacancy_id))
        if m and m.get("id"):
            return Target(vacancy_id=int(m["id"]), vacancy_title=m.get("title"), stage_id=m.get("stage_id"),
                          stage_title=m.get("stage_title"))
    return Target(vacancy_id=conn.vacancy_id, vacancy_title=conn.vacancy_title, stage_id=conn.stage_id,
                  stage_title=conn.stage_title)


def _link(db: Session, company_id: uuid.UUID, code: str, cand_id: uuid.UUID) -> AtsLink:
    """Связь кандидата с ATS под короткой блокировкой (два воркера, двойной клик, авто-передача + кнопка)."""
    q = select(AtsLink).where(AtsLink.company_id == company_id, AtsLink.provider == code,
                              AtsLink.candidate_user_id == cand_id)
    link = db.scalar(q)
    if link is None:
        db.add(AtsLink(company_id=company_id, provider=code, candidate_user_id=cand_id, vacancies=[]))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        link = db.scalar(q)
    now = utcnow()
    got = db.execute(update(AtsLink).where(AtsLink.id == link.id,
                                           or_(AtsLink.lock_until.is_(None), AtsLink.lock_until < now))
                     .values(lock_until=now + timedelta(seconds=LOCK_S))
                     .execution_options(synchronize_session=False)).rowcount
    db.commit()
    if got != 1:
        raise AtsError("Передача этого кандидата уже идёт — повтор через пару секунд", 409)
    db.refresh(link)
    return link


def _run_provider(db: Session, company_id: uuid.UUID, code: str, st: AtsSettings, p: dict, *,
                  cand_id: uuid.UUID, application: VacancyApplication | None, override: int | None,
                  force: bool) -> dict:
    if code == "huntflow" and not st.huntflow_account_id:
        raise AtsError("Хантфлоу: не задан id организации (account_id)", 422)
    provider = providers.make(db, company_id, code)
    target = _target(db, company_id, code, st, application=application, override=override)
    link = _link(db, company_id, code, cand_id)

    def saver(ls: LinkState) -> None:  # id в ATS фиксируем сразу: следующий шаг может упасть, повтор продолжит
        link.external_id, link.vacancies = ls.external_id, [dict(v) for v in ls.vacancies]
        db.commit()

    ls = LinkState(external_id=link.external_id, vacancies=[dict(v) for v in (link.vacancies or [])], saver=saver)
    try:
        res = provider.push(prof.build(p), target, ls, force=force)
    finally:
        link.lock_until = None
        db.commit()
    res["external_id"] = str(res["external_id"]) if res.get("external_id") is not None else None
    return res


def _run_webhook(st: AtsSettings, p: dict, delivery_id: str, event: str) -> dict:
    secret = decrypt(st.webhook_secret_enc)
    if not st.webhook_url or not secret:
        raise AtsError("Вебхук: не заданы адрес или секрет")
    code = post_webhook(st.webhook_url, secret, event, delivery_id, {"event": event, "delivery_id": delivery_id, **p})
    return {"http_status": code}


def deliver(db: Session, company_id: uuid.UUID, *, invitation_id: uuid.UUID | None = None,
            application_id: uuid.UUID | None = None, trigger: str = "invitation_accepted",
            only: str | set[str] | list[str] | None = None, vacancy_override: int | None = None,
            force: bool = False) -> list[AtsDelivery]:
    """Отправить кандидата во все включённые ATS компании (или только в ``only``). Возвращает записи журнала."""
    st = db.get(AtsSettings, company_id)
    company = db.get(Company, company_id)
    if st is None or company is None:
        return []
    inv = db.get(Invitation, invitation_id) if invitation_id else None
    app_ = db.get(VacancyApplication, application_id) if application_id else None
    if inv is not None and (inv.status != InvitationStatus.accepted or inv.company_id != company_id
                            or inv.contacts_revealed_at is None):  # доступ к контактам отозван кандидатом
        return []
    if inv is None and app_ is None:
        return []
    payload = export_payload(db, company, invitation=inv, application=app_)
    event = "candidate.accepted_invitation" if inv else "candidate.applied"
    targets = providers.enabled_targets(db, company_id, st)
    if only:
        want = {only} if isinstance(only, str) else set(only)
        targets = [t for t in targets if t in want]
    cand_id = (inv or app_).candidate_user_id
    out = []
    max_attempts = get_isettings().ats_max_attempts
    for target in targets:
        d = AtsDelivery(company_id=company_id, candidate_user_id=cand_id,
                        invitation_id=inv.id if inv else None, application_id=app_.id if app_ else None,
                        target=target, status="pending", trigger=trigger, result={})
        db.add(d)
        db.commit()  # не держим транзакцию открытой во время внешних HTTP-вызовов
        for attempt in range(1, max_attempts + 1):
            d.attempts = attempt
            try:
                if target == "webhook":
                    d.result = _run_webhook(st, payload, str(d.id), event)
                else:
                    d.result = _run_provider(db, company_id, target, st, payload, cand_id=cand_id,
                                             application=app_, override=vacancy_override, force=force)
                d.status, d.error, d.http_status = "ok", None, d.result.get("http_status", 200)
                break
            except AtsError as e:
                d.status, d.error, d.http_status = "error", str(e)[:500], e.status
                if e.status in NO_RETRY or attempt == max_attempts:
                    break
                time.sleep(0.5 if attempt == 1 else 2.0)
            except Exception as e:  # noqa: BLE001 — неожиданный ответ ATS не должен оставлять запись «pending»
                log.exception("ATS %s push failed", target)
                db.rollback()
                d.attempts = attempt
                d.status, d.error, d.http_status = "error", f"Внутренняя ошибка адаптера: {type(e).__name__}", None
                break
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
    return {"id": str(d.id), "target": d.target, "target_title": TARGET_TITLES.get(d.target, d.target),
            "status": d.status, "attempts": d.attempts,
            "http_status": d.http_status, "result": d.result, "error": d.error, "trigger": d.trigger,
            "candidate_ref": cp.public_ref if cp else None, "position_title": title,
            "invitation_id": str(d.invitation_id) if d.invitation_id else None,
            "application_id": str(d.application_id) if d.application_id else None,
            "created_at": d.created_at.isoformat(), "updated_at": d.updated_at.isoformat()}


def invitation_transfers(db: Session, company_id: uuid.UUID, inv: Invitation) -> list[dict]:
    """Состояние передачи принятого приглашения по каждой ATS работодателя (карточка приглашения, Ф4).

    Вместо одной общей кнопки «В ATS» с ответом «уже передано ранее» ×4 — строка на систему:
    state = sent («Передано», для «Потока» — с этапом «Новые» из ответа ATS или обратного канала) / error /
    pending / not_sent (подключена, но кандидата в неё ещё не передавали). Только принятые приглашения.
    """
    from app.integrations.ats.stages import PLATFORM_STAGES, PROVIDER_TITLES  # noqa: F401 — PROVIDER_TITLES для ясности

    if inv.status != InvitationStatus.accepted:
        return []
    st = db.get(AtsSettings, company_id)
    enabled = providers.enabled_targets(db, company_id, st)
    rows = db.scalars(select(AtsDelivery).where(AtsDelivery.company_id == company_id, AtsDelivery.invitation_id == inv.id)
                      .order_by(AtsDelivery.created_at.desc())).all()
    by: dict[str, list[AtsDelivery]] = {}
    for d in rows:
        by.setdefault(d.target, []).append(d)
    out = []
    for code in TARGET_TITLES:
        if code not in enabled and code not in by:
            continue
        ds = by.get(code, [])
        ok = next((d for d in ds if d.status == "ok"), None)
        last = ds[0] if ds else None
        state = "sent" if ok else "pending" if last is not None and last.status == "pending" \
            else "error" if last is not None else "not_sent"
        item = {"target": code, "title": TARGET_TITLES[code], "state": state, "enabled": code in enabled,
                "at": as_aware((ok or last).created_at).isoformat() if (ok or last) else None,
                "auto": bool(ok and ok.trigger == "invitation_accepted"),
                "error": last.error if state == "error" and last is not None else None,
                "attempts": len(ds), "stage": None}
        if code == "potok" and ok is not None:
            rec = inv.ats_stage or {}
            if rec.get("provider") == "potok" and rec.get("stage") in PLATFORM_STAGES:  # обратный канал: свежее
                item["stage"] = {"stage": rec["stage"], "title": PLATFORM_STAGES[rec["stage"]],
                                 "name": rec.get("stage_name") or PLATFORM_STAGES[rec["stage"]], "at": rec.get("at"),
                                 "synced": True}
            elif (ok.result or {}).get("stage_title"):  # этап при передаче (до первого опроса «Потока»)
                # передача этапа найма (Н8) — его этап; первичная передача — «на рассмотрении»
                st_ = ok.result.get("stage") if (ok.trigger or "").startswith("hiring_") else "review"
                item["stage"] = {"stage": st_, "title": PLATFORM_STAGES.get(st_, PLATFORM_STAGES["review"]),
                                 "name": ok.result["stage_title"], "at": as_aware(ok.created_at).isoformat(),
                                 "synced": False}
        elif ok is not None and (ok.trigger or "").startswith("hiring_") and (ok.result or {}).get("stage_title"):
            # этап найма (Н8) в Talantix / Хантфлоу / вебхуке — из ответа ATS на перевод
            st_ = ok.result.get("stage")
            item["stage"] = {"stage": st_, "title": PLATFORM_STAGES.get(st_, ok.result["stage_title"]),
                             "name": ok.result["stage_title"], "at": as_aware(ok.created_at).isoformat(),
                             "synced": False}
        out.append(item)
    return out


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
