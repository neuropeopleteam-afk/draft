"""Второй фактор входа (TOTP, RFC 6238) и одноразовые резервные коды

Revision ID: tf01
Revises: if01 (перевешена при слиянии в integ/0710; в ветке — fs01)
Create Date: 2026-10-07

Ветка feat/2fa: при слиянии down_revision указывает на актуальную голову integ/0710.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "tf01"
down_revision: str | None = "if01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_two_factor",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("secret_enc", sa.String(length=255), nullable=False),
        sa.Column("pending_secret_enc", sa.String(length=255), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_step", sa.BigInteger(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fail_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_two_factor_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_two_factor")),
    )
    op.create_table(
        "user_two_factor_recovery_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_two_factor_recovery_codes_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_two_factor_recovery_codes")),
    )
    op.create_index(op.f("ix_user_two_factor_recovery_codes_user_id"), "user_two_factor_recovery_codes", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_user_two_factor_recovery_codes_user_id"), table_name="user_two_factor_recovery_codes")
    op.drop_table("user_two_factor_recovery_codes")
    op.drop_table("user_two_factor")
