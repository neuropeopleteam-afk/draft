"""Проверка с живыми пользователями: участник (обезличенно), события пути, ответы анкеты.

* StudyParticipant — одна учётная запись, у которой включена обезличенная статистика прохождения (показано уведомление
  о ней). Имени, почты и IP здесь нет. user_id — служебная связь с учётной записью, чтобы брать факты пути из платформы
  (время опроса, теста, потребности); при удалении учётной записи становится NULL, цифры остаются обезличенными.
  declined_at — человек нажал «Не участвовать»: события и ответы удалены, статистика у него больше не собирается
  (строка остаётся только как отметка отказа).
* StudyEvent — обезличенное событие: view (нормализованный путь экрана), error (код и статус ошибки). Без тел запросов.
* StudyAnswer — необязательная анкета после пути (одна на участника): SUS (10 пунктов), оценки топ-5, доверие к
  грейду, «что мешало».
"""
from __future__ import annotations

from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, utcnow


class StudyParticipant(UUIDPk, Timestamps, Base):
    __tablename__ = "study_participants"

    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"), unique=True)
    role: Mapped[str] = mapped_column(sa.String(16))  # candidate | employer
    enrolled_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)  # показано уведомление, сбор начат
    last_seen_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    prompted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))  # анкета показана (один раз)
    declined_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (sa.CheckConstraint("role IN ('candidate', 'employer')", name="role"),)


class StudyEvent(UUIDPk, Base):
    __tablename__ = "study_events"

    participant_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("study_participants.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(sa.String(8))  # view | error
    key: Mapped[str] = mapped_column(sa.String(120))  # view — путь экрана (:id вместо идентификаторов); error — путь API
    status: Mapped[int | None] = mapped_column(sa.SmallInteger)  # error: HTTP-статус (0 — сеть недоступна)
    code: Mapped[str | None] = mapped_column(sa.String(64))  # error: код ошибки API
    at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)

    __table_args__ = (sa.CheckConstraint("kind IN ('view', 'error')", name="kind"),
                      sa.Index("ix_study_events_participant_at", "participant_id", "at"))


class StudyAnswer(UUIDPk, Timestamps, Base):
    __tablename__ = "study_answers"

    participant_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("study_participants.id", ondelete="CASCADE"), unique=True)
    sus: Mapped[list] = mapped_column(default=list)  # 10 ответов 1–5 в порядке пунктов шкалы
    ratings: Mapped[list] = mapped_column(default=list)  # [{ref, rank, rating}] — оценки топ-5 (работодатель)
    selection: Mapped[dict | None] = mapped_column()  # {need_id, version, algorithm, shown} — что оценивали
    belief: Mapped[int | None] = mapped_column(sa.SmallInteger)  # «верю грейду» 1–5
    grade_fit: Mapped[str | None] = mapped_column(sa.String(8))  # кандидат: lower | fit | higher
    tags: Mapped[list] = mapped_column(default=list)  # метки «что мешало»
    comment: Mapped[str | None] = mapped_column(sa.Text)  # без контактов (маскируется при сохранении)
    path_done: Mapped[bool] = mapped_column(default=False, server_default=sa.false())  # путь пройден целиком на момент анкеты
    submitted_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
