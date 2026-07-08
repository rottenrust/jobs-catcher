from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from jobs_catcher import criteria
from jobs_catcher.codex_integration import CoverLetterTooLong, validate_cover_letter_result
from jobs_catcher.db import make_engine, make_session_factory
from jobs_catcher.models import BackgroundJob, CoverLetter, CriteriaVersion, ProfileVersion, SearchRun, User, UserSchedule, Vacancy, VacancyScore, VacancySource
from jobs_catcher.settings import Settings
from jobs_catcher.source_adapters import ADAPTERS
from jobs_catcher.source_adapters.base import VacancyResult
from jobs_catcher.web import create_app
from jobs_catcher.worker import _upsert_vacancy, process_one

FIX = Path('tests/fixtures/sources')


def st(tmp_path, **overrides):
    base = Settings(database_url=f"sqlite:///{tmp_path/'app.sqlite3'}", data_dir=tmp_path/'data', upload_dir=tmp_path/'data/uploads', run_dir=tmp_path/'data/runs', allowed_hosts=("testserver",), codex_bin="python3")
    return Settings(**{**base.__dict__, **overrides})


def login_changed(client):
    assert client.post('/login', data={'login':'admin','password':'admin'}, follow_redirects=False).status_code == 303
    csrf = client.cookies.get('csrf')
    assert client.post('/change-password', data={'password':'admin review3 pass 42','csrf':csrf}, follow_redirects=False).status_code == 303
    return client.cookies.get('csrf')


@pytest.mark.parametrize('source,cls', sorted(ADAPTERS.items()))
def test_review3_adapter_source_specific_nonempty_fields_and_urls(source, cls, tmp_path):
    adapter = cls(st(tmp_path))
    url = adapter.build_search_url('Product Manager', {'locations':['Москва'], 'remote': True}, page=2)
    assert adapter.base_url in url
    assert parse_qs(urlparse(url).query)
    assert source in adapter.__class__.__module__
    rows = adapter.parse_search_page((FIX / f'{source}_search.html').read_text(encoding='utf-8'))
    assert rows and rows[0].external_id
    detail = adapter.parse_detail_page((FIX / f'{source}_detail.html').read_text(encoding='utf-8'), rows[0])
    normalized = adapter.normalize(detail)
    assert normalized['source'] == source
    assert normalized['external_id']
    assert normalized['canonical_url'].startswith('http')
    assert normalized['company'] == f'ACME {source}'
    assert normalized['salary']
    assert normalized['work_format']
    assert normalized['employment_type']
    assert normalized['published_at']
    assert normalized['requirements']
    assert normalized['responsibilities']
    assert normalized['conditions']
    assert normalized['skills']


class FakeResponse:
    status_code = 200
    text = '<html>ok</html>'
    def raise_for_status(self):
        return None

class FakeClient:
    def __init__(self):
        self.urls = []
    def get(self, url):
        self.urls.append(url)
        return FakeResponse()


def test_review3_delay_jitter_before_every_http_request(tmp_path):
    sleeps = []
    client = FakeClient()
    adapter = ADAPTERS['hh'](st(tmp_path, http_delay_seconds=1.5, http_jitter_seconds=0.25), client=client, sleeper=sleeps.append, random_func=lambda: 0.4)
    adapter._fetch('https://hh.ru/one')
    adapter._fetch('https://hh.ru/two')
    assert sleeps == [1.6, 1.6]
    assert client.urls == ['https://hh.ru/one', 'https://hh.ru/two']


def test_review3_normalized_vacancy_fields_survive_db_roundtrip(tmp_path):
    settings = st(tmp_path); create_app(settings=settings)
    engine = make_engine(settings.database_url); SessionLocal = make_session_factory(engine)
    item = {'source':'hh','external_id':'rich-1','title':'Ops Lead','company':'ACME','location':'Москва','work_format':'remote','employment_type':'full-time','salary':{'from':100000,'to':150000,'currency':'RUB','gross':True},'published_at':'2026-07-01','updated_at':'2026-07-02','source_url':'https://hh.ru/vacancy/rich-1','canonical_url':'https://hh.ru/vacancy/rich-1','description':'ops inventory','requirements':'inventory','responsibilities':'lead ops','conditions':'remote','skills':['inventory','leadership'],'raw_metadata':{'x':1},'content_hash':'richhash'}
    with SessionLocal() as db:
        vac = _upsert_vacancy(db, item)
        db.add(VacancySource(vacancy_id=vac.id, source='hh', external_id='rich-1', source_url=item['source_url'], raw_json=json.dumps(item)))
        db.commit()
    with SessionLocal() as db:
        vac = db.scalar(select(Vacancy).where(Vacancy.content_hash == 'richhash'))
        raw = json.loads(db.scalar(select(VacancySource.raw_json)).strip())
        assert vac.work_format == 'remote'
        assert vac.employment_type == 'full-time'
        assert json.loads(vac.salary_json)['from'] == 100000
        assert vac.published_at == '2026-07-01'
        assert 'inventory' in json.loads(vac.skills_json)
        assert raw['requirements'] == 'inventory'


def test_review3_criteria_textarea_get_post_roundtrip(tmp_path):
    app = create_app(settings=st(tmp_path)); c = TestClient(app); csrf = login_changed(c)
    page = c.get('/criteria')
    assert page.status_code == 200
    match = re.search(r'<textarea[^>]*name="criteria"[^>]*>(.*?)</textarea>', page.text, re.S)
    assert match
    text = match.group(1)
    assert '&quot;' not in text
    r = c.post('/criteria', data={'csrf': csrf, 'criteria': text})
    assert r.status_code == 200


def test_review3_profile_edit_creates_new_version_and_confirm(tmp_path):
    settings = st(tmp_path); app = create_app(settings=settings); c = TestClient(app); csrf = login_changed(c)
    profile = {'professional_title':'Old','skills':['ops'],'facts_for_applications':[]}
    engine = make_engine(settings.database_url); SessionLocal = make_session_factory(engine)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == 'admin'))
        db.add(ProfileVersion(user_id=user.id, version=1, data_json=json.dumps(profile), confirmed=False)); db.commit()
    edited = json.dumps({'professional_title':'New Ops Lead','skills':['ops','inventory'],'facts_for_applications':['saved']})
    r = c.post('/profile', data={'csrf': csrf, 'profile': edited}, follow_redirects=False)
    assert r.status_code == 303
    r = c.post('/profile/confirm', data={'csrf': c.cookies.get('csrf')})
    assert r.status_code == 200
    with SessionLocal() as db:
        versions = db.scalars(select(ProfileVersion).order_by(ProfileVersion.version)).all()
        assert [v.version for v in versions] == [1, 2]
        assert json.loads(versions[-1].data_json)['professional_title'] == 'New Ops Lead'
        assert versions[-1].confirmed is True


def test_review3_admin_user_management_ui_create_delete(tmp_path):
    app = create_app(settings=st(tmp_path)); c = TestClient(app); csrf = login_changed(c)
    page = c.get('/admin/users')
    assert page.status_code == 200 and 'name="login"' in page.text
    r = c.post('/admin/users', data={'csrf': csrf, 'login':'alice','password':'alice strong pass 42','display_name':'Alice'}, follow_redirects=False)
    assert r.status_code in {200, 303}
    page = c.get('/admin/users')
    assert 'alice' in page.text
    uid = re.search(r'data-user-id="(\d+)"[^>]*>alice', page.text).group(1)
    csrf = c.cookies.get('csrf')
    assert c.post(f'/admin/users/{uid}/delete', data={'csrf': csrf}, follow_redirects=False).status_code in {200, 303}
    assert 'alice' not in c.get('/admin/users').text


def test_review3_letter_visible_on_vacancy_page_with_copy_button(tmp_path):
    settings = st(tmp_path); app = create_app(settings=settings); c = TestClient(app); login_changed(c)
    engine = make_engine(settings.database_url); SessionLocal = make_session_factory(engine)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == 'admin'))
        run = SearchRun(user_id=user.id, status='completed'); db.add(run); db.flush()
        vac = Vacancy(normalized_title='ops', normalized_company='acme', normalized_location='', title='Ops', company='ACME', location='', description='inventory'); db.add(vac); db.flush()
        db.add(VacancyScore(user_id=user.id, run_id=run.id, vacancy_id=vac.id, prescore=16, final_score=16, decision='Откликаться', signals_json='{}', recommendations_json='{}'))
        db.add(CoverLetter(user_id=user.id, vacancy_id=vac.id, version=1, text='Готовое письмо до 300 символов.'))
        db.commit(); vid = vac.id
    page = c.get(f'/vacancies/{vid}')
    assert 'Готовое письмо' in page.text
    assert 'data-copy-target="cover-letter"' in page.text


def test_review3_effective_settings_apply_to_schedule_immediately(tmp_path):
    settings = st(tmp_path); app = create_app(settings=settings); c = TestClient(app); csrf = login_changed(c)
    assert c.post('/admin/settings', data={'csrf':csrf,'enabled_sources':'hh','min_schedule_interval_days':'2','max_schedule_interval_days':'10','timezone':'Europe/Moscow','http_delay_seconds':'0','http_jitter_seconds':'0','http_timeout_seconds':'5','http_retries':'1','max_search_queries':'2','max_results_per_source':'3','max_vacancies_per_run':'5','max_llm_candidates':'4','codex_batch_size':'2','codex_bin':'python3','resume_size_limit':'1048576','artifact_retention_days':'7','global_search_enabled':'on'}).status_code == 200
    csrf = c.cookies.get('csrf')
    assert c.post('/schedule', data={'csrf':csrf,'interval_days':'1','sources':'hh,habr','run_time':'09:00','timezone':'Europe/Moscow'}).status_code == 400
    r = c.post('/schedule', data={'csrf':csrf,'interval_days':'2','sources':'hh,habr','run_time':'09:00','timezone':'Europe/Moscow'})
    assert r.status_code == 200 and r.json()['sources'] == ['hh']


class BatchRunner:
    def __init__(self):
        self.ids = []
    def run(self, scenario, prompt, validator, run_dir):
        assert run_dir.exists()
        if scenario == 'vacancy_evaluation':
            data = json.loads(prompt.split('VACANCY=',1)[1].split('\nDETERMINISTIC=',1)[0])
            self.ids.append(data['id'])
            return validator({'vacancy_id':str(data['id']),'score':18,'decision':'Откликаться','confidence':'high','role_summary':'','matching_signals':[],'missing_signals':[],'red_flags':[],'applied_caps':[],'why_fits':'ok','why_not_or_risks':'','what_to_check_before_apply':[],'resume_angle':[],'cover_letter_points':[],'prescore_comment':'ok'})
        raise AssertionError(scenario)

class BatchAdapter:
    def search(self, query, preferences):
        return [VacancyResult(source='hh', external_id=str(i), title=('Other' if i == 0 else f'Ops {i}'), url=f'https://hh.ru/vacancy/{i}') for i in range(26)]
    def fetch_details(self, result):
        result.company='ACME'; result.description=('irrelevant text' if result.external_id == '0' else 'inventory operations full description'); return result
    def normalize(self, raw):
        return {'source':'hh','external_id':raw.external_id,'title':raw.title,'company':'ACME','location':'','source_url':raw.url,'canonical_url':raw.url,'description':raw.description,'requirements':('' if raw.external_id == '0' else 'inventory'),'responsibilities':('' if raw.external_id == '0' else 'ops'),'conditions':'','skills':([] if raw.external_id == '0' else ['inventory']),'raw_metadata':{},'content_hash':raw.external_id}


def test_review3_codex_candidates_processed_in_batches_without_truncating_total(tmp_path):
    settings = st(tmp_path, max_results_per_source=30, max_vacancies_per_run=30, max_llm_candidates=25, codex_batch_size=10)
    create_app(settings=settings); engine = make_engine(settings.database_url); SessionLocal = make_session_factory(engine)
    crit = json.loads(json.dumps(criteria.DEFAULT_CRITERIA)); crit['search']['queries']=['ops']; crit['scoring']['positive_rules']=[{'name':'ops','weight':20,'any_terms':['ops','inventory']}]
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == 'admin'))
        prof = ProfileVersion(user_id=user.id, version=1, data_json=json.dumps({'professional_title':'Ops'}), confirmed=True); db.add(prof); db.flush()
        db.add(CriteriaVersion(user_id=user.id, profile_version_id=prof.id, version=1, data_json=json.dumps(crit)))
        db.add(UserSchedule(user_id=user.id, interval_days=1, sources_json='["hh"]', next_run_at=datetime(2026,7,8,tzinfo=timezone.utc), enabled=True))
        db.add(BackgroundJob(user_id=user.id, type='scheduled_search', status='queued', payload_json='{}'))
        db.commit()
    runner = BatchRunner()
    assert process_one(SessionLocal, settings, runner=runner, adapter_factory=lambda source: BatchAdapter())
    assert len(runner.ids) == 25
    assert (settings.run_dir / '1' / 'llm-input.jsonl').exists()
    line = (settings.run_dir / '1' / 'llm-input.jsonl').read_text(encoding='utf-8').splitlines()[0]
    assert 'profile_version_id' in line and 'criteria_version_id' in line and 'deterministic_signals' in line


def test_review3_codex_runner_creates_run_dir_before_subprocess(tmp_path):
    from jobs_catcher.worker import CodexRunner
    seen = {}
    def fake_run(cmd, **kwargs):
        run_dir = Path(cmd[cmd.index('-C') + 1])
        seen['exists'] = run_dir.exists()
        class P:
            returncode = 0
            stdout = '{"professional_title":"Ops","experience":[],"companies":[],"roles":[],"periods":[],"responsibilities":[],"achievements":[],"projects":[],"skills":[],"technologies":[],"industries":[],"education":[],"languages":[],"strengths":[],"level":"","directions":[],"facts_for_applications":[],"ambiguous":[],"confidence":"high"}'
        return P()
    runner = CodexRunner(st(tmp_path), subprocess_run=fake_run)
    runner.run('profile_extraction', 'prompt', lambda data: data, tmp_path/'runs/job-1')
    assert seen['exists'] is True


def test_review3_shortening_prompt_contains_first_long_answer(tmp_path):
    long = 'x' * 350
    with pytest.raises(CoverLetterTooLong) as exc:
        validate_cover_letter_result({'text': long})
    assert exc.value.text == long


@pytest.mark.parametrize('patch', [
    {'scoring': {'decision_thresholds': [{'decision':'Maybe','min_score':0}]}},
    {'search': {'surprise': True}},
    {'output': {'surprise': True}},
    {'scoring': {'positive_rules': [{'name':'x','weight':1,'any_terms':['x'],'surprise':True}]}},
])
def test_review3_criteria_rejects_unknown_nested_and_decisions(patch):
    payload = json.loads(json.dumps(criteria.DEFAULT_CRITERIA))
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            payload[key].update(value)
        else:
            payload[key] = value
    with pytest.raises(ValueError):
        criteria.validate_criteria(payload)
