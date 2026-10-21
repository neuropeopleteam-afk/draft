"""Точки расширения бизнес-событий для интеграций (push, ATS). Вызываются фоновыми задачами FastAPI,
каждая открывает свою сессию БД; сбой интеграции не влияет на основную операцию."""
from __future__ import annotations

import logging
import uuid

from app.core.db import SessionLocal
from app.integrations.push.service import send_to_user

log = logging.getLogger(__name__)


def _rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₽"


def invitation_sent(inv_id: uuid.UUID) -> None:
    from app.modules.invitations.models import Invitation
    from app.modules.profiles.models import Company

    db = SessionLocal()
    try:
        i = db.get(Invitation, inv_id)
        if i is None:
            return
        c = db.get(Company, i.company_id)
        title = f"Новое приглашение: {c.name if c else 'компания'}"
        body = f"«{i.position_title}», {_rub(i.salary_from)} – {_rub(i.salary_to)}"
        send_to_user(db, i.candidate_user_id, title, body, "/candidate/invitations", f"inv-{i.id}")
        from app.modules.telegram.service import send_to_user as send_telegram

        send_telegram(db, i.candidate_user_id, title, body, "/candidate/invitations", f"inv-{i.id}")
    except Exception:  # noqa: BLE001
        log.exception("push invitation_sent failed")
    finally:
        db.close()


def invitation_answered(inv_id: uuid.UUID, accepted: bool) -> None:
    from app.integrations.ats.providers import enabled_targets
    from app.integrations.ats.service import company_settings, deliver
    from app.modules.invitations.models import Invitation
    from app.modules.profiles.models import CandidateProfile

    db = SessionLocal()
    try:
        i = db.get(Invitation, inv_id)
        if i is None:
            return
        ref = db.get(CandidateProfile, i.candidate_user_id).public_ref
        if i.employer_user_id:
            title = f"Кандидат {ref} {'принял' if accepted else 'отклонил'} приглашение"
            body = f"«{i.position_title}»" + (" — контакты открыты" if accepted else "")
            send_to_user(db, i.employer_user_id, title, body, "/employer/invitations", f"inv-{i.id}")
            from app.modules.telegram.service import send_to_user as send_telegram

            send_telegram(db, i.employer_user_id, title, body, "/employer/invitations", f"inv-{i.id}")
        if accepted:
            # Строки настроек у новой компании ещё нет (её создаёт первый заход в кабинет ATS), а «Поток» или Talantix
            # уже могут быть подключены: company_settings создаёт её с auto_push=True — как в кабинете по умолчанию
            st = company_settings(db, i.company_id)
            db.commit()
            if st.auto_push and enabled_targets(db, i.company_id, st):
                deliver(db, i.company_id, invitation_id=i.id, trigger="invitation_accepted")
    except Exception:  # noqa: BLE001
        log.exception("integrations invitation_answered failed")
    finally:
        db.close()
