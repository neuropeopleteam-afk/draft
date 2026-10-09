"""Проверка с живыми пользователями: участник, события пути, ответы анкеты.

* StudyParticipant — приглашение (одна строка = один человек). В базе только SHA-256 кода-ссылки; имени и почты здесь
  нет. user_id — служебная связь с учётной записью, чтобы брать факты пути из платформы; при удалении учётной записи
  становится NULL (ответы остаются обезличенными). label — «К-01», «Р-03»: по нему команда узнаёт ссылку, не зная имени.
  source — откуда участник (freelance_paid — приглашён через фриланс-биржу, оплачено; team — знакомые команды, без оплаты):
  подпись публичного блока строится по нему. is_test — репетиция команды: в публичные цифры не входит. withdrawn_at — отозванное согласие: события и ответы
  удалены, строка остаётся, чтобы код нельзя было использовать повторно.
* StudyEvent — обезличенное событие: view (нормализованный путь экрана), error (код и статус ошибки). Без тел запросов.
* StudyAnswer — анкета после пути (одна на участника): SUS (10 пунктов), оценки топ-5, доверие к грейду, комментарий.
"""
from __future__ import annotations

from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, utcnow


class StudyParticipant(UUIDPk, Timestamps, Base):
    __tablename__ = "study_participants"

    code_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    role: Mapped[str] = mapped_column(sa.String(16))  # candidate | employer
    label: Mapped[str] = mapped_column(sa.String(16))
    batch: Mapped[str] = mapped_column(sa.String(64), default="", server_default="")
    mode: Mapped[str] = mapped_column(sa.String(16), default="quick", server_default="quick")  # quick | register
    source: Mapped[str] = mapped_column(sa.String(16), default="freelance_paid", server_default="freelance_paid")
    is_test: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    is_active: Mapped[bool] = mapped_column(default=True, server_default=sa.true())
    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"), unique=True)
    opened_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    consent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    consent_version: Mapped[str | None] = mapped_column(sa.String(32))
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))  # согласие дано, путь начат
    joined_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))  # учётная запись привязана
    last_seen_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        sa.CheckConstraint("role IN ('candidate', 'employer')", name="role"),
        sa.CheckConstraint("mode IN ('register', 'quick')", name="mode"),
        sa.CheckConstraint("source IN ('freelance_paid', 'team')", name="source"),
        sa.Index("ix_study_participants_batch", "batch"),
    )


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
