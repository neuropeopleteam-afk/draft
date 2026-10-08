"""И7: задания работодателя с автопроверкой — задания и попытки кандидатов

Revision ID: tk01
Revises: rd01 (перевешена при слиянии в integ/0710)
Create Date: 2026-10-07
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "tk01"
down_revision: str | None = "rd01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "assignments",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("need_id", sa.Uuid(), nullable=True),
        sa.Column("vacancy_id", sa.Uuid(), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("direction_id", sa.String(length=32), nullable=False),
        sa.Column("grade_id", sa.String(length=16), nullable=False),
        sa.Column("stack_tags", JSONType, nullable=False),
        sa.Column("families", JSONType, nullable=False),
        sa.Column("coverage", JSONType, nullable=False),
        sa.Column("n_tasks", sa.Integer(), nullable=False),
        sa.Column("time_limit_min", sa.Integer(), nullable=False),
        sa.Column("salary_from", sa.Integer(), nullable=True),
        sa.Column("salary_to", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("jury_scope", sa.String(length=16), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('probe', 'vacancy', 'open')", name=op.f("ck_assignments_mode")),
        sa.CheckConstraint("status IN ('active', 'closed')", name=op.f("ck_assignments_status")),
        sa.CheckConstraint("n_tasks >= 3 AND n_tasks <= 5", name=op.f("ck_assignments_n_tasks")),
        sa.CheckConstraint("salary_from IS NULL OR (salary_from > 0 AND salary_from <= salary_to)",
                           name=op.f("ck_assignments_salary_range")),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_assignments_company_id_companies"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_assignments_created_by_users"),
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["need_id"], ["employer_needs.id"], name=op.f("fk_assignments_need_id_employer_needs"),
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vacancy_id"], ["vacancies.id"], name=op.f("fk_assignments_vacancy_id_vacancies"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["direction_id"], ["directions.id"], name=op.f("fk_assignments_direction_id_directions")),
        sa.ForeignKeyConstraint(["grade_id"], ["grades.id"], name=op.f("fk_assignments_grade_id_grades")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assignments")),
    )
    with op.batch_alter_table("assignments", schema=None) as b:
        b.create_index(b.f("ix_assignments_company_id"), ["company_id"], unique=False)
        b.create_index(b.f("ix_assignments_vacancy_id"), ["vacancy_id"], unique=False)
        b.create_index(b.f("ix_assignments_jury_scope"), ["jury_scope"], unique=False)
        b.create_index("ix_assignments_mode_status", ["mode", "status"], unique=False)

    op.create_table(
        "assignment_attempts",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_user_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tasks", JSONType, nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("correct", sa.Integer(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=True),
        sa.Column("skills", JSONType, nullable=False),
        sa.Column("time_spent_s", sa.Integer(), nullable=True),
        sa.Column("score_method", sa.String(length=16), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('probe', 'vacancy', 'feed')", name=op.f("ck_assignment_attempts_source")),
        sa.CheckConstraint("status IN ('offered', 'in_progress', 'scored', 'declined', 'expired')",
                           name=op.f("ck_assignment_attempts_status")),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"],
                                name=op.f("fk_assignment_attempts_assignment_id_assignments"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_user_id"], ["users.id"],
                                name=op.f("fk_assignment_attempts_candidate_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["vacancy_applications.id"],
                                name=op.f("fk_assignment_attempts_application_id_vacancy_applications"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assignment_attempts")),
        sa.UniqueConstraint("assignment_id", "candidate_user_id", name=op.f("uq_assignment_attempts_pair")),
    )
    with op.batch_alter_table("assignment_attempts", schema=None) as b:
        b.create_index(b.f("ix_assignment_attempts_assignment_id"), ["assignment_id"], unique=False)
        b.create_index(b.f("ix_assignment_attempts_application_id"), ["application_id"], unique=False)
        b.create_index("ix_assignment_attempts_candidate_status", ["candidate_user_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_table("assignment_attempts")
    op.drop_table("assignments")
