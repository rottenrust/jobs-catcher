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

def _list_of_strings(value, name: str, *, required: bool = True) -> None:
    if value is None and not required:
        return
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")

def _number(value, name: str, *, minimum: int | None = None, maximum: int | None = None, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} is below minimum")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} is above maximum")

def _validate_rule(rule: dict, kind: str, idx: int) -> None:
    if not isinstance(rule, dict):
        raise ValueError(f"{kind}[{idx}] must be an object")
    if not isinstance(rule.get("name"), str) or not rule["name"].strip():
        raise ValueError(f"{kind}[{idx}].name is required")
    if kind == "positive_rules":
        _number(rule.get("weight"), f"{kind}[{idx}].weight", minimum=1, maximum=22)
    else:
        _number(rule.get("penalty", 0), f"{kind}[{idx}].penalty", minimum=0, maximum=22)
        if "cap" in rule:
            _number(rule.get("cap"), f"{kind}[{idx}].cap", minimum=0, maximum=22)
    term_keys = [key for key in ("terms", "any_terms", "all_terms") if key in rule]
    if not term_keys:
        raise ValueError(f"{kind}[{idx}] must define terms")
    for key in term_keys:
        _list_of_strings(rule.get(key), f"{kind}[{idx}].{key}")

def validate_criteria(criteria: dict) -> dict:
    if not isinstance(criteria, dict):
        raise ValueError("criteria must be an object")
    unknown = set(criteria) - (REQUIRED | {"version"})
    if unknown:
        raise ValueError(f"unknown fields: {sorted(unknown)}")
    missing = REQUIRED - set(criteria)
    if missing:
        raise ValueError(f"missing fields: {sorted(missing)}")
    if criteria.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    if not isinstance(criteria.get("name"), str) or not criteria["name"].strip():
        raise ValueError("name is required")
    if not isinstance(criteria.get("profile_summary"), str):
        raise ValueError("profile_summary must be a string")
    search = criteria.get("search")
    if not isinstance(search, dict):
        raise ValueError("search must be an object")
    for key in ["desired_titles", "adjacent_titles", "directions", "queries", "locations", "work_formats", "employment_types", "seniority"]:
        _list_of_strings(search.get(key), f"search.{key}")
    salary = search.get("salary")
    if not isinstance(salary, dict):
        raise ValueError("search.salary must be an object")
    _number(salary.get("minimum"), "search.salary.minimum", minimum=0, nullable=True)
    if not isinstance(salary.get("currency"), str):
        raise ValueError("search.salary.currency must be a string")
    if salary.get("gross") is not None and not isinstance(salary.get("gross"), bool):
        raise ValueError("search.salary.gross must be boolean or null")
    scoring = criteria.get("scoring")
    if not isinstance(scoring, dict):
        raise ValueError("scoring must be an object")
    max_score = scoring.get("max_score")
    if max_score != 22:
        raise ValueError("max_score must be 22")
    for key in ["positive_rules", "red_flag_rules", "hard_reject_rules"]:
        rules = scoring.get(key)
        if not isinstance(rules, list):
            raise ValueError(f"scoring.{key} must be a list")
        for idx, rule in enumerate(rules):
            _validate_rule(rule, key, idx)
    thresholds = scoring.get("decision_thresholds") or []
    if not isinstance(thresholds, list) or len(thresholds) < 1:
        raise ValueError("decision thresholds must be a list")
    decisions = []
    mins = []
    for idx, item in enumerate(thresholds):
        if not isinstance(item, dict):
            raise ValueError(f"decision_thresholds[{idx}] must be an object")
        decision = item.get("decision")
        if not isinstance(decision, str) or not decision.strip():
            raise ValueError("decision is required")
        if decision in decisions:
            raise ValueError("decision thresholds must not contain duplicates")
        decisions.append(decision)
        _number(item.get("min_score"), f"decision_thresholds[{idx}].min_score", minimum=0, maximum=22)
        mins.append(item.get("min_score"))
    if mins != sorted(mins, reverse=True) or mins[-1:] != [0]:
        raise ValueError("decision thresholds must be descending and end at zero")
    output = criteria.get("output")
    if not isinstance(output, dict):
        raise ValueError("output must be an object")
    if not isinstance(output.get("language"), str):
        raise ValueError("output.language must be a string")
    _number(output.get("cover_letter_max_chars"), "output.cover_letter_max_chars", minimum=1, maximum=300)
    return copy.deepcopy(criteria)

def next_version(existing: list[dict], payload: dict) -> dict:
    version = max([v.get("version", 0) for v in existing] or [0]) + 1
    out = copy.deepcopy(payload)
    out["version"] = version
    return out
