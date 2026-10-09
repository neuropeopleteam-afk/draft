"""И23: импорт вакансий из ATS («Поток») — источник, id и ссылка вакансии в ATS, время импорта, дедупликация

Revision ID: oa01
Revises: pc01 (при слиянии в integ/0710 — текущая голова integ)
Create Date: 2026-10-09

Вакансии, созданные на платформе вручную, — source = NULL. Импортированные — source = 'potok', external_id = id
вакансии в «Потоке». Уникальный индекс (company_id, source, external_id) исключает дубликаты при повторном импорте
(NULL в source/external_id не участвуют в уникальности — ручные вакансии не ограничены).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "oa01"
down_revision: str | None = "pc01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("vacancies") as b:
        b.add_column(sa.Column("source", sa.String(length=16), nullable=True))
        b.add_column(sa.Column("external_id", sa.String(length=64), nullable=True))
        b.add_column(sa.Column("external_url", sa.String(length=500), nullable=True))
        b.add_column(sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("vacancies") as b:
        b.create_index("uq_vacancies_company_source_external", ["company_id", "source", "external_id"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("vacancies") as b:
        b.drop_index("uq_vacancies_company_source_external")
    with op.batch_alter_table("vacancies") as b:
        b.drop_column("imported_at")
        b.drop_column("external_url")
        b.drop_column("external_id")
        b.drop_column("source")
