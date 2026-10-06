"""ATS-провайдеры Talantix и «Поток»: подключения компании, связи кандидатов (идемпотентность), новые адресаты журнала.

Revision ID: at01
Revises: 0004
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

revision: str = "at01"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW = "target IN ('huntflow', 'talantix', 'potok', 'webhook')"
OLD = "target IN ('huntflow', 'webhook')"


def _set_targets(check: str) -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE ats_deliveries DROP CONSTRAINT IF EXISTS ck_ats_deliveries_target")
        op.execute(f"ALTER TABLE ats_deliveries ADD CONSTRAINT ck_ats_deliveries_target CHECK ({check})")
    else:  # SQLite: CHECK меняется только пересозданием таблицы
        with op.batch_alter_table("ats_deliveries", recreate="always") as b:
            b.drop_constraint(op.f("ck_ats_deliveries_target"), type_="check")
            b.create_check_constraint(op.f("ck_ats_deliveries_target"), sa.text(check))


def upgrade() -> None:
    op.create_table(
        "ats_connections",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=True),
        sa.Column("secrets_enc", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vacancy_id", sa.BigInteger(), nullable=True),
        sa.Column("vacancy_title", sa.String(length=255), nullable=True),
        sa.Column("stage_id", sa.BigInteger(), nullable=True),
        sa.Column("stage_title", sa.String(length=255), nullable=True),
        sa.Column("vacancy_map", JSONType, nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=True),
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check_ok", sa.Boolean(), nullable=True),
        sa.Column("last_check_info", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("provider IN ('talantix', 'potok')", name=op.f("ck_ats_connections_provider")),
        sa.CheckConstraint("mode IN ('demo', 'real')", name=op.f("ck_ats_connections_mode")),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_ats_connections_company_id_companies"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("company_id", "provider", name=op.f("pk_ats_connections")),
    )
    op.create_table(
        "ats_links",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("candidate_user_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=True),
        sa.Column("vacancies", JSONType, nullable=False),
        sa.Column("lock_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_ats_links_company_id_companies"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_user_id"], ["users.id"], name=op.f("fk_ats_links_candidate_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ats_links")),
        sa.UniqueConstraint("company_id", "provider", "candidate_user_id", name="uq_ats_links_company_provider_candidate"),
    )
    _set_targets(NEW)


def downgrade() -> None:
    op.execute("DELETE FROM ats_deliveries WHERE target IN ('talantix', 'potok')")
    _set_targets(OLD)
    op.drop_table("ats_links")
    op.drop_table("ats_connections")
