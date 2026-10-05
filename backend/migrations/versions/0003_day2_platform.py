"""День 2: опрос и приватность кандидата, резюме, зонды, рыночные диапазоны из открытых данных, демо-метки

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05

Рыночные диапазоны — калькулятор зарплат Хабр Карьеры (выгрузка 05.10.2026): «от» = 25-й перцентиль,
«до» = 75-й перцентиль, медиана — отдельно; округление до 5 000 ₽. Методика — docs/SALARY_SOURCES.md.
"""
from collections.abc import Sequence
from datetime import date
import secrets

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

MARKET_SOURCE = "Хабр Карьера, калькулятор зарплат (p25–p75)"
MARKET_AS_OF = date(2026, 10, 5)
# (направление, грейд): (от = p25, до = p75, медиана, число анкет)
MARKET = {
    ("backend", "junior"): (65000, 140000, 100000, 906),
    ("backend", "middle"): (150000, 290000, 220000, 3386),
    ("backend", "senior"): (275000, 430000, 340000, 2110),
    ("frontend", "junior"): (60000, 115000, 85000, 297),
    ("frontend", "middle"): (130000, 260000, 190000, 1319),
    ("frontend", "senior"): (255000, 405000, 335000, 808),
    ("qa", "junior"): (65000, 110000, 85000, 431),
    ("qa", "middle"): (120000, 205000, 155000, 1107),
    ("qa", "senior"): (210000, 340000, 270000, 464),
    ("data_ml", "junior"): (80000, 170000, 115000, 196),
    ("data_ml", "middle"): (165000, 300000, 225000, 441),
    ("data_ml", "senior"): (280000, 480000, 390000, 178),
    ("security", "junior"): (70000, 140000, 100000, 157),
    ("security", "middle"): (120000, 235000, 170000, 342),
    ("security", "senior"): (185000, 375000, 280000, 94),
}
# Прежние ориентиры дня 1 — для отката
OLD_MARKET = {
    ("backend", "junior"): (80_000, 150_000), ("backend", "middle"): (180_000, 300_000),
    ("backend", "senior"): (300_000, 450_000), ("frontend", "junior"): (70_000, 130_000),
    ("frontend", "middle"): (160_000, 280_000), ("frontend", "senior"): (280_000, 420_000),
    ("data_ml", "junior"): (90_000, 160_000), ("data_ml", "middle"): (200_000, 330_000),
    ("data_ml", "senior"): (330_000, 500_000), ("qa", "junior"): (60_000, 110_000),
    ("qa", "middle"): (130_000, 220_000), ("qa", "senior"): (220_000, 330_000),
    ("security", "junior"): (80_000, 140_000), ("security", "middle"): (180_000, 300_000),
    ("security", "senior"): (300_000, 450_000),
}
REF_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("is_demo", sa.Boolean(), server_default=sa.false(), nullable=False))
    with op.batch_alter_table("companies") as b:
        b.add_column(sa.Column("is_demo", sa.Boolean(), server_default=sa.false(), nullable=False))
    with op.batch_alter_table("candidate_profiles") as b:
        b.add_column(sa.Column("public_ref", sa.String(16), nullable=True))
        b.add_column(sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("roles", JSONType, server_default="[]", nullable=False))
        b.add_column(sa.Column("fsp_id_claimed", sa.String(64), nullable=True))
        b.add_column(sa.Column("jury_mode", sa.Boolean(), server_default=sa.false(), nullable=False))
        b.create_unique_constraint("uq_candidate_profiles_public_ref", ["public_ref"])
    with op.batch_alter_table("categories") as b:
        b.add_column(sa.Column("market_salary_median", sa.Integer(), nullable=True))
        b.add_column(sa.Column("market_sample_size", sa.Integer(), nullable=True))
        b.add_column(sa.Column("market_source", sa.String(255), nullable=True))
        b.add_column(sa.Column("market_as_of", sa.Date(), nullable=True))
    with op.batch_alter_table("probes") as b:
        b.add_column(sa.Column("answer_mode", sa.String(16), server_default="any", nullable=False))
        b.add_column(sa.Column("review", JSONType, nullable=True))
        b.add_column(sa.Column("events", JSONType, server_default="[]", nullable=False))
    with op.batch_alter_table("invitations") as b:
        b.add_column(sa.Column("decline_reason", sa.Text(), nullable=True))

    op.create_table(
        "candidate_resumes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("text_redacted", sa.Text(), nullable=False),
        sa.Column("pii_summary", JSONType, nullable=False),
        sa.Column("extracted", JSONType, nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_candidate_resumes_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_resumes")),
    )
    op.create_index(op.f("ix_candidate_resumes_user_id"), "candidate_resumes", ["user_id"], unique=False)

    conn = op.get_bind()
    cat = sa.table(
        "categories", sa.column("id", sa.String), sa.column("market_salary_from", sa.Integer),
        sa.column("market_salary_to", sa.Integer), sa.column("market_salary_median", sa.Integer),
        sa.column("market_sample_size", sa.Integer), sa.column("market_source", sa.String),
        sa.column("market_as_of", sa.Date),
    )
    for (d, g), (lo, hi, med, n) in MARKET.items():
        conn.execute(
            cat.update().where(cat.c.id == f"{d}.{g}").values(
                market_salary_from=lo, market_salary_to=hi, market_salary_median=med,
                market_sample_size=n, market_source=MARKET_SOURCE, market_as_of=MARKET_AS_OF,
            )
        )
    # Обезличенные ссылки для уже зарегистрированных кандидатов
    cp = sa.table("candidate_profiles", sa.column("user_id", sa.Uuid), sa.column("public_ref", sa.String))
    used: set[str] = set()
    for (uid,) in conn.execute(sa.select(cp.c.user_id).where(cp.c.public_ref.is_(None))).all():
        while True:
            ref = "C-" + "".join(secrets.choice(REF_ALPHABET) for _ in range(6))
            if ref not in used:
                used.add(ref)
                break
        conn.execute(cp.update().where(cp.c.user_id == uid).values(public_ref=ref))


def downgrade() -> None:
    conn = op.get_bind()
    cat = sa.table("categories", sa.column("id", sa.String), sa.column("market_salary_from", sa.Integer),
                   sa.column("market_salary_to", sa.Integer))
    for (d, g), (lo, hi) in OLD_MARKET.items():
        conn.execute(cat.update().where(cat.c.id == f"{d}.{g}").values(market_salary_from=lo, market_salary_to=hi))
    op.drop_index(op.f("ix_candidate_resumes_user_id"), table_name="candidate_resumes")
    op.drop_table("candidate_resumes")
    with op.batch_alter_table("invitations") as b:
        b.drop_column("decline_reason")
    with op.batch_alter_table("probes") as b:
        b.drop_column("events")
        b.drop_column("review")
        b.drop_column("answer_mode")
    with op.batch_alter_table("categories") as b:
        for c in ("market_as_of", "market_source", "market_sample_size", "market_salary_median"):
            b.drop_column(c)
    with op.batch_alter_table("candidate_profiles") as b:
        b.drop_constraint("uq_candidate_profiles_public_ref", type_="unique")
        for c in ("jury_mode", "fsp_id_claimed", "roles", "onboarding_completed_at", "public_ref"):
            b.drop_column(c)
    with op.batch_alter_table("companies") as b:
        b.drop_column("is_demo")
    with op.batch_alter_table("users") as b:
        b.drop_column("is_demo")
