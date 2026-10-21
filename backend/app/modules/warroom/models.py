"""Модели БД модуля «Боевой ИИ-Полигон» (warroom).

Хранит попытки прохождения боевых архитектурных инцидентов кандидатами (Senior / Lead / Principal)
с параметризованным зерном (seed), выбранными инженерными мерами и их численными параметрами,
патчем кода, письменным обоснованием, оценкой ИИ-рецензента с дословными цитатами, флагом выполнения
целевых показателей (SLO) в рамках бюджета и криптографической подписью SHA-256.
"""
from __future__ import annotations

from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, utcnow


class WarRoomAttempt(UUIDPk, Base):
    """Сохранённый результат прохождения боевого инцидента на полигоне."""

    __tablename__ = "warroom_attempts"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    test_session_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("test_sessions.id", ondelete="SET NULL"), index=True, nullable=True
    )
    scenario_id: Mapped[str] = mapped_column(sa.String(32), index=True)
    direction: Mapped[str] = mapped_column(sa.String(32), index=True)
    target_grade: Mapped[str] = mapped_column(sa.String(16))
    confirmed_grade: Mapped[str] = mapped_column(sa.String(16))
    seed: Mapped[int] = mapped_column(sa.Integer, default=1001)
    measures: Mapped[list] = mapped_column(sa.JSON, default=list)
    code_patch: Mapped[str] = mapped_column(sa.Text, default="")
    justification: Mapped[str] = mapped_column(sa.Text, default="")
    metrics: Mapped[dict] = mapped_column(sa.JSON, default=dict)
    slo_met: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    cost_rub_month: Mapped[int] = mapped_column(sa.Integer, default=0)
    cost_budget_rub_month: Mapped[int] = mapped_column(sa.Integer, default=0)
    sim_score: Mapped[float] = mapped_column(sa.Float, default=0.0)
    code_score: Mapped[float] = mapped_column(sa.Float, default=0.0)
    rubric_score: Mapped[float] = mapped_column(sa.Float, default=0.0)
    total_score: Mapped[float] = mapped_column(sa.Float, default=0.0)
    passed: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    reviewer_mode: Mapped[str] = mapped_column(sa.String(32), default="deterministic_simulator")
    rubric_details: Mapped[dict] = mapped_column(sa.JSON, default=dict)
    incident_stage: Mapped[dict] = mapped_column(sa.JSON, default=dict)
    elapsed_s: Mapped[int] = mapped_column(sa.Integer, default=0)
    sha256_sig: Mapped[str] = mapped_column(sa.String(64), default="")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, index=True)
