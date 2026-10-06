"""Экспертная разметка: эксперты по приглашению, пакет объектов (пары, ответы, Ангофф), оценки.

Revision ID: ex01
Revises: 0004
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "ex01"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "expert_panelists",
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("slot", sa.String(16), nullable=False),
        sa.Column("team_size", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column("profile", sa.String(255), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=True),
        sa.Column("pack", sa.String(16), nullable=False),
        sa.Column("assignment", JSONType, nullable=False),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("instructions_ack_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_expert_panelists_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expert_panelists")),
        sa.UniqueConstraint("user_id", name=op.f("uq_expert_panelists_user_id")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_expert_panelists_token_hash")),
    )
    op.create_index("ix_expert_panelists_code_demo", "expert_panelists", ["code", "is_demo"])
    op.create_table(
        "expert_items",
        sa.Column("pack", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(1), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("grp", sa.String(120), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("payload", JSONType, nullable=False),
        sa.Column("hidden", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("kind IN ('A', 'B', 'C')", name=op.f("ck_expert_items_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expert_items")),
        sa.UniqueConstraint("pack", "key", name="uq_expert_items_pack_key"),
    )
    op.create_index(op.f("ix_expert_items_pack"), "expert_items", ["pack"])
    op.create_table(
        "expert_labels",
        sa.Column("panelist_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("value", JSONType, nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["expert_items.id"], name=op.f("fk_expert_labels_item_id_expert_items"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["panelist_id"], ["expert_panelists.id"],
                                name=op.f("fk_expert_labels_panelist_id_expert_panelists"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expert_labels")),
        sa.UniqueConstraint("panelist_id", "item_id", name="uq_expert_labels_panelist_item"),
    )
    op.create_index(op.f("ix_expert_labels_panelist_id"), "expert_labels", ["panelist_id"])
    op.create_index(op.f("ix_expert_labels_item_id"), "expert_labels", ["item_id"])


def downgrade() -> None:
    op.drop_table("expert_labels")
    op.drop_table("expert_items")
    op.drop_table("expert_panelists")
