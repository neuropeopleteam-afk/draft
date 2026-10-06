"""Залы живой демонстрации и гости (эксперты жюри с телефона)."""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, utcnow


class LiveRoom(UUIDPk, Base):
    """Зал = одна песочница жюри. code — публичный (в QR), sid — секрет песочницы и наружу не отдаётся."""

    __tablename__ = "jury_live_rooms"

    code: Mapped[str] = mapped_column(sa.String(16), unique=True)
    sid: Mapped[str] = mapped_column(sa.String(16), unique=True)
    rev: Mapped[int] = mapped_column(default=0)  # растёт при каждом событии зала — экран не перерисовывает зря
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    last_activity_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class LiveGuest(UUIDPk, Base):
    """Гость зала: кандидат песочницы, мини-тест (ключи заданий — только здесь, наружу не отдаются) и его путь."""

    __tablename__ = "jury_live_guests"

    room_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("jury_live_rooms.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)  # sha256 токена гостя (X-Guest-Token)
    ref: Mapped[str] = mapped_column(sa.String(16))  # публичный номер кандидата «C-XXXXXX»
    number: Mapped[int] = mapped_column(default=1)  # «Гость 3» — порядковый номер в зале
    direction: Mapped[str] = mapped_column(sa.String(32))
    # testing → done → selected → invited → accepted | declined; no_category — θ ниже порога Junior
    stage: Mapped[str] = mapped_column(sa.String(16), default="testing")
    state: Mapped[dict] = mapped_column(default=dict)  # мини-тест: задания с ключами, ответы, θ
    result: Mapped[dict] = mapped_column(default=dict)  # публичный итог: θ, SE, категория, верно из 3
    selection: Mapped[dict] = mapped_column(default=dict)  # место в подборке, «почему», соседи
    invite: Mapped[dict] = mapped_column(default=dict)  # приглашение: id, вилка, push
    events: Mapped[list] = mapped_column(default=list)  # [{at, kind, ...}] — лента на большом экране
    push_state: Mapped[str] = mapped_column(sa.String(16), default="")  # "" → sending → done (push отправлен один раз)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    selected_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    invited_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
