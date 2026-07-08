from __future__ import annotations
import pytest
from jobs_catcher import auth, criteria, scoring, dedup, codex_integration, queue, audit

@pytest.mark.parametrize("score,decision", [(16,"Откликаться"),(12,"Адаптировать резюме"),(8,"Рассмотреть"),(7,"Мимо"),(0,"Мимо")])
def test_all_decision_thresholds(score, decision):
    assert scoring.decision_for_score(score, criteria.DEFAULT_CRITERIA) == decision

def test_prescore_bounds_caps_and_equality_exclusion():
    c={**criteria.DEFAULT_CRITERIA, "scoring": {**criteria.DEFAULT_CRITERIA["scoring"], "positive_rules": [{"name":"target","weight":12,"any_terms":["inventory","warehouse"]}], "red_flag_rules": [{"name":"night","penalty":8,"cap":8,"terms":["night"]}], "hard_reject_rules": []}}
    high=scoring.deterministic_prescore({"title":"Warehouse manager","description":"inventory process improvement"}, c)
    low=scoring.deterministic_prescore({"title":"Night guard","description":"night shifts"}, c)
    assert 0 <= high["score"] <= 22 and high["score"] > low["score"]
    assert low["caps"] and low["score"] <= 8
    rows=[{"user_id":1,"run_id":1,"vacancy_id":"eq","prescore":10,"has_full_description":True},{"user_id":1,"run_id":1,"vacancy_id":"hi","prescore":12,"has_full_description":True},{"user_id":1,"run_id":1,"vacancy_id":"no","prescore":22,"has_full_description":False}]
    assert scoring.run_average([], user_id=1, run_id=1) == 0
    assert scoring.codex_candidates(rows, user_id=1, run_id=1) == ["hi"]

def test_criteria_yaml_invalid_thresholds_and_immutability():
    y="""schema_version: 1
name: Test
profile_summary: ''
search: {desired_titles: [], adjacent_titles: [], directions: [], queries: [], locations: [], work_formats: [], employment_types: [], seniority: [], salary: {minimum: null, currency: RUB, gross: null}}
scoring: {max_score: 22, positive_rules: [], red_flag_rules: [], hard_reject_rules: [], decision_thresholds: [{decision: Мимо, min_score: 0}]}
output: {language: ru, cover_letter_max_chars: 300}
"""
    loaded=criteria.load_criteria(y,'.yaml')
    with pytest.raises(ValueError): criteria.validate_criteria(loaded)
    bad=criteria.DEFAULT_CRITERIA.copy(); bad["scoring"]={**criteria.DEFAULT_CRITERIA["scoring"], "decision_thresholds":[{"decision":"Мимо","min_score":0},{"decision":"Откликаться","min_score":16}]}
    with pytest.raises(ValueError): criteria.validate_criteria(bad)
    missing={"schema_version":1}
    with pytest.raises(ValueError): criteria.validate_criteria(missing)
    unknown={**criteria.DEFAULT_CRITERIA, "surprise": True}
    with pytest.raises(ValueError): criteria.validate_criteria(unknown)
    base=criteria.next_version([], criteria.DEFAULT_CRITERIA); new=criteria.next_version([base], {**criteria.DEFAULT_CRITERIA, "name":"New"})
    assert base["name"] == "Основной профиль" and new["version"] == 2

def test_dedup_merges_canonical_url_and_preserves_links():
    rows=[{"id":"1","title":"AI","company":"A","location":"M","canonical_url":"https://e/v?utm_source=x","url":"https://e/v?utm_source=x","content_hash":"h"},{"id":"2","title":"AI","company":"A","location":"M","canonical_url":"https://e/v","url":"https://other/v","content_hash":"h"}]
    out=dedup.deduplicate(rows)
    assert len(out)==1 and len(out[0]["source_links"])==2

def test_codex_validation_rejects_wrong_id_score_and_decision():
    base={"vacancy_id":"v","score":17,"decision":"Откликаться","confidence":"high","role_summary":"","matching_signals":[],"missing_signals":[],"red_flags":[],"applied_caps":[],"why_fits":"","why_not_or_risks":"","what_to_check_before_apply":[],"resume_angle":[],"cover_letter_points":[],"prescore_comment":""}
    for patch in [{"vacancy_id":"x"},{"score":23},{"score":1,"decision":"Откликаться"},{"confidence":"sure"}]:
        bad={**base, **patch}
        with pytest.raises(ValueError): codex_integration.validate_codex_result(bad,"v",criteria.DEFAULT_CRITERIA)
    cmd=codex_integration.codex_command("codex;rm -rf /","/tmp/run")
    assert isinstance(cmd, list) and cmd[0] == "codex;rm -rf /"

def test_queue_idempotency_stale_recovery_and_rate_limit_partitioning():
    q=queue.JobQueue(); a=q.enqueue(1,"scheduled_search",{"heartbeat":0}); b=q.enqueue(1,"scheduled_search",{"heartbeat":1}); c=q.enqueue(2,"scheduled_search",{"heartbeat":1})
    assert a==b and c!=a
    q.jobs[a]["status"]="running"; assert q.recover_stale(1000)==1 and q.jobs[a]["status"]=="queued"
    limiter=auth.LoginRateLimiter()
    for i in range(5): limiter.record_failure("alice",i)
    assert limiter.is_blocked("alice",10) and not limiter.is_blocked("bob",10)

def test_audit_redacts_broad_sensitive_fields():
    event=audit.redact_event({"session_token":"x","api_key":"k","letter":"full","resume_text":"cv","actor_id":1,"nested":{"token":"t"}})
    assert all(event[k]=="[REDACTED]" for k in ["session_token","api_key","letter","resume_text"])
    assert event["nested"]["token"] == "[REDACTED]"
    assert event["actor_id"] == 1
