"""День 3Б: интеграции — проверка работодателя в ЕГРЮЛ, ФСП ID (OIDC), ATS, вакансии и отклики, Web Push, SUS

Revision ID: i001
Revises: 0003
Create Date: 2026-10-05

Ветка integrations: при перебазировании на main down_revision указывает на актуальную голову main.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "i001"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table('ats_stub_records',
    sa.Column('stub_key', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('external_id', sa.Integer(), nullable=True),
    sa.Column('payload', JSONType, nullable=False),
    sa.Column('signature_valid', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ats_stub_records'))
    )
    with op.batch_alter_table('ats_stub_records', schema=None) as batch_op:
        batch_op.create_index('ix_ats_stub_records_key_created', ['stub_key', 'created_at'], unique=False)

    op.create_table('oidc_login_states',
    sa.Column('state', sa.String(length=64), nullable=False),
    sa.Column('nonce', sa.String(length=64), nullable=False),
    sa.Column('code_verifier', sa.String(length=128), nullable=False),
    sa.Column('intent', sa.String(length=8), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('return_to', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ticket', sa.String(length=64), nullable=True),
    sa.Column('ticket_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('claims', JSONType, nullable=True),
    sa.Column('result_user_id', sa.Uuid(), nullable=True),
    sa.Column('error', sa.String(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("intent IN ('login', 'link')", name=op.f('ck_oidc_login_states_intent')),
    sa.ForeignKeyConstraint(['result_user_id'], ['users.id'], name=op.f('fk_oidc_login_states_result_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_oidc_login_states_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_oidc_login_states')),
    sa.UniqueConstraint('state', name=op.f('uq_oidc_login_states_state')),
    sa.UniqueConstraint('ticket', name=op.f('uq_oidc_login_states_ticket'))
    )
    op.create_table('push_subscriptions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('endpoint', sa.String(length=1000), nullable=False),
    sa.Column('p256dh', sa.String(length=255), nullable=False),
    sa.Column('auth', sa.String(length=255), nullable=False),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failures', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_push_subscriptions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_push_subscriptions')),
    sa.UniqueConstraint('endpoint', name=op.f('uq_push_subscriptions_endpoint'))
    )
    with op.batch_alter_table('push_subscriptions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_push_subscriptions_user_id'), ['user_id'], unique=False)

    op.create_table('sus_responses',
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('context', sa.String(length=16), nullable=False),
    sa.Column('answers', JSONType, nullable=False),
    sa.Column('score', sa.Double(), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('is_demo', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("context IN ('e2e', 'jury', 'pilot', 'other')", name=op.f('ck_sus_responses_context')),
    sa.CheckConstraint('score >= 0 AND score <= 100', name=op.f('ck_sus_responses_score_range')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sus_responses_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sus_responses'))
    )
    with op.batch_alter_table('sus_responses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sus_responses_user_id'), ['user_id'], unique=False)

    op.create_table('ats_settings',
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('auto_push', sa.Boolean(), nullable=False),
    sa.Column('huntflow_enabled', sa.Boolean(), nullable=False),
    sa.Column('huntflow_base_url', sa.String(length=255), nullable=True),
    sa.Column('huntflow_account_id', sa.Integer(), nullable=True),
    sa.Column('huntflow_vacancy_id', sa.Integer(), nullable=True),
    sa.Column('huntflow_status_id', sa.Integer(), nullable=True),
    sa.Column('huntflow_token_enc', sa.Text(), nullable=True),
    sa.Column('webhook_enabled', sa.Boolean(), nullable=False),
    sa.Column('webhook_url', sa.String(length=500), nullable=True),
    sa.Column('webhook_secret_enc', sa.Text(), nullable=True),
    sa.Column('stub_key', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_ats_settings_company_id_companies'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('company_id', name=op.f('pk_ats_settings')),
    sa.UniqueConstraint('stub_key', name=op.f('uq_ats_settings_stub_key'))
    )
    op.create_table('company_registry_checks',
    sa.Column('inn', sa.String(length=12), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('data', JSONType, nullable=False),
    sa.Column('error', sa.String(length=255), nullable=True),
    sa.Column('source', sa.String(length=64), nullable=False),
    sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('requested_by_company', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("status IN ('found', 'not_found', 'captcha', 'error', 'invalid')", name=op.f('ck_company_registry_checks_status')),
    sa.ForeignKeyConstraint(['requested_by_company'], ['companies.id'], name=op.f('fk_company_registry_checks_requested_by_company_companies'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_registry_checks')),
    sa.UniqueConstraint('inn', name=op.f('uq_company_registry_checks_inn'))
    )
    op.create_table('vacancies',
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('category_id', sa.String(length=48), nullable=True),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('stack', JSONType, nullable=False),
    sa.Column('salary_from', sa.Integer(), nullable=False),
    sa.Column('salary_to', sa.Integer(), nullable=False),
    sa.Column('work_format', sa.String(length=16), nullable=False),
    sa.Column('city', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_demo', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('draft', 'published', 'closed')", name=op.f('ck_vacancies_status')),
    sa.CheckConstraint('salary_from > 0 AND salary_from <= salary_to', name=op.f('ck_vacancies_salary_range')),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_vacancies_category_id_categories')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_vacancies_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_vacancies_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_vacancies'))
    )
    with op.batch_alter_table('vacancies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_vacancies_company_id'), ['company_id'], unique=False)
        batch_op.create_index('ix_vacancies_status_published', ['status', 'published_at'], unique=False)

    op.create_table('vacancy_applications',
    sa.Column('vacancy_id', sa.Uuid(), nullable=False),
    sa.Column('candidate_user_id', sa.Uuid(), nullable=False),
    sa.Column('cover_letter', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('events', JSONType, nullable=False),
    sa.Column('employer_note', sa.Text(), nullable=True),
    sa.Column('viewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('sent', 'viewed', 'accepted', 'rejected', 'withdrawn')", name=op.f('ck_vacancy_applications_status')),
    sa.ForeignKeyConstraint(['candidate_user_id'], ['users.id'], name=op.f('fk_vacancy_applications_candidate_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vacancy_id'], ['vacancies.id'], name=op.f('fk_vacancy_applications_vacancy_id_vacancies'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_vacancy_applications')),
    sa.UniqueConstraint('vacancy_id', 'candidate_user_id', name='uq_vacancy_applications_pair')
    )
    with op.batch_alter_table('vacancy_applications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_vacancy_applications_candidate_user_id'), ['candidate_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_vacancy_applications_vacancy_id'), ['vacancy_id'], unique=False)

    op.create_table('ats_deliveries',
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('candidate_user_id', sa.Uuid(), nullable=False),
    sa.Column('invitation_id', sa.Uuid(), nullable=True),
    sa.Column('application_id', sa.Uuid(), nullable=True),
    sa.Column('target', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('result', JSONType, nullable=False),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.Column('trigger', sa.String(length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'ok', 'error')", name=op.f('ck_ats_deliveries_status')),
    sa.CheckConstraint("target IN ('huntflow', 'webhook')", name=op.f('ck_ats_deliveries_target')),
    sa.ForeignKeyConstraint(['application_id'], ['vacancy_applications.id'], name=op.f('fk_ats_deliveries_application_id_vacancy_applications'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['candidate_user_id'], ['users.id'], name=op.f('fk_ats_deliveries_candidate_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_ats_deliveries_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['invitation_id'], ['invitations.id'], name=op.f('fk_ats_deliveries_invitation_id_invitations'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ats_deliveries'))
    )
    with op.batch_alter_table('ats_deliveries', schema=None) as batch_op:
        batch_op.create_index('ix_ats_deliveries_company_created', ['company_id', 'created_at'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('ats_deliveries', schema=None) as batch_op:
        batch_op.drop_index('ix_ats_deliveries_company_created')

    op.drop_table('ats_deliveries')
    with op.batch_alter_table('vacancy_applications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_vacancy_applications_vacancy_id'))
        batch_op.drop_index(batch_op.f('ix_vacancy_applications_candidate_user_id'))

    op.drop_table('vacancy_applications')
    with op.batch_alter_table('vacancies', schema=None) as batch_op:
        batch_op.drop_index('ix_vacancies_status_published')
        batch_op.drop_index(batch_op.f('ix_vacancies_company_id'))

    op.drop_table('vacancies')
    op.drop_table('company_registry_checks')
    op.drop_table('ats_settings')
    with op.batch_alter_table('sus_responses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sus_responses_user_id'))

    op.drop_table('sus_responses')
    with op.batch_alter_table('push_subscriptions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_push_subscriptions_user_id'))

    op.drop_table('push_subscriptions')
    op.drop_table('oidc_login_states')
    with op.batch_alter_table('ats_stub_records', schema=None) as batch_op:
        batch_op.drop_index('ix_ats_stub_records_key_created')

    op.drop_table('ats_stub_records')
