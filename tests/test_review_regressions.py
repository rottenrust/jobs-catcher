from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from jobs_catcher import criteria
from jobs_catcher.settings import Settings
from jobs_catcher.web import create_app
from jobs_catcher.db import make_engine, make_session_factory
from jobs_catcher.models import AppSetting, BackgroundJob, CoverLetter, CriteriaVersion, ProfileVersion, SearchRun, User, UserSchedule, Vacancy, VacancyScore, VacancySource
from jobs_catcher.worker import process_one, schedule_due_jobs, compute_next_run_at
from jobs_catcher.source_adapters import ADAPTERS
from jobs_catcher.source_adapters.base import VacancyResult
from jobs_catcher.codex_integration import validate_cover_letter_result


def st(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path/'app.sqlite3'}", data_dir=tmp_path/'data', upload_dir=tmp_path/'data/uploads', run_dir=tmp_path/'data/runs', allowed_hosts=("testserver",), codex_bin="python3")


def login(client, login, password):
    r = client.post('/login', data={'login': login, 'password': password}, follow_redirects=False)
    assert r.status_code == 303
    return client.cookies.get('csrf')


def test_completed_daily_search_is_not_due_again_before_next_run(tmp_path):
    settings = st(tmp_path); create_app(settings=settings)
    engine = make_engine(settings.database_url); SessionLocal = make_session_factory(engine)
    with SessionLocal() as db:
        user_id = db.scalar(select(__import__('jobs_catcher.models', fromlist=['User']).User.id).where(__import__('jobs_catcher.models', fromlist=['User']).User.login == 'admin'))
        sched = UserSchedule(user_id=user_id, interval_days=1, run_time='09:30', timezone='Europe/Moscow', sources_json='["hh"]', next_run_at=datetime(2026,7,8,6,30,tzinfo=timezone.utc), enabled=True)
        db.add(sched); db.commit()
    assert schedule_due_jobs(SessionLocal, settings, now=datetime(2026,7,8,6,31,tzinfo=timezone.utc)) == 1
    assert schedule_due_jobs(SessionLocal, settings, now=datetime(2026,7,8,6,35,tzinfo=timezone.utc)) == 0
    with SessionLocal() as db:
        nxt = db.scalar(select(UserSchedule.next_run_at))
    assert nxt == datetime(2026,7,9,6,30,tzinfo=timezone.utc)


@pytest.mark.parametrize('interval,now,expected', [
    (1, datetime(2026,7,8,6,0,tzinfo=timezone.utc), datetime(2026,7,8,6,30,tzinfo=timezone.utc)),
    (2, datetime(2026,7,8,7,0,tzinfo=timezone.utc), datetime(2026,7,10,6,30,tzinfo=timezone.utc)),
    (7, datetime(2026,7,8,7,0,tzinfo=timezone.utc), datetime(2026,7,15,6,30,tzinfo=timezone.utc)),
])
def test_run_time_timezone_and_interval_compute_next_utc(interval, now, expected):
    assert compute_next_run_at(interval, '09:30', 'Europe/Moscow', now=now) == expected


def test_browser_forms_include_csrf_and_submit_without_manual_header(tmp_path):
    settings = st(tmp_path); app = create_app(settings=settings); c = TestClient(app)
    r = c.post('/login', data={'login':'admin','password':'admin'}, follow_redirects=False)
    assert r.status_code == 303
    page = c.get('/change-password')
    assert 'name="csrf"' in page.text
    token = c.cookies.get('csrf')
    assert c.post('/change-password', data={'password':'admin browser pass 42','csrf':token}, follow_redirects=False).status_code == 303
    assert c.get('/resume').status_code == 200 and 'name="csrf"' in c.get('/resume').text
    assert c.get('/onboarding').status_code == 200 and 'desired_titles' in c.get('/onboarding').text
    assert c.get('/criteria').status_code == 200
    assert c.get('/schedule').status_code == 200
    assert c.get('/admin/settings').status_code == 200


@pytest.mark.parametrize('source,cls', sorted(ADAPTERS.items()))
def test_each_production_adapter_parses_own_fixture(source, cls, tmp_path):
    settings = st(tmp_path)
    adapter = cls(settings)
    fixture_dir = Path('tests/fixtures/sources')
    rows = adapter.parse_search_page((fixture_dir / f'{source}_search.html').read_text(encoding='utf-8'))
    assert rows and all(isinstance(r, VacancyResult) for r in rows)
    detail = adapter.parse_detail_page((fixture_dir / f'{source}_detail.html').read_text(encoding='utf-8'), rows[0])
    normalized = adapter.normalize(detail)
    for key in ['source','external_id','title','company','location','work_format','employment_type','salary','published_at','updated_at','description','requirements','responsibilities','conditions','skills','source_url','canonical_url','content_hash']:
        assert key in normalized


def test_malformed_nested_criteria_is_rejected():
    bad = json.loads(json.dumps(criteria.DEFAULT_CRITERIA))
    bad['scoring']['positive_rules'] = [{'name': 'broken', 'weight': -1, 'any_terms': 'not-list'}]
    with pytest.raises(ValueError):
        criteria.validate_criteria(bad)
    bad2 = json.loads(json.dumps(criteria.DEFAULT_CRITERIA)); bad2['scoring']['decision_thresholds'] = [{'decision':'Откликаться','min_score':16},{'decision':'Откликаться','min_score':12},{'decision':'Мимо','min_score':0}]
    with pytest.raises(ValueError):
        criteria.validate_criteria(bad2)


def test_cover_letter_shortening_second_attempt():
    first = {'text': 'x' * 350}
    with pytest.raises(ValueError):
        validate_cover_letter_result(first)
    second = {'text': 'Коротко: мой подтвержденный опыт поможет быстро принести пользу вашей команде.'}
    assert len(validate_cover_letter_result(second)['text']) <= 300


def test_admin_settings_persist_and_apply(tmp_path):
    settings = st(tmp_path); app = create_app(settings=settings); c = TestClient(app)
    csrf = login(c,'admin','admin')
    csrf = c.cookies.get('csrf')
    c.post('/change-password', data={'password':'admin settings pass 42','csrf':csrf}, follow_redirects=False)
    csrf = c.cookies.get('csrf')
    r = c.post('/admin/settings', data={'enabled_sources':'hh,habr','min_schedule_interval_days':'2','max_results_per_source':'3','csrf':csrf})
    assert r.status_code == 200
    engine = make_engine(settings.database_url); SessionLocal = make_session_factory(engine)
    with SessionLocal() as db:
        assert db.scalar(select(AppSetting).where(AppSetting.key == 'enabled_sources')).value_json == '["hh", "habr"]'


class ManyResultsAdapter:
    def __init__(self, source):
        self.source = source
    def search(self, query, preferences):
        return [VacancyResult(source=self.source, external_id=f'{query}-{idx}', title=f'Warehouse Manager {idx}', url=f'https://example.test/{self.source}/{query}/{idx}') for idx in range(5)]
    def fetch_details(self, result):
        result.company = 'LimitCo'; result.location = 'Москва'; result.description = 'warehouse inventory manager operations'
        return result
    def normalize(self, raw):
        return {'source':raw.source,'external_id':raw.external_id,'title':raw.title,'company':raw.company,'location':raw.location,'source_url':raw.url,'canonical_url':raw.url,'description':raw.description,'requirements':'inventory','responsibilities':'operations','conditions':'','skills':['inventory'],'raw_metadata':{},'content_hash':raw.external_id}

class CountingRunner:
    def __init__(self):
        self.scenarios = []
    def run(self, scenario, prompt, validator, run_dir):
        self.scenarios.append(scenario)
        if scenario == 'vacancy_evaluation':
            data = json.loads(prompt.split('VACANCY=',1)[1].split('\nDETERMINISTIC=',1)[0])
            return validator({'vacancy_id':str(data['id']),'score':16,'decision':'Откликаться','confidence':'high','role_summary':data['title'],'matching_signals':['inventory'],'missing_signals':[],'red_flags':[],'applied_caps':[],'why_fits':'fits','why_not_or_risks':'','what_to_check_before_apply':[],'resume_angle':['inventory'],'cover_letter_points':['value'],'prescore_comment':'ok'})
        raise AssertionError(scenario)

def test_worker_respects_disabled_sources_and_global_limits(tmp_path):
    settings = Settings(**{**st(tmp_path).__dict__, 'enabled_sources':('hh',), 'max_results_per_source':2, 'max_vacancies_per_run':3, 'max_llm_candidates':5, 'codex_batch_size':1})
    create_app(settings=settings)
    engine = make_engine(settings.database_url); SessionLocal = make_session_factory(engine)
    crit = json.loads(json.dumps(criteria.DEFAULT_CRITERIA)); crit['search']['queries']=['warehouse','operations']; crit['scoring']['positive_rules']=[{'name':'inventory','weight':16,'any_terms':['warehouse','inventory']}]
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == 'admin'))
        profile = ProfileVersion(user_id=user.id, version=1, data_json=json.dumps({'professional_title':'Warehouse Manager'}), confirmed=True); db.add(profile); db.flush()
        db.add(CriteriaVersion(user_id=user.id, profile_version_id=profile.id, version=1, data_json=json.dumps(crit)))
        db.add(UserSchedule(user_id=user.id, interval_days=1, run_time='09:00', timezone='Europe/Moscow', sources_json='["hh","habr"]', next_run_at=datetime(2026,7,8,6,0,tzinfo=timezone.utc), enabled=True))
        db.add(BackgroundJob(user_id=user.id, type='scheduled_search', status='queued', payload_json='{}', active_key='admin:scheduled_search'))
        db.commit()
    runner = CountingRunner()
    def factory(source):
        assert source == 'hh'
        return ManyResultsAdapter(source)
    assert process_one(SessionLocal, settings, runner=runner, adapter_factory=factory)
    with SessionLocal() as db:
        assert db.scalar(select(VacancySource).where(VacancySource.source == 'habr')) is None
        assert len(db.scalars(select(VacancyScore)).all()) == 2
    assert runner.scenarios.count('vacancy_evaluation') <= 1

class ShorteningRunner:
    def __init__(self):
        self.scenarios = []
    def run(self, scenario, prompt, validator, run_dir):
        self.scenarios.append(scenario)
        if scenario == 'cover_letter':
            return validator({'text': 'x' * 350})
        if scenario == 'cover_letter_shorten':
            assert 'сократи' in prompt.lower()
            return validator({'text': 'Коротко: мой опыт поможет быстро принести пользу вашей команде.'})
        raise AssertionError(scenario)

def test_cover_letter_uses_dedicated_shortening_retry(tmp_path):
    settings = st(tmp_path); create_app(settings=settings)
    engine = make_engine(settings.database_url); SessionLocal = make_session_factory(engine)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == 'admin'))
        profile = ProfileVersion(user_id=user.id, version=1, data_json=json.dumps({'professional_title':'Ops'}), confirmed=True); db.add(profile); db.flush()
        run = SearchRun(user_id=user.id, status='completed'); db.add(run); db.flush()
        vacancy = Vacancy(normalized_title='ops', normalized_company='acme', normalized_location='', title='Ops', company='ACME', location='', description='inventory'); db.add(vacancy); db.flush()
        db.add(VacancyScore(user_id=user.id, run_id=run.id, vacancy_id=vacancy.id, profile_version_id=profile.id, prescore=16, final_score=16, decision='Откликаться', signals_json='{}', recommendations_json='{}'))
        db.add(BackgroundJob(user_id=user.id, type='generate_cover_letter', status='queued', payload_json=json.dumps({'vacancy_id': vacancy.id})))
        db.commit()
    runner = ShorteningRunner()
    assert process_one(SessionLocal, settings, runner=runner)
    assert runner.scenarios == ['cover_letter', 'cover_letter_shorten']
    with SessionLocal() as db:
        letter = db.scalar(select(CoverLetter))
        assert letter and len(letter.text) <= 300

def test_production_startup_without_alembic_migration_is_controlled_error(tmp_path):
    settings = Settings(**{**st(tmp_path).__dict__, 'environment':'production'})
    with pytest.raises(RuntimeError, match='migrat'):
        create_app(settings=settings)
