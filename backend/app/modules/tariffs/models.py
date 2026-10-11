"""Тариф компании, метка «Партнёр ФСП» и демонстрационные счета (миграция tr01).

Строки нет — действует тариф по умолчанию (plans.DEFAULT_PLAN, у песочниц жюри — plans.JURY_DEFAULTS). Счёт —
демонстрационный: настоящей оплаты нет, номер «Д-…», статус demo. Удаляются каскадом вместе с компанией.
"""
from __future__ import annotations

from datetime import date, datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, utcnow

PLAN_IDS = ("start", "hire")  # выбирает сам работодатель; «Партнёр ФСП» — флаг fsp_partner, его ставит ФСП


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class CompanyTariff(Timestamps, Base):
    __tablename__ = "company_tariffs"
    __table_args__ = (sa.CheckConstraint(_in("plan", PLAN_IDS), name="plan"),)

    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    plan: Mapped[str] = mapped_column(sa.String(16), default="start")
    plan_since: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    # «Партнёр ФСП»: выдаёт и снимает роль fsp_analyst/admin; пока флаг стоит, действует тариф «Партнёр ФСП»
    fsp_partner: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    partner_since: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    partner_granted_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    partner_note: Mapped[str | None] = mapped_column(sa.String(300))  # например «спонсорский пакет Кубка России»
    # заявка работодателя «Стать партнёром ФСП» (ФСП видит её в кабинете и решает)
    partner_requested_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    partner_request_note: Mapped[str | None] = mapped_column(sa.String(500))
    is_demo: Mapped[bool] = mapped_column(default=False, server_default=sa.false())  # демо-данные (tariffs.demo)


class DemoInvoice(UUIDPk, Base):
    __tablename__ = "tariff_invoices"

    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(sa.String(32), unique=True)
    plan: Mapped[str] = mapped_column(sa.String(16))
    amount_rub: Mapped[int] = mapped_column(sa.Integer)
    vat_rub: Mapped[int] = mapped_column(sa.Integer)
    period_from: Mapped[date] = mapped_column(sa.Date)
    period_to: Mapped[date] = mapped_column(sa.Date)
    status: Mapped[str] = mapped_column(sa.String(16), default="demo")  # demo — оплата не проводится
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
