from __future__ import annotations
from fastapi.testclient import TestClient
from jobs_catcher.web import create_app, Store

def login(client, login, password):
    r=client.post('/login', data={'login':login,'password':password}, follow_redirects=False)
    assert r.status_code == 303
    return client.cookies.get('csrf'), client.cookies.get('session')

def setup_users():
    store=Store(); app=create_app(store); admin=TestClient(app)
    csrf, old=login(admin,'admin','admin')
    admin.post('/change-password', data={'password':'admin strong password 42'}, headers={'x-csrf-token':csrf}, follow_redirects=False)
    assert admin.cookies.get('session') != old
    csrf=admin.cookies.get('csrf')
    admin.post('/admin/users', data={'login':'alice','password':'alice temporary 42'}, headers={'x-csrf-token':csrf})
    user=TestClient(app); ucsrf,_=login(user,'alice','alice temporary 42')
    return store, app, admin, csrf, user, ucsrf

def test_auth_matrix_unauth_non_admin_deleted_and_logout_invalidation():
    store, app, admin, acsrf, user, ucsrf = setup_users()
    anon=TestClient(app)
    for path in ['/dashboard','/vacancies','/export','/admin/audit']:
        assert anon.get(path).status_code == 401
    for path in ['/signup','/register','/users/new']:
        assert anon.get(path).status_code == 404
    assert user.get('/admin/audit').status_code == 403
    assert user.post('/admin/users', data={'login':'mallory','password':'mallory strong 42'}, headers={'x-csrf-token':ucsrf}).status_code == 403
    assert user.post('/change-password', data={'password':'alice strong password 42'}, headers={'x-csrf-token':ucsrf}, follow_redirects=False).status_code == 303
    ucsrf=user.cookies.get('csrf')
    assert user.post('/logout', headers={'x-csrf-token':ucsrf}, follow_redirects=False).status_code == 303
    assert user.get('/dashboard').status_code == 401
    ucsrf,_=login(user,'alice','alice strong password 42')
    assert admin.delete('/admin/users/2').status_code == 403
    assert admin.delete('/admin/users/2', headers={'x-csrf-token':acsrf}).status_code == 200
    assert user.get('/dashboard').status_code == 401
    assert TestClient(app).post('/login', data={'login':'alice','password':'alice strong password 42'}).status_code == 401

def test_csrf_matrix_rate_limit_and_secure_cookie_in_production():
    prod=create_app(Store(), production=True); pc=TestClient(prod)
    r=pc.post('/login', data={'login':'admin','password':'admin'}, follow_redirects=False)
    assert 'secure' in r.headers['set-cookie'].lower()
    store, app, admin, acsrf, user, ucsrf = setup_users()
    old_session=user.cookies.get('session')
    ucsrf2,new_session=login(user,'alice','alice temporary 42')
    assert new_session != old_session
    for path, data in [('/change-password', {'password':'alice strong password 42'}), ('/schedule', {'interval_days':'1'}), ('/logout', {})]:
        assert user.post(path, data=data).status_code == 403
    assert admin.delete('/admin/users/2').status_code == 403
    bad=TestClient(app)
    for i in range(5): bad.post('/login', data={'login':'nobody','password':'bad'})
    assert bad.post('/login', data={'login':'nobody','password':'bad'}).status_code == 429
    other=TestClient(app)
    assert other.post('/login', data={'login':'someone_else','password':'bad'}).status_code == 401

def test_upload_extract_errors_are_client_errors():
    _store, _app, _admin, _acsrf, user, ucsrf = setup_users()
    assert user.post('/change-password', data={'password':'alice strong password 42'}, headers={'x-csrf-token':ucsrf}, follow_redirects=False).status_code == 303
    ucsrf=user.cookies.get('csrf')
    r=user.post('/resume', files={'file':('resume.pdf', b'%PDF-1.4\nno text layer\n%%EOF', 'application/pdf')}, headers={'x-csrf-token':ucsrf})
    assert r.status_code == 400
    r=user.post('/criteria', content='{}', headers={'x-csrf-token':ucsrf})
    assert r.status_code == 400
