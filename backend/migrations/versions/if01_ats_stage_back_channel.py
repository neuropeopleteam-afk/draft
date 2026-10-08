"""Обратный канал ATS → платформа: этап подбора у приглашения и отклика, журнал этапов, отметка опроса

Revision ID: if01
Revises: ct01 (перевешена при слиянии в integ/0710; в ветке — qr01)
Create Date: 2026-10-07

Ветка infra2: при перебазировании down_revision указывает на актуальную голову main.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "if01"
down_revision: str | None = "ct01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("invitations") as b:
        b.add_column(sa.Column("ats_stage", JSONType, nullable=True))
    with op.batch_alter_table("vacancy_applications") as b:
        b.add_column(sa.Column("ats_stage", JSONType, nullable=True))
    with op.batch_alter_table("ats_connections") as b:
        b.add_column(sa.Column("stages_synced_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("stages_sync_info", JSONType, nullable=False, server_default="{}"))
    op.create_table(
        "ats_stage_events",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("candidate_user_id", sa.Uuid(), nullable=True),
        sa.Column("invitation_id", sa.Uuid(), nullable=True),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("external_id", sa.String(length=64), nullable=True),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("join_id", sa.BigInteger(), nullable=True),
        sa.Column("stage_id", sa.BigInteger(), nullable=True),
        sa.Column("stage_name", sa.String(length=255), nullable=True),
        sa.Column("stage_type", sa.String(length=64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("stage", sa.String(length=16), nullable=True),
        sa.Column("prev_stage", sa.String(length=16), nullable=True),
        sa.Column("effect", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("status IN ('ok', 'error')", name=op.f("ck_ats_stage_events_status")),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_ats_stage_events_company_id_companies"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_user_id"], ["users.id"],
                                name=op.f("fk_ats_stage_events_candidate_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invitation_id"], ["invitations.id"],
                                name=op.f("fk_ats_stage_events_invitation_id_invitations"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["application_id"], ["vacancy_applications.id"],
                                name=op.f("fk_ats_stage_events_application_id_vacancy_applications"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ats_stage_events")),
    )
    with op.batch_alter_table("ats_stage_events") as b:
        b.create_index("ix_ats_stage_events_company_created", ["company_id", "created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("ats_stage_events") as b:
        b.drop_index("ix_ats_stage_events_company_created")
    op.drop_table("ats_stage_events")
    with op.batch_alter_table("ats_connections") as b:
        b.drop_column("stages_sync_info")
        b.drop_column("stages_synced_at")
    with op.batch_alter_table("vacancy_applications") as b:
        b.drop_column("ats_stage")
    with op.batch_alter_table("invitations") as b:
        b.drop_column("ats_stage")
