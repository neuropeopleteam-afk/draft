"""И25 + Н6: подписка работодателя на потребность («новые подходящие») и напоминания — таблицы

Revision ID: sb01
Revises: tk01 (голова базы integ/0710 на 08.10; слиянщик перевешивает на актуальную голову)
Create Date: 2026-10-08
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "sb01"
down_revision: str | None = "tk01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "need_subscriptions",
        sa.Column("need_id", sa.Uuid(), nullable=False),
        sa.Column("employer_user_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("frequency", sa.String(length=16), server_default="instant", nullable=False),
        sa.Column("baseline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("definition_hash", sa.String(length=40), nullable=True),
        sa.Column("top", JSONType, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_digest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("frequency IN ('instant', 'daily', 'weekly')", name=op.f("ck_need_subscriptions_frequency")),
        sa.ForeignKeyConstraint(["need_id"], ["employer_needs.id"], name=op.f("fk_need_subscriptions_need_id_employer_needs"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employer_user_id"], ["users.id"], name=op.f("fk_need_subscriptions_employer_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_need_subscriptions")),
        sa.UniqueConstraint("need_id", name="uq_need_subscriptions_need_id"),
    )
    with op.batch_alter_table("need_subscriptions", schema=None) as b:
        b.create_index(b.f("ix_need_subscriptions_employer_user_id"), ["employer_user_id"], unique=False)

    op.create_table(
        "need_sub_entries",
        sa.Column("sub_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_user_id", sa.Uuid(), nullable=False),
        sa.Column("ref", sa.String(length=16), nullable=False),
        sa.Column("in_top", sa.Boolean(), nullable=False),
        sa.Column("is_new", sa.Boolean(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("result", JSONType, nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["sub_id"], ["need_subscriptions.id"], name=op.f("fk_need_sub_entries_sub_id_need_subscriptions"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_user_id"], ["users.id"], name=op.f("fk_need_sub_entries_candidate_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_need_sub_entries")),
        sa.UniqueConstraint("sub_id", "candidate_user_id", name="uq_need_sub_entries_pair"),
    )
    with op.batch_alter_table("need_sub_entries", schema=None) as b:
        b.create_index(b.f("ix_need_sub_entries_sub_id"), ["sub_id"], unique=False)

    op.create_table(
        "user_notifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("dedupe_key", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("url", sa.String(length=255), nullable=False),
        sa.Column("payload", JSONType, nullable=False),
        sa.Column("channels", JSONType, nullable=False),
        sa.Column("delivery", sa.String(length=16), nullable=False),
        sa.Column("digest", sa.String(length=16), nullable=True),
        sa.Column("push_state", sa.String(length=16), nullable=True),
        sa.Column("email_state", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_notifications_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_notifications")),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_user_notifications_dedupe"),
    )
    with op.batch_alter_table("user_notifications", schema=None) as b:
        b.create_index("ix_user_notifications_user_created", ["user_id", "created_at"], unique=False)
        b.create_index("ix_user_notifications_delivery", ["delivery"], unique=False)

    op.create_table(
        "notify_prefs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("push_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("reminders_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_digest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_weekly_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_notify_prefs_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_notify_prefs")),
    )

    op.create_table(
        "subs_dirty",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_subs_dirty")),
    )
    with op.batch_alter_table("subs_dirty", schema=None) as b:
        b.create_index(b.f("ix_subs_dirty_at"), ["at"], unique=False)

    op.create_table(
        "subs_state",
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stats", JSONType, nullable=True),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_subs_state")),
    )


def downgrade() -> None:
    for t in ("subs_state", "subs_dirty", "notify_prefs", "user_notifications", "need_sub_entries", "need_subscriptions"):
        op.drop_table(t)
