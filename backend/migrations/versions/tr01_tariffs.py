"""Я29: тарифы работодателя, метка «Партнёр ФСП», демонстрационные счета

Revision ID: tr01
Revises: iv01
Create Date: 2026-10-11

company_tariffs — тариф компании («Старт» / «Найм»), метка «Партнёр ФСП» (ставит ФСП) и заявка на неё;
tariff_invoices — демонстрационные счета (настоящей оплаты нет). Без строки тарифа действует «Старт».
Всё используется только при TARIFFS_ENABLED (по умолчанию выключено).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "tr01"
down_revision: str | None = "iv01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "company_tariffs",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("plan", sa.String(length=16), nullable=False),
        sa.Column("plan_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        sa.Column("fsp_partner", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("partner_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("partner_granted_by", sa.Uuid(), nullable=True),
        sa.Column("partner_note", sa.String(length=300), nullable=True),
        sa.Column("partner_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("partner_request_note", sa.String(length=500), nullable=True),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("plan IN ('start', 'hire')", name=op.f("ck_company_tariffs_plan")),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_company_tariffs_company_id_companies"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], name=op.f("fk_company_tariffs_changed_by_users"),
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["partner_granted_by"], ["users.id"],
                                name=op.f("fk_company_tariffs_partner_granted_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("company_id", name=op.f("pk_company_tariffs")),
    )
    op.create_table(
        "tariff_invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("plan", sa.String(length=16), nullable=False),
        sa.Column("amount_rub", sa.Integer(), nullable=True),  # None — цена «по запросу», счёт без суммы
        sa.Column("vat_rub", sa.Integer(), nullable=True),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_tariff_invoices_company_id_companies"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_tariff_invoices_created_by_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tariff_invoices")),
        sa.UniqueConstraint("number", name=op.f("uq_tariff_invoices_number")),
    )
    op.create_index(op.f("ix_tariff_invoices_company_id"), "tariff_invoices", ["company_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_tariff_invoices_company_id"), table_name="tariff_invoices")
    op.drop_table("tariff_invoices")
    op.drop_table("company_tariffs")
