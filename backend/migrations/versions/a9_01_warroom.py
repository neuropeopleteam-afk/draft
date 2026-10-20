"""Боевой ИИ-Полигон: попытки прохождения архитектурных инцидентов (warroom_attempts)

Revision ID: a9_01_warroom
Revises: tw01
Create Date: 2026-10-20
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "a9_01_warroom"
down_revision: str | None = "tw01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "warroom_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("test_session_id", sa.Uuid(), nullable=True),
        sa.Column("scenario_id", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("target_grade", sa.String(length=16), nullable=False),
        sa.Column("confirmed_grade", sa.String(length=16), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False, server_default="1001"),
        sa.Column("measures", sa.JSON(), nullable=False),
        sa.Column("code_patch", sa.Text(), nullable=False, server_default=""),
        sa.Column("justification", sa.Text(), nullable=False, server_default=""),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("slo_met", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("cost_rub_month", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_budget_rub_month", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sim_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("code_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rubric_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reviewer_mode", sa.String(length=32), nullable=False, server_default="deterministic_simulator"),
        sa.Column("rubric_details", sa.JSON(), nullable=False),
        sa.Column("incident_stage", sa.JSON(), nullable=False),
        sa.Column("elapsed_s", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256_sig", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_warroom_attempts_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_session_id"], ["test_sessions.id"], name=op.f("fk_warroom_attempts_test_session_id_test_sessions"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_warroom_attempts")),
    )
    op.create_index("ix_warroom_attempts_user_id", "warroom_attempts", ["user_id"])
    op.create_index("ix_warroom_attempts_scenario_id", "warroom_attempts", ["scenario_id"])
    op.create_index("ix_warroom_attempts_direction", "warroom_attempts", ["direction"])
    op.create_index("ix_warroom_attempts_created_at", "warroom_attempts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_warroom_attempts_created_at", table_name="warroom_attempts")
    op.drop_index("ix_warroom_attempts_direction", table_name="warroom_attempts")
    op.drop_index("ix_warroom_attempts_scenario_id", table_name="warroom_attempts")
    op.drop_index("ix_warroom_attempts_user_id", table_name="warroom_attempts")
    op.drop_table("warroom_attempts")
