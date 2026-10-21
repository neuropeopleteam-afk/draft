"""Признак синтетического (модельного) кандидата в профиле для бейджа «демо-профиль» и фильтра real_only

Revision ID: a2_01
Revises: tw01
Create Date: 2026-10-20
"""
from collections.abc import Sequence
import json

from alembic import op
import sqlalchemy as sa

revision: str = "a2_01"
down_revision: str | None = "tw01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_profiles",
        sa.Column("is_synthetic", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index("ix_candidate_profiles_is_synthetic", "candidate_profiles", ["is_synthetic"])
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE candidate_profiles SET is_synthetic = true "
        "WHERE jury_mode = false AND user_id IN ("
        "SELECT id FROM users WHERE is_demo = true OR email LIKE '%.invalid')"
    ))
    syn_refs = {
        r[0] for r in conn.execute(
            sa.text("SELECT public_ref FROM candidate_profiles WHERE is_synthetic = true AND public_ref IS NOT NULL")
        ).fetchall()
    }
    if syn_refs:
        rows = conn.execute(sa.text("SELECT id, results FROM selection_versions")).fetchall()
        for row_id, raw in rows:
            data = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(data, list):
                continue
            changed = False
            for item in data:
                if isinstance(item, dict) and item.get("ref") in syn_refs:
                    item["is_synthetic"] = True
                    card = item.get("card")
                    if isinstance(card, dict):
                        card["is_synthetic"] = True
                        card["is_demo"] = True
                    changed = True
            if changed:
                conn.execute(
                    sa.text("UPDATE selection_versions SET results = :res WHERE id = :id"),
                    {"res": json.dumps(data, ensure_ascii=False), "id": row_id},
                )


def downgrade() -> None:
    op.drop_index("ix_candidate_profiles_is_synthetic", table_name="candidate_profiles")
    op.drop_column("candidate_profiles", "is_synthetic")
