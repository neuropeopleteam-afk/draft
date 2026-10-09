"""Демо отметки интереса для персон жюри (сид песочницы): у Марии, Ильи и Артёма числа за неделю не нулевые.

События синтетические (случайные ключи работодателей и потребностей, названий нет) и относятся только к демо-учёткам.
Зонды — настоящие записи от второй демо-компании песочницы: так K в отметке считается теми же правилами, что и у живых
кандидатов. Антон («Пройдите тест сами») без категории — честный ноль и подсказка пройти тест. Сбой не ломает сид жюри.
"""
from __future__ import annotations

from datetime import timedelta
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.modules.mydata import interest

log = logging.getLogger("mydata.demo")

# (число работодателей, число подборок, лучшее место, работодателей на прошлой неделе, зонд (название, текст))
PROFILE = {
    "maria": (5, 4, 2, 3),
    "ilya": (3, 3, 4, 1),
    "junior": (2, 2, 7, 0),
}
PROBE_TEXT = ("Опишите, как вы организуете расчёт слотов доставки, чтобы два заказа не заняли один слот при "
              "параллельных запросах. Достаточно подхода на полстраницы.")


def seed_jury_interest(db: Session, eu, c, maria, ilya, junior) -> None:
    """Вызывается из jury.seed после создания персон и компаний; ``c`` — основная демо-компания песочницы."""
    from app.modules.invitations.models import Probe
    from app.modules.invitations.service import create_probe
    from app.modules.profiles.models import Company

    try:
        for key, prof in (("maria", maria), ("ilya", ilya), ("junior", junior)):
            n, m, best, prev = PROFILE[key]
            interest.seed_demo(db, prof.user_id, employers=n, selections=m, best_rank=best, previous_employers=prev,
                               seed=1)
        c2 = db.scalar(select(Company).where(Company.created_by == eu.id, Company.id != c.id))
        if c2 is not None:
            for prof, title in ((maria, "Короткая задача: слоты доставки"), (ilya, "Короткая задача: идемпотентность платежей")):
                p = create_probe(db, eu, c2, prof, title=title, task_text=PROBE_TEXT, answer_mode="any",
                                 salary_from=230_000, salary_to=270_000, time_limit_min=15, need_id=None)
                p.created_at = utcnow() - timedelta(days=2)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("jury: demo interest failed")
