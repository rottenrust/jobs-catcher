from __future__ import annotations
import io, zipfile
from fastapi.testclient import TestClient
from jobs_catcher.web import create_app, Store

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

def make_docx(text="Resume AI integrations"):
    bio=io.BytesIO()
    with zipfile.ZipFile(bio,"w") as z:
        z.writestr("word/document.xml", f"<w:document><w:t>{text}</w:t></w:document>")
    return bio.getvalue()

def login(client, login, password):
    r=client.post("/login", data={"login":login,"password":password}, follow_redirects=False)
    assert r.status_code == 303
    return client.cookies.get("csrf")

def test_full_closed_multi_user_flow_and_isolation():
    store=Store(); app=create_app(store); c=TestClient(app)
    csrf=login(c,"admin","admin")
    assert c.post("/change-password", data={"password":"admin is now strong 42"}, headers={"x-csrf-token":csrf}, follow_redirects=False).status_code == 303
    csrf=c.cookies.get("csrf")
    r=c.post("/admin/users", data={"login":"alice","password":"temporary strong 42","display_name":"Alice"}, headers={"x-csrf-token":csrf})
    uid=r.json()["id"]
    r2=c.post("/admin/users", data={"login":"bob","password":"temporary strong 43"}, headers={"x-csrf-token":csrf})
    bob=r2.json()["id"]
    assert c.get("/signup").status_code == 404

    alice=TestClient(app); csrf=login(alice,"alice","temporary strong 42")
    assert alice.post("/resume", files={"file":("cv.docx", make_docx(), DOCX_MIME)}, headers={"x-csrf-token":csrf}).status_code == 403
    assert alice.post("/change-password", data={"password":"alice strong password 42"}, headers={"x-csrf-token":csrf}, follow_redirects=False).status_code == 303
    csrf=alice.cookies.get("csrf")
    assert alice.post("/resume", files={"file":("cv.docx", make_docx(), DOCX_MIME)}, headers={"x-csrf-token":csrf}).status_code == 200
    assert alice.post("/onboarding", data={"desired_titles":"AI Solution Analyst","locations":"Москва","remote":"true"}, headers={"x-csrf-token":csrf}).status_code == 200
    assert alice.post("/profile/confirm", headers={"x-csrf-token":csrf}).json()["criteria_version"] == 1
    bad=alice.post("/schedule", data={"interval_days":"0"}, headers={"x-csrf-token":csrf})
    assert bad.status_code >= 400
    assert alice.post("/schedule", data={"interval_days":"1","sources":"hh,habr,superjob"}, headers={"x-csrf-token":csrf}).status_code == 200
    run=alice.post("/worker/run-fixtures", headers={"x-csrf-token":csrf}).json()
    vid=run["vacancies"][0]
    html=alice.get("/vacancies").text
    assert "Откликаться" in html and "Мимо" in html
    assert alice.get(f"/vacancies/{vid}").status_code == 200
    assert (uid, vid) in store.viewed
    exported=alice.get("/export").text
    assert "ОТКЛИКАТЬСЯ" in exported and "https://e/1" in exported and "Resume AI" not in exported
    letter=alice.post(f"/vacancies/{vid}/letter", headers={"x-csrf-token":csrf}).json()
    assert letter["length"] <= 300

    bobc=TestClient(app); bcsrf=login(bobc,"bob","temporary strong 43")
    assert bobc.get("/dashboard").status_code == 403
    assert bobc.post("/change-password", data={"password":"bob strong password 43"}, headers={"x-csrf-token":bcsrf}, follow_redirects=False).status_code == 303
    bcsrf=bobc.cookies.get("csrf")
    assert bobc.get(f"/vacancies/{vid}").status_code == 404
    assert bobc.post(f"/vacancies/{vid}/letter", headers={"x-csrf-token":bcsrf}).status_code == 404
    admin=TestClient(app); csrf=login(admin,"admin","admin is now strong 42")
    audit=admin.get("/admin/audit").json()
    actions={e["action"] for e in audit}
    assert {"login","user_created","resume_uploaded","profile_confirmed","criteria_changed","schedule_changed","search_completed","letter_generated"} <= actions
    assert admin.delete(f"/admin/users/{uid}", headers={"x-csrf-token":csrf}).status_code == 200
    assert uid not in store.resumes

def test_csrf_required_for_mutating_routes_and_cookie_flags():
    app=create_app(Store()); c=TestClient(app)
    r=c.post("/login", data={"login":"admin","password":"admin"}, follow_redirects=False)
    assert "httponly" in r.headers["set-cookie"].lower()
    assert "samesite=lax" in r.headers["set-cookie"].lower()
    assert c.post("/change-password", data={"password":"admin is now strong 42"}).status_code == 403
