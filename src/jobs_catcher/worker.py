from __future__ import annotations

import hashlib, json, time
from dataclasses import replace
from datetime import datetime, time as dt_time, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import codex_integration, criteria, scoring, queue
from .db import bootstrap_admin, create_schema, make_engine, make_session_factory, utcnow
from .dedup import normalize_title
from .models import (
    BackgroundJob, CoverLetter, CriteriaVersion, ProfileVersion, ResumeFile, SearchRun,
    SourceHealth, UserSchedule, Vacancy, VacancyScore, VacancySource, RunVacancy,
    AppSetting,
)
from .settings import Settings, load_settings
from .source_adapters import ADAPTERS


def dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)

def loads(text: str | None, default=None):
    if not text:
        return {} if default is None else default
    return json.loads(text)

SETTINGS_KEYS = {
    "enabled_sources", "min_schedule_interval_days", "max_schedule_interval_days",
    "http_delay_seconds", "http_jitter_seconds", "http_timeout_seconds",
    "http_retries", "max_search_queries", "max_results_per_source",
    "max_vacancies_per_run", "max_llm_candidates", "codex_batch_size",
    "resume_size_limit", "artifact_retention_days", "global_search_enabled",
}

def settings_from_db(db: Session, base: Settings) -> Settings:
    values = {}
    for row in db.scalars(select(AppSetting)).all():
        if row.key not in SETTINGS_KEYS:
            continue
        value = loads(row.value_json)
        if row.key == "enabled_sources":
            value = tuple(x for x in value if x in ADAPTERS)
        values[row.key] = value
    return replace(base, **values) if values else base

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


def recover_stale_jobs(db: Session, stale_after_seconds: int = 900) -> int:
    threshold = utcnow().timestamp() - stale_after_seconds
    jobs = db.scalars(select(BackgroundJob).where(BackgroundJob.status.in_(queue.ACTIVE_STATUSES - {"queued"}))).all()
    count = 0
    for job in jobs:
        if not job.heartbeat_at or job.heartbeat_at.timestamp() < threshold:
            job.status = "queued"; job.attempts += 1; count += 1
    return count


def claim_next_job(db: Session) -> BackgroundJob | None:
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.status == "queued").order_by(BackgroundJob.id).limit(1))
    if not job: return None
    job.status = "running"; job.started_at = utcnow(); job.heartbeat_at = utcnow(); job.attempts += 1; db.flush(); return job


def generate_criteria_from_profile(profile: dict, onboarding: dict) -> dict:
    titles = onboarding.get("desired_titles") or [profile.get("professional_title", "")]
    terms = [x for x in titles + onboarding.get("directions", []) + profile.get("skills", []) + onboarding.get("must_have", []) if x]
    crit = json.loads(json.dumps(criteria.DEFAULT_CRITERIA, ensure_ascii=False))
    crit["profile_summary"] = profile.get("professional_title", "")
    crit["search"].update({"desired_titles": titles, "adjacent_titles": onboarding.get("adjacent_roles", []), "directions": onboarding.get("directions", []), "queries": titles[:5], "locations": onboarding.get("cities", []), "work_formats": [onboarding.get("work_format", "any")], "employment_types": onboarding.get("employment_types", []), "seniority": [onboarding.get("seniority", "any")], "salary": {"minimum": int(onboarding.get("salary_minimum") or 0) or None, "currency": onboarding.get("currency", "RUB"), "gross": onboarding.get("gross")}})
    crit["scoring"]["positive_rules"] = [{"name":"target role/domain terms","weight":12,"any_terms":terms[:20]}, {"name":"must-have conditions","weight":5,"any_terms":onboarding.get("must_have", [])}, {"name":"seniority/work format","weight":5,"any_terms":[onboarding.get("seniority",""), onboarding.get("work_format","")]}]
    crit["scoring"]["red_flag_rules"] = [{"name":"stop factors","penalty":8,"cap":8,"terms":onboarding.get("stop_factors", []) + onboarding.get("undesired_duties", [])}]
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


def _upsert_vacancy(db: Session, item: dict) -> Vacancy:
    norm_title = normalize_title(item.get("title", "")); norm_company = (item.get("company") or "").lower().strip(); norm_loc = (item.get("location") or "").lower().strip()
    content_hash = item.get("content_hash") or hashlib.sha256((item.get("description") or "").encode()).hexdigest()
    existing = None
    if item.get("canonical_url"):
        existing = db.scalar(select(Vacancy).where(Vacancy.canonical_url == item["canonical_url"]))
    if not existing and content_hash:
        existing = db.scalar(select(Vacancy).where(Vacancy.content_hash == content_hash, Vacancy.normalized_title == norm_title, Vacancy.normalized_company == norm_company))
    if not existing:
        existing = db.scalar(select(Vacancy).where(Vacancy.normalized_title == norm_title, Vacancy.normalized_company == norm_company, Vacancy.normalized_location == norm_loc, Vacancy.content_hash == content_hash))
    if existing:
        return existing
    v = Vacancy(normalized_title=norm_title, normalized_company=norm_company, normalized_location=norm_loc, canonical_url=item.get("canonical_url"), content_hash=content_hash, title=item.get("title",""), company=item.get("company",""), location=item.get("location",""), description=item.get("description", ""))
    db.add(v); db.flush(); return v


def handle_scheduled_search(db: Session, job: BackgroundJob, settings: Settings, runner, adapter_factory=None) -> None:
    settings = settings_from_db(db, settings)
    profile = db.scalar(select(ProfileVersion).where(ProfileVersion.user_id == job.user_id, ProfileVersion.confirmed == True).order_by(ProfileVersion.version.desc()))
    crit_v = db.scalar(select(CriteriaVersion).where(CriteriaVersion.user_id == job.user_id).order_by(CriteriaVersion.version.desc()))
    if not profile or not crit_v: raise RuntimeError("profile and criteria required")
    crit = loads(crit_v.data_json); profile_data = loads(profile.data_json)
    run = SearchRun(user_id=job.user_id, job_id=job.id, status="running"); db.add(run); db.flush()
    queries = crit["search"].get("queries") or crit["search"].get("desired_titles") or [profile_data.get("professional_title", "")]
    schedule = db.scalar(select(UserSchedule).where(UserSchedule.user_id == job.user_id))
    requested_sources = loads(schedule.sources_json, list(settings.enabled_sources)) if schedule else list(settings.enabled_sources)
    selected_sources = [source for source in requested_sources if source in settings.enabled_sources and source in ADAPTERS]
    errors=[]; scores=[]
    total_seen = 0
    for source in selected_sources:
        if total_seen >= settings.max_vacancies_per_run:
            break
        try:
            Adapter = ADAPTERS[source]
            adapter = adapter_factory(source) if adapter_factory else Adapter(settings)
            source_seen = 0
            for query in queries[:settings.max_search_queries]:
                if source_seen >= settings.max_results_per_source or total_seen >= settings.max_vacancies_per_run:
                    break
                for result in adapter.search(query, loads(schedule.preferences_json, {}) if schedule else {}):
                    if source_seen >= settings.max_results_per_source or total_seen >= settings.max_vacancies_per_run:
                        break
                    full = adapter.fetch_details(result)
                    item = adapter.normalize(full)
                    vacancy = _upsert_vacancy(db, item)
                    src = db.scalar(select(VacancySource).where(VacancySource.source == source, VacancySource.external_id == item["external_id"]))
                    if not src:
                        db.add(VacancySource(vacancy_id=vacancy.id, source=source, external_id=item["external_id"], source_url=item["source_url"], raw_json=dumps(item.get("raw_metadata", {}))))
                    if db.scalar(select(RunVacancy).where(RunVacancy.run_id == run.id, RunVacancy.vacancy_id == vacancy.id)):
                        continue
                    db.add(RunVacancy(run_id=run.id, vacancy_id=vacancy.id, has_full_description=bool(vacancy.description)))
                    pre = scoring.deterministic_prescore({**item, "id": vacancy.id}, crit)
                    score = VacancyScore(user_id=job.user_id, run_id=run.id, vacancy_id=vacancy.id, profile_version_id=profile.id, criteria_version_id=crit_v.id, prescore=pre["score"], final_score=pre["score"], decision=pre["decision"], signals_json=dumps(pre), recommendations_json=dumps({"why_fits":"Deterministic criteria match","resume_angle":pre["positive_signals"],"risks":pre["red_flags"]}))
                    db.add(score); db.flush(); scores.append({"user_id":job.user_id,"run_id":run.id,"vacancy_id":vacancy.id,"prescore":pre["score"],"has_full_description":bool(vacancy.description)})
                    source_seen += 1; total_seen += 1
            health = db.scalar(select(SourceHealth).where(SourceHealth.source == source)) or SourceHealth(source=source, status="ok")
            health.status="ok"; health.last_error=None; health.checked_at=utcnow(); db.add(health)
        except Exception as exc:
            errors.append({"source":source,"error":str(exc)})
            health = db.scalar(select(SourceHealth).where(SourceHealth.source == source)) or SourceHealth(source=source, status="error")
            health.status="error"; health.last_error=str(exc); db.add(health)
    avg = scoring.run_average(scores, user_id=job.user_id, run_id=run.id); run.average_prescore = avg
    candidates = scoring.codex_candidates(scores, user_id=job.user_id, run_id=run.id)[:min(settings.max_llm_candidates, settings.codex_batch_size)]
    outputs=[]
    for vacancy_id in candidates:
        score = db.scalar(select(VacancyScore).where(VacancyScore.user_id == job.user_id, VacancyScore.run_id == run.id, VacancyScore.vacancy_id == vacancy_id))
        vacancy = db.get(Vacancy, vacancy_id); pre = loads(score.signals_json)
        prompt = codex_integration.build_vacancy_evaluation_prompt(profile_data, crit, {"id": str(vacancy.id), "title": vacancy.title, "company": vacancy.company, "description": vacancy.description}, pre)
        try:
            result = runner.run("vacancy_evaluation", prompt, lambda data, vid=str(vacancy.id): codex_integration.validate_codex_result(data, vid, crit), settings.run_dir / f"run-{run.id}")
            score.final_score = result["score"]; score.decision = result["decision"]; score.recommendations_json = dumps(result); outputs.append(result)
        except Exception as exc:
            errors.append({"vacancy_id":vacancy_id,"error":str(exc)})
    run.status="completed"; run.finished_at=utcnow(); run.summary_json=dumps({"errors":errors,"candidates":candidates,"average_prescore":avg})
    codex_integration.write_run_artifacts(settings.run_dir / str(run.id), [{"vacancy_id":x["vacancy_id"],"prescore":x["prescore"]} for x in scores if x["vacancy_id"] in candidates], outputs, errors, {"status":"completed","average_prescore":avg,"llm_candidates":len(candidates)})
    if schedule:
        schedule.last_run_at=utcnow()


def handle_cover_letter(db: Session, job: BackgroundJob, settings: Settings, runner) -> None:
    payload=loads(job.payload_json); vacancy=db.get(Vacancy, payload["vacancy_id"]); score=db.scalar(select(VacancyScore).where(VacancyScore.user_id==job.user_id, VacancyScore.vacancy_id==vacancy.id).order_by(VacancyScore.id.desc()))
    profile=db.scalar(select(ProfileVersion).where(ProfileVersion.user_id==job.user_id, ProfileVersion.confirmed==True).order_by(ProfileVersion.version.desc()))
    prompt=codex_integration.build_cover_letter_prompt(loads(profile.data_json), {"title":vacancy.title,"company":vacancy.company,"description":vacancy.description}, loads(score.recommendations_json))
    run_dir = settings.run_dir / f"job-{job.id}"
    try:
        result=runner.run("cover_letter", prompt, codex_integration.validate_cover_letter_result, run_dir)
    except ValueError as exc:
        if "too long" not in str(exc):
            raise
        shorten_prompt = codex_integration.build_cover_letter_shortening_prompt(getattr(exc, "text", "") or prompt, 300)
        result=runner.run("cover_letter_shorten", shorten_prompt, codex_integration.validate_cover_letter_result, run_dir)
    latest=db.scalar(select(CoverLetter).where(CoverLetter.user_id==job.user_id, CoverLetter.vacancy_id==vacancy.id).order_by(CoverLetter.version.desc()))
    db.add(CoverLetter(user_id=job.user_id, vacancy_id=vacancy.id, version=(latest.version if latest else 0)+1, text=result["text"]))

HANDLERS = {"resume_profile_extraction": handle_profile_extraction, "criteria_generation": handle_criteria_generation, "scheduled_search": handle_scheduled_search, "generate_cover_letter": handle_cover_letter}


def process_one(SessionLocal, settings: Settings, runner=None, adapter_factory=None) -> bool:
    runner = runner or CodexRunner(settings)
    with SessionLocal() as db:
        recover_stale_jobs(db); job = claim_next_job(db)
        if not job: db.commit(); return False
        db.commit()
    with SessionLocal() as db:
        job = db.get(BackgroundJob, job.id)
        try:
            job.heartbeat_at = utcnow(); job.status = "running"; db.flush()
            if job.type == "scheduled_search": handle_scheduled_search(db, job, settings, runner, adapter_factory)
            elif job.type in HANDLERS: HANDLERS[job.type](db, job, settings, runner)
            else: raise RuntimeError(f"unknown job type {job.type}")
            job.status="completed"; job.progress=100; job.technical_error=None; job.finished_at=utcnow(); job.active_key=None; db.commit(); return True
        except Exception as exc:
            job.technical_error = str(exc)[:1000]; job.status = "queued" if job.attempts < job.max_attempts else "failed"; job.finished_at = utcnow() if job.status == "failed" else None; job.active_key=None if job.status in {"failed","completed"} else job.active_key; db.commit(); return True


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
        schedule_due_jobs(SessionLocal, settings)
        process_one(SessionLocal, settings)
        time.sleep(5)

if __name__ == "__main__":
    main()
