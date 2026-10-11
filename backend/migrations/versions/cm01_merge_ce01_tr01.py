"""Слияние голов: каталог расширения (ce01) и тарифы (tr01) — обе после iv01

Revision ID: cm01
Revises: ce01, tr01
Create Date: 2026-10-11

Только объединение ветвей истории миграций (alembic merge): схема не меняется, upgrade/downgrade пусты.
"""
from collections.abc import Sequence

revision: str = "cm01"
down_revision: str | Sequence[str] | None = ("ce01", "tr01")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
