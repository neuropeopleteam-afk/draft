"""Демо найма в песочнице жюри (Н8).

* «Python-разработчик (платёжный шлюз)» — принятое приглашение с чатом «удобно в четверг в 11:00?» — «да»: у него
  уже назначено собеседование на ближайший четверг, 11:00 МСК (видеозвонок, демо-ссылка). Работодатель видит его
  в карточке и может сразу отметить «прошло» (демо-компании — без ожидания начала) и отправить оффер.
* Путь Ильи жюри проходит само: Илья принимает приглашение → «Предложить время собеседования» (готовые слоты) →
  Илья выбирает → «прошло» → оффер (готовые значения) → Илья принимает → «Вышел на работу» → этап в «Потоке» и обратно.
Сбой демо не ломает сид жюри.
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timedelta, timezone
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.enums import InvitationStatus
from app.modules.hiring.models import HiringInterview
from app.modules.hiring.service import MSK, slot_text
from app.modules.invitations.models import Invitation, InvitationEvent
from app.modules.profiles.models import Company

log = logging.getLogger(__name__)
DEMO_LINK = "https://telemost.yandex.ru/j/demo-vstrechny"
SCHEDULED_TITLE = "Python-разработчик (платёжный шлюз)"


def next_thursday_11(now: datetime) -> datetime:
    d = now.astimezone(MSK).date() + timedelta(days=1)
    while d.weekday() != 3:
        d += timedelta(days=1)
    return datetime.combine(d, dtime(11, 0), MSK)


def seed_jury_hiring(db: Session, c: Company) -> dict:
    try:
        return _seed(db, c)
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("jury: demo hiring failed")
        return {}


def _seed(db: Session, c: Company) -> dict:
    inv = db.scalar(select(Invitation).where(Invitation.company_id == c.id, Invitation.position_title == SCHEDULED_TITLE,
                                             Invitation.status == InvitationStatus.accepted))
    if inv is None or inv.contacts_revealed_at is None:
        return {}
    if db.scalar(select(HiringInterview.id).where(HiringInterview.invitation_id == inv.id)) is not None:
        return {"scheduled": str(inv.id)}
    now = utcnow()
    at = next_thursday_11(now).astimezone(timezone.utc)  # в UTC: SQLite хранит время без пояса
    slot = {"id": "demo01", "starts_at": at.isoformat(), "duration_min": 60, "format": "video",
            "place": DEMO_LINK}
    alt = {**slot, "id": "demo02", "starts_at": (at + timedelta(hours=4)).isoformat()}
    iv = HiringInterview(invitation_id=inv.id, company_id=c.id, candidate_user_id=inv.candidate_user_id,
                         created_by=inv.employer_user_id, round=1, title="Собеседование с тимлидом",
                         status="scheduled", slots=[slot, alt], chosen_slot="demo01", starts_at=at, duration_min=60,
                         format="video", place=DEMO_LINK, created_at=now - timedelta(hours=26),
                         updated_at=now - timedelta(hours=2))
    db.add(iv)
    for kind, actor, ago, note in (
            ("interview_proposed", inv.employer_user_id, 26, f"Собеседование с тимлидом: {slot_text(slot)}; "
                                                             f"{slot_text(alt)}"),
            ("interview_scheduled", inv.candidate_user_id, 2, slot_text(slot))):
        db.add(InvitationEvent(invitation_id=inv.id, from_status=inv.status, to_status=inv.status, actor_user_id=actor,
                               note=note, kind=kind, created_at=now - timedelta(hours=ago)))
    db.commit()
    return {"scheduled": str(inv.id)}
