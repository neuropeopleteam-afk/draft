"""Контакт: переписка по приглашению и отклику, встречное предложение, отзыв доступа к контактам,
основание суммы «до вычета НДФЛ / на руки» (поток И4).

Revision ID: ct01
Revises: qr01
Create Date: 2026-10-07

Ветка contact: при слиянии down_revision указывает на актуальную голову main.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "ct01"
down_revision: str | None = "qr01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BASIS_TABLES = ("invitations", "probes", "vacancies", "cups")


def upgrade() -> None:
    # Существующие суммы — до вычета НДФЛ (так было подписано в API: «₽ в месяц до вычета НДФЛ»)
    for t in BASIS_TABLES:
        op.add_column(t, sa.Column("salary_basis", sa.String(length=8), nullable=False, server_default="gross"))
    op.add_column("invitations", sa.Column("contacts_revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("invitation_events", sa.Column("kind", sa.String(length=32), nullable=True))

    op.create_table(
        "contact_messages",
        sa.Column("invitation_id", sa.Uuid(), nullable=True),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("sender_user_id", sa.Uuid(), nullable=True),
        sa.Column("sender_side", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("masked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("(invitation_id IS NULL) <> (application_id IS NULL)",
                           name=op.f("ck_contact_messages_one_thread")),
        sa.CheckConstraint("sender_side IN ('candidate', 'employer')", name=op.f("ck_contact_messages_sender_side")),
        sa.CheckConstraint("mode IN ('qa', 'chat')", name=op.f("ck_contact_messages_mode")),
        sa.ForeignKeyConstraint(["invitation_id"], ["invitations.id"],
                                name=op.f("fk_contact_messages_invitation_id_invitations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["vacancy_applications.id"],
                                name=op.f("fk_contact_messages_application_id_vacancy_applications"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"],
                                name=op.f("fk_contact_messages_sender_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_messages")),
    )
    op.create_index("ix_contact_messages_invitation_created", "contact_messages", ["invitation_id", "created_at"])
    op.create_index("ix_contact_messages_application_created", "contact_messages", ["application_id", "created_at"])
    op.create_index("ix_contact_messages_sender_created", "contact_messages", ["sender_user_id", "created_at"])

    op.create_table(
        "invitation_counters",
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_user_id", sa.Uuid(), nullable=False),
        sa.Column("salary_from", sa.Integer(), nullable=False),
        sa.Column("salary_to", sa.Integer(), nullable=False),
        sa.Column("salary_basis", sa.String(length=8), nullable=False),
        sa.Column("offer_from", sa.Integer(), nullable=False),
        sa.Column("offer_to", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("employer_note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("salary_from > 0 AND salary_from <= salary_to", name=op.f("ck_invitation_counters_salary_range")),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'declined', 'withdrawn')",
                           name=op.f("ck_invitation_counters_status")),
        sa.ForeignKeyConstraint(["invitation_id"], ["invitations.id"],
                                name=op.f("fk_invitation_counters_invitation_id_invitations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_user_id"], ["users.id"],
                                name=op.f("fk_invitation_counters_candidate_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"],
                                name=op.f("fk_invitation_counters_decided_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitation_counters")),
    )
    op.create_index("ix_invitation_counters_invitation_created", "invitation_counters", ["invitation_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_invitation_counters_invitation_created", table_name="invitation_counters")
    op.drop_table("invitation_counters")
    for ix in ("ix_contact_messages_sender_created", "ix_contact_messages_application_created",
               "ix_contact_messages_invitation_created"):
        op.drop_index(ix, table_name="contact_messages")
    op.drop_table("contact_messages")
    with op.batch_alter_table("invitation_events") as b:
        b.drop_column("kind")
    with op.batch_alter_table("invitations") as b:
        b.drop_column("contacts_revoked_at")
    for t in BASIS_TABLES:
        with op.batch_alter_table(t) as b:
            b.drop_column("salary_basis")
