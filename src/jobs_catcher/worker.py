from __future__ import annotations

import hashlib, json, os, socket, time, uuid
from datetime import datetime, time as dt_time, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import codex_integration, criteria, scoring, queue
from .db import bootstrap_admin, create_schema, make_engine, make_session_factory, utcnow
from .dedup import normalize_title
from .models import (
    BackgroundJob, CoverLetter, CriteriaVersion, ProfileVersion, ResumeFile, SearchRun,
    SourceHealth, UserSchedule, Vacancy, VacancyScore, VacancySource, RunVacancy,
    AuditLog,
)
from .settings import Settings, load_settings
from .source_adapters import ADAPTERS
from .settings_effective import cleanup_old_run_artifacts, load_effective_settings


def dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)

def loads(text: str | None, default=None):
    if not text:
        return {} if default is None else default
    return json.loads(text)

def settings_from_db(db: Session, base: Settings) -> Settings:
    return load_effective_settings(db, base)


def audit(db: Session, action: str, actor_id=None, target_user_id=None, **meta) -> None:
    db.add(AuditLog(action=action, actor_user_id=actor_id, target_user_id=target_user_id, metadata_json=dumps(meta)))


def validate_run_time(value: str) -> tuple[int, int]:
    try:
        hour_s, minute_s = value.split(":", 1)
        hour, minute = int(hour_s), int(minute_s)
    except Exception as exc:
        raise ValueError("run_time must be HH:MM") from exc
    if hour not in range(24) or minute not in range(60):
        raise ValueError("run_time must be HH:MM")
    return hour, minute

def validate_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be an IANA timezone") from exc

def compute_next_run_at(interval_days: int, run_time: str, timezone_name: str, *, now: datetime | None = None) -> datetime:
    if interval_days < 1:
        raise ValueError("minimum schedule interval is one day")
    hour, minute = validate_run_time(run_time)
    tz = validate_timezone(timezone_name)
    now_utc = now or utcnow()
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_local = now_utc.astimezone(tz)
    target_local = datetime.combine(now_local.date(), dt_time(hour, minute), tzinfo=tz)
    if now_local >= target_local:
        target_local = target_local + timedelta(days=interval_days)
    return target_local.astimezone(timezone.utc)

class CodexRunner:
    def __init__(self, settings: Settings, subprocess_run=codex_integration.default_subprocess_run):
        self.settings = settings
        self.subprocess_run = subprocess_run
    def run(self, scenario: str, prompt: str, validator, run_dir: Path) -> dict:
        run_dir.mkdir(parents=True, exist_ok=True)
        cmd = codex_integration.codex_command(self.settings.codex_bin, str(run_dir))
        return codex_integration.run_json_with_retry(self.subprocess_run, cmd, prompt, validator, timeout=180)

class DeterministicMockCodexRunner:
    def run(self, scenario: str, prompt: str, validator, run_dir: Path) -> dict:
        if scenario == "profile_extraction":
            return validator({"professional_title":"Operations Manager","experience":[],"companies":[],"roles":[],"periods":[],"responsibilities":[],"achievements":[],"projects":[],"skills":["warehouse","inventory","team leadership"],"technologies":[],"industries":["logistics"],"education":[],"languages":[],"strengths":["process improvement"],"level":"middle","directions":["operations"],"facts_for_applications":["inventory optimization"],"ambiguous":[],"confidence":"high"})
        if scenario == "criteria_generation":
            data = json.loads(prompt.split("ONBOARDING=",1)[1]) if "ONBOARDING=" in prompt else {}
            titles = data.get("desired_titles") or ["operations manager"]
            terms = titles + data.get("directions", []) + data.get("must_have", [])
            crit = criteria.DEFAULT_CRITERIA.copy(); crit["search"] = {**criteria.DEFAULT_CRITERIA["search"], "desired_titles": titles, "queries": titles, "locations": data.get("cities", [])}
            crit["scoring"] = {**criteria.DEFAULT_CRITERIA["scoring"], "positive_rules":[{"name":"target terms","weight":12,"any_terms":terms},{"name":"management","weight":5,"any_terms":["manage","manager","руковод","управл"]},{"name":"domain","weight":5,"any_terms":data.get("must_have", []) or terms}], "red_flag_rules":[{"name":"stop factors","penalty":8,"cap":8,"terms":data.get("stop_factors", [])}], "hard_reject_rules":[]}
            return validator(crit)
        if scenario == "vacancy_evaluation":
            vacancy = json.loads(prompt.split("VACANCY=",1)[1].split("\nDETERMINISTIC=",1)[0])
            deterministic = json.loads(prompt.split("DETERMINISTIC=",1)[1])
            result = {"vacancy_id":str(vacancy["id"]),"score":deterministic["score"],"decision":deterministic["decision"],"confidence":"high","role_summary":vacancy.get("title",""),"matching_signals":deterministic.get("positive_signals",[]),"missing_signals":deterministic.get("missing_signals",[]),"red_flags":deterministic.get("red_flags",[]),"applied_caps":deterministic.get("caps",[]),"why_fits":"Matches configured criteria","why_not_or_risks":"","what_to_check_before_apply":["details"],"resume_angle":["confirmed facts"],"cover_letter_points":["value"],"prescore_comment":"criteria-driven"}
            return validator(result)
        if scenario in {"cover_letter", "cover_letter_shorten"}:
            return validator({"text":"Здравствуйте! Заинтересовала вакансия: мой подтвержденный опыт поможет быстро принести практическую пользу команде."})
        raise RuntimeError(scenario)


def session_factory(settings: Settings):
    engine = make_engine(settings.database_url)
    if not settings.production:
        create_schema(engine)
    SessionLocal = make_session_factory(engine)
    with SessionLocal() as db: bootstrap_admin(db)
    return SessionLocal


def enqueue_job(db: Session, user_id: int | None, job_type: str, payload: dict, active_key: str | None = None) -> BackgroundJob:
    if active_key:
        existing = db.scalar(select(BackgroundJob).where(BackgroundJob.active_key == active_key, BackgroundJob.status.in_(queue.ACTIVE_STATUSES)))
        if existing: return existing
    job = BackgroundJob(user_id=user_id, type=job_type, payload_json=dumps(payload), active_key=active_key, status="queued")
    db.add(job); db.flush(); return job


def touch_job(db: Session, job: BackgroundJob, *, progress: int | None = None, lease_seconds: int = 900) -> None:
    now = utcnow()
    job.heartbeat_at = now
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    if progress is not None:
        job.progress = progress
    db.flush()


def heartbeat_job(SessionLocal, job_id: int, worker_id: str, *, progress: int | None = None, lease_seconds: int = 900) -> bool:
    now = utcnow()
    values = {
        "heartbeat_at": now,
        "lease_expires_at": now + timedelta(seconds=lease_seconds),
    }
    if progress is not None:
        values["progress"] = progress
    with SessionLocal() as db:
        result = db.execute(
            update(BackgroundJob)
            .where(
                BackgroundJob.id == job_id,
                BackgroundJob.worker_id == worker_id,
                BackgroundJob.status.in_(queue.ACTIVE_STATUSES - {"queued"}),
            )
            .values(**values)
        )
        db.commit()
        return result.rowcount == 1


def make_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"


def recover_stale_jobs(db: Session, stale_after_seconds: int = 900) -> int:
    now = utcnow()
    threshold = now - timedelta(seconds=stale_after_seconds)
    jobs = db.scalars(select(BackgroundJob).where(BackgroundJob.status.in_(queue.ACTIVE_STATUSES - {"queued"}))).all()
    count = 0
    for job in jobs:
        lease_expired = bool(job.lease_expires_at and job.lease_expires_at <= now)
        heartbeat_stale = bool((not job.lease_expires_at) and ((not job.heartbeat_at) or job.heartbeat_at < threshold))
        if lease_expired or heartbeat_stale:
            job.status = "queued"
            job.worker_id = None
            job.lease_expires_at = None
            job.attempts += 1
            count += 1
    return count


def claim_next_job(db: Session, worker_id: str | None = None, lease_seconds: int = 900) -> BackgroundJob | None:
    candidate_id = db.scalar(select(BackgroundJob.id).where(BackgroundJob.status == "queued").order_by(BackgroundJob.id).limit(1))
    if candidate_id is None:
        return None
    now = utcnow()
    worker_id = worker_id or make_worker_id()
    result = db.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == candidate_id, BackgroundJob.status == "queued")
        .values(status="running", started_at=now, heartbeat_at=now, lease_expires_at=now + timedelta(seconds=lease_seconds), worker_id=worker_id, attempts=BackgroundJob.attempts + 1)
    )
    if result.rowcount != 1:
        db.flush()
        return None
    db.flush()
    return db.get(BackgroundJob, candidate_id)


def _as_list(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, tuple):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in str(value).replace(";", ",").split(",") if x.strip()]


def _as_bool(value) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"true", "on", "1", "yes"}


def build_search_preferences(crit: dict, profile_data: dict) -> dict:
    search = crit.get("search", {}) if isinstance(crit, dict) else {}
    onboarding = profile_data.get("onboarding", {}) if isinstance(profile_data, dict) else {}
    salary = dict(search.get("salary") or {})
    if not salary.get("minimum") and onboarding.get("salary_minimum"):
        salary["minimum"] = int(onboarding.get("salary_minimum") or 0) or None
    if not salary.get("currency"):
        salary["currency"] = onboarding.get("currency", "RUB")
    if salary.get("gross") is None and _as_bool(onboarding.get("gross")) is not None:
        salary["gross"] = _as_bool(onboarding.get("gross"))
    work_formats = _as_list(search.get("work_formats")) or _as_list(onboarding.get("work_formats")) or _as_list(onboarding.get("work_format"))
    remote = bool(search.get("remote") or onboarding.get("remote") or "remote" in work_formats)
    return {
        "locations": _as_list(search.get("locations")) or _as_list(onboarding.get("cities")),
        "all_russia": bool(search.get("all_russia") or onboarding.get("all_russia")),
        "remote": remote,
        "work_formats": work_formats,
        "employment_types": _as_list(search.get("employment_types")) or _as_list(onboarding.get("employment_types")),
        "salary": salary,
        "seniority": _as_list(search.get("seniority")) or _as_list(onboarding.get("seniority")),
    }


def generate_criteria_from_profile(profile: dict, onboarding: dict) -> dict:
    titles = _as_list(onboarding.get("desired_titles")) or [profile.get("professional_title", "")]
    terms = [x for x in titles + _as_list(onboarding.get("directions")) + _as_list(profile.get("skills")) + _as_list(onboarding.get("must_have")) if x]
    gross = _as_bool(onboarding.get("gross"))
    crit = json.loads(json.dumps(criteria.DEFAULT_CRITERIA, ensure_ascii=False))
    crit["profile_summary"] = profile.get("professional_title", "")
    crit["search"].update({
        "desired_titles": titles,
        "adjacent_titles": _as_list(onboarding.get("adjacent_roles")),
        "directions": _as_list(onboarding.get("directions")),
        "queries": titles[:5],
        "locations": _as_list(onboarding.get("cities")),
        "work_formats": _as_list(onboarding.get("work_format")) or ["any"],
        "employment_types": _as_list(onboarding.get("employment_types")),
        "seniority": _as_list(onboarding.get("seniority")) or ["any"],
        "salary": {"minimum": int(onboarding.get("salary_minimum") or 0) or None, "currency": onboarding.get("currency", "RUB"), "gross": gross},
    })
    crit["scoring"]["positive_rules"] = [
        {"name":"target role/domain terms","weight":12,"any_terms":terms[:20]},
        {"name":"must-have conditions","weight":5,"any_terms":_as_list(onboarding.get("must_have"))},
        {"name":"seniority/work format","weight":5,"any_terms":_as_list(onboarding.get("seniority")) + _as_list(onboarding.get("work_format"))},
    ]
    crit["scoring"]["red_flag_rules"] = [{"name":"stop factors","penalty":8,"cap":8,"terms":_as_list(onboarding.get("stop_factors")) + _as_list(onboarding.get("undesired_duties"))}]
    return criteria.validate_criteria(crit)


def handle_profile_extraction(db: Session, job: BackgroundJob, settings: Settings, runner) -> None:
    payload = loads(job.payload_json); resume = db.get(ResumeFile, payload["resume_file_id"])
    prompt = codex_integration.build_profile_extraction_prompt(resume.extracted_text)
    profile = runner.run("profile_extraction", prompt, codex_integration.validate_profile_result, settings.run_dir / f"job-{job.id}")
    latest = db.scalar(select(ProfileVersion).where(ProfileVersion.user_id == job.user_id).order_by(ProfileVersion.version.desc()))
    version = (latest.version if latest else 0) + 1
    db.add(ProfileVersion(user_id=job.user_id, resume_file_id=resume.id, version=version, data_json=dumps(profile), confirmed=False))


def handle_criteria_generation(db: Session, job: BackgroundJob, settings: Settings, runner) -> None:
    payload = loads(job.payload_json); profile = db.get(ProfileVersion, payload.get("profile_version_id")) or db.scalar(select(ProfileVersion).where(ProfileVersion.user_id == job.user_id).order_by(ProfileVersion.version.desc()))
    profile_data = loads(profile.data_json); onboarding = profile_data.get("onboarding", {})
    prompt = codex_integration.build_criteria_generation_prompt(profile_data, onboarding)
    try:
        crit = runner.run("criteria_generation", prompt, criteria.validate_criteria, settings.run_dir / f"job-{job.id}")
    except Exception:
        crit = generate_criteria_from_profile(profile_data, onboarding)
    latest = db.scalar(select(CriteriaVersion).where(CriteriaVersion.user_id == job.user_id).order_by(CriteriaVersion.version.desc()))
    db.add(CriteriaVersion(user_id=job.user_id, profile_version_id=profile.id, version=(latest.version if latest else 0)+1, data_json=dumps(crit)))


def _apply_vacancy_fields(v: Vacancy, item: dict, norm_title: str, norm_company: str, norm_loc: str, content_hash: str) -> None:
    v.normalized_title = norm_title
    v.normalized_company = norm_company
    v.normalized_location = norm_loc
    v.canonical_url = item.get("canonical_url") or v.canonical_url
    v.content_hash = content_hash
    v.title = item.get("title", "")
    v.company = item.get("company", "")
    v.location = item.get("location", "")
    v.description = item.get("description", "")
    v.work_format = item.get("work_format") or ""
    v.employment_type = item.get("employment_type") or ""
    v.salary_json = dumps(item.get("salary")) if item.get("salary") is not None else "{}"
    v.published_at = item.get("published_at") or ""
    v.updated_at = item.get("updated_at") or ""
    v.requirements = item.get("requirements") or ""
    v.responsibilities = item.get("responsibilities") or ""
    v.conditions = item.get("conditions") or ""
    v.skills_json = dumps(item.get("skills") or [])
    v.normalized_json = dumps(item)


def _upsert_vacancy(db: Session, item: dict) -> Vacancy:
    norm_title = normalize_title(item.get("title", ""))
    norm_company = (item.get("company") or "").lower().strip()
    norm_loc = (item.get("location") or "").lower().strip()
    content_hash = item.get("content_hash") or hashlib.sha256((item.get("description") or "").encode()).hexdigest()
    existing = None
    if item.get("source") and item.get("external_id"):
        source_row = db.scalar(select(VacancySource).where(VacancySource.source == item["source"], VacancySource.external_id == item["external_id"]))
        if source_row:
            existing = db.get(Vacancy, source_row.vacancy_id)
    if not existing and item.get("canonical_url"):
        existing = db.scalar(select(Vacancy).where(Vacancy.canonical_url == item["canonical_url"]))
    if not existing and content_hash:
        existing = db.scalar(select(Vacancy).where(Vacancy.content_hash == content_hash, Vacancy.normalized_title == norm_title, Vacancy.normalized_company == norm_company))
    if not existing:
        existing = db.scalar(select(Vacancy).where(Vacancy.normalized_title == norm_title, Vacancy.normalized_company == norm_company, Vacancy.normalized_location == norm_loc, Vacancy.content_hash == content_hash))
    if existing:
        _apply_vacancy_fields(existing, item, norm_title, norm_company, norm_loc, content_hash)
        db.flush()
        return existing
    v = Vacancy(normalized_title=norm_title, normalized_company=norm_company, normalized_location=norm_loc, title=item.get("title", ""))
    _apply_vacancy_fields(v, item, norm_title, norm_company, norm_loc, content_hash)
    db.add(v)
    db.flush()
    return v


def _upsert_source_snapshot(db: Session, vacancy: Vacancy, item: dict) -> VacancySource:
    source = item["source"]
    external_id = item["external_id"]
    row = db.scalar(select(VacancySource).where(VacancySource.source == source, VacancySource.external_id == external_id))
    if not row:
        row = VacancySource(vacancy_id=vacancy.id, source=source, external_id=external_id, source_url=item.get("source_url") or item.get("canonical_url") or "", raw_json=dumps(item))
        db.add(row)
    else:
        row.vacancy_id = vacancy.id
        row.source_url = item.get("source_url") or item.get("canonical_url") or row.source_url
        row.raw_json = dumps(item)
        row.fetched_at = utcnow()
    db.flush()
    return row


def handle_scheduled_search(db: Session, job: BackgroundJob, settings: Settings, runner, adapter_factory=None) -> None:
    settings = settings_from_db(db, settings)
    profile = db.scalar(select(ProfileVersion).where(ProfileVersion.user_id == job.user_id, ProfileVersion.confirmed == True).order_by(ProfileVersion.version.desc()))
    crit_v = db.scalar(select(CriteriaVersion).where(CriteriaVersion.user_id == job.user_id).order_by(CriteriaVersion.version.desc()))
    if not profile or not crit_v:
        raise RuntimeError("profile and criteria required")
    crit = loads(crit_v.data_json)
    profile_data = loads(profile.data_json)
    preferences = build_search_preferences(crit, profile_data)
    run = SearchRun(user_id=job.user_id, job_id=job.id, status="running")
    db.add(run)
    db.flush()
    audit(db, "search_started", job.user_id, job.user_id, run_id=run.id)
    queries = crit["search"].get("queries") or crit["search"].get("desired_titles") or [profile_data.get("professional_title", "")]
    schedule = db.scalar(select(UserSchedule).where(UserSchedule.user_id == job.user_id))
    requested_sources = loads(schedule.sources_json, list(settings.enabled_sources)) if schedule else list(settings.enabled_sources)
    selected_sources = [source for source in requested_sources if source in settings.enabled_sources and source in ADAPTERS]
    errors=[]
    scores=[]
    attempted_sources = 0
    successful_sources = 0
    total_seen = 0
    for source in selected_sources:
        if total_seen >= settings.max_vacancies_per_run:
            break
        attempted_sources += 1
        adapter = None
        try:
            Adapter = ADAPTERS[source]
            adapter = adapter_factory(source) if adapter_factory else Adapter(settings)
            source_seen = 0
            for query in queries[:settings.max_search_queries]:
                if source_seen >= settings.max_results_per_source or total_seen >= settings.max_vacancies_per_run:
                    break
                touch_job(db, job, progress=min(55, 5 + total_seen))
                for result in adapter.search(query, preferences):
                    if source_seen >= settings.max_results_per_source or total_seen >= settings.max_vacancies_per_run:
                        break
                    touch_job(db, job, progress=min(60, 10 + total_seen))
                    full = adapter.fetch_details(result)
                    item = adapter.normalize(full)
                    vacancy = _upsert_vacancy(db, item)
                    _upsert_source_snapshot(db, vacancy, item)
                    if db.scalar(select(RunVacancy).where(RunVacancy.run_id == run.id, RunVacancy.vacancy_id == vacancy.id)):
                        continue
                    db.add(RunVacancy(run_id=run.id, vacancy_id=vacancy.id, has_full_description=bool(vacancy.description)))
                    pre = scoring.deterministic_prescore({**item, "id": vacancy.id}, crit)
                    score = VacancyScore(user_id=job.user_id, run_id=run.id, vacancy_id=vacancy.id, profile_version_id=profile.id, criteria_version_id=crit_v.id, prescore=pre["score"], final_score=pre["score"], decision=pre["decision"], signals_json=dumps(pre), recommendations_json=dumps({"why_fits":"Deterministic criteria match","resume_angle":pre["positive_signals"],"risks":pre["red_flags"]}))
                    db.add(score)
                    db.flush()
                    scores.append({"user_id":job.user_id,"run_id":run.id,"vacancy_id":vacancy.id,"prescore":pre["score"],"has_full_description":bool(vacancy.description)})
                    source_seen += 1
                    total_seen += 1
            successful_sources += 1
            health = db.scalar(select(SourceHealth).where(SourceHealth.source == source)) or SourceHealth(source=source, status="ok")
            health.status="ok"; health.last_error=None; health.checked_at=utcnow(); db.add(health)
        except Exception as exc:
            errors.append({"source":source,"error":str(exc)})
            audit(db, "source_error", job.user_id, job.user_id, run_id=run.id, source=source, error=str(exc)[:500])
            health = db.scalar(select(SourceHealth).where(SourceHealth.source == source)) or SourceHealth(source=source, status="error")
            health.status="error"; health.last_error=str(exc); health.checked_at=utcnow(); db.add(health)
        finally:
            if adapter is not None and hasattr(adapter, "close"):
                adapter.close()
    avg = scoring.run_average(scores, user_id=job.user_id, run_id=run.id)
    run.average_prescore = avg
    candidates = scoring.codex_candidates(scores, user_id=job.user_id, run_id=run.id)[:settings.max_llm_candidates]
    outputs=[]
    llm_inputs=[]
    run_dir = settings.run_dir / str(run.id)
    run_dir.mkdir(parents=True, exist_ok=True)
    batch_size = max(1, settings.codex_batch_size)
    for start in range(0, len(candidates), batch_size):
        touch_job(db, job, progress=min(95, 60 + int(35 * start / max(1, len(candidates)))))
        for vacancy_id in candidates[start:start + batch_size]:
            score = db.scalar(select(VacancyScore).where(VacancyScore.user_id == job.user_id, VacancyScore.run_id == run.id, VacancyScore.vacancy_id == vacancy_id))
            vacancy = db.get(Vacancy, vacancy_id)
            pre = loads(score.signals_json)
            vacancy_payload = {"id": str(vacancy.id), "title": vacancy.title, "company": vacancy.company, "location": vacancy.location, "description": vacancy.description, "work_format": vacancy.work_format, "employment_type": vacancy.employment_type, "salary": loads(vacancy.salary_json), "requirements": vacancy.requirements, "responsibilities": vacancy.responsibilities, "conditions": vacancy.conditions, "skills": loads(vacancy.skills_json, [])}
            input_record = {"user_id": job.user_id, "run_id": run.id, "vacancy_id": vacancy.id, "profile_version_id": profile.id, "criteria_version_id": crit_v.id, "profile": profile_data, "criteria": crit, "vacancy": vacancy_payload, "deterministic_signals": pre}
            llm_inputs.append(input_record)
            prompt = codex_integration.build_vacancy_evaluation_prompt(profile_data, crit, vacancy_payload, pre)
            try:
                job.status="codex_scoring"
                job.progress=min(95, 60 + int(35 * (len(outputs)+1) / max(1, len(candidates))))
                touch_job(db, job, progress=job.progress)
                result = runner.run("vacancy_evaluation", prompt, lambda data, vid=str(vacancy.id): codex_integration.validate_codex_result(data, vid, crit), run_dir)
                score.final_score = result["score"]
                score.decision = result["decision"]
                score.recommendations_json = dumps(result)
                outputs.append(result)
            except Exception as exc:
                errors.append({"vacancy_id":vacancy_id,"error":str(exc)})
                audit(db, "codex_error", job.user_id, job.user_id, run_id=run.id, vacancy_id=vacancy_id, error=str(exc)[:500])
    if attempted_sources == 0 or successful_sources == 0:
        status = "failed"
    elif errors:
        status = "partial"
    else:
        status = "completed"
    run.status=status
    run.finished_at=utcnow()
    summary = {"errors":errors,"candidates":candidates,"average_prescore":avg,"attempted_sources":attempted_sources,"successful_sources":successful_sources}
    run.summary_json=dumps(summary)
    codex_integration.write_run_artifacts(run_dir, llm_inputs, outputs, errors, {"status":status,"average_prescore":avg,"llm_candidates":len(candidates)})
    audit(db, "search_finished", job.user_id, job.user_id, run_id=run.id, status=status, errors=len(errors))
    if schedule:
        schedule.last_run_at=utcnow()


def handle_cover_letter(db: Session, job: BackgroundJob, settings: Settings, runner) -> None:
    settings = settings_from_db(db, settings)
    payload=loads(job.payload_json)
    vacancy=db.get(Vacancy, payload["vacancy_id"])
    score=db.scalar(select(VacancyScore).where(VacancyScore.user_id==job.user_id, VacancyScore.vacancy_id==vacancy.id).order_by(VacancyScore.id.desc()))
    profile=db.scalar(select(ProfileVersion).where(ProfileVersion.user_id==job.user_id, ProfileVersion.confirmed==True).order_by(ProfileVersion.version.desc()))
    crit_v=db.scalar(select(CriteriaVersion).where(CriteriaVersion.user_id==job.user_id).order_by(CriteriaVersion.version.desc()))
    crit=loads(crit_v.data_json) if crit_v else criteria.DEFAULT_CRITERIA
    max_chars=int((crit.get("output") or {}).get("cover_letter_max_chars") or 300)
    prompt=codex_integration.build_cover_letter_prompt(loads(profile.data_json), {"title":vacancy.title,"company":vacancy.company,"description":vacancy.description}, loads(score.recommendations_json))
    run_dir = settings.run_dir / f"job-{job.id}"
    validator = lambda data: codex_integration.validate_cover_letter_result(data, max_chars=max_chars)
    try:
        result=runner.run("cover_letter", prompt, validator, run_dir)
    except codex_integration.CoverLetterTooLong as exc:
        shorten_prompt = codex_integration.build_cover_letter_shortening_prompt(exc.text, max_chars)
        result=runner.run("cover_letter_shorten", shorten_prompt, validator, run_dir)
    latest=db.scalar(select(CoverLetter).where(CoverLetter.user_id==job.user_id, CoverLetter.vacancy_id==vacancy.id).order_by(CoverLetter.version.desc()))
    db.add(CoverLetter(user_id=job.user_id, vacancy_id=vacancy.id, version=(latest.version if latest else 0)+1, text=result["text"]))

HANDLERS = {"resume_profile_extraction": handle_profile_extraction, "criteria_generation": handle_criteria_generation, "scheduled_search": handle_scheduled_search, "generate_cover_letter": handle_cover_letter}


def process_one(SessionLocal, settings: Settings, runner=None, adapter_factory=None) -> bool:
    worker_id = make_worker_id()
    with SessionLocal() as db:
        recover_stale_jobs(db)
        job = claim_next_job(db, worker_id=worker_id)
        if not job:
            db.commit()
            return False
        job_id = job.id
        db.commit()
    with SessionLocal() as db:
        effective = settings_from_db(db, settings)
        active_runner = runner or CodexRunner(effective)
        cleanup_old_run_artifacts(effective)
        job = db.get(BackgroundJob, job_id)
        try:
            if not job or job.worker_id != worker_id:
                return True
            job.status = "running"
            touch_job(db, job, progress=job.progress)
            if job.type == "scheduled_search":
                handle_scheduled_search(db, job, effective, active_runner, adapter_factory)
            elif job.type in HANDLERS:
                HANDLERS[job.type](db, job, effective, active_runner)
            else:
                raise RuntimeError(f"unknown job type {job.type}")
            result = db.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id, BackgroundJob.worker_id == worker_id)
                .values(
                    status="completed",
                    progress=100,
                    technical_error=None,
                    finished_at=utcnow(),
                    active_key=None,
                    worker_id=None,
                    lease_expires_at=None,
                )
            )
            if result.rowcount != 1:
                db.rollback()
                return True
            db.commit()
            return True
        except Exception as exc:
            db.rollback()
            message = str(exc)[:1000]
            with SessionLocal() as fail_db:
                failed = fail_db.get(BackgroundJob, job_id)
                if failed and failed.worker_id == worker_id:
                    failed.technical_error = message
                    failed.status = "queued" if failed.attempts < failed.max_attempts else "failed"
                    failed.finished_at = utcnow() if failed.status == "failed" else None
                    failed.active_key = None if failed.status in {"failed", "completed"} else failed.active_key
                    failed.worker_id = None
                    failed.lease_expires_at = None
                    audit(fail_db, "job_error", failed.user_id, failed.user_id, job_id=failed.id, error=message[:500])
                fail_db.commit()
            return True


def schedule_due_jobs(SessionLocal, settings: Settings, *, now: datetime | None = None) -> int:
    count=0
    now = now or utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    with SessionLocal() as db:
        settings = settings_from_db(db, settings)
        if not settings.global_search_enabled:
            return 0
        for sched in db.scalars(select(UserSchedule).where(UserSchedule.enabled == True, UserSchedule.next_run_at <= now)).all():
            active_key=f"{sched.user_id}:scheduled_search"
            if not db.scalar(select(BackgroundJob).where(BackgroundJob.active_key==active_key, BackgroundJob.status.in_(queue.ACTIVE_STATUSES))):
                enqueue_job(db, sched.user_id, "scheduled_search", {"schedule_id":sched.id}, active_key=active_key); count+=1
                sched.next_run_at = compute_next_run_at(max(settings.min_schedule_interval_days, sched.interval_days), sched.run_time, sched.timezone, now=now)
        db.commit()
    return count


def main() -> None:
    settings = load_settings(); settings.ensure_dirs(); SessionLocal = session_factory(settings)
    while True:
        with SessionLocal() as db:
            cleanup_old_run_artifacts(settings_from_db(db, settings))
        schedule_due_jobs(SessionLocal, settings)
        process_one(SessionLocal, settings)
        time.sleep(5)

if __name__ == "__main__":
    main()
