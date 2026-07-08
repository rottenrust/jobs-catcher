from __future__ import annotations

import io, json, zipfile
from pathlib import Path
from fastapi.testclient import TestClient
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from jobs_catcher.settings import Settings
from jobs_catcher.web import create_app
from jobs_catcher.db import make_engine
from jobs_catcher.models import BackgroundJob, CoverLetter, CriteriaVersion, ResumeFile, UserSchedule, UserSession, VacancyScore, VacancyUIState
from jobs_catcher.worker import DeterministicMockCodexRunner, process_one, schedule_due_jobs, session_factory
from jobs_catcher.source_adapters.base import VacancyResult
from jobs_catcher import scoring

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

def make_docx(text="Warehouse operations inventory manager"):
    bio=io.BytesIO()
    with zipfile.ZipFile(bio,"w") as z:
        z.writestr("word/document.xml", f"<w:document><w:t>{text}</w:t></w:document>")
    return bio.getvalue()

def settings(tmp_path):
    data=tmp_path/'data'; uploads=data/'uploads'; runs=data/'runs'
    return Settings(database_url=f"sqlite:///{tmp_path/'app.sqlite3'}", data_dir=data, upload_dir=uploads, run_dir=runs, allowed_hosts=("testserver",), codex_bin="codex", environment="development")

def login(client, login, password):
    r=client.post('/login', data={'login':login,'password':password}, follow_redirects=False)
    assert r.status_code == 303
    return client.cookies.get('csrf')

def change_password(client, csrf, password):
    r=client.post('/change-password', data={'password':password}, headers={'x-csrf-token':csrf}, follow_redirects=False)
    assert r.status_code == 303
    return client.cookies.get('csrf')

class FixtureAdapter:
    def __init__(self, source): self.source=source
    def search(self, query, preferences):
        if self.source == 'superjob':
            raise RuntimeError('blocked fixture')
        return [VacancyResult(source=self.source, external_id=f'{self.source}-1', title='Warehouse Operations Manager', url=f'https://example.test/{self.source}/1')]
    def fetch_details(self, result):
        result.company='LogiCo'; result.location='Москва'; result.description='Warehouse inventory manager process improvement team leadership operations'
        return result
    def normalize(self, raw):
        return {'source':raw.source,'external_id':raw.external_id,'title':raw.title,'company':raw.company,'location':raw.location,'source_url':raw.url,'canonical_url':raw.url,'description':raw.description,'requirements':'inventory leadership','responsibilities':'warehouse operations','conditions':'','skills':['inventory','operations'],'raw_metadata':{},'content_hash':'same-cross-source-duplicate'}

def adapter_factory(source): return FixtureAdapter(source)

def test_alembic_empty_db_repeat_and_downgrade_upgrade(tmp_path):
    db=tmp_path/'alembic.sqlite3'
    cfg=Config('alembic.ini'); cfg.set_main_option('sqlalchemy.url', f'sqlite:///{db}')
    command.upgrade(cfg, 'head')
    command.upgrade(cfg, 'head')
    engine=make_engine(f'sqlite:///{db}')
    with engine.connect() as c:
        tables={r[0] for r in c.exec_driver_sql("select name from sqlite_master where type='table'")}
    assert {'users','user_sessions','background_jobs','vacancy_scores','audit_log'} <= tables
    command.downgrade(cfg, 'base')
    command.upgrade(cfg, 'head')

def test_app_restart_persistence_admin_password_and_deleted_session(tmp_path):
    st=settings(tmp_path); app=create_app(settings=st); c=TestClient(app)
    csrf=login(c,'admin','admin'); csrf=change_password(c, csrf, 'admin persistent pass 42')
    r=c.post('/admin/users', data={'login':'alice','password':'alice temporary pass 42'}, headers={'x-csrf-token':csrf}); uid=r.json()['id']
    alice=TestClient(app); acsrf=login(alice,'alice','alice temporary pass 42'); acsrf=change_password(alice, acsrf, 'alice persistent pass 42')
    app2=create_app(settings=st); c2=TestClient(app2)
    assert c2.post('/login', data={'login':'admin','password':'admin'}).status_code == 401
    csrf2=login(c2,'admin','admin persistent pass 42')
    assert c2.delete(f'/admin/users/{uid}', headers={'x-csrf-token':csrf2}).status_code == 200
    assert alice.get('/dashboard').status_code == 401
    assert TestClient(app2).post('/login', data={'login':'alice','password':'alice persistent pass 42'}).status_code == 401

def test_fixture_e2e_persistence_worker_restart_non_ai_criteria(tmp_path):
    st=settings(tmp_path); app=create_app(settings=st); c=TestClient(app)
    csrf=login(c,'admin','admin'); csrf=change_password(c, csrf, 'admin persistent pass 42')
    uid=c.post('/admin/users', data={'login':'ops','password':'ops temporary pass 42'}, headers={'x-csrf-token':csrf}).json()['id']
    user=TestClient(app); ucsrf=login(user,'ops','ops temporary pass 42'); ucsrf=change_password(user, ucsrf, 'ops persistent pass 42')
    upload=user.post('/resume', files={'file':('ops.docx', make_docx(), DOCX_MIME)}, headers={'x-csrf-token':ucsrf}).json()
    assert Path(st.upload_dir / upload['stored']).exists()
    SessionLocal=session_factory(st); runner=DeterministicMockCodexRunner()
    assert process_one(SessionLocal, st, runner=runner)
    onboarding={'desired_titles':'Warehouse Operations Manager','directions':'operations, inventory','cities':'Москва','work_format':'office','seniority':'middle','must_have':'inventory, process improvement','stop_factors':'night shifts'}
    assert user.post('/onboarding', data=onboarding, headers={'x-csrf-token':ucsrf}).status_code == 200
    assert user.post('/profile/confirm', headers={'x-csrf-token':ucsrf}).status_code == 200
    assert process_one(SessionLocal, st, runner=runner)
    with SessionLocal() as db:
        crit=json.loads(db.scalar(select(CriteriaVersion).where(CriteriaVersion.user_id==uid).order_by(CriteriaVersion.version.desc())).data_json)
    good=scoring.deterministic_prescore({'title':'Warehouse Operations Manager','description':'inventory process improvement team leadership'}, crit)
    bad=scoring.deterministic_prescore({'title':'LLM Engineer','description':'RAG agents API'}, crit)
    assert good['score'] > bad['score']
    assert user.post('/schedule', data={'interval_days':'1','sources':'hh,habr,superjob,rabota,geekjob,getmatch'}, headers={'x-csrf-token':ucsrf}).status_code == 200
    with SessionLocal() as db:
        due_at = db.scalar(select(UserSchedule.next_run_at).where(UserSchedule.user_id == uid))
    assert schedule_due_jobs(SessionLocal, st) == 0
    assert schedule_due_jobs(SessionLocal, st, now=due_at) == 1
    # Simulate worker restart: new SessionLocal and same DB still see queued job.
    SessionLocal2=session_factory(st)
    with SessionLocal2() as db:
        assert db.scalar(select(BackgroundJob).where(BackgroundJob.type=='scheduled_search')).status == 'queued'
    assert process_one(SessionLocal2, st, runner=runner, adapter_factory=adapter_factory)
    with SessionLocal2() as db:
        scores=db.scalars(select(VacancyScore).where(VacancyScore.user_id==uid)).all()
        assert len(scores) >= 1
        assert all(s.criteria_version_id for s in scores)
    html=user.get('/vacancies').text
    assert 'Warehouse Operations Manager' in html and 'LLM Engineer' not in html
    first_id=scores[0].vacancy_id
    assert user.get(f'/vacancies/{first_id}').status_code == 200
    app_restart=create_app(settings=st); after=TestClient(app_restart); ucsrf=login(after,'ops','ops persistent pass 42')
    assert after.get(f'/vacancies/{first_id}').status_code == 200
    with SessionLocal2() as db:
        assert db.scalar(select(VacancyUIState).where(VacancyUIState.user_id==uid, VacancyUIState.vacancy_id==first_id)).viewed_at is not None
    exported=after.get('/export').text
    assert 'Warehouse Operations Manager' in exported
    after.post(f'/vacancies/{first_id}/letter', headers={'x-csrf-token':ucsrf}).json()['job_id']
    assert process_one(SessionLocal2, st, runner=runner)
    with SessionLocal2() as db:
        letter=db.scalar(select(CoverLetter).where(CoverLetter.user_id==uid, CoverLetter.vacancy_id==first_id))
        assert letter and len(letter.text) <= 300
        admin_audit=after.get('/admin/audit')
        assert admin_audit.status_code == 403
    admin=TestClient(app_restart); acsrf=login(admin,'admin','admin persistent pass 42')
    assert admin.get('/admin/jobs').status_code == 200
    assert admin.get('/admin/runs').status_code == 200
    assert admin.get('/admin/source-health').status_code == 200
    assert admin.delete(f'/admin/users/{uid}', headers={'x-csrf-token':acsrf}).status_code == 200
    with SessionLocal2() as db:
        assert not db.scalars(select(ResumeFile).where(ResumeFile.user_id==uid)).all()
        assert not db.scalars(select(UserSession).where(UserSession.user_id==uid)).all()
