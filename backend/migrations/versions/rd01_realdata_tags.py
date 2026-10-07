"""Separate broad stack tags, no candidate changes.

Revision ID: rd01
Revises: ir01 (в ветке feat/realdata — qr01; перевешена при слиянии в integ/0710)
"""
from alembic import op
import sqlalchemy as sa

revision = "rd01"
down_revision = "ir01"
branch_labels = None
depends_on = None
TAGS = [
    ("kotlin", "Kotlin", "language", "backend"),
    ("csharp", "C#", "language", "backend"),
    ("php", "PHP", "language", "backend"),
    ("kubernetes", "Kubernetes", "tool", None),
]


def upgrade():
    table = sa.table("stack_tags", sa.column("id", sa.String), sa.column("title", sa.String),
                     sa.column("kind", sa.String), sa.column("direction_id", sa.String),
                     sa.column("sort_order", sa.Integer))
    op.bulk_insert(table, [{**dict(zip(("id", "title", "kind", "direction_id"), row)), "sort_order": 90}
                          for row in TAGS])


def downgrade():
    # Removing referenced tags should fail rather than silently destroying candidate facts.
    op.execute(sa.text("DELETE FROM stack_tags WHERE id IN ('kotlin','csharp','php','kubernetes')"))
