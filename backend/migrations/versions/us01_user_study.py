"""Проверка с живыми пользователями: участники, события пути, ответы анкеты

Revision ID: us01
Revises: sb01 (голова integ/0710 на момент ветки; перед слиянием — перевесить на текущую голову)
Create Date: 2026-10-09
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "us01"
down_revision: str | None = "sb01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "study_participants",
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prompted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('candidate', 'employer')", name=op.f("ck_study_participants_role")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_study_participants_user_id_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_participants")),
        sa.UniqueConstraint("user_id", name=op.f("uq_study_participants_user_id")),
    )

    op.create_table(
        "study_events",
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.SmallInteger(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("kind IN ('view', 'error')", name=op.f("ck_study_events_kind")),
        sa.ForeignKeyConstraint(["participant_id"], ["study_participants.id"],
                                name=op.f("fk_study_events_participant_id_study_participants"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_events")),
    )
    with op.batch_alter_table("study_events", schema=None) as b:
        b.create_index(b.f("ix_study_events_participant_id"), ["participant_id"], unique=False)
        b.create_index("ix_study_events_participant_at", ["participant_id", "at"], unique=False)

    op.create_table(
        "study_answers",
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("sus", JSONType, nullable=False),
        sa.Column("ratings", JSONType, nullable=False),
        sa.Column("selection", JSONType, nullable=True),
        sa.Column("belief", sa.SmallInteger(), nullable=True),
        sa.Column("grade_fit", sa.String(length=8), nullable=True),
        sa.Column("tags", JSONType, nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("path_done", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["participant_id"], ["study_participants.id"],
                                name=op.f("fk_study_answers_participant_id_study_participants"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_answers")),
        sa.UniqueConstraint("participant_id", name=op.f("uq_study_answers_participant_id")),
    )


def downgrade() -> None:
    for t in ("study_answers", "study_events", "study_participants"):
        op.drop_table(t)
