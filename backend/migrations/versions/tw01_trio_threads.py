"""Трёхсторонняя связь: работодатель ↔ кандидат ↔ представитель ФСП

Revision ID: tw01
Revises: cm01
Create Date: 2026-10-20

trio_threads — канал по приглашению (одно приглашение — один канал), статус pending/active/closed;
trio_messages — сообщения трёх сторон и системные отметки (кто подключился, кто закрыл).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "tw01"
down_revision: str | None = "cm01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trio_threads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_user_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by_side", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'active', 'closed')", name=op.f("ck_trio_threads_status")),
        sa.CheckConstraint("created_by_side IN ('candidate', 'employer')", name=op.f("ck_trio_threads_created_by_side")),
        sa.ForeignKeyConstraint(["invitation_id"], ["invitations.id"], name=op.f("fk_trio_threads_invitation_id_invitations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_trio_threads_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_user_id"], ["users.id"], name=op.f("fk_trio_threads_candidate_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_trio_threads_created_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trio_threads")),
        sa.UniqueConstraint("invitation_id", name=op.f("uq_trio_threads_invitation_id")),
    )
    op.create_index("ix_trio_threads_candidate", "trio_threads", ["candidate_user_id"])
    op.create_index("ix_trio_threads_company", "trio_threads", ["company_id"])
    op.create_table(
        "trio_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("sender_user_id", sa.Uuid(), nullable=True),
        sa.Column("sender_side", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("masked", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sender_side IN ('candidate', 'employer', 'fsp', 'system')", name=op.f("ck_trio_messages_sender_side")),
        sa.ForeignKeyConstraint(["thread_id"], ["trio_threads.id"], name=op.f("fk_trio_messages_thread_id_trio_threads"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"], name=op.f("fk_trio_messages_sender_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trio_messages")),
    )
    op.create_index("ix_trio_messages_thread_created", "trio_messages", ["thread_id", "created_at"])
    op.create_index("ix_trio_messages_sender_created", "trio_messages", ["sender_user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_trio_messages_sender_created", table_name="trio_messages")
    op.drop_index("ix_trio_messages_thread_created", table_name="trio_messages")
    op.drop_table("trio_messages")
    op.drop_index("ix_trio_threads_company", table_name="trio_threads")
    op.drop_index("ix_trio_threads_candidate", table_name="trio_threads")
    op.drop_table("trio_threads")
