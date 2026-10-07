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
    _refresh_ratings(op.get_bind())


def _refresh_ratings(conn):
    """Core/reflection, не ORM: соседние миграции могут ещё не создать поля новой модели."""
    from collections import defaultdict
    from datetime import date
    import math

    meta = sa.MetaData()
    profiles = sa.Table("candidate_profiles", meta, autoload_with=conn)
    passports = sa.Table("fsp_passports", meta, autoload_with=conn)
    achievements = sa.Table("fsp_achievements", meta, autoload_with=conn)
    facts = sa.Table("candidate_facts", meta, autoload_with=conn)
    by_user = defaultdict(list)
    for row in conn.execute(sa.select(achievements, passports.c.user_id).join(
            passports, achievements.c.passport_id == passports.c.id)).mappings():
        by_user[row["user_id"]].append(row)
    tests, probes = {}, {}
    for row in conn.execute(sa.select(facts).where(facts.c.evidence_level != "T0").order_by(facts.c.created_at)).mappings():
        if row["kind"] == "test_result":
            tests[row["user_id"]] = row["value"] or {}
        elif row["kind"] == "probe":
            uid = row["user_id"]
            probes[uid] = max(probes.get(uid, 0), (row["value"] or {}).get("score", 0))
    for p in conn.execute(sa.select(profiles.c.user_id, profiles.c.current_grade_id).where(
            profiles.c.current_category_id.is_not(None))).mappings():
        events = {}
        for a in by_user[p["user_id"]]:
            if not a["verified"]:
                continue
            place = a["place"] or 99
            title = (a["result_title"] or "").lower()
            result = (1 if place == 1 or "победител" in title else .85 if place <= 3 or "приз" in title
                      else .6 if place <= 10 or "финалист" in title else .15)
            result = {"winner": 1, "prize": .85, "finalist": .6, "participant": .15}.get(a["result_kind"], result)
            age = max(0, (date.today() - a["event_date"]).days / 365.25 - 1) if a["event_date"] else 0
            value = result * (.7 + .3 * math.exp(-age / 3))
            key = a["event_id"] or (a["event_name"].strip().casefold(), a["event_date"])
            events[key] = max(events.get(key, 0), value)
        vals = sorted(events.values(), reverse=True)
        fsp = round(.8 * vals[0] + .2 * (1 - math.exp(-sum(vals[1:]))), 3) if vals else 0
        t = tests.get(p["user_id"], {})
        cut = {"junior": -1., "middle": 0., "senior": 1.}.get(p["current_grade_id"])
        test = round(1 / (1 + math.exp(-1.7 * (t["theta"] - cut))), 3) if cut is not None and t.get("theta") is not None else 0
        rating = round(.65 * test + .10 * probes.get(p["user_id"], 0) + .25 * fsp, 4)
        conn.execute(profiles.update().where(profiles.c.user_id == p["user_id"]).values(rating_score=rating))


def downgrade():
    op.drop_column("invitations", "employment_terms")
    for name in ("team_result", "sport_rank", "evsk_code", "result_kind", "event_id"):
        op.drop_column("fsp_achievements", name)
    for name in ("parental_consent_at", "parental_consent", "age_group"):
        op.drop_column("candidate_profiles", name)
