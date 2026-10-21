"""Волна 1 (20.10.2026): сведение параллельных веток миграций агентов в одну голову.

Revision ID: w1_merge
Revises: a1_01, a7_01_telegram_links, a9_01_warroom
"""
revision: str = "w1_merge"
down_revision = ("a1_01", "a7_01_telegram_links", "a9_01_warroom")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
