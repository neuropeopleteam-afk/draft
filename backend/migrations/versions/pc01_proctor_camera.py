"""И16: камера во время теста по согласию — режим камеры в сессии, события без кадров, новый вид согласия

Revision ID: pc01
Revises: tf01 (перевешена при слиянии в integ/0710; в ветке — qr01)
Create Date: 2026-10-07

Таблицы proctor_sessions и proctor_events удаляются каскадом вместе с попыткой теста (test_sessions).
Вид согласия «proctoring» добавляется в CHECK-ограничение consents.kind (перечисление хранится как VARCHAR + CHECK).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "pc01"
down_revision: str | None = "tf01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
KINDS_OLD = ("processing", "publication")
KINDS_NEW = KINDS_OLD + ("proctoring",)
CK = "ck_consents_consent_kind"


def _consent_kinds(kinds: tuple[str, ...]) -> None:
    cond = "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"
    if op.get_bind().dialect.name == "sqlite":
        # SQLite не умеет менять CHECK — batch пересоздаёт таблицу; старое ограничение задаём явно,
        # чтобы оно не перенеслось в новую таблицу из отражённой схемы
        old = sa.Table("consents", sa.MetaData(),
                       sa.Column("user_id", sa.Uuid(), nullable=False),
                       sa.Column("kind", sa.String(32), nullable=False),
                       sa.Column("document_version", sa.String(32), nullable=False),
                       sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
                       sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
                       sa.Column("id", sa.Uuid(), nullable=False),
                       sa.PrimaryKeyConstraint("id", name="pk_consents"),
                       sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_consents_user_id_users",
                                               ondelete="CASCADE"),
                       sa.Index("ix_consents_user_id", "user_id"),
                       sa.CheckConstraint(cond, name=CK))
        with op.batch_alter_table("consents", copy_from=old, recreate="always"):
            pass
        return
    op.drop_constraint(op.f(CK), "consents", type_="check")
    op.create_check_constraint(op.f(CK), "consents", sa.text(cond))


def upgrade() -> None:
    _consent_kinds(KINDS_NEW)
    op.create_table(
        "proctor_sessions",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=120), nullable=True),
        sa.Column("consent_id", sa.Uuid(), nullable=True),
        sa.Column("consent_version", sa.String(length=32), nullable=True),
        sa.Column("client", JSONType, nullable=False),
        sa.Column("windows", JSONType, nullable=False),
        sa.Column("stop_reason", sa.String(length=16), nullable=True),
        sa.Column("resumes", sa.Integer(), nullable=False),
        sa.Column("observed", JSONType, nullable=False),
        sa.Column("events_count", sa.Integer(), nullable=False),
        sa.Column("events_dropped", sa.Integer(), nullable=False),
        sa.Column("summary", JSONType, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["test_sessions.id"],
                                name=op.f("fk_proctor_sessions_session_id_test_sessions"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_proctor_sessions_user_id_users"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["consent_id"], ["consents.id"], name=op.f("fk_proctor_sessions_consent_id_consents"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proctor_sessions")),
        sa.UniqueConstraint("session_id", name=op.f("uq_proctor_sessions_session_id")),
    )
    op.create_index(op.f("ix_proctor_sessions_user_id"), "proctor_sessions", ["user_id"], unique=False)
    op.create_table(
        "proctor_events",
        sa.Column("proctor_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("faces", sa.SmallInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["proctor_id"], ["proctor_sessions.id"],
                                name=op.f("fk_proctor_events_proctor_id_proctor_sessions"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proctor_events")),
    )
    op.create_index(op.f("ix_proctor_events_proctor_id"), "proctor_events", ["proctor_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_proctor_events_proctor_id"), table_name="proctor_events")
    op.drop_table("proctor_events")
    op.drop_index(op.f("ix_proctor_sessions_user_id"), table_name="proctor_sessions")
    op.drop_table("proctor_sessions")
    op.execute(sa.text("DELETE FROM consents WHERE kind = 'proctoring'"))
    _consent_kinds(KINDS_OLD)
