from __future__ import annotations
import copy, json
import yaml

DEFAULT_CRITERIA = {
    "schema_version": 1, "name": "Основной профиль", "profile_summary": "",
    "search": {"desired_titles": [], "adjacent_titles": [], "directions": [], "queries": [], "locations": [], "work_formats": [], "employment_types": [], "seniority": [], "salary": {"minimum": None, "currency": "RUB", "gross": None}},
    "scoring": {"max_score": 22, "positive_rules": [], "red_flag_rules": [], "hard_reject_rules": [], "decision_thresholds": [{"decision": "Откликаться", "min_score": 16}, {"decision": "Адаптировать резюме", "min_score": 12}, {"decision": "Рассмотреть", "min_score": 8}, {"decision": "Мимо", "min_score": 0}]},
    "output": {"language": "ru", "cover_letter_max_chars": 300},
}
REQUIRED = {"schema_version", "name", "profile_summary", "search", "scoring", "output"}

def load_criteria(text: str, suffix: str) -> dict:
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        raise ValueError("unsupported criteria format")
    if not isinstance(data, dict):
        raise ValueError("criteria must be an object")
    return data

def validate_criteria(criteria: dict) -> dict:
    unknown = set(criteria) - (REQUIRED | {"version"})
    if unknown:
        raise ValueError(f"unknown fields: {sorted(unknown)}")
    missing = REQUIRED - set(criteria)
    if missing:
        raise ValueError(f"missing fields: {sorted(missing)}")
    scoring = criteria.get("scoring") or {}
    max_score = scoring.get("max_score")
    if max_score != 22:
        raise ValueError("max_score must be 22")
    thresholds = scoring.get("decision_thresholds") or []
    mins = [t.get("min_score") for t in thresholds]
    if mins != sorted(mins, reverse=True) or mins[-1:] != [0]:
        raise ValueError("decision thresholds must be descending and end at zero")
    return copy.deepcopy(criteria)

def next_version(existing: list[dict], payload: dict) -> dict:
    version = max([v.get("version", 0) for v in existing] or [0]) + 1
    out = copy.deepcopy(payload)
    out["version"] = version
    return out
