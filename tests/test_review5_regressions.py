
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from jobs_catcher.db import make_engine, make_session_factory, utcnow
from jobs_catcher.models import AppSetting, BackgroundJob, CriteriaVersion, ProfileVersion, ResumeFile, SourceHealth, User, UserSchedule
from jobs_catcher.settings import Settings
from jobs_catcher.source_adapters import ADAPTERS
from jobs_catcher.source_adapters.base import VacancyResult
from jobs_catcher.web import create_app
from jobs_catcher.worker import HANDLERS, claim_next_job, heartbeat_job, process_one, recover_stale_jobs


def st(tmp_path, **overrides):
    base = Settings(database_url=f"sqlite:///{tmp_path/'app.sqlite3'}", data_dir=tmp_path/'data', upload_dir=tmp_path/'data/uploads', run_dir=tmp_path/'data/runs', allowed_hosts=("testserver",), codex_bin="python3", http_delay_seconds=0, http_jitter_seconds=0)
    return Settings(**{**base.__dict__, **overrides})


def login_changed(client):
    assert client.post('/login', data={'login':'admin','password':'admin'}, follow_redirects=False).status_code == 303
    csrf = client.cookies.get('csrf')
    assert client.post('/change-password', data={'password':'admin review5 pass 42','csrf':csrf}, follow_redirects=False).status_code == 303
    return client.cookies.get('csrf')


SOURCE_DETAILS = {
    'hh': '<main><h1 data-qa="vacancy-title">HH Ops Lead</h1><a data-qa="vacancy-company-name">HH Corp</a><span data-qa="vacancy-view-raw-address">Moscow</span><div data-qa="vacancy-salary">210 000 - 250 000 RUB net</div><p data-qa="vacancy-view-employment-mode">full-time</p><p data-qa="vacancy-view-work-schedule">remote</p><time data-qa="vacancy-date" datetime="2026-07-05">5 July</time><div data-qa="vacancy-description"><p>HH clean description</p><strong>Requirements</strong><p>HH requirements</p><strong>Responsibilities</strong><p>HH responsibilities</p><strong>Conditions</strong><p>HH conditions</p></div><div data-qa="skills-element">inventory</div><div data-qa="skills-element">ops</div><footer>navigation noise</footer></main>',
    'habr': '<article><h1 class="page-title">Habr Ops Lead</h1><a class="company_name">Habr Corp</a><span class="location">Saint Petersburg</span><div class="salary">180000-230000 RUB gross</div><span class="remote-work">remote</span><span class="employment-type">full-time</span><time class="published_at" datetime="2026-07-06"></time><div class="vacancy-description"><section class="requirements">Habr requirements</section><section class="responsibilities">Habr responsibilities</section><section class="conditions">Habr conditions</section><p>Habr clean description</p></div><a class="skill">python</a><a class="skill">analytics</a><aside>noise</aside></article>',
    'superjob': '<section><h1 class="_title">SuperJob Ops Lead</h1><span class="f-test-text-vacancy-item-company-name">SuperJob Corp</span><span class="address">Kazan</span><span class="payment">200 000 rub</span><span class="place-of-work">office</span><span class="employment">part-time</span><time class="date-published" datetime="2026-07-07"></time><div class="vacancy-text"><h3>Requirements</h3><p>SJ requirements</p><h3>Responsibilities</h3><p>SJ responsibilities</p><h3>Conditions</h3><p>SJ conditions</p><p>SJ clean description</p></div><span class="catalogues">sales</span></section>',
    'rabota': '<div><h1 class="vacancy-title">Rabota Ops Lead</h1><div class="company-name">Rabota Corp</div><div class="vacancy-location">Yekaterinburg</div><div class="vacancy-salary">150 000 RUB</div><div class="work-format">hybrid</div><div class="employment">contract</div><time class="published" datetime="2026-07-08"></time><div class="vacancy-description"><b>Requirements</b><p>Rabota requirements</p><b>Responsibilities</b><p>Rabota responsibilities</p><b>Conditions</b><p>Rabota conditions</p><p>Rabota clean description</p></div><span class="skill-item">crm</span></div>',
    'geekjob': '<main><h1 class="job-title">GeekJob Ops Lead</h1><span class="company">GeekJob Corp</span><span class="city">Novosibirsk</span><span class="salary">170000 RUB net</span><span class="format">remote</span><span class="employment">full-time</span><time class="date" datetime="2026-07-09"></time><div class="description"><p>Geek clean description</p><h4>Requirements</h4><p>Geek requirements</p><h4>Responsibilities</h4><p>Geek responsibilities</p><h4>Conditions</h4><p>Geek conditions</p></div><span class="tag">product</span><span class="tag">ops</span></main>',
    'getmatch': '<main><h1 class="vacancy__title">GetMatch Ops Lead</h1><a class="company">GetMatch Corp</a><span class="location">Tbilisi</span><div class="salary">250000-300000 RUB</div><div class="work-format">relocation</div><div class="employment-type">full-time</div><time class="published" datetime="2026-07-10"></time><section class="about-vacancy"><p>GetMatch clean description</p><h3>Requirements</h3><p>GetMatch requirements</p><h3>Responsibilities</h3><p>GetMatch responsibilities</p><h3>Conditions</h3><p>GetMatch conditions</p></section><li class="skill">go</li><li class="skill">platform</li></main>',
}

EXPECTED = {
    'hh': ('HH Corp', 'Moscow', 'remote', 'full-time', {'from': 210000, 'to': 250000, 'currency': 'RUB', 'gross': False}, '2026-07-05', ['inventory', 'ops'], 'HH clean description'),
    'habr': ('Habr Corp', 'Saint Petersburg', 'remote', 'full-time', {'from': 180000, 'to': 230000, 'currency': 'RUB', 'gross': True}, '2026-07-06', ['python', 'analytics'], 'Habr clean description'),
    'superjob': ('SuperJob Corp', 'Kazan', 'office', 'part-time', {'from': 200000, 'currency': 'RUB', 'gross': None}, '2026-07-07', ['sales'], 'SJ clean description'),
    'rabota': ('Rabota Corp', 'Yekaterinburg', 'hybrid', 'contract', {'from': 150000, 'currency': 'RUB', 'gross': None}, '2026-07-08', ['crm'], 'Rabota clean description'),
    'geekjob': ('GeekJob Corp', 'Novosibirsk', 'remote', 'full-time', {'from': 170000, 'currency': 'RUB', 'gross': False}, '2026-07-09', ['product', 'ops'], 'Geek clean description'),
    'getmatch': ('GetMatch Corp', 'Tbilisi', 'relocation', 'full-time', {'from': 250000, 'to': 300000, 'currency': 'RUB', 'gross': None}, '2026-07-10', ['go', 'platform'], 'GetMatch clean description'),
}


@pytest.mark.parametrize('source,cls', sorted(ADAPTERS.items()))
def test_review5_each_adapter_uses_source_specific_detail_structure(source, cls, tmp_path):
    adapter = cls(st(tmp_path))
    row = VacancyResult(source=source, external_id=f'{source}-r5', title='fallback', url=f'{adapter.base_url}/vacancies/{source}-r5')
    normalized = adapter.normalize(adapter.parse_detail_page(SOURCE_DETAILS[source], row))
    company, location, work_format, employment, salary, published, skills, desc = EXPECTED[source]
    assert normalized['company'] == company
    assert normalized['location'] == location
    assert normalized['work_format'] == work_format
    assert normalized['employment_type'] == employment
    assert normalized['salary'] == salary
    assert normalized['published_at'] == published
    assert normalized['skills'] == skills
    assert desc in normalized['description']
    assert 'navigation noise' not in normalized['description']


def test_review5_salary_without_gross_marker_keeps_gross_unknown(tmp_path):
    adapter = ADAPTERS['rabota'](st(tmp_path))
    row = VacancyResult(source='rabota', external_id='salary-unknown', title='Ops', url='https://rabota.ru/rabota/vacancy/salary-unknown')
    normalized = adapter.normalize(adapter.parse_detail_page('<h1>Ops</h1><div data-field="salary">150 000 RUB</div>', row))
    assert normalized['salary'] == {'from': 150000, 'currency': 'RUB', 'gross': None}


def test_review5_heartbeat_committed_and_prevents_reclaim(tmp_path):
    settings = st(tmp_path); create_app(settings=settings)
    SessionLocal = make_session_factory(make_engine(settings.database_url))
    with SessionLocal() as db:
        db.add(BackgroundJob(type='scheduled_search', status='queued', payload_json='{}'))
        db.commit()
    with SessionLocal() as db:
        job = claim_next_job(db, worker_id='worker-a', lease_seconds=1)
        db.commit(); jid = job.id
    assert heartbeat_job(SessionLocal, jid, 'worker-a', progress=33, lease_seconds=120)
    with SessionLocal() as observer:
        fresh = observer.get(BackgroundJob, jid)
        assert fresh.progress == 33
        assert fresh.lease_expires_at > utcnow() + timedelta(seconds=30)
        assert recover_stale_jobs(observer, stale_after_seconds=0) == 0


def test_review5_upload_final_rename_failure_leaves_no_active_row_job_or_orphan(tmp_path, monkeypatch):
    settings = st(tmp_path); app = create_app(settings=settings); c = TestClient(app); csrf = login_changed(c)
    original_replace = Path.replace
    def fail_replace(self, target):
        if self.name.endswith('.tmp'):
            raise OSError('rename failed')
        return original_replace(self, target)
    monkeypatch.setattr(Path, 'replace', fail_replace)
    # Valid minimal docx ZIP, so the failure point is final rename, not extraction.
    import io, zipfile
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, 'w') as z:
        z.writestr('word/document.xml', '<w:document><w:t>Ops resume text</w:t></w:document>')
    response = c.post('/resume', files={'file':('cv.docx', bio.getvalue(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')}, data={'csrf':csrf})
    assert response.status_code >= 400
    SessionLocal = make_session_factory(make_engine(settings.database_url))
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == 'admin'))
        assert db.scalars(select(ResumeFile).where(ResumeFile.user_id == user.id, ResumeFile.active == True)).all() == []
        assert db.scalars(select(BackgroundJob).where(BackgroundJob.user_id == user.id)).all() == []
    assert list(settings.upload_dir.glob('*')) == []


def schema_signature(engine):
    insp = inspect(engine)
    return {table: [(c['name'], str(c['type']), bool(c['nullable'])) for c in insp.get_columns(table)] for table in sorted(t for t in insp.get_table_names() if t != 'alembic_version')}


def test_review5_migration_history_schema_consistency(tmp_path):
    db = tmp_path / 'schema.sqlite3'
    cfg = Config('alembic.ini'); cfg.set_main_option('sqlalchemy.url', f'sqlite:///{db}')
    command.upgrade(cfg, '0001_initial')
    engine = make_engine(f'sqlite:///{db}')
    assert 'work_format' not in {c['name'] for c in inspect(engine).get_columns('vacancies')}
    command.upgrade(cfg, 'head')
    upgraded_head = schema_signature(engine)
    command.downgrade(cfg, '0001_initial')
    assert 'work_format' not in {c['name'] for c in inspect(engine).get_columns('vacancies')}
    command.upgrade(cfg, 'head')
    assert schema_signature(engine) == upgraded_head
    fresh = tmp_path / 'fresh.sqlite3'
    fresh_cfg = Config('alembic.ini'); fresh_cfg.set_main_option('sqlalchemy.url', f'sqlite:///{fresh}')
    command.upgrade(fresh_cfg, 'head')
    assert schema_signature(make_engine(f'sqlite:///{fresh}')) == upgraded_head


def test_review5_env_example_secret_rejected_in_production(tmp_path):
    secret = next(line.split('=', 1)[1] for line in Path('.env.example').read_text().splitlines() if line.startswith('SESSION_SECRET='))
    settings = st(tmp_path, environment='production', session_secret=secret)
    cfg = Config('alembic.ini'); cfg.set_main_option('sqlalchemy.url', settings.database_url); command.upgrade(cfg, 'head')
    with pytest.raises(RuntimeError, match='SESSION_SECRET'):
        create_app(settings=settings)


def test_review5_worker_handler_exception_rolls_back_partial_data_and_updates_job(tmp_path):
    settings = st(tmp_path); create_app(settings=settings)
    SessionLocal = make_session_factory(make_engine(settings.database_url))
    with SessionLocal() as db:
        db.add(BackgroundJob(type='boom', status='queued', payload_json='{}', max_attempts=1))
        db.commit()
    def boom_handler(db, job, settings, runner):
        db.add(SourceHealth(source='partial', status='ok'))
        db.flush()
        raise IntegrityError('stmt', {}, Exception('db exploded'))
    old = HANDLERS.get('boom'); HANDLERS['boom'] = boom_handler
    try:
        assert process_one(SessionLocal, settings, runner=object())
    finally:
        if old is None:
            HANDLERS.pop('boom', None)
        else:
            HANDLERS['boom'] = old
    with SessionLocal() as db:
        assert db.scalar(select(SourceHealth).where(SourceHealth.source == 'partial')) is None
        job = db.scalar(select(BackgroundJob))
        assert job.status == 'failed'
        assert 'db exploded' in job.technical_error


def test_review5_invalid_admin_settings_do_not_persist_or_break_effective_settings(tmp_path):
    settings = st(tmp_path); app = create_app(settings=settings); c = TestClient(app); csrf = login_changed(c)
    good = {'csrf':csrf,'enabled_sources':'hh','min_schedule_interval_days':'1','max_schedule_interval_days':'10','timezone':'Europe/Amsterdam','http_delay_seconds':'0','http_jitter_seconds':'0','http_timeout_seconds':'5','http_retries':'1','max_search_queries':'2','max_results_per_source':'3','max_vacancies_per_run':'5','max_llm_candidates':'4','codex_batch_size':'2','codex_bin':'python3','resume_size_limit':'1048576','artifact_retention_days':'7','global_search_enabled':'on'}
    assert c.post('/admin/settings', data=good).status_code == 200
    csrf = c.cookies.get('csrf')
    bad = {**good, 'csrf': csrf, 'timezone': 'Not/AZone', 'http_timeout_seconds': '-1', 'codex_bin': ''}
    assert c.post('/admin/settings', data=bad).status_code == 400
    SessionLocal = make_session_factory(make_engine(settings.database_url))
    with SessionLocal() as db:
        values = {row.key: json.loads(row.value_json) for row in db.scalars(select(AppSetting)).all()}
        assert values['timezone'] == 'Europe/Amsterdam'
        assert values['http_timeout_seconds'] == 5.0
        assert values['codex_bin'] == 'python3'
    assert c.get('/admin/settings').status_code == 200


def test_review5_web_write_can_commit_during_source_search_stage(tmp_path):
    from jobs_catcher import criteria as criteria_mod
    settings = st(tmp_path); create_app(settings=settings)
    SessionLocal = make_session_factory(make_engine(settings.database_url))
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == 'admin'))
        profile = ProfileVersion(user_id=user.id, version=1, data_json=json.dumps({'professional_title':'Ops','onboarding':{}}, ensure_ascii=False), confirmed=True)
        db.add(profile); db.flush()
        db.add(CriteriaVersion(user_id=user.id, profile_version_id=profile.id, version=1, data_json=json.dumps(criteria_mod.DEFAULT_CRITERIA, ensure_ascii=False)))
        db.add(UserSchedule(user_id=user.id, interval_days=1, run_time='09:00', timezone='Europe/Amsterdam', sources_json=json.dumps(['hh']), preferences_json='{}'))
        db.add(BackgroundJob(user_id=user.id, type='scheduled_search', status='queued', payload_json='{}', max_attempts=1))
        db.commit()

    class ConcurrentWriteAdapter:
        def search(self, query, preferences):
            with SessionLocal() as other:
                other.add(AppSetting(key='concurrent_write_probe', value_json=json.dumps('ok')))
                other.commit()
            return []
        def close(self):
            pass

    assert process_one(SessionLocal, settings, runner=object(), adapter_factory=lambda source: ConcurrentWriteAdapter())
    with SessionLocal() as db:
        assert json.loads(db.get(AppSetting, 'concurrent_write_probe').value_json) == 'ok'
        job = db.scalar(select(BackgroundJob))
        assert job.status == 'completed'
