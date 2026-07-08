from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_settings",
        sa.Column('key', sa.String(120), primary_key=True, nullable=False),
        sa.Column('value_json', sa.String(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "login_attempts",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('login', sa.String(120), nullable=False),
        sa.Column('ip', sa.String(80), nullable=False, default=''),
        sa.Column('success', sa.Boolean(), nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_attempts_created_at", "login_attempts", ['created_at'], unique=False)
    op.create_index("ix_login_attempts_login", "login_attempts", ['login'], unique=False)

    op.create_table(
        "source_health",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('source', sa.String(40), nullable=False, unique=True),
        sa.Column('status', sa.String(40), nullable=False),
        sa.Column('last_error', sa.String()),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('login', sa.String(120), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(512), nullable=False),
        sa.Column('role', sa.String(32), nullable=False, default='user'),
        sa.Column('display_name', sa.String(200)),
        sa.Column('must_change_password', sa.Boolean(), nullable=False, default=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_login", "users", ['login'], unique=True)

    op.create_table(
        "vacancies",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('normalized_title', sa.String(255), nullable=False),
        sa.Column('normalized_company', sa.String(255), nullable=False),
        sa.Column('normalized_location', sa.String(255), nullable=False, default=''),
        sa.Column('canonical_url', sa.String()),
        sa.Column('content_hash', sa.String(64)),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('company', sa.String(500), nullable=False, default=''),
        sa.Column('location', sa.String(255), nullable=False, default=''),
        sa.Column('description', sa.String(), nullable=False, default=''),
        sa.Column('work_format', sa.String(80), nullable=False, default=''),
        sa.Column('employment_type', sa.String(120), nullable=False, default=''),
        sa.Column('salary_json', sa.String(), nullable=False, default='{}'),
        sa.Column('published_at', sa.String(40), nullable=False, default=''),
        sa.Column('updated_at', sa.String(40), nullable=False, default=''),
        sa.Column('requirements', sa.String(), nullable=False, default=''),
        sa.Column('responsibilities', sa.String(), nullable=False, default=''),
        sa.Column('conditions', sa.String(), nullable=False, default=''),
        sa.Column('skills_json', sa.String(), nullable=False, default='[]'),
        sa.Column('normalized_json', sa.String(), nullable=False, default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_vacancies_content_hash", "vacancies", ['content_hash'], unique=False)
    op.create_index("ix_vacancies_normalized_company", "vacancies", ['normalized_company'], unique=False)
    op.create_index("ix_vacancies_normalized_title", "vacancies", ['normalized_title'], unique=False)

    op.create_table(
        "audit_log",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('action', sa.String(120), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), sa.ForeignKey("users.id", ondelete='SET NULL')),
        sa.Column('target_user_id', sa.Integer(), sa.ForeignKey("users.id", ondelete='SET NULL')),
        sa.Column('ip', sa.String(80), nullable=False, default=''),
        sa.Column('user_agent', sa.String(255), nullable=False, default=''),
        sa.Column('metadata_json', sa.String(), nullable=False, default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_action", "audit_log", ['action'], unique=False)

    op.create_table(
        "background_jobs",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey("users.id", ondelete='CASCADE')),
        sa.Column('type', sa.String(80), nullable=False),
        sa.Column('status', sa.String(40), nullable=False, default='queued'),
        sa.Column('payload_json', sa.String(), nullable=False, default='{}'),
        sa.Column('progress', sa.Integer(), nullable=False, default=0),
        sa.Column('attempts', sa.Integer(), nullable=False, default=0),
        sa.Column('max_attempts', sa.Integer(), nullable=False, default=2),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.Column('user_message', sa.String()),
        sa.Column('technical_error', sa.String()),
        sa.Column('active_key', sa.String(160), unique=True),
    )
    op.create_index("ix_background_jobs_heartbeat_at", "background_jobs", ['heartbeat_at'], unique=False)
    op.create_index("ix_background_jobs_status", "background_jobs", ['status'], unique=False)
    op.create_index("ix_background_jobs_user_id", "background_jobs", ['user_id'], unique=False)
    op.create_index("ix_jobs_user_type_status", "background_jobs", ['user_id', 'type', 'status'], unique=False)

    op.create_table(
        "cover_letters",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey("users.id", ondelete='CASCADE'), nullable=False),
        sa.Column('vacancy_id', sa.Integer(), sa.ForeignKey("vacancies.id", ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('text', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cover_letters_user_id", "cover_letters", ['user_id'], unique=False)
    op.create_index("ix_cover_letters_vacancy_id", "cover_letters", ['vacancy_id'], unique=False)

    op.create_table(
        "resume_files",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey("users.id", ondelete='CASCADE'), nullable=False),
        sa.Column('original_name', sa.String(255), nullable=False),
        sa.Column('stored_name', sa.String(80), nullable=False),
        sa.Column('mime', sa.String(160), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('path', sa.String(), nullable=False),
        sa.Column('extracted_text', sa.String(), nullable=False, default=''),
        sa.Column('active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_resume_files_active", "resume_files", ['active'], unique=False)
    op.create_index("ix_resume_files_user_id", "resume_files", ['user_id'], unique=False)

    op.create_table(
        "user_schedules",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey("users.id", ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('interval_days', sa.Integer(), nullable=False),
        sa.Column('run_time', sa.String(8), nullable=False, default='09:00'),
        sa.Column('timezone', sa.String(80), nullable=False, default='Europe/Moscow'),
        sa.Column('sources_json', sa.String(), nullable=False),
        sa.Column('preferences_json', sa.String(), nullable=False, default='{}'),
        sa.Column('next_run_at', sa.DateTime(timezone=True)),
        sa.Column('last_run_at', sa.DateTime(timezone=True)),
        sa.Column('enabled', sa.Boolean(), nullable=False, default=True),
    )
    op.create_index("ix_user_schedules_next_run_at", "user_schedules", ['next_run_at'], unique=False)

    op.create_table(
        "user_sessions",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey("users.id", ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(128), nullable=False, unique=True),
        sa.Column('csrf_hash', sa.String(128), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ['user_id'], unique=False)

    op.create_table(
        "vacancy_sources",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('vacancy_id', sa.Integer(), sa.ForeignKey("vacancies.id", ondelete='CASCADE'), nullable=False),
        sa.Column('source', sa.String(40), nullable=False),
        sa.Column('external_id', sa.String(200), nullable=False),
        sa.Column('source_url', sa.String(), nullable=False),
        sa.Column('raw_json', sa.String(), nullable=False, default='{}'),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('source', 'external_id', name="uq_source_external"),
    )
    op.create_index("ix_vacancy_sources_vacancy_id", "vacancy_sources", ['vacancy_id'], unique=False)

    op.create_table(
        "vacancy_ui_state",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey("users.id", ondelete='CASCADE'), nullable=False),
        sa.Column('vacancy_id', sa.Integer(), sa.ForeignKey("vacancies.id", ondelete='CASCADE'), nullable=False),
        sa.Column('viewed_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('user_id', 'vacancy_id', name="uq_ui_user_vacancy"),
    )
    op.create_index("ix_vacancy_ui_state_user_id", "vacancy_ui_state", ['user_id'], unique=False)
    op.create_index("ix_vacancy_ui_state_vacancy_id", "vacancy_ui_state", ['vacancy_id'], unique=False)

    op.create_table(
        "profile_versions",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey("users.id", ondelete='CASCADE'), nullable=False),
        sa.Column('resume_file_id', sa.Integer(), sa.ForeignKey("resume_files.id", ondelete='SET NULL')),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('data_json', sa.String(), nullable=False),
        sa.Column('confirmed', sa.Boolean(), nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'version', name="uq_profile_user_version"),
    )
    op.create_index("ix_profile_versions_user_id", "profile_versions", ['user_id'], unique=False)

    op.create_table(
        "search_runs",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey("users.id", ondelete='CASCADE'), nullable=False),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey("background_jobs.id", ondelete='SET NULL')),
        sa.Column('status', sa.String(40), nullable=False, default='running'),
        sa.Column('average_prescore', sa.Float()),
        sa.Column('summary_json', sa.String(), nullable=False, default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
    )
    op.create_index("ix_search_runs_user_id", "search_runs", ['user_id'], unique=False)

    op.create_table(
        "criteria_versions",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey("users.id", ondelete='CASCADE'), nullable=False),
        sa.Column('profile_version_id', sa.Integer(), sa.ForeignKey("profile_versions.id", ondelete='SET NULL')),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('data_json', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'version', name="uq_criteria_user_version"),
    )
    op.create_index("ix_criteria_versions_user_id", "criteria_versions", ['user_id'], unique=False)

    op.create_table(
        "run_vacancies",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('run_id', sa.Integer(), sa.ForeignKey("search_runs.id", ondelete='CASCADE'), nullable=False),
        sa.Column('vacancy_id', sa.Integer(), sa.ForeignKey("vacancies.id", ondelete='CASCADE'), nullable=False),
        sa.Column('has_full_description', sa.Boolean(), nullable=False, default=True),
        sa.UniqueConstraint('run_id', 'vacancy_id', name="uq_run_vacancy"),
    )
    op.create_index("ix_run_vacancies_run_id", "run_vacancies", ['run_id'], unique=False)
    op.create_index("ix_run_vacancies_vacancy_id", "run_vacancies", ['vacancy_id'], unique=False)

    op.create_table(
        "vacancy_scores",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey("users.id", ondelete='CASCADE'), nullable=False),
        sa.Column('run_id', sa.Integer(), sa.ForeignKey("search_runs.id", ondelete='CASCADE'), nullable=False),
        sa.Column('vacancy_id', sa.Integer(), sa.ForeignKey("vacancies.id", ondelete='CASCADE'), nullable=False),
        sa.Column('profile_version_id', sa.Integer(), sa.ForeignKey("profile_versions.id", ondelete='SET NULL')),
        sa.Column('criteria_version_id', sa.Integer(), sa.ForeignKey("criteria_versions.id", ondelete='SET NULL')),
        sa.Column('prescore', sa.Integer(), nullable=False),
        sa.Column('final_score', sa.Integer()),
        sa.Column('decision', sa.String(80), nullable=False),
        sa.Column('signals_json', sa.String(), nullable=False, default='{}'),
        sa.Column('recommendations_json', sa.String(), nullable=False, default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_vacancy_scores_run_id", "vacancy_scores", ['run_id'], unique=False)
    op.create_index("ix_vacancy_scores_user_id", "vacancy_scores", ['user_id'], unique=False)
    op.create_index("ix_vacancy_scores_vacancy_id", "vacancy_scores", ['vacancy_id'], unique=False)


def downgrade():
    op.drop_table("vacancy_scores")
    op.drop_table("run_vacancies")
    op.drop_table("criteria_versions")
    op.drop_table("search_runs")
    op.drop_table("profile_versions")
    op.drop_table("vacancy_ui_state")
    op.drop_table("vacancy_sources")
    op.drop_table("user_sessions")
    op.drop_table("user_schedules")
    op.drop_table("resume_files")
    op.drop_table("cover_letters")
    op.drop_table("background_jobs")
    op.drop_table("audit_log")
    op.drop_table("vacancies")
    op.drop_table("users")
    op.drop_table("source_health")
    op.drop_table("login_attempts")
    op.drop_table("app_settings")
