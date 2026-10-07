"""Исправления 07.10: источник экспертной разметки, место в кубке без повтора, неразрывные пробелы в демо-кубке

Revision ID: fx01
Revises: qr01
Create Date: 2026-10-07

* expert_panelists.source — кто размечает: «people» (люди) или «model» (языковая модель по экспертному протоколу),
  source_model — название модели. Подпись на /validation#experts строится из этих полей.
* Факты кубков: место было и в названии («Кубок «…»: 2 место из 5»), и в вердикте («2 место из 5») — в карточках
  подборки, PDF и ATS оно показывалось дважды. Название оставляем без места, место — в вердикте.
* Описание демо-кубка «Маршрутизация заказов»: «220–280 тыс. ₽» с неразрывными пробелами (не переносится по строкам).
"""
from collections.abc import Sequence
import re

from alembic import op
import sqlalchemy as sa

revision: str = "fx01"
down_revision: str | None = "qr01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLACE = re.compile(r": \d+ место из \d+$")
NBSP = "\u00a0"


def upgrade() -> None:
    with op.batch_alter_table("expert_panelists") as b:
        b.add_column(sa.Column("source", sa.String(length=16), nullable=False, server_default="people"))
        b.add_column(sa.Column("source_model", sa.String(length=64), nullable=True))

    conn = op.get_bind()
    facts = sa.table("candidate_facts", sa.column("id", sa.Uuid()), sa.column("title", sa.String()),
                     sa.column("source_ref", sa.String()))
    rows = conn.execute(sa.select(facts.c.id, facts.c.title).where(facts.c.source_ref.like("cup:%"))).all()
    for fid, title in rows:
        new = PLACE.sub("", title or "")
        if new != title:
            conn.execute(facts.update().where(facts.c.id == fid).values(title=new))

    cups = sa.table("cups", sa.column("id", sa.Uuid()), sa.column("description", sa.Text()))
    old = "220–280 тыс. ₽"
    for cid, text in conn.execute(sa.select(cups.c.id, cups.c.description)
                                  .where(cups.c.description.like(f"%{old}%"))).all():
        conn.execute(cups.update().where(cups.c.id == cid)
                     .values(description=text.replace(old, f"220–280{NBSP}тыс.{NBSP}₽")))


def downgrade() -> None:
    with op.batch_alter_table("expert_panelists") as b:
        b.drop_column("source_model")
        b.drop_column("source")
    # названия фактов кубков и описание не возвращаем: место осталось в вердикте, пробелы — косметика
