from __future__ import annotations

import json, shutil, uuid
from datetime import timedelta
from html import escape
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import auth, criteria, documents, export, queue
from .db import bootstrap_admin, create_schema, make_engine, make_session_factory, session_expiry, utcnow
from .models import (
    AppSetting, AuditLog, BackgroundJob, CoverLetter, CriteriaVersion, LoginAttempt,
    ProfileVersion, ResumeFile, SearchRun, SourceHealth, User, UserSchedule,
    UserSession, Vacancy, VacancyScore, VacancySource, VacancyUIState,
)
from .settings import Settings, load_settings
from .worker import compute_next_run_at, validate_run_time, validate_timezone

class Store:  # compatibility shim for old tests; production uses Settings/DB only.
    def __init__(self, database_url: str | None = None, upload_dir: Path | None = None, data_dir: Path | None = None):
        self.settings = Settings(database_url=database_url or "sqlite:///:memory:", data_dir=data_dir or Path("data-test"), upload_dir=upload_dir or Path("data-test/uploads"), run_dir=(data_dir or Path("data-test")) / "runs", allowed_hosts=("testserver", "localhost", "127.0.0.1"))

def dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)

def loads(text: str | None, default=None):
    if not text:
        return {} if default is None else default
    return json.loads(text)

def create_app(store: Store | None = None, *, settings: Settings | None = None, production: bool | None = None) -> FastAPI:
    if settings is None:
        settings = store.settings if store is not None else load_settings()
    if production is not None:
        settings = Settings(**{**settings.__dict__, "environment": "production" if production else settings.environment})
    settings.ensure_dirs()
    engine = make_engine(settings.database_url)
    if settings.production and settings.database_url != "sqlite:///:memory:":
        SessionLocal = make_session_factory(engine)
        try:
            with SessionLocal() as db:
                db.execute(select(func.count(User.id))).scalar()
                db.execute(select(func.count()).select_from(AppSetting)).scalar()
        except Exception as exc:
            raise RuntimeError("database is not migrated; run alembic upgrade head before production startup") from exc
    else:
        create_schema(engine)
        SessionLocal = make_session_factory(engine)
    with SessionLocal() as db:
        bootstrap_admin(db)

    app = FastAPI(title="Jobs Catcher")
    templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))
    app.state.settings = settings
    app.state.engine = engine
    app.state.SessionLocal = SessionLocal
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts) + ["testserver"])

    def db_session() -> Session:
        return SessionLocal()

    def audit(db: Session, action: str, actor_id=None, target_user_id=None, request: Request | None = None, **meta):
        from .audit import redact_event
        safe = redact_event(meta)
        db.add(AuditLog(action=action, actor_user_id=actor_id, target_user_id=target_user_id, ip=(request.client.host if request and request.client else ""), user_agent=(request.headers.get("user-agent", "")[:255] if request else ""), metadata_json=dumps(safe)))

    def current_user(db: Session, request: Request) -> tuple[User, str]:
        token = request.cookies.get("session")
        token_hash = auth.hash_token(token or "")
        session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash, UserSession.expires_at > utcnow()))
        if not session:
            raise HTTPException(401)
        user = db.get(User, session.user_id)
        if not user or user.deleted_at is not None:
            db.execute(delete(UserSession).where(UserSession.token_hash == token_hash)); db.commit()
            raise HTTPException(401)
        if user.must_change_password and request.url.path not in {"/change-password", "/logout"}:
            raise HTTPException(403, "password change required")
        return user, token or ""

    def require_csrf(request: Request, token: str, csrf: str | None = None):
        value = csrf or request.headers.get("x-csrf-token") or request.query_params.get("csrf")
        if not auth.verify_csrf(token, value or ""):
            raise HTTPException(403, "CSRF")

    def require_admin(db: Session, request: Request) -> tuple[User, str]:
        user, token = current_user(db, request)
        if user.role != "superuser":
            raise HTTPException(403)
        return user, token

    def set_session_cookie(resp, token: str):
        resp.set_cookie("session", token, httponly=True, samesite="lax", secure=settings.production)
        resp.set_cookie("csrf", auth.csrf_token(token), httponly=False, samesite="lax", secure=settings.production)

    def csrf_input(token: str) -> str:
        return f'<input type="hidden" name="csrf" value="{escape(auth.csrf_token(token))}">'

    def enqueue(db: Session, user_id: int | None, job_type: str, payload: dict, active_key: str | None = None) -> BackgroundJob:
        if active_key:
            existing = db.scalar(select(BackgroundJob).where(BackgroundJob.active_key == active_key, BackgroundJob.status.in_(queue.ACTIVE_STATUSES)))
            if existing:
                return existing
        job = BackgroundJob(user_id=user_id, type=job_type, status="queued", payload_json=dumps(payload), active_key=active_key)
        db.add(job)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            with db_session() as db2:
                existing = db2.scalar(select(BackgroundJob).where(BackgroundJob.active_key == active_key))
                return existing
        return job

    @app.middleware("http")
    async def security_headers(request, call_next):
        try:
            resp = await call_next(request)
        except HTTPException:
            raise
        resp.headers["x-content-type-options"] = "nosniff"
        resp.headers["x-frame-options"] = "DENY"
        resp.headers["referrer-policy"] = "same-origin"
        resp.headers["content-security-policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
        return resp

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        checks = {"db": False, "data_dir": False, "upload_dir": False, "codex_bin": bool(shutil.which(settings.codex_bin) or Path(settings.codex_bin).exists())}
        try:
            with db_session() as db:
                db.execute(select(func.count(User.id))).scalar()
            checks["db"] = True
        except Exception:
            checks["db"] = False
        for key, path in [("data_dir", settings.data_dir), ("upload_dir", settings.upload_dir)]:
            try:
                path.mkdir(parents=True, exist_ok=True)
                probe = path / ".ready"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
                checks[key] = True
            except Exception:
                checks[key] = False
        ok = all(checks.values())
        return JSONResponse({"status": "ready" if ok else "not_ready", **checks}, status_code=200 if ok else 503)

    @app.get("/signup")
    @app.get("/register")
    @app.get("/users/new")
    def no_signup():
        raise HTTPException(404)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        return templates.TemplateResponse(request, "login.html", {"title": "Login"})

    @app.post("/login")
    def login(request: Request, login: str = Form(...), password: str = Form(...)):
        now = utcnow()
        ip = request.client.host if request.client else ""
        with db_session() as db:
            failures = db.scalar(select(func.count(LoginAttempt.id)).where(LoginAttempt.login == login, LoginAttempt.ip == ip, LoginAttempt.success == False, LoginAttempt.created_at >= now - timedelta(minutes=15)))
            if failures >= 5:
                raise HTTPException(429)
            user = db.scalar(select(User).where(User.login == login, User.deleted_at.is_(None)))
            if not user or not auth.verify_password(user.password_hash, password):
                db.add(LoginAttempt(login=login, ip=ip, success=False)); audit(db, "login_failed", None, None, request, login=login); db.commit(); raise HTTPException(401)
            db.add(LoginAttempt(login=login, ip=ip, success=True))
            old_hash = auth.hash_token(request.cookies.get("session") or "")
            db.execute(delete(UserSession).where(UserSession.token_hash == old_hash))
            token, session_obj = auth.new_session(user.id)
            db.add(UserSession(user_id=user.id, token_hash=session_obj.token_hash, csrf_hash=auth.hash_token(auth.csrf_token(token)), expires_at=session_expiry()))
            audit(db, "login", user.id, user.id, request)
            db.commit()
            resp = RedirectResponse("/change-password" if user.must_change_password else "/dashboard", status_code=303)
            set_session_cookie(resp, token)
            return resp

    @app.post("/logout")
    def logout(request: Request):
        with db_session() as db:
            user, token = current_user(db, request); require_csrf(request, token)
            db.execute(delete(UserSession).where(UserSession.token_hash == auth.hash_token(token)))
            audit(db, "logout", user.id, user.id, request); db.commit()
        resp = RedirectResponse("/login", status_code=303); resp.delete_cookie("session"); resp.delete_cookie("csrf"); return resp

    @app.get("/change-password", response_class=HTMLResponse)
    def change_password_page(request: Request):
        with db_session() as db:
            _, token = current_user(db, request)
        return templates.TemplateResponse(request, "change_password.html", {"title": "Change Password", "csrf": auth.csrf_token(token)})

    @app.post("/change-password")
    def change_password(request: Request, password: str = Form(...), csrf: str | None = Form(None)):
        with db_session() as db:
            user, token = current_user(db, request); require_csrf(request, token, csrf)
            auth.validate_password(user.login, password)
            user.password_hash = auth.hash_password(password); user.must_change_password = False
            db.execute(delete(UserSession).where(UserSession.user_id == user.id))
            new_token, session_obj = auth.new_session(user.id)
            db.add(UserSession(user_id=user.id, token_hash=session_obj.token_hash, csrf_hash=auth.hash_token(auth.csrf_token(new_token)), expires_at=session_expiry()))
            audit(db, "password_changed", user.id, user.id, request); db.commit()
            resp = RedirectResponse("/dashboard", status_code=303); set_session_cookie(resp, new_token); return resp

    @app.get("/resume", response_class=HTMLResponse)
    def resume_page(request: Request):
        with db_session() as db:
            _, token = current_user(db, request)
        return templates.TemplateResponse(request, "resume.html", {"title": "Resume", "csrf": auth.csrf_token(token)})

    @app.get("/onboarding", response_class=HTMLResponse)
    def onboarding_page(request: Request):
        with db_session() as db:
            _, token = current_user(db, request)
        return templates.TemplateResponse(request, "onboarding.html", {"title": "Onboarding", "csrf": auth.csrf_token(token), "onboarding": {}})

    @app.get("/profile", response_class=HTMLResponse)
    def profile_page(request: Request):
        with db_session() as db:
            user, token = current_user(db, request)
            profile = db.scalar(select(ProfileVersion).where(ProfileVersion.user_id == user.id).order_by(ProfileVersion.version.desc()))
            body = escape(profile.data_json if profile else "{}")
        return templates.TemplateResponse(request, "profile.html", {"title": "Profile", "csrf": auth.csrf_token(token), "profile": body})

    @app.get("/criteria", response_class=HTMLResponse)
    def criteria_page(request: Request):
        with db_session() as db:
            user, token = current_user(db, request)
            row = db.scalar(select(CriteriaVersion).where(CriteriaVersion.user_id == user.id).order_by(CriteriaVersion.version.desc()))
            body = escape(row.data_json if row else dumps(criteria.DEFAULT_CRITERIA))
        return templates.TemplateResponse(request, "criteria.html", {"title": "Criteria", "csrf": auth.csrf_token(token), "criteria_text": body})

    @app.get("/schedule", response_class=HTMLResponse)
    def schedule_page(request: Request):
        with db_session() as db:
            user, token = current_user(db, request)
            sched = db.scalar(select(UserSchedule).where(UserSchedule.user_id == user.id))
        interval = sched.interval_days if sched else settings.min_schedule_interval_days
        sources = ",".join(loads(sched.sources_json, list(settings.enabled_sources)) if sched else settings.enabled_sources)
        run_time = sched.run_time if sched else "09:00"
        tz = sched.timezone if sched else "Europe/Moscow"
        return templates.TemplateResponse(request, "schedule.html", {"title": "Schedule", "csrf": auth.csrf_token(token), "interval_days": interval, "sources": sources, "run_time": run_time, "timezone": tz})

    @app.post("/admin/users")
    def create_user(request: Request, login: str = Form(...), password: str = Form(...), display_name: str = Form("")):
        with db_session() as db:
            admin, token = require_admin(db, request); require_csrf(request, token); auth.validate_password(login, password)
            user = User(login=login, password_hash=auth.hash_password(password), role="user", display_name=display_name or None, must_change_password=True)
            db.add(user); db.flush(); audit(db, "user_created", admin.id, user.id, request); db.commit(); return {"id": user.id}

    @app.delete("/admin/users/{uid}")
    def delete_user(uid: int, request: Request):
        with db_session() as db:
            admin, token = require_admin(db, request); require_csrf(request, token)
            user = db.get(User, uid)
            if not user or user.deleted_at is not None: raise HTTPException(404)
            files = [Path(r.path) for r in db.scalars(select(ResumeFile).where(ResumeFile.user_id == uid)).all()]
            user.deleted_at = utcnow(); user.login = f"deleted-{uid}-{user.login}"; user.must_change_password = True
            for model in [UserSession, LoginAttempt, UserSchedule, BackgroundJob, SearchRun, VacancyScore, VacancyUIState, CoverLetter, CriteriaVersion, ProfileVersion, ResumeFile]:
                if hasattr(model, "user_id"):
                    db.execute(delete(model).where(model.user_id == uid))
            audit(db, "user_deleted", admin.id, uid, request); db.commit()
            for path in files:
                try: path.unlink(missing_ok=True)
                except Exception: pass
            return {"deleted": uid}

    @app.post("/resume")
    async def upload_resume(request: Request, file: UploadFile = File(...), csrf: str | None = Form(None)):
        content = await file.read()
        with db_session() as db:
            user, token = current_user(db, request); require_csrf(request, token, csrf)
            check = documents.validate_upload(file.filename or "", content, file.content_type or "", max_bytes=settings.resume_size_limit)
            try:
                text = documents.extract_docx_text(content) if check.kind == "docx" else documents.extract_pdf_text(content)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            stored_name = f"{uuid.uuid4().hex}.{check.kind}"
            path = settings.upload_dir / stored_name
            path.write_bytes(content)
            old_paths = [Path(r.path) for r in db.scalars(select(ResumeFile).where(ResumeFile.user_id == user.id, ResumeFile.active == True)).all()]
            db.execute(update(ResumeFile).where(ResumeFile.user_id == user.id).values(active=False))
            resume = ResumeFile(user_id=user.id, original_name=check.original_name, stored_name=stored_name, mime=file.content_type or "", size=len(content), sha256=check.sha256, path=str(path), extracted_text=text, active=True)
            db.add(resume); db.flush()
            enqueue(db, user.id, "resume_profile_extraction", {"resume_file_id": resume.id})
            audit(db, "resume_uploaded", user.id, user.id, request, filename=check.safe_name, sha256=check.sha256)
            db.commit()
            for old in old_paths:
                try: old.unlink(missing_ok=True)
                except Exception: pass
            return {"id": resume.id, "kind": check.kind, "sha256": check.sha256, "stored": stored_name}

    @app.post("/onboarding")
    async def onboarding(request: Request):
        form = await request.form()
        with db_session() as db:
            user, token = current_user(db, request); require_csrf(request, token, form.get("csrf"))
            data = {k: form.get(k) for k in form.keys() if k != "csrf"}
            for key in ["desired_titles", "directions", "adjacent_roles", "cities", "employment_types", "must_have", "undesired_duties", "stop_factors"]:
                if isinstance(data.get(key), str):
                    data[key] = [x.strip() for x in data[key].replace(";", ",").split(",") if x.strip()]
            data["remote"] = str(form.get("remote", "")).lower() in {"true", "on", "1", "yes"}
            data["all_russia"] = str(form.get("all_russia", "")).lower() in {"true", "on", "1", "yes"}
            data["relocation"] = str(form.get("relocation", "")).lower() in {"true", "on", "1", "yes"}
            latest = db.scalar(select(ProfileVersion).where(ProfileVersion.user_id == user.id).order_by(ProfileVersion.version.desc()))
            profile = loads(latest.data_json) if latest else {"professional_title": (data.get("desired_titles") or ["Профиль"])[0], "facts_for_applications": []}
            profile["onboarding"] = data
            version = (latest.version if latest else 0) + 1
            pv = ProfileVersion(user_id=user.id, resume_file_id=latest.resume_file_id if latest else None, version=version, data_json=dumps(profile), confirmed=False)
            db.add(pv); audit(db, "onboarding_saved", user.id, user.id, request); db.commit(); return profile

    @app.post("/profile/confirm")
    def confirm_profile(request: Request, csrf: str | None = Form(None)):
        with db_session() as db:
            user, token = current_user(db, request); require_csrf(request, token, csrf)
            profile = db.scalar(select(ProfileVersion).where(ProfileVersion.user_id == user.id).order_by(ProfileVersion.version.desc()))
            if not profile: raise HTTPException(400)
            profile.confirmed = True
            audit(db, "profile_confirmed", user.id, user.id, request, profile_version_id=profile.id)
            # criteria generation job, handled by worker; also create fallback criteria for immediate editability
            enqueue(db, user.id, "criteria_generation", {"profile_version_id": profile.id})
            db.commit(); return {"confirmed": True, "profile_version_id": profile.id}

    @app.post("/criteria")
    async def save_criteria(request: Request):
        suffix = request.query_params.get("format", ".json")
        csrf = None
        if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded") or request.headers.get("content-type", "").startswith("multipart/form-data"):
            form = await request.form()
            csrf = form.get("csrf")
            text = str(form.get("criteria") or "{}")
        else:
            body = await request.body()
            text = body.decode() if body else "{}"
        with db_session() as db:
            user, token = current_user(db, request); require_csrf(request, token, csrf)
            try:
                payload = criteria.load_criteria(text or "{}", suffix)
                valid = criteria.validate_criteria(payload)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            latest = db.scalar(select(CriteriaVersion).where(CriteriaVersion.user_id == user.id).order_by(CriteriaVersion.version.desc()))
            profile = db.scalar(select(ProfileVersion).where(ProfileVersion.user_id == user.id, ProfileVersion.confirmed == True).order_by(ProfileVersion.version.desc()))
            version = (latest.version if latest else 0) + 1
            cv = CriteriaVersion(user_id=user.id, profile_version_id=profile.id if profile else None, version=version, data_json=dumps(valid))
            db.add(cv); audit(db, "criteria_changed", user.id, user.id, request, version=version); db.commit(); return {"version": version, "id": cv.id}

    @app.post("/schedule")
    def schedule(request: Request, interval_days: int = Form(...), sources: str = Form("hh,habr,superjob,rabota,geekjob,getmatch"), run_time: str = Form("09:00"), timezone: str = Form("Europe/Moscow"), csrf: str | None = Form(None)):
        with db_session() as db:
            user, token = current_user(db, request); require_csrf(request, token, csrf)
            try:
                queue.validate_schedule(interval_days)
                validate_run_time(run_time); validate_timezone(timezone)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            if interval_days < settings.min_schedule_interval_days or interval_days > settings.max_schedule_interval_days: raise HTTPException(400)
            selected = [s.strip() for s in sources.split(",") if s.strip() and s.strip() in settings.enabled_sources]
            if not selected: raise HTTPException(400, "no enabled sources selected")
            sched = db.scalar(select(UserSchedule).where(UserSchedule.user_id == user.id))
            if not sched:
                sched = UserSchedule(user_id=user.id, interval_days=interval_days, sources_json=dumps(selected)); db.add(sched)
            sched.interval_days = interval_days; sched.sources_json = dumps(selected); sched.run_time = run_time; sched.timezone = timezone; sched.next_run_at = compute_next_run_at(interval_days, run_time, timezone, now=utcnow())
            audit(db, "schedule_changed", user.id, user.id, request); db.commit(); return {"interval_days": interval_days, "sources": selected}

    @app.get("/vacancies", response_class=HTMLResponse)
    def vacancies(request: Request, decision: str | None = None, hide_viewed: bool = False):
        with db_session() as db:
            user, _ = current_user(db, request)
            rows = db.execute(select(Vacancy, VacancyScore).join(VacancyScore, VacancyScore.vacancy_id == Vacancy.id).where(VacancyScore.user_id == user.id).order_by(VacancyScore.final_score.desc().nullslast(), VacancyScore.prescore.desc())).all()
            rendered = []
            for v, score in rows:
                if decision and score.decision != decision: continue
                viewed = db.scalar(select(VacancyUIState).where(VacancyUIState.user_id == user.id, VacancyUIState.vacancy_id == v.id, VacancyUIState.viewed_at.is_not(None)))
                if hide_viewed and viewed: continue
                rendered.append({"vacancy": v, "score": score})
            return templates.TemplateResponse(request, "vacancies.html", {"title": "Vacancies", "rows": rendered})

    @app.get("/vacancies/{vid}", response_class=HTMLResponse)
    def vacancy_detail(vid: int, request: Request):
        with db_session() as db:
            user, _ = current_user(db, request)
            score = db.scalar(select(VacancyScore).where(VacancyScore.user_id == user.id, VacancyScore.vacancy_id == vid))
            if not score: raise HTTPException(404)
            v = db.get(Vacancy, vid)
            state = db.scalar(select(VacancyUIState).where(VacancyUIState.user_id == user.id, VacancyUIState.vacancy_id == vid))
            if not state:
                state = VacancyUIState(user_id=user.id, vacancy_id=vid); db.add(state)
            state.viewed_at = utcnow(); db.commit()
            rec = loads(score.recommendations_json)
            _, token = current_user(db, request)
            return templates.TemplateResponse(request, "vacancy_detail.html", {"title": v.title, "vacancy": v, "recommendations": rec, "csrf": auth.csrf_token(token)})

    @app.get("/export", response_class=PlainTextResponse)
    def export_text(request: Request):
        with db_session() as db:
            user, _ = current_user(db, request)
            rows=[]
            for v, score in db.execute(select(Vacancy, VacancyScore).join(VacancyScore, VacancyScore.vacancy_id == Vacancy.id).where(VacancyScore.user_id == user.id)).all():
                rec=loads(score.recommendations_json)
                src=db.scalar(select(VacancySource).where(VacancySource.vacancy_id == v.id))
                rows.append({"decision":score.decision,"title":v.title,"company":v.company,"url":src.source_url if src else v.canonical_url,"why":rec.get("why_fits",""),"resume_angle":"; ".join(rec.get("resume_angle",[])) if isinstance(rec.get("resume_angle"), list) else rec.get("resume_angle","")})
            return export.plain_text_selection(rows)

    @app.post("/vacancies/{vid}/letter")
    def letter(vid: int, request: Request, csrf: str | None = Form(None)):
        with db_session() as db:
            user, token = current_user(db, request); require_csrf(request, token, csrf)
            if not db.scalar(select(VacancyScore).where(VacancyScore.user_id == user.id, VacancyScore.vacancy_id == vid)): raise HTTPException(404)
            job = enqueue(db, user.id, "generate_cover_letter", {"vacancy_id": vid})
            audit(db, "letter_requested", user.id, user.id, request, vacancy_id=vid); db.commit(); return {"job_id": job.id}

    @app.get("/admin/audit")
    def audit_log(request: Request):
        with db_session() as db:
            require_admin(db, request)
            rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200)).all()
            return [{"action": r.action, "actor_id": r.actor_user_id, "target_user_id": r.target_user_id, "metadata": loads(r.metadata_json), "created_at": r.created_at.isoformat()} for r in rows]

    @app.get("/admin/jobs")
    def admin_jobs(request: Request):
        with db_session() as db:
            require_admin(db, request)
            return [{"id": j.id, "type": j.type, "status": j.status, "attempts": j.attempts, "progress": j.progress} for j in db.scalars(select(BackgroundJob).order_by(BackgroundJob.id.desc()).limit(200))]

    @app.get("/admin/runs")
    def admin_runs(request: Request):
        with db_session() as db:
            require_admin(db, request)
            return [{"id": r.id, "user_id": r.user_id, "status": r.status, "average_prescore": r.average_prescore} for r in db.scalars(select(SearchRun).order_by(SearchRun.id.desc()).limit(100))]

    @app.get("/admin/source-health")
    def admin_source_health(request: Request):
        with db_session() as db:
            require_admin(db, request)
            return [{"source": s.source, "status": s.status, "last_error": s.last_error} for s in db.scalars(select(SourceHealth))]

    @app.get("/admin/settings", response_class=HTMLResponse)
    def admin_settings(request: Request):
        with db_session() as db:
            _, token = require_admin(db, request)
            values = {row.key: loads(row.value_json) for row in db.scalars(select(AppSetting)).all()}
        enabled = ",".join(values.get("enabled_sources", list(settings.enabled_sources)))
        min_interval = values.get("min_schedule_interval_days", settings.min_schedule_interval_days)
        max_results = values.get("max_results_per_source", settings.max_results_per_source)
        return templates.TemplateResponse(request, "admin_settings.html", {"title": "Admin Settings", "csrf": auth.csrf_token(token), "enabled_sources": enabled, "min_schedule_interval_days": min_interval, "max_results_per_source": max_results})

    @app.post("/admin/settings")
    def save_admin_settings(request: Request, enabled_sources: str = Form(""), min_schedule_interval_days: int = Form(1), max_results_per_source: int = Form(20), csrf: str | None = Form(None)):
        with db_session() as db:
            admin, token = require_admin(db, request); require_csrf(request, token, csrf)
            selected = [src.strip() for src in enabled_sources.split(",") if src.strip() in {"hh", "habr", "superjob", "rabota", "geekjob", "getmatch"}]
            if not selected or min_schedule_interval_days < 1 or max_results_per_source < 1:
                raise HTTPException(400)
            payload = {"enabled_sources": selected, "min_schedule_interval_days": min_schedule_interval_days, "max_results_per_source": max_results_per_source}
            for key, value in payload.items():
                row = db.get(AppSetting, key) or AppSetting(key=key, value_json="null")
                row.value_json = dumps(value); row.updated_at = utcnow(); db.add(row)
            audit(db, "settings_changed", admin.id, None, request, keys=list(payload))
            db.commit()
            return {"saved": True, **payload}

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        with db_session() as db:
            user, _ = current_user(db, request)
            jobs = db.scalar(select(func.count(BackgroundJob.id)).where(BackgroundJob.user_id == user.id, BackgroundJob.status.in_(queue.ACTIVE_STATUSES)))
            scores = db.scalar(select(func.count(VacancyScore.id)).where(VacancyScore.user_id == user.id))
            return templates.TemplateResponse(request, "dashboard.html", {"title": "Dashboard", "jobs": jobs, "scores": scores})

    return app
