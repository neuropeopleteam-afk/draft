"""«Мои данные» и отметка интереса: события интереса работодателей, журнал удаления, метка удалённого профиля

Revision ID: md01
Revises: oa01 (перевешена при слиянии волны 4: в ветке была mu01)
Create Date: 2026-10-09

* candidate_interest_events — «карточку открыл работодатель» и «попал в подборку» без названия компании;
* account_deletion_log — журнал уничтожения ПДн без идентификаторов;
* candidate_profiles.deleted_at — метка обезличенной записи после удаления учётной записи (профиль-«надгробие»
  сохраняет только обезличенный ref, на который ссылаются приглашения работодателей).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "md01"
down_revision: str | None = "oa01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "candidate_interest_events",
        sa.Column("candidate_user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("company_key", sa.Uuid(), nullable=False),
        sa.Column("need_key", sa.Uuid(), nullable=True),
        sa.Column("rank", sa.SmallInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("kind IN ('card_view', 'selection')", name=op.f("ck_candidate_interest_events_kind")),
        sa.ForeignKeyConstraint(["candidate_user_id"], ["users.id"],
                                name=op.f("fk_candidate_interest_events_candidate_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_interest_events")),
    )
    op.create_index("ix_candidate_interest_events_cand_created", "candidate_interest_events",
                    ["candidate_user_id", "created_at"])
    op.create_table(
        "account_deletion_log",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("details", JSONType, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_deletion_log")),
    )
    op.add_column("candidate_profiles", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("candidate_profiles", "deleted_at")
    op.drop_table("account_deletion_log")
    op.drop_index("ix_candidate_interest_events_cand_created", table_name="candidate_interest_events")
    op.drop_table("candidate_interest_events")
