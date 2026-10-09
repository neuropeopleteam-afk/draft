"""Напоминания (Н6) по приглашениям и откликам. Каждое создаётся один раз (dedupe_key), порог — в настройках.

* приглашение без ответа 3 дня → кандидату (push и письмо); напоминание не старше 14 дней от создания приглашения;
* за сутки до истечения срока ответа → кандидату;
* срок истёк → приглашение получает статус «Истекло» (с записью в истории), работодателю — строка в дайджест;
* отклик без решения работодателя 5 дней → работодателю, в дайджест.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import logging

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_aware
from app.core.enums import InvitationStatus
from app.integrations.vacancies.models import Vacancy, VacancyApplication
from app.modules.auth.models import User
from app.modules.invitations.models import Invitation, InvitationEvent
from app.modules.profiles.models import CandidateProfile, Company, EmployerProfile
from app.modules.subs import texts
from app.modules.subs.delivery import add_notification, is_synthetic, prefs_of

log = logging.getLogger(__name__)
OPEN = (InvitationStatus.sent, InvitationStatus.viewed)
WINDOW_DAYS = 14  # о приглашении старше этого срока без ответа уже не напоминаем: поздно
BATCH = 500


def _wants(db: Session, user: User | None) -> bool:
    return user is not None and not is_synthetic(user.email) and prefs_of(db, user.id).reminders_enabled


def invitations_to_candidate(db: Session, now: datetime, only: set | None = None) -> dict:
    s = get_settings()
    n3 = nexp = 0
    after, before = now - timedelta(days=WINDOW_DAYS), now - timedelta(days=s.reminder_invite_days)
    q = (select(Invitation, Company.name).join(Company, Company.id == Invitation.company_id)
         .where(Invitation.status.in_(OPEN), Invitation.created_at <= before, Invitation.created_at > after,
                or_(Invitation.expires_at.is_(None), Invitation.expires_at > now)))
    if only is not None:
        q = q.where(Invitation.candidate_user_id.in_(only))
    for inv, company in db.execute(q.limit(BATCH)).all():
        u = db.get(User, inv.candidate_user_id)
        if not _wants(db, u):
            continue
        days = max(s.reminder_invite_days, (now - as_aware(inv.created_at)).days)
        title, body = texts.inv_unanswered(company, inv.position_title, inv.salary_from, inv.salary_to, days,
                                           as_aware(inv.expires_at) if inv.expires_at else None)
        n3 += add_notification(db, u.id, "inv_unanswered", f"inv3:{inv.id}", title, body, "/candidate/invitations",
                               channels=["push", "email"], payload={"invitation_id": str(inv.id)}, now=now) is not None
    horizon = now + timedelta(hours=s.reminder_expiry_hours)
    q = (select(Invitation, Company.name).join(Company, Company.id == Invitation.company_id)
         .where(Invitation.status.in_(OPEN), Invitation.expires_at.is_not(None), Invitation.expires_at > now,
                Invitation.expires_at <= horizon))
    if only is not None:
        q = q.where(Invitation.candidate_user_id.in_(only))
    for inv, company in db.execute(q.limit(BATCH)).all():
        u = db.get(User, inv.candidate_user_id)
        if not _wants(db, u):
            continue
        title, body = texts.inv_expiring(company, inv.position_title, as_aware(inv.expires_at))
        nexp += add_notification(db, u.id, "inv_expiring", f"invexp:{inv.id}", title, body, "/candidate/invitations",
                                 channels=["push", "email"], payload={"invitation_id": str(inv.id)}, now=now) is not None
    db.commit()
    return {"inv_unanswered": n3, "inv_expiring": nexp}


def expire_invitations(db: Session, now: datetime, only: set | None = None) -> dict:
    """Срок ответа истёк: статус «Истекло» и строка работодателю в дайджест."""
    n = 0
    q = select(Invitation).where(Invitation.status.in_(OPEN), Invitation.expires_at.is_not(None),
                                 Invitation.expires_at <= now)
    if only is not None:
        q = q.where(Invitation.candidate_user_id.in_(only))
    for inv in db.scalars(q.limit(BATCH)).all():
        prev = inv.status
        inv.status = InvitationStatus.expired
        db.add(InvitationEvent(invitation_id=inv.id, from_status=prev, to_status=InvitationStatus.expired,
                               actor_user_id=None, note="Срок ответа истёк"))
        eu = db.get(User, inv.employer_user_id) if inv.employer_user_id else None
        if _wants(db, eu):
            ref = db.scalar(select(CandidateProfile.public_ref).where(CandidateProfile.user_id == inv.candidate_user_id))
            title, body = texts.inv_expired_employer(ref or "кандидат", inv.position_title)
            add_notification(db, eu.id, "inv_expired", f"invdone:{inv.id}", title, body, "/employer/invitations",
                             channels=[], digest="queued", payload={"invitation_id": str(inv.id), "freq": "daily"}, now=now)
        n += 1
    db.commit()
    return {"inv_expired": n}


def stale_applications(db: Session, now: datetime, only: set | None = None) -> dict:
    s = get_settings()
    n = 0
    before, after = now - timedelta(days=s.reminder_application_days), now - timedelta(days=30)
    q = (select(VacancyApplication, Vacancy).join(Vacancy, Vacancy.id == VacancyApplication.vacancy_id)
         .where(VacancyApplication.status.in_(("sent", "viewed")), VacancyApplication.created_at <= before,
                VacancyApplication.created_at > after, Vacancy.status != "closed"))
    if only is not None:
        q = q.where(Vacancy.created_by.in_(only))
    for app, vac in db.execute(q.limit(BATCH)).all():
        uid = vac.created_by or db.scalar(select(EmployerProfile.user_id).where(EmployerProfile.company_id == vac.company_id)
                                          .order_by(EmployerProfile.created_at).limit(1))
        eu = db.get(User, uid) if uid else None
        if not _wants(db, eu):
            continue
        ref = db.scalar(select(CandidateProfile.public_ref).where(CandidateProfile.user_id == app.candidate_user_id))
        days = max(s.reminder_application_days, (now - as_aware(app.created_at)).days)
        title, body = texts.app_stale_employer(ref or "кандидат", vac.title, days)
        n += add_notification(db, eu.id, "app_stale", f"app5:{app.id}", title, body, "/employer/vacancies",
                              channels=[], digest="queued", payload={"application_id": str(app.id), "freq": "daily"},
                              now=now) is not None
    db.commit()
    return {"app_stale": n}


def run(db: Session, now: datetime, only: set | None = None) -> dict:
    """only — ограничить пользователями (песочница жюри: «перемотать время»)."""
    out: dict = {}
    for step in (invitations_to_candidate, expire_invitations, stale_applications):
        try:
            out.update(step(db, now, only))
        except Exception:  # noqa: BLE001 — один сбой не останавливает остальные напоминания
            db.rollback()
            log.exception("subs: напоминания, шаг %s", step.__name__)
    return out
