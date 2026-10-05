"""Модуль fsp: паспорт достижений участника ФСП по дисциплинам ЕВСК.

Реестр ФСП на хакатоне недоступен: паспорт заполняется демо-данными (source=demo), в дальнейшем —
через ФСП ID (Keycloak, OIDC) и синхронизацию с реестром (T2). Отсутствие паспорта — нейтральное состояние.
"""
from datetime import date, datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, str_enum, utcnow
from app.core.enums import FspEventLevel, FspLinkSource


class FspPassport(UUIDPk, Timestamps, Base):
    __tablename__ = "fsp_passports"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    fsp_subject: Mapped[str | None] = mapped_column(sa.String(255), unique=True)  # sub из ФСП ID
    link_source: Mapped[FspLinkSource] = mapped_column(str_enum(FspLinkSource, "fsp_link_source"))
    linked_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    synced_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    sport_rank: Mapped[str | None] = mapped_column(sa.String(64))  # спортивный разряд/звание по ЕВСК
    raw: Mapped[dict] = mapped_column(default=dict)


class FspAchievement(UUIDPk, Base):
    __tablename__ = "fsp_achievements"

    passport_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("fsp_passports.id", ondelete="CASCADE"), index=True)
    discipline: Mapped[str] = mapped_column(sa.String(64))  # код дисциплины (см. catalog.FSP_DISCIPLINES)
    event_name: Mapped[str] = mapped_column(sa.String(255))
    event_level: Mapped[FspEventLevel] = mapped_column(str_enum(FspEventLevel, "fsp_event_level"))
    event_date: Mapped[date | None]
    place: Mapped[int | None]
    result_title: Mapped[str | None] = mapped_column(sa.String(100))  # победитель, призёр, финалист, участник
    team_name: Mapped[str | None] = mapped_column(sa.String(200))
    role_in_team: Mapped[str | None] = mapped_column(sa.String(100))
    verified: Mapped[bool] = mapped_column(default=False)  # True — подтверждено реестром (T2)
    source_ref: Mapped[str | None] = mapped_column(sa.String(255))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
