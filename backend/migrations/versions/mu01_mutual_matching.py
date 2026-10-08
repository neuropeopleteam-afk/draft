"""Взаимный подбор (Н9), обратная связь по подборке (Н2), ссылка для нанимающего руководителя (Н3)

Revision ID: mu01
Revises: tk01 (голова integ/0710 2112a11)
Create Date: 2026-10-08

Только новые таблицы: существующие кандидаты, потребности и версии подборок не меняются. SQLite и PostgreSQL 16.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "mu01"
down_revision: str | None = "tk01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "candidate_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("offers_status", sa.String(length=16), nullable=True),
        sa.Column("interest_tags", JSONType, nullable=False),
        sa.Column("interest_tasks", JSONType, nullable=False),
        sa.Column("salary_signal", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint("offers_status IS NULL OR offers_status IN ('active', 'open', 'not_looking')",
                           name=op.f("ck_candidate_preferences_offers_status")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_candidate_preferences_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_candidate_preferences")),
    )
    op.create_table(
        "selection_feedback",
        sa.Column("need_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("candidate_ref", sa.String(length=16), nullable=False),
        sa.Column("verdict", sa.String(length=8), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=True),
        sa.Column("comment", sa.String(length=300), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint("verdict IN ('fit', 'unfit')", name=op.f("ck_selection_feedback_verdict")),
        sa.CheckConstraint("reason IS NULL OR reason IN ('skill', 'grade', 'format', 'salary', 'other')",
                           name=op.f("ck_selection_feedback_reason")),
        sa.ForeignKeyConstraint(["need_id"], ["employer_needs.id"],
                                name=op.f("fk_selection_feedback_need_id_employer_needs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_selection_feedback_created_by_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_selection_feedback")),
        sa.UniqueConstraint("need_id", "candidate_ref", name="uq_selection_feedback_need_ref"),
    )
    op.create_index("ix_selection_feedback_need_id", "selection_feedback", ["need_id"])
    op.create_table(
        "selection_shares",
        sa.Column("need_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("views", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_viewed_at", TS, nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["need_id"], ["employer_needs.id"],
                                name=op.f("fk_selection_shares_need_id_employer_needs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_selection_shares_created_by_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_selection_shares")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_selection_shares_token_hash")),
    )
    op.create_index("ix_selection_shares_need_id", "selection_shares", ["need_id"])
    op.create_table(
        "share_reactions",
        sa.Column("share_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_ref", sa.String(length=16), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("author", sa.String(length=80), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint("verdict IN ('interesting', 'no')", name=op.f("ck_share_reactions_verdict")),
        sa.ForeignKeyConstraint(["share_id"], ["selection_shares.id"],
                                name=op.f("fk_share_reactions_share_id_selection_shares"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_share_reactions")),
        sa.UniqueConstraint("share_id", "candidate_ref", name="uq_share_reactions_share_ref"),
    )
    op.create_index("ix_share_reactions_share_id", "share_reactions", ["share_id"])
    op.create_table(
        "offer_fit_checks",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_user_id", sa.Uuid(), nullable=True),
        sa.Column("salary_bucket", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_offer_fit_checks_company_id_companies"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_user_id"], ["users.id"],
                                name=op.f("fk_offer_fit_checks_candidate_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_offer_fit_checks")),
    )
    op.create_index("ix_offer_fit_checks_company_created", "offer_fit_checks", ["company_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_offer_fit_checks_company_created", table_name="offer_fit_checks")
    op.drop_table("offer_fit_checks")
    op.drop_index("ix_share_reactions_share_id", table_name="share_reactions")
    op.drop_table("share_reactions")
    op.drop_index("ix_selection_shares_need_id", table_name="selection_shares")
    op.drop_table("selection_shares")
    op.drop_index("ix_selection_feedback_need_id", table_name="selection_feedback")
    op.drop_table("selection_feedback")
    op.drop_table("candidate_preferences")
