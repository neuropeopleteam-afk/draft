"""Я15: сессии интервьюера — «устная защита» попытки теста и «ИИ-интервью» этапом найма

Revision ID: iv01
Revises: fp01
Create Date: 2026-10-10

Таблица interview_sessions: попытка теста (защита) или приглашение (интервью), кандидат, режим, статус, вердикт
модели, вопросы с подтверждёнными цитатами, расшифровка (только текст), стоимость. Каскадное удаление вместе с
попыткой, приглашением и учётной записью.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "iv01"
down_revision: str | None = "fp01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
T = "interview_sessions"


def upgrade() -> None:
    op.create_table(
        T,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("candidate_user_id", sa.Uuid(), nullable=False),
        sa.Column("test_session_id", sa.Uuid(), nullable=True),
        sa.Column("invitation_id", sa.Uuid(), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("engine", sa.String(length=8), nullable=False),
        sa.Column("state", JSONType, nullable=False),
        sa.Column("channel", sa.String(length=8), nullable=True),
        sa.Column("jury_scope", sa.String(length=16), nullable=True),
        sa.Column("is_example", sa.Boolean(), nullable=False),
        sa.Column("minutes", sa.SmallInteger(), nullable=False),
        sa.Column("max_questions", sa.SmallInteger(), nullable=False),
        sa.Column("context_meta", JSONType, nullable=False),
        sa.Column("result", JSONType, nullable=False),
        sa.Column("transcript", JSONType, nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("cost", JSONType, nullable=True),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.Column("consent_version", sa.String(length=32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("mode IN ('defense', 'interview')", name=op.f("ck_interview_sessions_mode")),
        sa.CheckConstraint("status IN ('invited', 'created', 'in_progress', 'evaluating', 'completed', 'failed', "
                           "'expired', 'cancelled')", name=op.f("ck_interview_sessions_status")),
        sa.ForeignKeyConstraint(["candidate_user_id"], ["users.id"],
                                name=op.f("fk_interview_sessions_candidate_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_session_id"], ["test_sessions.id"],
                                name=op.f("fk_interview_sessions_test_session_id_test_sessions"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invitation_id"], ["invitations.id"],
                                name=op.f("fk_interview_sessions_invitation_id_invitations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                name=op.f("fk_interview_sessions_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_interview_sessions_created_by_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_sessions")),
    )
    op.create_index("ix_interview_sessions_candidate_created", T, ["candidate_user_id", "created_at"])
    op.create_index(op.f("ix_interview_sessions_test_session_id"), T, ["test_session_id"])
    op.create_index(op.f("ix_interview_sessions_invitation_id"), T, ["invitation_id"])
    op.create_index(op.f("ix_interview_sessions_jury_scope"), T, ["jury_scope"])
    op.create_index(op.f("ix_interview_sessions_created_at"), T, ["created_at"])


def downgrade() -> None:
    for ix in ("created_at", "jury_scope", "invitation_id", "test_session_id"):
        op.drop_index(op.f(f"ix_interview_sessions_{ix}"), table_name=T)
    op.drop_index("ix_interview_sessions_candidate_created", table_name=T)
    op.drop_table(T)
