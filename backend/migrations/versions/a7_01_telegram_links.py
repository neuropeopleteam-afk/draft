"""Привязка Telegram для уведомлений о приглашениях и сообщениях

Revision ID: a7_01_telegram_links
Revises: tw01
Create Date: 2026-10-20
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "a7_01_telegram_links"
down_revision: str | None = "tw01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("link_code", sa.String(length=64), nullable=True),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chat_id", sa.String(length=64), nullable=True),
        sa.Column("tg_username", sa.String(length=128), nullable=True),
        sa.Column("tg_first_name", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_telegram_links_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_links")),
        sa.UniqueConstraint("user_id", name=op.f("uq_telegram_links_user_id")),
        sa.UniqueConstraint("link_code", name=op.f("uq_telegram_links_link_code")),
    )
    op.create_index("ix_telegram_links_user_id", "telegram_links", ["user_id"])
    op.create_index("ix_telegram_links_link_code", "telegram_links", ["link_code"])
    op.create_index("ix_telegram_links_chat_id", "telegram_links", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_telegram_links_chat_id", table_name="telegram_links")
    op.drop_index("ix_telegram_links_link_code", table_name="telegram_links")
    op.drop_index("ix_telegram_links_user_id", table_name="telegram_links")
    op.drop_table("telegram_links")
