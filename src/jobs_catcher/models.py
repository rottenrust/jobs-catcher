from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime as SADateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now_utc() -> datetime:
    return datetime.now(timezone.utc)

class UTCDateTime(TypeDecorator):
    impl = SADateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

DateTime = UTCDateTime

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    login: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    display_name: Mapped[str | None] = mapped_column(String(200))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    user: Mapped[User] = relationship()

class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    login: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    ip: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True, nullable=False)

class ResumeFile(Base):
    __tablename__ = "resume_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(80), nullable=False)
    mime: Mapped[str] = mapped_column(String(160), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

class ProfileVersion(Base):
    __tablename__ = "profile_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    resume_file_id: Mapped[int | None] = mapped_column(ForeignKey("resume_files.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_profile_user_version"),)

class CriteriaVersion(Base):
    __tablename__ = "criteria_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    profile_version_id: Mapped[int | None] = mapped_column(ForeignKey("profile_versions.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_criteria_user_version"),)

class UserSchedule(Base):
    __tablename__ = "user_schedules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    run_time: Mapped[str] = mapped_column(String(8), default="09:00", nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), default="Europe/Moscow", nullable=False)
    sources_json: Mapped[str] = mapped_column(Text, nullable=False)
    preferences_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="queued")
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    worker_id: Mapped[str | None] = mapped_column(String(120), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_message: Mapped[str | None] = mapped_column(Text)
    technical_error: Mapped[str | None] = mapped_column(Text)
    active_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    __table_args__ = (Index("ix_jobs_user_type_status", "user_id", "type", "status"),)

class SearchRun(Base):
    __tablename__ = "search_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("background_jobs.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(40), default="running", nullable=False)
    average_prescore: Mapped[float | None] = mapped_column(Float)
    summary_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class Vacancy(Base):
    __tablename__ = "vacancies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_title: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    normalized_company: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    normalized_location: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    location: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    work_format: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    employment_type: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    salary_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    published_at: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    requirements: Mapped[str] = mapped_column(Text, default="", nullable=False)
    responsibilities: Mapped[str] = mapped_column(Text, default="", nullable=False)
    conditions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    skills_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    normalized_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

class VacancySource(Base):
    __tablename__ = "vacancy_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_source_external"),)

class RunVacancy(Base):
    __tablename__ = "run_vacancies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("search_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"), index=True, nullable=False)
    has_full_description: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint("run_id", "vacancy_id", name="uq_run_vacancy"),)

class VacancyScore(Base):
    __tablename__ = "vacancy_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    run_id: Mapped[int] = mapped_column(ForeignKey("search_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"), index=True, nullable=False)
    profile_version_id: Mapped[int | None] = mapped_column(ForeignKey("profile_versions.id", ondelete="SET NULL"))
    criteria_version_id: Mapped[int | None] = mapped_column(ForeignKey("criteria_versions.id", ondelete="SET NULL"))
    prescore: Mapped[int] = mapped_column(Integer, nullable=False)
    final_score: Mapped[int | None] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(80), nullable=False)
    signals_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    recommendations_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

class VacancyUIState(Base):
    __tablename__ = "vacancy_ui_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"), index=True, nullable=False)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("user_id", "vacancy_id", name="uq_ui_user_vacancy"),)

class CoverLetter(Base):
    __tablename__ = "cover_letters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

class SourceHealth(Base):
    __tablename__ = "source_health"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    ip: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    user_agent: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
