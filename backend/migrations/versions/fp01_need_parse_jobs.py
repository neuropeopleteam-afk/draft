"""И27: быстрый разбор потребности — фоновые задачи уточнения моделью и кэш разбора по тексту

Revision ID: fp01
Revises: mu01 (голова integ/0710 1da1080 на 09.10; было pc01 → tk02 — перевешено при слияниях)
Create Date: 2026-10-09

Таблица need_parse_jobs: задача фонового уточнения разбора (status pending → done | failed) и одновременно кэш:
строка done с тем же ключом (хеш нормализованного текста и подсказок) отдаётся без повторного вызова модели.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "fp01"
down_revision: str | None = "mu01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "need_parse_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result", JSONType, nullable=True),
        sa.Column("delta", JSONType, nullable=True),
        sa.Column("llm", JSONType, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_need_parse_jobs_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_need_parse_jobs")),
    )
    op.create_index(op.f("ix_need_parse_jobs_key"), "need_parse_jobs", ["key"])
    op.create_index(op.f("ix_need_parse_jobs_user_id"), "need_parse_jobs", ["user_id"])
    op.create_index(op.f("ix_need_parse_jobs_created_at"), "need_parse_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_need_parse_jobs_created_at"), table_name="need_parse_jobs")
    op.drop_index(op.f("ix_need_parse_jobs_user_id"), table_name="need_parse_jobs")
    op.drop_index(op.f("ix_need_parse_jobs_key"), table_name="need_parse_jobs")
    op.drop_table("need_parse_jobs")
