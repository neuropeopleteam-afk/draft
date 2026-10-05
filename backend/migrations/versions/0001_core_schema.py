"""Ядро схемы: пользователи, справочник, профили, опрос, банк заданий, тесты, подбор, приглашения, ФСП

Revision ID: 0001
Revises: 
Create Date: 2026-10-05 09:41:58.967269
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Сгенерировано alembic autogenerate по app/models.py; CHECK для перечислений создаёт sa.Enum.
    op.create_table('directions',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('code_language', sa.String(length=32), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_directions'))
    )
    op.create_table('grades',
    sa.Column('id', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=50), nullable=False),
    sa.Column('level', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_grades')),
    sa.UniqueConstraint('level', name=op.f('uq_grades_level'))
    )
    op.create_table('task_families',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('direction', sa.Enum('common', 'backend', 'frontend', 'data_ml', 'qa', 'security', name='bank_direction', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('skills', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('target_grades', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('format', sa.Enum('find_bug', 'predict_output', 'choose_fix', 'open_book_3step', 'mcq_concept', 'open_answer', name='task_format', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('invariants', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('time_limit_s', sa.Integer(), nullable=False),
    sa.Column('canary', sa.Boolean(), nullable=False),
    sa.Column('prior_difficulty', sa.Double(), nullable=False),
    sa.Column('calibrated_difficulty', sa.Double(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('source_hash', sa.String(length=64), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('quarantined_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('exposure_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_task_families'))
    )
    with op.batch_alter_table('task_families', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_task_families_direction'), ['direction'], unique=False)

    op.create_table('users',
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('candidate', 'employer', 'admin', name='user_role', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('is_email_verified', sa.Boolean(), nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fsp_subject', sa.String(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('fsp_subject', name=op.f('uq_users_fsp_subject'))
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('candidate_facts',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('value', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('evidence_level', sa.Enum('T0', 'T1', 'T2', name='evidence_level', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('source', sa.Enum('self_report', 'resume', 'test', 'probe', 'fsp_registry', name='fact_source', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('source_ref', sa.String(length=100), nullable=True),
    sa.Column('weight', sa.Double(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_candidate_facts_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_candidate_facts'))
    )
    with op.batch_alter_table('candidate_facts', schema=None) as batch_op:
        batch_op.create_index('ix_candidate_facts_user_level', ['user_id', 'evidence_level'], unique=False)

    op.create_table('categories',
    sa.Column('id', sa.String(length=48), nullable=False),
    sa.Column('direction_id', sa.String(length=32), nullable=False),
    sa.Column('grade_id', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=100), nullable=False),
    sa.Column('market_salary_from', sa.Integer(), nullable=False),
    sa.Column('market_salary_to', sa.Integer(), nullable=False),
    sa.CheckConstraint('market_salary_from <= market_salary_to', name=op.f('ck_categories_market_range')),
    sa.ForeignKeyConstraint(['direction_id'], ['directions.id'], name=op.f('fk_categories_direction_id_directions')),
    sa.ForeignKeyConstraint(['grade_id'], ['grades.id'], name=op.f('fk_categories_grade_id_grades')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categories')),
    sa.UniqueConstraint('direction_id', 'grade_id', name='uq_categories_direction_grade')
    )
    op.create_table('companies',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('inn', sa.String(length=12), nullable=True),
    sa.Column('industry', sa.String(length=200), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('website', sa.String(length=255), nullable=True),
    sa.Column('city', sa.String(length=100), nullable=True),
    sa.Column('contact_email', sa.String(length=254), nullable=True),
    sa.Column('contact_phone', sa.String(length=32), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_companies_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_companies'))
    )
    op.create_table('consents',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Enum('processing', 'publication', name='consent_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('document_version', sa.String(length=32), nullable=False),
    sa.Column('granted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_consents_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_consents'))
    )
    with op.batch_alter_table('consents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_consents_user_id'), ['user_id'], unique=False)

    op.create_table('email_verifications',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('purpose', sa.Enum('email_confirm', 'password_reset', name='verification_purpose', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('code_hash', sa.String(length=128), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_email_verifications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_verifications'))
    )
    with op.batch_alter_table('email_verifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_email_verifications_user_id'), ['user_id'], unique=False)

    op.create_table('fsp_passports',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('fsp_subject', sa.String(length=255), nullable=True),
    sa.Column('link_source', sa.Enum('demo', 'keycloak', 'registry', name='fsp_link_source', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('linked_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sport_rank', sa.String(length=64), nullable=True),
    sa.Column('raw', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_fsp_passports_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fsp_passports')),
    sa.UniqueConstraint('fsp_subject', name=op.f('uq_fsp_passports_fsp_subject')),
    sa.UniqueConstraint('user_id', name=op.f('uq_fsp_passports_user_id'))
    )
    op.create_table('stack_tags',
    sa.Column('id', sa.String(length=48), nullable=False),
    sa.Column('title', sa.String(length=100), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('direction_id', sa.String(length=32), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['direction_id'], ['directions.id'], name=op.f('fk_stack_tags_direction_id_directions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stack_tags'))
    )
    with op.batch_alter_table('stack_tags', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stack_tags_direction_id'), ['direction_id'], unique=False)

    op.create_table('survey_responses',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('direction_id', sa.String(length=32), nullable=False),
    sa.Column('claimed_grade_id', sa.String(length=16), nullable=False),
    sa.Column('experience_years', sa.Numeric(precision=4, scale=1), nullable=True),
    sa.Column('answers', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['claimed_grade_id'], ['grades.id'], name=op.f('fk_survey_responses_claimed_grade_id_grades')),
    sa.ForeignKeyConstraint(['direction_id'], ['directions.id'], name=op.f('fk_survey_responses_direction_id_directions')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_survey_responses_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_survey_responses'))
    )
    with op.batch_alter_table('survey_responses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_survey_responses_user_id'), ['user_id'], unique=False)

    op.create_table('task_variants',
    sa.Column('id', sa.String(length=100), nullable=False),
    sa.Column('family_id', sa.String(length=80), nullable=False),
    sa.Column('seed', sa.BigInteger(), nullable=False),
    sa.Column('stem', sa.Text(), nullable=False),
    sa.Column('code', sa.Text(), nullable=True),
    sa.Column('code_language', sa.String(length=24), nullable=True),
    sa.Column('options', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('answer_key', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('rubric', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('meta', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('exposure_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['family_id'], ['task_families.id'], name=op.f('fk_task_variants_family_id_task_families'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_task_variants')),
    sa.UniqueConstraint('family_id', 'seed', name='uq_task_variants_family_seed')
    )
    with op.batch_alter_table('task_variants', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_task_variants_family_id'), ['family_id'], unique=False)

    op.create_table('candidate_profiles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=True),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('telegram', sa.String(length=64), nullable=True),
    sa.Column('city', sa.String(length=100), nullable=True),
    sa.Column('work_format', sa.Enum('office', 'hybrid', 'remote', 'any', name='work_format', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('relocation', sa.Boolean(), nullable=False),
    sa.Column('experience_years', sa.Numeric(precision=4, scale=1), nullable=True),
    sa.Column('headline', sa.String(length=200), nullable=True),
    sa.Column('about', sa.Text(), nullable=True),
    sa.Column('salary_min_hidden', sa.Integer(), nullable=True),
    sa.Column('current_direction_id', sa.String(length=32), nullable=True),
    sa.Column('current_grade_id', sa.String(length=16), nullable=True),
    sa.Column('current_category_id', sa.String(length=48), nullable=True),
    sa.Column('rating_score', sa.Double(), nullable=True),
    sa.Column('grade_locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('privacy', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('visible_to_employers', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('salary_min_hidden IS NULL OR salary_min_hidden > 0', name=op.f('ck_candidate_profiles_salary_min')),
    sa.ForeignKeyConstraint(['current_category_id'], ['categories.id'], name=op.f('fk_candidate_profiles_current_category_id_categories')),
    sa.ForeignKeyConstraint(['current_direction_id'], ['directions.id'], name=op.f('fk_candidate_profiles_current_direction_id_directions')),
    sa.ForeignKeyConstraint(['current_grade_id'], ['grades.id'], name=op.f('fk_candidate_profiles_current_grade_id_grades')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_candidate_profiles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_candidate_profiles'))
    )
    with op.batch_alter_table('candidate_profiles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_candidate_profiles_current_category_id'), ['current_category_id'], unique=False)

    op.create_table('employer_needs',
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('raw_text', sa.Text(), nullable=False),
    sa.Column('requirements', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('direction_id', sa.String(length=32), nullable=True),
    sa.Column('grade_id', sa.String(length=16), nullable=True),
    sa.Column('salary_from', sa.Integer(), nullable=True),
    sa.Column('salary_to', sa.Integer(), nullable=True),
    sa.Column('status', sa.Enum('draft', 'active', 'closed', name='need_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('salary_from IS NULL OR salary_to IS NULL OR salary_from <= salary_to', name=op.f('ck_employer_needs_salary_range')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_employer_needs_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_employer_needs_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['direction_id'], ['directions.id'], name=op.f('fk_employer_needs_direction_id_directions')),
    sa.ForeignKeyConstraint(['grade_id'], ['grades.id'], name=op.f('fk_employer_needs_grade_id_grades')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_employer_needs'))
    )
    with op.batch_alter_table('employer_needs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_employer_needs_company_id'), ['company_id'], unique=False)

    op.create_table('employer_profiles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=True),
    sa.Column('full_name', sa.String(length=200), nullable=True),
    sa.Column('position', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_employer_profiles_company_id_companies'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_employer_profiles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_employer_profiles'))
    )
    with op.batch_alter_table('employer_profiles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_employer_profiles_company_id'), ['company_id'], unique=False)

    op.create_table('fsp_achievements',
    sa.Column('passport_id', sa.Uuid(), nullable=False),
    sa.Column('discipline', sa.String(length=64), nullable=False),
    sa.Column('event_name', sa.String(length=255), nullable=False),
    sa.Column('event_level', sa.Enum('school', 'regional', 'interregional', 'national', 'international', name='fsp_event_level', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('event_date', sa.Date(), nullable=True),
    sa.Column('place', sa.Integer(), nullable=True),
    sa.Column('result_title', sa.String(length=100), nullable=True),
    sa.Column('team_name', sa.String(length=200), nullable=True),
    sa.Column('role_in_team', sa.String(length=100), nullable=True),
    sa.Column('verified', sa.Boolean(), nullable=False),
    sa.Column('source_ref', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['passport_id'], ['fsp_passports.id'], name=op.f('fk_fsp_achievements_passport_id_fsp_passports'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fsp_achievements'))
    )
    with op.batch_alter_table('fsp_achievements', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_fsp_achievements_passport_id'), ['passport_id'], unique=False)

    op.create_table('survey_stack_tags',
    sa.Column('survey_id', sa.Uuid(), nullable=False),
    sa.Column('stack_tag_id', sa.String(length=48), nullable=False),
    sa.Column('self_level', sa.SmallInteger(), nullable=False),
    sa.ForeignKeyConstraint(['stack_tag_id'], ['stack_tags.id'], name=op.f('fk_survey_stack_tags_stack_tag_id_stack_tags')),
    sa.ForeignKeyConstraint(['survey_id'], ['survey_responses.id'], name=op.f('fk_survey_stack_tags_survey_id_survey_responses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('survey_id', 'stack_tag_id', name=op.f('pk_survey_stack_tags'))
    )
    op.create_table('test_sessions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('survey_id', sa.Uuid(), nullable=True),
    sa.Column('direction_id', sa.String(length=32), nullable=False),
    sa.Column('claimed_grade_id', sa.String(length=16), nullable=False),
    sa.Column('status', sa.Enum('created', 'in_progress', 'finished', 'expired', 'aborted', name='test_session_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('form_seed', sa.BigInteger(), nullable=False),
    sa.Column('is_sandbox', sa.Boolean(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('score', sa.Double(), nullable=True),
    sa.Column('theta', sa.Double(), nullable=True),
    sa.Column('theta_se', sa.Double(), nullable=True),
    sa.Column('result_grade_id', sa.String(length=16), nullable=True),
    sa.Column('result', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['claimed_grade_id'], ['grades.id'], name=op.f('fk_test_sessions_claimed_grade_id_grades')),
    sa.ForeignKeyConstraint(['direction_id'], ['directions.id'], name=op.f('fk_test_sessions_direction_id_directions')),
    sa.ForeignKeyConstraint(['result_grade_id'], ['grades.id'], name=op.f('fk_test_sessions_result_grade_id_grades')),
    sa.ForeignKeyConstraint(['survey_id'], ['survey_responses.id'], name=op.f('fk_test_sessions_survey_id_survey_responses'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_test_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_test_sessions'))
    )
    with op.batch_alter_table('test_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_test_sessions_user_id'), ['user_id'], unique=False)

    op.create_table('grade_history',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('direction_id', sa.String(length=32), nullable=False),
    sa.Column('from_grade_id', sa.String(length=16), nullable=True),
    sa.Column('to_grade_id', sa.String(length=16), nullable=False),
    sa.Column('reason', sa.Enum('initial', 'retest_up', 'retest_down', 'sandbox', 'admin', name='grade_change_reason', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('test_session_id', sa.Uuid(), nullable=True),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['direction_id'], ['directions.id'], name=op.f('fk_grade_history_direction_id_directions')),
    sa.ForeignKeyConstraint(['from_grade_id'], ['grades.id'], name=op.f('fk_grade_history_from_grade_id_grades')),
    sa.ForeignKeyConstraint(['test_session_id'], ['test_sessions.id'], name=op.f('fk_grade_history_test_session_id_test_sessions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['to_grade_id'], ['grades.id'], name=op.f('fk_grade_history_to_grade_id_grades')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_grade_history_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_grade_history'))
    )
    with op.batch_alter_table('grade_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_grade_history_user_id'), ['user_id'], unique=False)

    op.create_table('probes',
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('employer_user_id', sa.Uuid(), nullable=True),
    sa.Column('candidate_user_id', sa.Uuid(), nullable=False),
    sa.Column('need_id', sa.Uuid(), nullable=True),
    sa.Column('variant_id', sa.String(length=100), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('task_text', sa.Text(), nullable=False),
    sa.Column('salary_from', sa.Integer(), nullable=False),
    sa.Column('salary_to', sa.Integer(), nullable=False),
    sa.Column('time_limit_s', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('sent', 'viewed', 'submitted', 'reviewed', 'declined', 'expired', name='probe_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('answer', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('score', sa.Double(), nullable=True),
    sa.Column('viewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('salary_from > 0 AND salary_from <= salary_to', name=op.f('ck_probes_salary_range')),
    sa.ForeignKeyConstraint(['candidate_user_id'], ['users.id'], name=op.f('fk_probes_candidate_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_probes_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['employer_user_id'], ['users.id'], name=op.f('fk_probes_employer_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['need_id'], ['employer_needs.id'], name=op.f('fk_probes_need_id_employer_needs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['variant_id'], ['task_variants.id'], name=op.f('fk_probes_variant_id_task_variants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_probes'))
    )
    with op.batch_alter_table('probes', schema=None) as batch_op:
        batch_op.create_index('ix_probes_candidate_status', ['candidate_user_id', 'status'], unique=False)
        batch_op.create_index(batch_op.f('ix_probes_company_id'), ['company_id'], unique=False)

    op.create_table('selection_versions',
    sa.Column('need_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('parent_version', sa.Integer(), nullable=True),
    sa.Column('filters', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('requirements', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('results', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('algorithm_version', sa.String(length=32), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_selection_versions_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['need_id'], ['employer_needs.id'], name=op.f('fk_selection_versions_need_id_employer_needs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_selection_versions')),
    sa.UniqueConstraint('need_id', 'version', name='uq_selection_versions_need_version')
    )
    with op.batch_alter_table('selection_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_selection_versions_need_id'), ['need_id'], unique=False)

    op.create_table('test_session_items',
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('variant_id', sa.String(length=100), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('shown_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['test_sessions.id'], name=op.f('fk_test_session_items_session_id_test_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['variant_id'], ['task_variants.id'], name=op.f('fk_test_session_items_variant_id_task_variants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_test_session_items')),
    sa.UniqueConstraint('session_id', 'position', name='uq_test_session_items_position')
    )
    with op.batch_alter_table('test_session_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_test_session_items_session_id'), ['session_id'], unique=False)

    op.create_table('invitations',
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('employer_user_id', sa.Uuid(), nullable=True),
    sa.Column('candidate_user_id', sa.Uuid(), nullable=False),
    sa.Column('need_id', sa.Uuid(), nullable=True),
    sa.Column('probe_id', sa.Uuid(), nullable=True),
    sa.Column('position_title', sa.String(length=200), nullable=False),
    sa.Column('offer_description', sa.Text(), nullable=False),
    sa.Column('salary_from', sa.Integer(), nullable=False),
    sa.Column('salary_to', sa.Integer(), nullable=False),
    sa.Column('contact_method', sa.String(length=255), nullable=False),
    sa.Column('evidence', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.Enum('sent', 'viewed', 'accepted', 'declined', 'withdrawn', 'expired', name='invitation_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('viewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('contacts_revealed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('salary_from > 0 AND salary_from <= salary_to', name=op.f('ck_invitations_salary_range')),
    sa.ForeignKeyConstraint(['candidate_user_id'], ['users.id'], name=op.f('fk_invitations_candidate_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_invitations_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['employer_user_id'], ['users.id'], name=op.f('fk_invitations_employer_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['need_id'], ['employer_needs.id'], name=op.f('fk_invitations_need_id_employer_needs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['probe_id'], ['probes.id'], name=op.f('fk_invitations_probe_id_probes'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invitations'))
    )
    with op.batch_alter_table('invitations', schema=None) as batch_op:
        batch_op.create_index('ix_invitations_candidate_status', ['candidate_user_id', 'status'], unique=False)
        batch_op.create_index('ix_invitations_pair_created', ['company_id', 'candidate_user_id', 'created_at'], unique=False)

    op.create_table('test_answers',
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('item_id', sa.Uuid(), nullable=False),
    sa.Column('answer', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('is_correct', sa.Boolean(), nullable=True),
    sa.Column('score', sa.Double(), nullable=True),
    sa.Column('grading', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('time_spent_ms', sa.Integer(), nullable=True),
    sa.Column('answered_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['test_session_items.id'], name=op.f('fk_test_answers_item_id_test_session_items'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['test_sessions.id'], name=op.f('fk_test_answers_session_id_test_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_test_answers')),
    sa.UniqueConstraint('item_id', name=op.f('uq_test_answers_item_id'))
    )
    with op.batch_alter_table('test_answers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_test_answers_session_id'), ['session_id'], unique=False)

    op.create_table('invitation_events',
    sa.Column('invitation_id', sa.Uuid(), nullable=False),
    sa.Column('from_status', sa.Enum('sent', 'viewed', 'accepted', 'declined', 'withdrawn', 'expired', name='invitation_from_status', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('to_status', sa.Enum('sent', 'viewed', 'accepted', 'declined', 'withdrawn', 'expired', name='invitation_to_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_invitation_events_actor_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['invitation_id'], ['invitations.id'], name=op.f('fk_invitation_events_invitation_id_invitations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invitation_events'))
    )
    with op.batch_alter_table('invitation_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_invitation_events_invitation_id'), ['invitation_id'], unique=False)

    # ### end Alembic commands ###


def downgrade() -> None:
    # Сгенерировано alembic autogenerate по app/models.py; CHECK для перечислений создаёт sa.Enum.
    with op.batch_alter_table('invitation_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_invitation_events_invitation_id'))

    op.drop_table('invitation_events')
    with op.batch_alter_table('test_answers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_test_answers_session_id'))

    op.drop_table('test_answers')
    with op.batch_alter_table('invitations', schema=None) as batch_op:
        batch_op.drop_index('ix_invitations_pair_created')
        batch_op.drop_index('ix_invitations_candidate_status')

    op.drop_table('invitations')
    with op.batch_alter_table('test_session_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_test_session_items_session_id'))

    op.drop_table('test_session_items')
    with op.batch_alter_table('selection_versions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_selection_versions_need_id'))

    op.drop_table('selection_versions')
    with op.batch_alter_table('probes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_probes_company_id'))
        batch_op.drop_index('ix_probes_candidate_status')

    op.drop_table('probes')
    with op.batch_alter_table('grade_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_grade_history_user_id'))

    op.drop_table('grade_history')
    with op.batch_alter_table('test_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_test_sessions_user_id'))

    op.drop_table('test_sessions')
    op.drop_table('survey_stack_tags')
    with op.batch_alter_table('fsp_achievements', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_fsp_achievements_passport_id'))

    op.drop_table('fsp_achievements')
    with op.batch_alter_table('employer_profiles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_employer_profiles_company_id'))

    op.drop_table('employer_profiles')
    with op.batch_alter_table('employer_needs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_employer_needs_company_id'))

    op.drop_table('employer_needs')
    with op.batch_alter_table('candidate_profiles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_candidate_profiles_current_category_id'))

    op.drop_table('candidate_profiles')
    with op.batch_alter_table('task_variants', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_task_variants_family_id'))

    op.drop_table('task_variants')
    with op.batch_alter_table('survey_responses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_survey_responses_user_id'))

    op.drop_table('survey_responses')
    with op.batch_alter_table('stack_tags', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stack_tags_direction_id'))

    op.drop_table('stack_tags')
    op.drop_table('fsp_passports')
    with op.batch_alter_table('email_verifications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_email_verifications_user_id'))

    op.drop_table('email_verifications')
    with op.batch_alter_table('consents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_consents_user_id'))

    op.drop_table('consents')
    op.drop_table('companies')
    op.drop_table('categories')
    with op.batch_alter_table('candidate_facts', schema=None) as batch_op:
        batch_op.drop_index('ix_candidate_facts_user_level')

    op.drop_table('candidate_facts')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    with op.batch_alter_table('task_families', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_task_families_direction'))

    op.drop_table('task_families')
    op.drop_table('grades')
    op.drop_table('directions')
    # ### end Alembic commands ###
