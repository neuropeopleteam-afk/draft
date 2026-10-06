"""Экспертная разметка: эксперты по приглашению, пакет объектов разметки (A — пары, B — ответы, C — Ангофф), оценки.

* ExpertPanelist — эксперт панели (код E1…E3, слот назначения). Вход — по персональной ссылке: в базе хранится
  только SHA-256 токена. Учётка пользователя с ролью expert создаётся вместе с приглашением (без регистрации).
  Демо-эксперт жюри тоже получает «панелиста» (is_demo): его оценки сохраняются, но в метрики не входят.
* ExpertItem — объект разметки пакета (версия pack). payload — то, что видит эксперт (вслепую: без ранга, скора,
  источника и меток системы), hidden — служебное (ранги платформы и BM25, источник пула, метка по правилам,
  параметры семейства, оценки модели-оценщика). Пакет — снимок: не зависит от последующих изменений демо-данных.
* ExpertLabel — оценка эксперта (одна на объект, перезаписывается при правке — сохраняется по ходу работы).
"""
from __future__ import annotations

from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, utcnow


class ExpertPanelist(UUIDPk, Timestamps, Base):
    __tablename__ = "expert_panelists"

    code: Mapped[str] = mapped_column(sa.String(16))  # E1, E2, E3; у демо — DEMO
    slot: Mapped[str] = mapped_column(sa.String(16))  # план назначения: E1 | E2 | E3 | DEMO
    team_size: Mapped[int] = mapped_column(default=3)
    display_name: Mapped[str | None] = mapped_column(sa.String(120))
    profile: Mapped[str | None] = mapped_column(sa.String(255))  # «тимлид Backend» — для отчёта, не для расчёта
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    token_hash: Mapped[str | None] = mapped_column(sa.String(64), unique=True)
    pack: Mapped[str] = mapped_column(sa.String(16))
    assignment: Mapped[dict] = mapped_column(default=dict)  # {"A": [ключи], "B": [...], "C": [...]}
    is_demo: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    is_active: Mapped[bool] = mapped_column(default=True, server_default=sa.true())
    instructions_ack_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (sa.Index("ix_expert_panelists_code_demo", "code", "is_demo"),)


class ExpertItem(UUIDPk, Base):
    __tablename__ = "expert_items"

    pack: Mapped[str] = mapped_column(sa.String(16), index=True)
    kind: Mapped[str] = mapped_column(sa.String(1))  # A | B | C
    key: Mapped[str] = mapped_column(sa.String(200))
    grp: Mapped[str | None] = mapped_column(sa.String(120))  # A — потребность (N00), B — семейство, C — блок
    position: Mapped[int] = mapped_column(default=0)
    payload: Mapped[dict] = mapped_column(default=dict)
    hidden: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)

    __table_args__ = (sa.UniqueConstraint("pack", "key", name="uq_expert_items_pack_key"),
                      sa.CheckConstraint("kind IN ('A', 'B', 'C')", name="kind"))


class ExpertLabel(UUIDPk, Timestamps, Base):
    __tablename__ = "expert_labels"

    panelist_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("expert_panelists.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("expert_items.id", ondelete="CASCADE"), index=True)
    value: Mapped[dict] = mapped_column(default=dict)
    comment: Mapped[str | None] = mapped_column(sa.Text)
    seconds: Mapped[int | None] = mapped_column()  # время на объект по часам браузера (для темпа, не для расчёта)

    __table_args__ = (sa.UniqueConstraint("panelist_id", "item_id", name="uq_expert_labels_panelist_item"),)
