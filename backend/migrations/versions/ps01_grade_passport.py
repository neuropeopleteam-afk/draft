"""Подписанный паспорт грейда (Ed25519): реестр паспортов и открытых ключей подписи

Revision ID: ps01
Revises: fx01 (перевешена при слиянии в integ/0710; в ветке — qr01)
Create Date: 2026-10-07

Ветка passport: при слиянии down_revision указывает на актуальную голову main (координатор выстраивает цепочку).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "ps01"
down_revision: str | None = "fx01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "grade_passports",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("public_ref", sa.String(length=16), nullable=True),
        sa.Column("category_id", sa.String(length=64), nullable=False),
        sa.Column("grade_status", sa.String(length=16), nullable=False),
        sa.Column("kid", sa.String(length=64), nullable=False),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("signature", sa.String(length=128), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("test_session_id", sa.Uuid(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_grade_passports_user_id_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grade_passports")),
    )
    op.create_index("ix_grade_passports_user_active", "grade_passports", ["user_id", "revoked_at"])
    op.create_table(
        "passport_keys",
        sa.Column("kid", sa.String(length=64), nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=False),
        sa.Column("test_key", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("kid", name=op.f("pk_passport_keys")),
    )


def downgrade() -> None:
    op.drop_table("passport_keys")
    op.drop_index("ix_grade_passports_user_active", table_name="grade_passports")
    op.drop_table("grade_passports")
