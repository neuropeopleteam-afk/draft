"""Жалобы кандидатов на приглашения (нереальная вилка, не та роль, спам) — для индекса доверия работодателя.

Revision ID: em01
Revises: 0004
Create Date: 2026-10-06

Ветка employer: при слиянии down_revision указывает на актуальную голову main.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "em01"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invitation_complaints",
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_user_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["invitation_id"], ["invitations.id"],
                                name=op.f("fk_invitation_complaints_invitation_id_invitations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                name=op.f("fk_invitation_complaints_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_user_id"], ["users.id"],
                                name=op.f("fk_invitation_complaints_candidate_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitation_complaints")),
        sa.UniqueConstraint("invitation_id", name=op.f("uq_invitation_complaints_invitation_id")),
    )
    with op.batch_alter_table("invitation_complaints", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_invitation_complaints_company_id"), ["company_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("invitation_complaints", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_invitation_complaints_company_id"))
    op.drop_table("invitation_complaints")
