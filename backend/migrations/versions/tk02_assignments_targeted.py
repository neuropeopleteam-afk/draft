"""К5: адресные задания — причина предложения («почему вам»), рубрика с оценкой работодателя, настройки ленты

Revision ID: tk02
Revises: sb01 (перевешено слиянщиком волны 3; в ветке — tk01)
Create Date: 2026-10-08
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "tk02"
down_revision: str | None = "sb01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("assignments", schema=None) as b:
        b.add_column(sa.Column("rubric", JSONType, nullable=True))  # критерии и баллы, видны до отправки
        b.add_column(sa.Column("approach_prompt", sa.Text(), nullable=True))  # просьба описать подход (оценивает работодатель)
    with op.batch_alter_table("assignment_attempts", schema=None) as b:
        b.add_column(sa.Column("why", JSONType, nullable=True))  # причина предложения: слепок на момент выдачи
        b.add_column(sa.Column("approach_text", sa.Text(), nullable=True))  # ответ о подходе (без контактов)
        b.add_column(sa.Column("rubric_result", JSONType, nullable=True))  # баллы по критериям: авто и работодатель
        b.add_column(sa.Column("review_status", sa.String(length=16), server_default="none", nullable=False))
        b.add_column(sa.Column("final_points", sa.Integer(), nullable=True))  # итог по рубрике, 0..100
        b.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("remind_at", sa.DateTime(timezone=True), nullable=True))  # последнее напоминание кандидату
        b.add_column(sa.Column("remind_count", sa.Integer(), server_default="0", nullable=False))
        b.add_column(sa.Column("review_remind_at", sa.DateTime(timezone=True), nullable=True))  # напоминание работодателю
        b.add_column(sa.Column("review_remind_count", sa.Integer(), server_default="0", nullable=False))
    op.create_table(
        "assignment_prefs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("frequency_days", sa.Integer(), server_default="7", nullable=False),  # 0 — не предлагать
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_assignment_prefs_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_assignment_prefs")),
    )


def downgrade() -> None:
    op.drop_table("assignment_prefs")
    with op.batch_alter_table("assignment_attempts", schema=None) as b:
        for c in ("review_remind_count", "review_remind_at", "remind_count", "remind_at", "reviewed_at", "final_points",
                  "review_status", "rubric_result", "approach_text", "why"):
            b.drop_column(c)
    with op.batch_alter_table("assignments", schema=None) as b:
        b.drop_column("approach_prompt")
        b.drop_column("rubric")
