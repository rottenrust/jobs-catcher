from __future__ import annotations

import time
from dataclasses import dataclass, field
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, JSONResponse

from . import auth, criteria, documents, export, queue, scoring

@dataclass
class Store:
    users: dict[int, dict] = field(default_factory=dict)
    sessions: dict[str, int] = field(default_factory=dict)
    resumes: dict[int, dict] = field(default_factory=dict)
    profiles: dict[int, dict] = field(default_factory=dict)
    criteria_versions: dict[int, list[dict]] = field(default_factory=dict)
    schedules: dict[int, dict] = field(default_factory=dict)
    vacancies: dict[int, dict] = field(default_factory=dict)
    viewed: set[tuple[int, int]] = field(default_factory=set)
    letters: list[dict] = field(default_factory=list)
    audit: list[dict] = field(default_factory=list)
    jobs: queue.JobQueue = field(default_factory=queue.JobQueue)
    next_user: int = 1
    next_vacancy: int = 1
    limiter: auth.LoginRateLimiter = field(default_factory=auth.LoginRateLimiter)

    def bootstrap(self):
        if not self.users:
            self.users[1] = {"id": 1, "login": "admin", "password_hash": auth.hash_password("admin"), "role": "superuser", "must_change_password": True, "deleted": False, "display_name": "Admin"}
            self.next_user = 2


def create_app(store: Store | None = None, *, production: bool = False) -> FastAPI:
    store = store or Store(); store.bootstrap()
    app = FastAPI(title="Jobs Catcher")
    app.state.store = store

    def audit(action, actor_id=None, target_user_id=None, **meta):
        store.audit.append({"action": action, "actor_id": actor_id, "target_user_id": target_user_id, "meta": meta})

    def current_user(request: Request):
        token = request.cookies.get("session")
        uid = store.sessions.get(auth.hash_token(token or ""))
        if not uid: raise HTTPException(401)
        user = store.users.get(uid)
        if not user or user.get("deleted"):
            if token: store.sessions.pop(auth.hash_token(token), None)
            raise HTTPException(401)
        if user.get("must_change_password") and request.url.path not in {"/change-password", "/logout"}:
            raise HTTPException(403, "password change required")
        return user, token

    def require_csrf(request: Request, token: str):
        value = request.headers.get("x-csrf-token") or request.query_params.get("csrf")
        if not auth.verify_csrf(token, value or ""):
            raise HTTPException(403, "CSRF")

    def require_admin(request: Request):
        user, token = current_user(request)
        if user["role"] != "superuser": raise HTTPException(403)
        return user, token

    @app.middleware("http")
    async def security_headers(request, call_next):
        resp = await call_next(request)
        resp.headers["x-content-type-options"] = "nosniff"
        resp.headers["x-frame-options"] = "DENY"
        resp.headers["referrer-policy"] = "same-origin"
        return resp

    @app.get("/health/live")
    def live(): return {"status": "ok"}

    @app.get("/health/ready")
    def ready(): return {"status": "ready", "db": True}

    @app.get("/signup")
    def signup(): raise HTTPException(404)

    @app.post("/login")
    def login(login: str = Form(...), password: str = Form(...)):
        now = int(time.time())
        if store.limiter.is_blocked(login, now): raise HTTPException(429)
        user = next((u for u in store.users.values() if u["login"] == login and not u.get("deleted")), None)
        if not user or not auth.verify_password(user["password_hash"], password):
            store.limiter.record_failure(login, now); audit("login_failed", None, None, login=login); raise HTTPException(401)
        token, session = auth.new_session(user["id"]); store.sessions[session.token_hash] = user["id"]
        audit("login", user["id"], user["id"])
        target = "/change-password" if user["must_change_password"] else "/dashboard"
        resp = RedirectResponse(target, status_code=303)
        resp.set_cookie("session", token, httponly=True, samesite="lax", secure=production)
        resp.set_cookie("csrf", auth.csrf_token(token), httponly=False, samesite="lax", secure=production)
        return resp

    @app.post("/logout")
    def logout(request: Request):
        user, token = current_user(request); require_csrf(request, token)
        store.sessions.pop(auth.hash_token(token), None); audit("logout", user["id"], user["id"])
        resp = RedirectResponse("/login", status_code=303); resp.delete_cookie("session"); return resp

    @app.post("/change-password")
    def change_password(request: Request, password: str = Form(...)):
        user, token = current_user(request); require_csrf(request, token)
        auth.validate_password(user["login"], password)
        user["password_hash"] = auth.hash_password(password); user["must_change_password"] = False
        store.sessions.pop(auth.hash_token(token), None)
        new_token, session = auth.new_session(user["id"]); store.sessions[session.token_hash] = user["id"]
        audit("password_changed", user["id"], user["id"])
        resp = RedirectResponse("/dashboard", status_code=303); resp.set_cookie("session", new_token, httponly=True, samesite="lax", secure=production); resp.set_cookie("csrf", auth.csrf_token(new_token), samesite="lax", secure=production); return resp

    @app.post("/admin/users")
    def create_user(request: Request, login: str = Form(...), password: str = Form(...), display_name: str = Form("")):
        admin, token = require_admin(request); require_csrf(request, token); auth.validate_password(login, password)
        uid = store.next_user; store.next_user += 1
        store.users[uid] = {"id": uid, "login": login, "password_hash": auth.hash_password(password), "role": "user", "must_change_password": True, "deleted": False, "display_name": display_name}
        audit("user_created", admin["id"], uid)
        return {"id": uid}

    @app.delete("/admin/users/{uid}")
    def delete_user(uid: int, request: Request):
        admin, token = require_admin(request); require_csrf(request, token)
        if uid not in store.users: raise HTTPException(404)
        store.users[uid]["deleted"] = True; store.resumes.pop(uid, None); store.profiles.pop(uid, None); store.criteria_versions.pop(uid, None); audit("user_deleted", admin["id"], uid); return {"deleted": uid}

    @app.post("/resume")
    async def upload_resume(request: Request, file: UploadFile = File(...)):
        user, token = current_user(request); require_csrf(request, token)
        content = await file.read(); check = documents.validate_upload(file.filename or "", content, file.content_type or "")
        text = documents.extract_docx_text(content) if check.kind == "docx" else documents.extract_pdf_text(content)
        store.resumes[user["id"]] = {"name": check.original_name, "safe_name": check.safe_name, "sha256": check.sha256, "kind": check.kind, "text": text}
        store.jobs.enqueue(user["id"], "resume_profile_extraction", {"heartbeat": int(time.time())}); audit("resume_uploaded", user["id"], user["id"], filename=check.safe_name)
        return {"kind": check.kind, "sha256": check.sha256}

    @app.post("/onboarding")
    def onboarding(request: Request, desired_titles: str = Form("AI Analyst"), locations: str = Form("Москва"), remote: bool = Form(False)):
        user, token = current_user(request); require_csrf(request, token)
        profile = {"title": desired_titles, "locations": [locations], "remote": remote, "confirmed": False, "facts": []}
        store.profiles[user["id"]] = profile
        return profile

    @app.post("/profile/confirm")
    def confirm_profile(request: Request):
        user, token = current_user(request); require_csrf(request, token)
        if user["id"] not in store.profiles: raise HTTPException(400)
        store.profiles[user["id"]]["confirmed"] = True
        c = criteria.DEFAULT_CRITERIA.copy(); c["search"] = dict(criteria.DEFAULT_CRITERIA["search"]); c["search"]["desired_titles"] = [store.profiles[user["id"]]["title"]]; c["search"]["locations"] = store.profiles[user["id"]]["locations"]
        store.criteria_versions[user["id"]] = [criteria.next_version([], criteria.validate_criteria(c))]
        audit("profile_confirmed", user["id"], user["id"]); audit("criteria_changed", user["id"], user["id"])
        return {"confirmed": True, "criteria_version": 1}

    @app.post("/criteria")
    def save_criteria(request: Request, payload: dict):
        user, token = current_user(request); require_csrf(request, token)
        valid = criteria.validate_criteria(payload); versions = store.criteria_versions.setdefault(user["id"], [])
        version = criteria.next_version(versions, valid); versions.append(version); audit("criteria_changed", user["id"], user["id"], version=version["version"]); return version

    @app.post("/schedule")
    def schedule(request: Request, interval_days: int = Form(...), sources: str = Form("hh,habr")):
        user, token = current_user(request); require_csrf(request, token)
        try:
            queue.validate_schedule(interval_days)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        store.schedules[user["id"]] = {"interval_days": interval_days, "sources": [s.strip() for s in sources.split(",") if s.strip()]}; audit("schedule_changed", user["id"], user["id"]); return store.schedules[user["id"]]

    @app.post("/worker/run-fixtures")
    def run_fixtures(request: Request):
        user, token = current_user(request); require_csrf(request, token)
        if not store.profiles.get(user["id"], {}).get("confirmed"): raise HTTPException(400)
        c = store.criteria_versions[user["id"]][-1]
        samples = [{"title":"AI Solution Analyst","company":"ACME","description":"LLM RAG agent API integration requirements analyst chatbot prototype AI","url":"https://e/1"},{"title":"QA engineer","company":"Other","description":"QA support manual testing","url":"https://e/2"}]
        created=[]
        for s in samples:
            vid=store.next_vacancy; store.next_vacancy+=1; pre=scoring.deterministic_prescore(s,c); s.update({"id":vid,"user_id":user["id"],"decision":pre["decision"],"score":pre["score"],"why":"LLM/API fit" if pre["score"]>8 else "Low fit","resume_angle":"analysis and integrations"}); store.vacancies[vid]=s; created.append(vid)
        audit("search_completed", user["id"], user["id"], count=len(created)); return {"vacancies": created}

    @app.get("/vacancies", response_class=HTMLResponse)
    def vacancies(request: Request):
        user, _ = current_user(request); rows=[v for v in store.vacancies.values() if v["user_id"]==user["id"]]
        return "\n".join(f"<article>{v['decision']} {v['title']} {v['company']}</article>" for v in rows)

    @app.get("/vacancies/{vid}", response_class=HTMLResponse)
    def vacancy_detail(vid: int, request: Request):
        user, _ = current_user(request); v=store.vacancies.get(vid)
        if not v or v["user_id"] != user["id"]: raise HTTPException(404)
        store.viewed.add((user["id"], vid)); return f"<h1>{v['title']}</h1><p>{v['description']}</p>"

    @app.get("/export", response_class=PlainTextResponse)
    def export_text(request: Request):
        user, _ = current_user(request); rows=[v for v in store.vacancies.values() if v["user_id"]==user["id"]]
        return export.plain_text_selection(rows)

    @app.post("/vacancies/{vid}/letter")
    def letter(vid: int, request: Request):
        user, token = current_user(request); require_csrf(request, token); v=store.vacancies.get(vid)
        if not v or v["user_id"] != user["id"]: raise HTTPException(404)
        text = export.validate_cover_letter(f"Здравствуйте! Заинтересовала вакансия {v['title']}: могу быть полезен опытом в анализе требований, AI-интеграциях и запуске практичных решений.")
        store.letters.append({"user_id": user["id"], "vacancy_id": vid, "text": text}); audit("letter_generated", user["id"], user["id"], vacancy_id=vid); return {"text": text, "length": len(text)}

    @app.get("/admin/audit")
    def audit_log(request: Request):
        require_admin(request); return JSONResponse(store.audit)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request): current_user(request); return "Dashboard"

    return app
