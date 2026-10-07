"""Камера во время теста по согласию: режим камеры в сессии теста и события (без кадров).

Анализ видео идёт только в браузере кандидата; сервер получает только события «нет лица в кадре», «несколько
лиц», «камера закрыта», «камера не передаёт изображение» с длительностью и номером задания, а также сколько
времени камера наблюдала каждое задание. Изображения, признаки лица и биометрия не передаются и не хранятся.

Срок хранения — как у попытки теста: строки удаляются каскадом вместе с test_sessions (и с учётной записью).
"""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, utcnow


class ProctorSession(UUIDPk, Base):
    """Режим камеры в одной сессии теста: camera | declined | unsupported | denied."""

    __tablename__ = "proctor_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("test_sessions.id", ondelete="CASCADE"), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(sa.String(16))
    reason: Mapped[str | None] = mapped_column(sa.String(120))  # почему без камеры: браузер, отказ в доступе
    consent_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("consents.id", ondelete="SET NULL"))
    consent_version: Mapped[str | None] = mapped_column(sa.String(32))
    client: Mapped[dict] = mapped_column(default=dict)  # модель, частота анализа — без данных о человеке
    # Окна наблюдения по номерам заданий: [{"from": 1, "to": null, "mid": false}]; to — первое задание без камеры
    windows: Mapped[list] = mapped_column(default=list)
    stop_reason: Mapped[str | None] = mapped_column(sa.String(16))  # user | revoked | error
    resumes: Mapped[int] = mapped_column(default=0)  # камера включена снова после перезагрузки страницы
    # Сколько камера наблюдала каждое задание: {"<номер>": {"ms": …, "frames": …, "face": …}}
    observed: Mapped[dict] = mapped_column(default=dict)
    events_count: Mapped[int] = mapped_column(default=0)
    events_dropped: Mapped[int] = mapped_column(default=0)
    summary: Mapped[dict | None]  # итог после завершения теста (то же, что попало в достоверность)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class ProctorEvent(UUIDPk, Base):
    """Интервал без нормального кадра: no_face | multi_face | blocked | camera_off. Только длительность и счётчик."""

    __tablename__ = "proctor_events"

    proctor_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("proctor_sessions.id", ondelete="CASCADE"),
                                                  index=True)
    position: Mapped[int] = mapped_column(sa.SmallInteger)  # номер задания в сессии
    kind: Mapped[str] = mapped_column(sa.String(16))
    duration_ms: Mapped[int]
    faces: Mapped[int | None] = mapped_column(sa.SmallInteger)  # сколько лиц было в кадре (для multi_face)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))  # по часам браузера, справочно
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
