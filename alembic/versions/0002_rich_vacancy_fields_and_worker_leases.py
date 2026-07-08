from alembic import op
import sqlalchemy as sa

revision = "0002_rich_vacancy_fields_and_worker_leases"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _columns(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _add_column_if_missing(table_name, column):
    if column.name not in _columns(table_name):
        op.add_column(table_name, column)


def _create_index_if_missing(name, table_name, columns):
    if name not in _indexes(table_name):
        op.create_index(name, table_name, columns, unique=False)


def upgrade():
    _add_column_if_missing("vacancies", sa.Column("work_format", sa.String(80), nullable=False, server_default=""))
    _add_column_if_missing("vacancies", sa.Column("employment_type", sa.String(120), nullable=False, server_default=""))
    _add_column_if_missing("vacancies", sa.Column("salary_json", sa.Text(), nullable=False, server_default="{}"))
    _add_column_if_missing("vacancies", sa.Column("published_at", sa.String(40), nullable=True))
    _add_column_if_missing("vacancies", sa.Column("updated_at", sa.String(40), nullable=True))
    _add_column_if_missing("vacancies", sa.Column("requirements", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("vacancies", sa.Column("responsibilities", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("vacancies", sa.Column("conditions", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("vacancies", sa.Column("skills_json", sa.Text(), nullable=False, server_default="[]"))
    _add_column_if_missing("vacancies", sa.Column("normalized_json", sa.Text(), nullable=False, server_default="{}"))
    _add_column_if_missing("background_jobs", sa.Column("worker_id", sa.String(120), nullable=True))
    _add_column_if_missing("background_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    _create_index_if_missing("ix_background_jobs_worker_id", "background_jobs", ["worker_id"])
    _create_index_if_missing("ix_background_jobs_lease_expires_at", "background_jobs", ["lease_expires_at"])


def downgrade():
    existing = _indexes("background_jobs")
    if "ix_background_jobs_lease_expires_at" in existing:
        op.drop_index("ix_background_jobs_lease_expires_at", table_name="background_jobs")
    if "ix_background_jobs_worker_id" in existing:
        op.drop_index("ix_background_jobs_worker_id", table_name="background_jobs")
    for table_name, column_name in [
        ("background_jobs", "lease_expires_at"),
        ("background_jobs", "worker_id"),
        ("vacancies", "normalized_json"),
        ("vacancies", "skills_json"),
        ("vacancies", "conditions"),
        ("vacancies", "responsibilities"),
        ("vacancies", "requirements"),
        ("vacancies", "updated_at"),
        ("vacancies", "published_at"),
        ("vacancies", "salary_json"),
        ("vacancies", "employment_type"),
        ("vacancies", "work_format"),
    ]:
        if column_name in _columns(table_name):
            op.drop_column(table_name, column_name)
