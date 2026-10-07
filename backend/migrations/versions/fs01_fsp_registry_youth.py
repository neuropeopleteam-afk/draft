"""Реестр ФСП v1, возрастная группа и безопасные условия оффера."""
from alembic import op, context
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "fs01"
down_revision = "qr01"
branch_labels = None
depends_on = None
JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade():
    op.add_column("candidate_profiles", sa.Column("age_group", sa.String(8), nullable=False, server_default="18+"))
    op.add_column("candidate_profiles", sa.Column("parental_consent", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("candidate_profiles", sa.Column("parental_consent_at", sa.DateTime(timezone=True), nullable=True))
    for name, typ in (("event_id", sa.String(100)), ("result_kind", sa.String(16)),
                      ("evsk_code", sa.String(64)), ("sport_rank", sa.String(64)), ("team_result", JSONType)):
        op.add_column("fsp_achievements", sa.Column(name, typ, nullable=True))
    op.add_column("invitations", sa.Column("employment_terms", JSONType, nullable=True))
    if context.is_offline_mode():
        return  # DDL для проверки PostgreSQL; пересчёт выполняется при online-upgrade
    # Пересчёт старых материализованных рейтингов после смены формулы; SELECT/UPDATE, без демо-пересева.
    from sqlalchemy.orm import Session
    from app.modules.profiles.facts import load_bundles
    from app.modules.profiles.models import CandidateProfile

    with Session(bind=op.get_bind()) as db:
        ids = list(db.scalars(sa.select(CandidateProfile.user_id).where(CandidateProfile.current_category_id.is_not(None))))
        for b in load_bundles(db, ids).values():
            b.profile.rating_score = b.strength()
        db.flush()
        db.commit()


def downgrade():
    op.drop_column("invitations", "employment_terms")
    for name in ("team_result", "sport_rank", "evsk_code", "result_kind", "event_id"):
        op.drop_column("fsp_achievements", name)
    for name in ("parental_consent_at", "parental_consent", "age_group"):
        op.drop_column("candidate_profiles", name)
