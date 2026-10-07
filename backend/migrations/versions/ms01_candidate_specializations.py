"""Две специализации с независимыми тестами и таймерами, перенос основной категории."""
from datetime import UTC, datetime
import json

from alembic import op
import sqlalchemy as sa

revision = "ms01"
down_revision = "qr01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "candidate_specializations",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("candidate_profiles.user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("direction_id", sa.String(32), sa.ForeignKey("directions.id"), primary_key=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("grade_id", sa.String(32), sa.ForeignKey("grades.id")),
        sa.Column("category_id", sa.String(64), sa.ForeignKey("categories.id")),
        sa.Column("status", sa.String(32), nullable=False, server_default="declared"),
        sa.Column("theta", sa.Float()), sa.Column("theta_se", sa.Float()), sa.Column("rating_score", sa.Float()),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("test_session_id", sa.Uuid(), sa.ForeignKey("test_sessions.id", ondelete="SET NULL")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('declared', 'confirmed', 'provisional')", name=op.f("ck_candidate_specializations_status")),
        sa.CheckConstraint("(grade_id IS NULL AND category_id IS NULL) OR "
                           "(grade_id IS NOT NULL AND category_id IS NOT NULL AND category_id = direction_id || '.' || grade_id)",
                           name=op.f("ck_candidate_specializations_category_direction")),
    )
    op.create_index("ix_candidate_specializations_category_id", "candidate_specializations", ["category_id"])
    op.create_index("uq_candidate_specializations_primary", "candidate_specializations", ["user_id"], unique=True,
                    sqlite_where=sa.text("is_primary = 1"), postgresql_where=sa.text("is_primary = true"))
    op.create_index("uq_candidate_specializations_secondary", "candidate_specializations", ["user_id"], unique=True,
                    sqlite_where=sa.text("is_primary = 0"), postgresql_where=sa.text("is_primary = false"))
    # Core reflection keeps UUID/JSON/date conversion portable; no imports of evolving application models.
    conn = op.get_bind()
    md = sa.MetaData()
    profiles = sa.Table("candidate_profiles", md, autoload_with=conn)
    facts = sa.Table("candidate_facts", md, autoload_with=conn)
    surveys = sa.Table("survey_responses", md, autoload_with=conn)
    sessions = sa.Table("test_sessions", md, autoload_with=conn)
    target = sa.Table("candidate_specializations", md, autoload_with=conn)
    now = datetime.now(UTC)
    for p in conn.execute(sa.select(profiles)).mappings():
        direction = p["current_direction_id"]
        if not direction:
            direction = conn.scalar(sa.select(surveys.c.direction_id).where(surveys.c.user_id == p["user_id"])
                                    .order_by(surveys.c.created_at.desc()).limit(1))
        if not direction:
            continue
        fact = conn.execute(sa.select(facts).where(facts.c.user_id == p["user_id"], facts.c.kind == "test_result",
                                                  facts.c.key.like(f"{direction}.%"))
                            .order_by(facts.c.created_at.desc()).limit(1)).mappings().first()
        v = (fact["value"] or {}) if fact else {}
        if isinstance(v, str):
            v = json.loads(v)
        session = conn.execute(sa.select(sessions).where(
            sessions.c.user_id == p["user_id"], sessions.c.direction_id == direction,
            sessions.c.result_grade_id == p["current_grade_id"])
            .order_by(sessions.c.created_at.desc()).limit(1)).mappings().first() if p["current_category_id"] else None
        conn.execute(target.insert().values(
            user_id=p["user_id"], direction_id=direction, is_primary=True,
            grade_id=p["current_grade_id"], category_id=p["current_category_id"],
            status="confirmed" if p["current_category_id"] else "declared",
            theta=v.get("theta", session["theta"] if session else None),
            theta_se=v.get("se", session["theta_se"] if session else None), rating_score=p["rating_score"],
            locked_until=p["grade_locked_until"], test_session_id=session["id"] if session else None,
            confirmed_at=fact["created_at"] if fact else session["finished_at"] if session else None,
            created_at=p["created_at"] or now, updated_at=p["updated_at"] or now,
        ))


def downgrade():
    op.drop_table("candidate_specializations")
