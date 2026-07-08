from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text

from jobs_catcher import criteria
from jobs_catcher.db import make_engine, make_session_factory
from jobs_catcher.models import (
    BackgroundJob,
    CriteriaVersion,
    ProfileVersion,
    SearchRun,
    User,
    UserSchedule,
    VacancySource,
)
from jobs_catcher.settings import Settings
from jobs_catcher.source_adapters import ADAPTERS
from jobs_catcher.source_adapters.base import VacancyResult
from jobs_catcher.web import create_app
from jobs_catcher.worker import (
    _upsert_source_snapshot,
    _upsert_vacancy,
    build_search_preferences,
    claim_next_job,
    generate_criteria_from_profile,
    process_one,
)


def st(tmp_path, **overrides):
    base = Settings(
        database_url=f"sqlite:///{tmp_path/'app.sqlite3'}",
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "data/uploads",
        run_dir=tmp_path / "data/runs",
        allowed_hosts=("testserver",),
        codex_bin="python3",
        http_delay_seconds=0,
        http_jitter_seconds=0,
    )
    return Settings(**{**base.__dict__, **overrides})


def login_changed(client):
    assert client.post("/login", data={"login": "admin", "password": "admin"}, follow_redirects=False).status_code == 303
    csrf = client.cookies.get("csrf")
    assert client.post("/change-password", data={"password": "admin review4 pass 42", "csrf": csrf}, follow_redirects=False).status_code == 303
    return client.cookies.get("csrf")


POSITIVE_DETAIL = """
<html><body>
<h1>{title}</h1>
<div class="company">{company}</div>
<span data-field="location">Москва</span>
<span data-field="salary" data-from="210000" data-to="260000" data-currency="RUB" data-gross="false">210 000 - 260 000 ₽ net</span>
<span data-field="work_format">remote</span>
<span data-field="employment_type">full-time</span>
<time data-field="published_at" datetime="2026-07-03">3 июля</time>
<time data-field="updated_at" datetime="2026-07-04">4 июля</time>
<section data-field="requirements">Опыт складской логистики</section>
<section data-field="responsibilities">Управлять операционными процессами</section>
<section data-field="conditions">Удаленная работа и ДМС</section>
<ul data-field="skills"><li>inventory</li><li>leadership</li></ul>
</body></html>
"""

NEGATIVE_DETAIL = """
<html><body>
<h1>{title}</h1>
<div class="company">{company}</div>
<p>Only plain vacancy text without salary, dates, sections or skills.</p>
</body></html>
"""


@pytest.mark.parametrize("source,cls", sorted(ADAPTERS.items()))
def test_review4_adapter_extracts_exact_fields_and_does_not_invent_missing(source, cls, tmp_path):
    adapter = cls(st(tmp_path))
    row = VacancyResult(source=source, external_id=f"{source}-42", title="Ops Lead", url=f"{adapter.base_url}/vacancies/{source}-42")
    normalized = adapter.normalize(adapter.parse_detail_page(POSITIVE_DETAIL.format(title="Ops Lead", company=f"ACME {source}"), row))
    assert normalized["salary"] == {"from": 210000, "to": 260000, "currency": "RUB", "gross": False}
    assert normalized["work_format"] == "remote"
    assert normalized["employment_type"] == "full-time"
    assert normalized["published_at"] == "2026-07-03"
    assert normalized["updated_at"] == "2026-07-04"
    assert normalized["requirements"] == "Опыт складской логистики"
    assert normalized["responsibilities"] == "Управлять операционными процессами"
    assert normalized["conditions"] == "Удаленная работа и ДМС"
    assert normalized["skills"] == ["inventory", "leadership"]

    missing_row = VacancyResult(source=source, external_id=f"{source}-43", title="Plain Ops", url=f"{adapter.base_url}/vacancies/{source}-43")
    missing = adapter.normalize(adapter.parse_detail_page(NEGATIVE_DETAIL.format(title="Plain Ops", company=f"ACME {source}"), missing_row))
    assert missing["salary"] is None
    assert missing["work_format"] == ""
    assert missing["employment_type"] == ""
    assert missing["published_at"] is None
    assert missing["updated_at"] is None
    assert missing["requirements"] == ""
    assert missing["responsibilities"] == ""
    assert missing["conditions"] == ""
    assert missing["skills"] == []


@pytest.mark.parametrize("source,cls", sorted(ADAPTERS.items()))
def test_review4_source_specific_search_urls_include_preferences(source, cls, tmp_path):
    adapter = cls(st(tmp_path))
    url = adapter.build_search_url(
        "Operations Manager",
        {
            "locations": ["Москва"],
            "all_russia": False,
            "remote": True,
            "work_formats": ["remote"],
            "employment_types": ["full-time"],
            "salary": {"minimum": 180000, "currency": "RUB", "gross": False},
            "seniority": ["middle"],
        },
        page=1,
    )
    query = parse_qs(urlparse(url).query)
    assert query
    assert any("Operations Manager" in value for values in query.values() for value in values)
    assert any("180000" in value for values in query.values() for value in values)
    assert any("remote" in value.lower() or "удален" in value.lower() for values in query.values() for value in values)
    assert any("Москва" in value or "1" == value for values in query.values() for value in values)


def test_review4_onboarding_and_criteria_build_effective_search_preferences(tmp_path):
    profile = {
        "professional_title": "Operations Manager",
        "onboarding": {
            "cities": ["Москва"],
            "remote": True,
            "all_russia": False,
            "work_format": "remote",
            "employment_types": ["full-time"],
            "salary_minimum": "180000",
            "currency": "RUB",
            "gross": True,
            "seniority": "middle",
        },
        "skills": ["inventory"],
    }
    generated = generate_criteria_from_profile(profile, profile["onboarding"])
    assert generated["search"]["salary"]["gross"] is True
    assert criteria.validate_criteria(generated)
    preferences = build_search_preferences(generated, profile)
    assert preferences["locations"] == ["Москва"]
    assert preferences["remote"] is True
    assert preferences["salary"] == {"minimum": 180000, "currency": "RUB", "gross": True}
    assert preferences["work_formats"] == ["remote"]
    assert preferences["employment_types"] == ["full-time"]
    assert preferences["seniority"] == ["middle"]


def test_review4_worker_passes_effective_preferences_to_adapter(tmp_path):
    settings = st(tmp_path, enabled_sources=("hh",), max_results_per_source=1, max_vacancies_per_run=1)
    create_app(settings=settings)
    engine = make_engine(settings.database_url)
    SessionLocal = make_session_factory(engine)
    crit = json.loads(json.dumps(criteria.DEFAULT_CRITERIA))
    crit["search"].update({"queries": ["ops"], "locations": ["Москва"], "work_formats": ["remote"], "employment_types": ["full-time"], "salary": {"minimum": 180000, "currency": "RUB", "gross": False}})
    seen = {}

    class PrefAdapter:
        def search(self, query, preferences):
            seen["query"] = query
            seen["preferences"] = preferences
            return []

        def close(self):
            seen["closed"] = True

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == "admin"))
        profile = ProfileVersion(user_id=user.id, version=1, confirmed=True, data_json=json.dumps({"professional_title": "Ops", "onboarding": {"remote": True}}))
        db.add(profile)
        db.flush()
        db.add(CriteriaVersion(user_id=user.id, profile_version_id=profile.id, version=1, data_json=json.dumps(crit)))
        db.add(UserSchedule(user_id=user.id, interval_days=1, sources_json='["hh"]', enabled=True, next_run_at=datetime.now(timezone.utc)))
        db.add(BackgroundJob(user_id=user.id, type="scheduled_search", status="queued", payload_json="{}"))
        db.commit()
    assert process_one(SessionLocal, settings, runner=object(), adapter_factory=lambda source: PrefAdapter())
    assert seen["query"] == "ops"
    assert seen["preferences"]["locations"] == ["Москва"]
    assert seen["preferences"]["remote"] is True
    assert seen["preferences"]["salary"]["minimum"] == 180000
    assert seen["closed"] is True


def test_review4_atomic_claim_only_one_worker_gets_job(tmp_path):
    settings = st(tmp_path)
    create_app(settings=settings)
    engine = make_engine(settings.database_url)
    SessionLocal = make_session_factory(engine)
    with SessionLocal() as db:
        db.add(BackgroundJob(type="scheduled_search", status="queued", payload_json="{}"))
        db.commit()
    with SessionLocal() as first, SessionLocal() as second:
        a = claim_next_job(first, worker_id="worker-a", lease_seconds=60)
        first.commit()
        b = claim_next_job(second, worker_id="worker-b", lease_seconds=60)
        second.commit()
    assert a is not None
    assert b is None
    with SessionLocal() as db:
        job = db.get(BackgroundJob, a.id)
        assert job.worker_id == "worker-a"
        assert job.lease_expires_at > datetime.now(timezone.utc)


def test_review4_old_0001_database_upgrades_to_rich_and_lease_columns(tmp_path):
    db_path = tmp_path / "old.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("create table alembic_version (version_num varchar(32) not null)"))
        conn.execute(text("insert into alembic_version(version_num) values ('0001_initial')"))
        conn.execute(text("create table vacancies (id integer primary key, normalized_title varchar(255) not null, normalized_company varchar(255) not null, normalized_location varchar(255) not null default '', canonical_url varchar, content_hash varchar(64), title varchar(500) not null, company varchar(500) not null default '', location varchar(255) not null default '', description varchar not null default '', created_at datetime not null)"))
        conn.execute(text("create table users (id integer primary key, login varchar(120) not null, password_hash varchar(512) not null, role varchar(32) not null, display_name varchar(200), must_change_password boolean not null, deleted_at datetime, created_at datetime not null)"))
        conn.execute(text("create table background_jobs (id integer primary key, user_id integer, type varchar(80) not null, status varchar(40) not null default 'queued', payload_json varchar not null default '{}', progress integer not null default 0, attempts integer not null default 0, max_attempts integer not null default 2, heartbeat_at datetime, created_at datetime not null, started_at datetime, finished_at datetime, user_message varchar, technical_error varchar, active_key varchar(160))"))
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")
    columns = {c["name"] for c in inspect(engine).get_columns("vacancies")}
    job_columns = {c["name"] for c in inspect(engine).get_columns("background_jobs")}
    assert {"work_format", "employment_type", "salary_json", "published_at", "updated_at", "requirements", "responsibilities", "conditions", "skills_json", "normalized_json"} <= columns
    assert {"worker_id", "lease_expires_at"} <= job_columns


def test_review4_db_settings_apply_resume_limit_codex_path_timezone_without_restart(tmp_path):
    settings = st(tmp_path)
    app = create_app(settings=settings)
    client = TestClient(app)
    csrf = login_changed(client)
    assert client.post(
        "/admin/settings",
        data={
            "csrf": csrf,
            "enabled_sources": "hh",
            "min_schedule_interval_days": "1",
            "max_schedule_interval_days": "10",
            "timezone": "Europe/Amsterdam",
            "http_delay_seconds": "0",
            "http_jitter_seconds": "0",
            "http_timeout_seconds": "5",
            "http_retries": "1",
            "max_search_queries": "2",
            "max_results_per_source": "3",
            "max_vacancies_per_run": "5",
            "max_llm_candidates": "4",
            "codex_batch_size": "2",
            "codex_bin": "/custom/codex",
            "resume_size_limit": "10",
            "artifact_retention_days": "7",
            "global_search_enabled": "on",
        },
    ).status_code == 200
    csrf = client.cookies.get("csrf")
    assert client.post("/resume", files={"file": ("big.pdf", b"%PDF-" + b"x" * 50, "application/pdf")}, data={"csrf": csrf}).status_code == 400
    schedule = client.get("/schedule")
    assert "Europe/Amsterdam" in schedule.text
    ready = client.get("/health/ready")
    assert ready.json()["codex_bin"] is False


def test_review4_production_rejects_placeholder_session_secret(tmp_path):
    settings = st(tmp_path, environment="production", session_secret="dev-only-change-me")
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        create_app(settings=settings)


def test_review4_repeat_fetch_updates_vacancy_and_source_snapshot(tmp_path):
    settings = st(tmp_path)
    create_app(settings=settings)
    engine = make_engine(settings.database_url)
    SessionLocal = make_session_factory(engine)
    first = {"source": "hh", "external_id": "same-1", "title": "Ops", "company": "ACME", "location": "Москва", "source_url": "https://hh.ru/vacancy/same-1", "canonical_url": "https://hh.ru/vacancy/same-1", "description": "description A", "salary": {"from": 100000}, "requirements": "A", "responsibilities": "", "conditions": "", "skills": ["a"], "content_hash": "hash-a"}
    second = {**first, "description": "description B", "salary": {"from": 220000}, "requirements": "B", "skills": ["b"], "content_hash": "hash-b"}
    with SessionLocal() as db:
        vacancy = _upsert_vacancy(db, first)
        _upsert_source_snapshot(db, vacancy, first)
        db.commit()
        vacancy_id = vacancy.id
    with SessionLocal() as db:
        vacancy = _upsert_vacancy(db, second)
        _upsert_source_snapshot(db, vacancy, second)
        db.commit()
    with SessionLocal() as db:
        vacancy = db.get(type(vacancy), vacancy_id)
        source = db.scalar(select(VacancySource).where(VacancySource.source == "hh", VacancySource.external_id == "same-1"))
        assert vacancy.id == vacancy_id
        assert vacancy.description == "description B"
        assert json.loads(vacancy.salary_json)["from"] == 220000
        assert json.loads(vacancy.skills_json) == ["b"]
        assert json.loads(source.raw_json)["description"] == "description B"


def test_review4_all_sources_failed_and_partial_run_status(tmp_path):
    settings = st(tmp_path, enabled_sources=("hh", "habr"), max_results_per_source=1)
    create_app(settings=settings)
    engine = make_engine(settings.database_url)
    SessionLocal = make_session_factory(engine)
    crit = json.loads(json.dumps(criteria.DEFAULT_CRITERIA))
    crit["search"]["queries"] = ["ops"]

    class Adapter:
        def __init__(self, source):
            self.source = source

        def search(self, query, preferences):
            if self.source == "hh":
                raise RuntimeError("boom")
            return [VacancyResult(source=self.source, external_id="ok", title="Ops", url="https://example.test/ok")]

        def fetch_details(self, result):
            result.company = "ACME"
            result.description = "ops inventory"
            return result

        def normalize(self, raw):
            return {"source": raw.source, "external_id": raw.external_id, "title": raw.title, "company": raw.company, "location": "", "source_url": raw.url, "canonical_url": raw.url, "description": raw.description, "requirements": "ops", "responsibilities": "", "conditions": "", "skills": ["ops"], "raw_metadata": {}, "content_hash": raw.source}

        def close(self):
            return None

    def seed(sources):
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login == "admin"))
            db.query(SearchRun).delete()
            db.query(BackgroundJob).delete()
            profile = db.scalar(select(ProfileVersion).where(ProfileVersion.user_id == user.id)) or ProfileVersion(user_id=user.id, version=1, confirmed=True, data_json=json.dumps({"professional_title": "Ops"}))
            db.add(profile)
            db.flush()
            if not db.scalar(select(CriteriaVersion).where(CriteriaVersion.user_id == user.id)):
                db.add(CriteriaVersion(user_id=user.id, profile_version_id=profile.id, version=1, data_json=json.dumps(crit)))
            sched = db.scalar(select(UserSchedule).where(UserSchedule.user_id == user.id)) or UserSchedule(user_id=user.id, interval_days=1, sources_json=json.dumps(sources), enabled=True, next_run_at=datetime.now(timezone.utc))
            sched.sources_json = json.dumps(sources)
            db.add(sched)
            db.add(BackgroundJob(user_id=user.id, type="scheduled_search", status="queued", payload_json="{}"))
            db.commit()

    seed(["hh", "habr"])
    assert process_one(SessionLocal, settings, runner=object(), adapter_factory=lambda source: Adapter(source))
    with SessionLocal() as db:
        assert db.scalar(select(SearchRun).order_by(SearchRun.id.desc())).status == "partial"
    seed(["hh"])
    assert process_one(SessionLocal, settings, runner=object(), adapter_factory=lambda source: Adapter(source))
    with SessionLocal() as db:
        assert db.scalar(select(SearchRun).order_by(SearchRun.id.desc())).status == "failed"
