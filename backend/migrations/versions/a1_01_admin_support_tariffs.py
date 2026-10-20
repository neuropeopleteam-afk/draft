"""Заявки на подключение тарифов (tariff_requests) и обращения в поддержку (support_tickets).

Revision ID: a1_01
Revises: tw01
Create Date: 2026-10-20
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "a1_01"
down_revision: str | None = "tw01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tariff_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("plan", sa.String(length=16), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("contact_name", sa.String(length=200), nullable=True),
        sa.Column("contact_email", sa.String(length=254), nullable=False),
        sa.Column("contact_phone", sa.String(length=64), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("admin_note", sa.String(length=500), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_tariff_requests_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_tariff_requests_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], name=op.f("fk_tariff_requests_resolved_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tariff_requests")),
    )
    op.create_index("ix_tariff_requests_company_id", "tariff_requests", ["company_id"])
    op.create_index("ix_tariff_requests_user_id", "tariff_requests", ["user_id"])

    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("admin_reply", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_support_tickets_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], name=op.f("fk_support_tickets_resolved_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_tickets")),
    )
    op.create_index("ix_support_tickets_user_id", "support_tickets", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_support_tickets_user_id", table_name="support_tickets")
    op.drop_table("support_tickets")
    op.drop_index("ix_tariff_requests_user_id", table_name="tariff_requests")
    op.drop_index("ix_tariff_requests_company_id", table_name="tariff_requests")
    op.drop_table("tariff_requests")
