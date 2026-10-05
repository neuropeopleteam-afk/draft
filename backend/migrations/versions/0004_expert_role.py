"""Роль expert (проверка развёрнутых ответов) — отдельно от admin.

Revision ID: 0004
Revises: i001
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: str | None = "i001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW = "role IN ('candidate', 'employer', 'admin', 'expert')"
OLD = "role IN ('candidate', 'employer', 'admin')"


def _set(check: str) -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_user_role")
        op.execute(f"ALTER TABLE users ADD CONSTRAINT ck_users_user_role CHECK ({check})")
    else:  # SQLite: CHECK меняется только пересозданием таблицы
        with op.batch_alter_table("users", recreate="always") as b:
            b.drop_constraint(op.f("ck_users_user_role"), type_="check")
            b.create_check_constraint(op.f("ck_users_user_role"), sa.text(check))


def upgrade() -> None:
    _set(NEW)


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'expert'")
    _set(OLD)
