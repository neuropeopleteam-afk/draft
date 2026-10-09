"""Найм после принятия приглашения: собеседование (слоты), оффер со встречным, исход найма (поток Н8)

Revision ID: hr01
Revises: tk02
Create Date: 2026-10-09

Только новые таблицы; существующие не меняются. Строки удаляются каскадом вместе с приглашением (и компанией).
При слиянии down_revision — текущая голова integ/0710.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "hr01"
down_revision: str | None = "tk02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _refs(t: str) -> list:
    return [
        sa.ForeignKeyConstraint(["invitation_id"], ["invitations.id"], name=op.f(f"fk_{t}_invitation_id_invitations"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f(f"fk_{t}_company_id_companies"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_user_id"], ["users.id"], name=op.f(f"fk_{t}_candidate_user_id_users"),
                                ondelete="CASCADE"),
    ]


def upgrade() -> None:
    op.create_table(
        "hiring_interviews",
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("slots", JSONType, nullable=False),
        sa.Column("chosen_slot", sa.String(length=8), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_min", sa.Integer(), nullable=True),
        sa.Column("format", sa.String(length=16), nullable=True),
        sa.Column("place", sa.String(length=500), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("candidate_note", sa.Text(), nullable=True),
        sa.Column("reschedules", sa.Integer(), nullable=False),
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("status IN ('proposed', 'reschedule', 'scheduled', 'done', 'cancelled')",
                           name=op.f("ck_hiring_interviews_status")),
        *_refs("hiring_interviews"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_hiring_interviews_created_by_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hiring_interviews")),
    )
    op.create_index("ix_hiring_interviews_invitation_created", "hiring_interviews", ["invitation_id", "created_at"])
    op.create_index("ix_hiring_interviews_status_starts", "hiring_interviews", ["status", "starts_at"])

    op.create_table(
        "hiring_offers",
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("salary", sa.Integer(), nullable=False),
        sa.Column("salary_basis", sa.String(length=8), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("respond_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("counters", JSONType, nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("status IN ('sent', 'accepted', 'declined', 'withdrawn', 'expired')",
                           name=op.f("ck_hiring_offers_status")),
        sa.CheckConstraint("salary > 0", name=op.f("ck_hiring_offers_salary_positive")),
        *_refs("hiring_offers"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_hiring_offers_created_by_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hiring_offers")),
    )
    op.create_index("ix_hiring_offers_invitation_created", "hiring_offers", ["invitation_id", "created_at"])

    op.create_table(
        "hiring_outcomes",
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_user_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("outcome IN ('hired', 'declined', 'rejected')", name=op.f("ck_hiring_outcomes_outcome")),
        *_refs("hiring_outcomes"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name=op.f("fk_hiring_outcomes_decided_by_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hiring_outcomes")),
        sa.UniqueConstraint("invitation_id", name=op.f("uq_hiring_outcomes_invitation_id")),
    )
    op.create_index("ix_hiring_outcomes_company_id", "hiring_outcomes", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_hiring_outcomes_company_id", table_name="hiring_outcomes")
    op.drop_table("hiring_outcomes")
    op.drop_index("ix_hiring_offers_invitation_created", table_name="hiring_offers")
    op.drop_table("hiring_offers")
    op.drop_index("ix_hiring_interviews_status_starts", table_name="hiring_interviews")
    op.drop_index("ix_hiring_interviews_invitation_created", table_name="hiring_interviews")
    op.drop_table("hiring_interviews")
