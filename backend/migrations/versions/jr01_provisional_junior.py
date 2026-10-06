"""«Junior (предварительно)»: признак предварительной категории в профиле кандидата, причины истории грейда
provisional (присвоена предварительно) и confirmed (предварительная подтверждена — не смена грейда)

Revision ID: jr01
Revises: x001
Create Date: 2026-10-06

CHECK-ограничение перечисления причин (VARCHAR + CHECK, см. app.core.db.str_enum) пересоздаётся с новыми
значениями: в SQLite — через batch (пересоздание таблицы), в PostgreSQL — DROP/ADD CONSTRAINT.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "jr01"
down_revision: str | None = "x001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REASONS_OLD = ("initial", "retest_up", "retest_down", "sandbox", "admin")
REASONS_NEW = (*REASONS_OLD, "provisional", "confirmed")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _recheck(values: tuple[str, ...]) -> None:
    with op.batch_alter_table("grade_history") as b:
        b.drop_constraint(op.f("ck_grade_history_grade_change_reason"), type_="check")
        b.create_check_constraint(op.f("ck_grade_history_grade_change_reason"), _in("reason", values))


def upgrade() -> None:
    _recheck(REASONS_NEW)
    with op.batch_alter_table("candidate_profiles") as b:
        b.add_column(sa.Column("grade_provisional", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.execute("UPDATE grade_history SET reason = 'initial' WHERE reason IN ('provisional', 'confirmed')")
    _recheck(REASONS_OLD)
    with op.batch_alter_table("candidate_profiles") as b:
        b.drop_column("grade_provisional")
