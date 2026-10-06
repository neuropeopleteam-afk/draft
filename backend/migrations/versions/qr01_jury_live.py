"""Идея 13: живая демонстрация для жюри — залы (QR) и гости с мини-тестом

Revision ID: qr01
Revises: x001
Create Date: 2026-10-06

Ветка qr: при перебазировании на main down_revision указывает на актуальную голову main.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "qr01"
down_revision: str | None = "x001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "jury_live_rooms",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("sid", sa.String(length=16), nullable=False),
        sa.Column("rev", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jury_live_rooms")),
        sa.UniqueConstraint("code", name=op.f("uq_jury_live_rooms_code")),
        sa.UniqueConstraint("sid", name=op.f("uq_jury_live_rooms_sid")),
    )
    op.create_table(
        "jury_live_guests",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("ref", sa.String(length=16), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("state", JSONType, nullable=False),
        sa.Column("result", JSONType, nullable=False),
        sa.Column("selection", JSONType, nullable=False),
        sa.Column("invite", JSONType, nullable=False),
        sa.Column("events", JSONType, nullable=False),
        sa.Column("push_state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["jury_live_rooms.id"],
                                name=op.f("fk_jury_live_guests_room_id_jury_live_rooms"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                name=op.f("fk_jury_live_guests_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jury_live_guests")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_jury_live_guests_token_hash")),
    )
    with op.batch_alter_table("jury_live_guests") as b:
        b.create_index(b.f("ix_jury_live_guests_room_id"), ["room_id"], unique=False)
        b.create_index(b.f("ix_jury_live_guests_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("jury_live_guests") as b:
        b.drop_index(b.f("ix_jury_live_guests_user_id"))
        b.drop_index(b.f("ix_jury_live_guests_room_id"))
    op.drop_table("jury_live_guests")
    op.drop_table("jury_live_rooms")
