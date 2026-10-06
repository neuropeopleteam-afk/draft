"""Лимит перезапусков теста в демо-режиме жюри; демо-режим — только у демо-учёток.

* sandbox_test_starts — начала тестов в демо-режиме (по почте, без FK: счётчик переживает сброс жюри);
* jury_mode сбрасывается у всех не-демо кандидатов (режим жюри теперь только для users.is_demo).

Ветка feat/feedback: при слиянии координатор выстроит цепочку (down_revision — актуальная голова main).

Revision ID: fb01
Revises: 0004
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "fb01"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sandbox_test_starts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sandbox_test_starts")),
    )
    op.create_index(op.f("ix_sandbox_test_starts_email"), "sandbox_test_starts", ["email"])
    op.create_index(op.f("ix_sandbox_test_starts_created_at"), "sandbox_test_starts", ["created_at"])
    profiles = sa.table("candidate_profiles", sa.column("user_id", sa.Uuid()), sa.column("jury_mode", sa.Boolean()))
    users = sa.table("users", sa.column("id", sa.Uuid()), sa.column("is_demo", sa.Boolean()))
    op.execute(profiles.update()
               .where(profiles.c.jury_mode.is_(sa.true()),
                      ~profiles.c.user_id.in_(sa.select(users.c.id).where(users.c.is_demo.is_(sa.true()))))
               .values(jury_mode=sa.false()))


def downgrade() -> None:
    op.drop_index(op.f("ix_sandbox_test_starts_created_at"), table_name="sandbox_test_starts")
    op.drop_index(op.f("ix_sandbox_test_starts_email"), table_name="sandbox_test_starts")
    op.drop_table("sandbox_test_starts")
