"""Идеи 9–10: роль «ФСП» (fsp_analyst) для кабинета обезличенной аналитики; «Кубок работодателя» — кубки,
участия, уровень мероприятия «platform» в паспорте ФСП

Revision ID: x001
Revises: 0004
Create Date: 2026-10-05

Ветка ideas: при перебазировании на main down_revision указывает на актуальную голову main.
CHECK-ограничения перечислений (VARCHAR + CHECK, см. app.core.db.str_enum) пересоздаются с новым значением;
в SQLite — через batch (пересоздание таблицы), в PostgreSQL — DROP/ADD CONSTRAINT.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "x001"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

ROLES_OLD = ("candidate", "employer", "admin", "expert")
ROLES_NEW = (*ROLES_OLD, "fsp_analyst")
LEVELS_OLD = ("school", "regional", "interregional", "national", "international")
LEVELS_NEW = (*LEVELS_OLD, "platform")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _recheck(table: str, name: str, col: str, values: tuple[str, ...]) -> None:
    with op.batch_alter_table(table) as b:
        b.drop_constraint(op.f(name), type_="check")
        b.create_check_constraint(op.f(name), _in(col, values))


def upgrade() -> None:
    _recheck("users", "ck_users_user_role", "role", ROLES_NEW)
    _recheck("fsp_achievements", "ck_fsp_achievements_fsp_event_level", "event_level", LEVELS_NEW)

    op.create_table(
        "cups",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category_id", sa.String(length=48), nullable=False),
        sa.Column("direction_id", sa.String(length=32), nullable=False),
        sa.Column("grade_id", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("task_text", sa.Text(), nullable=True),
        sa.Column("rubric", JSONType, nullable=True),
        sa.Column("task_families", JSONType, nullable=False),
        sa.Column("time_limit_min", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("salary_from", sa.Integer(), nullable=False),
        sa.Column("salary_to", sa.Integer(), nullable=False),
        sa.Column("invite_top_n", sa.Integer(), nullable=False),
        sa.Column("min_score", sa.Float(), nullable=False),
        sa.Column("position_title", sa.String(length=200), nullable=False),
        sa.Column("offer_description", sa.Text(), nullable=False),
        sa.Column("contact_method", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", JSONType, nullable=False),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("salary_from > 0 AND salary_from <= salary_to", name=op.f("ck_cups_salary_range")),
        sa.CheckConstraint("invite_top_n >= 1 AND invite_top_n <= 20", name=op.f("ck_cups_invite_top_n")),
        sa.CheckConstraint("starts_at < ends_at", name=op.f("ck_cups_period")),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], name=op.f("fk_cups_category_id_categories")),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_cups_company_id_companies"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_cups_created_by_users"),
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["direction_id"], ["directions.id"], name=op.f("fk_cups_direction_id_directions")),
        sa.ForeignKeyConstraint(["grade_id"], ["grades.id"], name=op.f("fk_cups_grade_id_grades")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cups")),
    )
    with op.batch_alter_table("cups") as b:
        b.create_index("ix_cups_category_ends", ["category_id", "ends_at"], unique=False)
        b.create_index(b.f("ix_cups_company_id"), ["company_id"], unique=False)

    op.create_table(
        "cup_entries",
        sa.Column("cup_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_user_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tasks", JSONType, nullable=False),
        sa.Column("answer", JSONType, nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("score_method", sa.String(length=16), nullable=True),
        sa.Column("grading", JSONType, nullable=True),
        sa.Column("time_spent_s", sa.Integer(), nullable=True),
        sa.Column("place", sa.Integer(), nullable=True),
        sa.Column("invitation_id", sa.Uuid(), nullable=True),
        sa.Column("invite_note", sa.String(length=255), nullable=True),
        sa.Column("passport_status", sa.String(length=16), nullable=True),
        sa.Column("passport_written_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_user_id"], ["users.id"],
                                name=op.f("fk_cup_entries_candidate_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cup_id"], ["cups.id"], name=op.f("fk_cup_entries_cup_id_cups"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invitation_id"], ["invitations.id"],
                                name=op.f("fk_cup_entries_invitation_id_invitations"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cup_entries")),
        sa.UniqueConstraint("cup_id", "candidate_user_id", name="uq_cup_entries_cup_candidate"),
    )
    with op.batch_alter_table("cup_entries") as b:
        b.create_index("ix_cup_entries_candidate", ["candidate_user_id"], unique=False)
        b.create_index(b.f("ix_cup_entries_cup_id"), ["cup_id"], unique=False)


def downgrade() -> None:
    op.drop_table("cup_entries")
    op.drop_table("cups")
    op.execute(sa.text("DELETE FROM fsp_achievements WHERE event_level = 'platform'"))
    op.execute(sa.text("DELETE FROM users WHERE role = 'fsp_analyst'"))
    _recheck("fsp_achievements", "ck_fsp_achievements_fsp_event_level", "event_level", LEVELS_OLD)
    _recheck("users", "ck_users_user_role", "role", ROLES_OLD)
