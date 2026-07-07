from __future__ import annotations
import json, types, pytest
from jobs_catcher import codex_integration, criteria

def valid(v='v'):
    return {"vacancy_id":v,"score":17,"decision":"Откликаться","confidence":"high","role_summary":"","matching_signals":[],"missing_signals":[],"red_flags":[],"applied_caps":[],"why_fits":"","why_not_or_risks":"","what_to_check_before_apply":[],"resume_angle":[],"cover_letter_points":[],"prescore_comment":""}

def test_codex_stdout_must_be_strict_json_only_and_no_extra_fields():
    with pytest.raises(ValueError): codex_integration.parse_codex_stdout('prefix '+json.dumps(valid()), 'v', criteria.DEFAULT_CRITERIA)
    bad=valid(); bad['extra']='x'
    with pytest.raises(ValueError): codex_integration.parse_codex_stdout(json.dumps(bad), 'v', criteria.DEFAULT_CRITERIA)

def test_codex_subprocess_uses_shell_false_and_retries_once():
    calls=[]
    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if len(calls)==1:
            return types.SimpleNamespace(returncode=0, stdout='not json', stderr='resume secret')
        return types.SimpleNamespace(returncode=0, stdout=json.dumps(valid()), stderr='')
    out=codex_integration.run_codex_with_retry(fake_run, ['codex','exec'], 'v', criteria.DEFAULT_CRITERIA, timeout=5)
    assert out['vacancy_id']=='v' and len(calls)==2
    assert all(k['shell'] is False and k['timeout']==5 and k['capture_output'] is True for _,k in calls)
