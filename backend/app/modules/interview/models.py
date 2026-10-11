"""Сессии интервьюера: «устная защита» попытки теста (mode=defense) и «ИИ-интервью» как этап найма (mode=interview).

Что хранится: статус, вердикт модели, вопросы с подтверждёнными цитатами, расшифровка (только текст — без видео и
звука), длительность, стоимость, версия согласия. Имя для обращения не хранится (передаётся сервису и забывается).
Срок хранения — как у попытки теста и приглашения: строки удаляются каскадом вместе с test_sessions / invitations и
с учётной записью; кандидат может удалить запись сам (DELETE /api/interview/sessions/{id}).
"""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, utcnow

MODES = ("defense", "interview")
# invited — работодатель пригласил, кандидат ещё не начал; created — сессия заведена, разговор не начат;
# in_progress — идёт разговор; evaluating — разговор окончен, идёт оценка; completed — есть результат;
# failed / expired / cancelled — без результата; deleted — содержимое удалено по просьбе кандидата (остаётся отметка о
# факте сессии без текста и результата — чтобы удаление не давало повторную защиту той же попытки)
STATUSES = ("invited", "created", "in_progress", "evaluating", "completed", "failed", "expired", "cancelled", "deleted")
ACTIVE = ("created", "in_progress")
FINAL = ("completed", "failed", "expired", "cancelled", "deleted")
VERDICTS = ("confirmed", "discrepancies", "insufficient")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class InterviewSession(UUIDPk, Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        sa.CheckConstraint(_in("mode", MODES), name="mode"),
        sa.CheckConstraint(_in("status", STATUSES), name="status"),
        sa.Index("ix_interview_sessions_candidate_created", "candidate_user_id", "created_at"),
    )

    mode: Mapped[str] = mapped_column(sa.String(16))
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    # защита — попытка теста; интервью — приглашение (компания — для доступа работодателя)
    test_session_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("test_sessions.id", ondelete="CASCADE"),
                                                              index=True)
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("invitations.id", ondelete="CASCADE"),
                                                            index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(sa.String(16), default="created")
    verdict: Mapped[str | None] = mapped_column(sa.String(16))
    score: Mapped[float | None]
    # engine — движок (app/modules/interview/engine), stub — заглушка продукта, example — готовый пример для жюри
    engine: Mapped[str] = mapped_column(sa.String(8), default="stub")
    # состояние разговора у движка (контекст, план вопросов, номер вопроса) — между репликами; после оценки очищается
    state: Mapped[dict] = mapped_column(default=dict)
    channel: Mapped[str | None] = mapped_column(sa.String(8))  # voice | text — последний использованный
    # песочница жюри (sid или shared) — лимит живых запусков; is_example — готовый пример «модельный кандидат»
    jury_scope: Mapped[str | None] = mapped_column(sa.String(16), index=True)
    is_example: Mapped[bool] = mapped_column(default=False)
    minutes: Mapped[int] = mapped_column(sa.SmallInteger, default=3)
    max_questions: Mapped[int] = mapped_column(sa.SmallInteger, default=3)
    # что ушло в движок — названия заданий и навыков, без текстов (тексты — в попытке теста и потребности)
    context_meta: Mapped[dict] = mapped_column(default=dict)
    # нормализованный результат: {questions: [{text, topic, task_ref, quotes: [{text, confirmed}], note}], summary,
    # quotes_confirmed, quotes_total, stub}
    result: Mapped[dict] = mapped_column(default=dict)
    transcript: Mapped[list | None]  # [{role: interviewer|candidate, text}] — только текст; работодателю
    duration_s: Mapped[int | None]
    cost: Mapped[dict | None]  # {usd, parts, estimated} — как посчитал движок
    error: Mapped[str | None] = mapped_column(sa.String(200))
    consent_version: Mapped[str | None] = mapped_column(sa.String(32))
    note: Mapped[str | None] = mapped_column(sa.Text)  # комментарий работодателя к приглашению на ИИ-интервью
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
