"""Напоминание о собеседовании: за сутки до начала — push и письмо кандидату, push работодателю (один раз).

Фоновый поток на процесс (как лента заданий и опрос этапов ATS), HIRING_REMIND_POLL_S — период обхода, 0 — выключено
(тесты вызывают remind_due напрямую). Повтор исключён отметкой reminded_at, которая ставится до отправки.
В кабинете то же напоминание — счётчик у раздела «Приглашения» и плашка на странице (GET /api/hiring/todo).
"""
from __future__ import annotations

import logging
import os
import threading
import time

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, utcnow
from app.integrations.push.service import send_to_user
from app.modules.auth.models import User
from app.modules.hiring.models import HiringInterview
from app.modules.hiring.service import FORMATS, REMIND_BEFORE, msk
from app.modules.invitations.models import Invitation
from app.modules.notifications.mailer import notify

log = logging.getLogger(__name__)
_started: list[threading.Thread] = []


def remind_due(db: Session) -> int:
    now = utcnow()
    rows = db.scalars(select(HiringInterview).where(HiringInterview.status == "scheduled",
                                                    HiringInterview.reminded_at.is_(None),
                                                    HiringInterview.starts_at > now,
                                                    HiringInterview.starts_at <= now + REMIND_BEFORE)).all()
    sent = 0
    for iv in rows:
        got = db.execute(update(HiringInterview).where(HiringInterview.id == iv.id, HiringInterview.reminded_at.is_(None))
                         .values(reminded_at=now).execution_options(synchronize_session=False)).rowcount
        db.commit()
        if got != 1:  # другой воркер уже напомнил
            continue
        inv = db.get(Invitation, iv.invitation_id)
        when = f"{msk(iv.starts_at)} · {FORMATS.get(iv.format or '', '').lower()}"
        try:
            cu = db.get(User, iv.candidate_user_id)
            send_to_user(db, iv.candidate_user_id, "Скоро собеседование", f"«{inv.position_title}»: {when}",
                         "/candidate/invitations", f"hire-remind-{iv.id}")
            if cu is not None:
                notify(cu.email, f"Напоминание: собеседование «{inv.position_title}»",
                       [f"Собеседование по приглашению «{inv.position_title}» — {when}.",
                        f"Ссылка или адрес: {iv.place}" if iv.place else "Формат и детали — в кабинете.",
                        "Если время не подходит, попросите другое в кабинете, в разделе «Приглашения»."],
                       is_demo=cu.is_demo, link_path="/candidate/invitations")
            if inv.employer_user_id:
                send_to_user(db, inv.employer_user_id, "Скоро собеседование", f"«{inv.position_title}»: {when}",
                             "/employer/invitations", f"hire-remind-{iv.id}")
            sent += 1
        except Exception:  # noqa: BLE001 — сбой отправки не ломает обход
            db.rollback()
            log.exception("hiring reminder failed")
    return sent


def start_background(interval_s: int | None = None) -> threading.Thread | None:
    interval_s = int(os.getenv("HIRING_REMIND_POLL_S", "300")) if interval_s is None else interval_s
    if interval_s <= 0 or _started:
        return None

    def loop() -> None:
        time.sleep(min(60, interval_s))
        while True:
            db = SessionLocal()
            try:
                remind_due(db)
            except Exception:  # noqa: BLE001
                log.exception("hiring reminders")
            finally:
                db.close()
            time.sleep(interval_s)

    t = threading.Thread(target=loop, name="hiring-reminders", daemon=True)
    _started.append(t)
    t.start()
    return t
