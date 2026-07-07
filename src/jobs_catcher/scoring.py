from __future__ import annotations

DECISIONS = ["Откликаться", "Адаптировать резюме", "Рассмотреть", "Мимо"]


def decision_for_score(score: int, criteria: dict) -> str:
    for row in criteria["scoring"]["decision_thresholds"]:
        if score >= row["min_score"]:
            return row["decision"]
    return "Мимо"


def _text(vacancy: dict) -> str:
    fields = ["title", "company", "location", "description", "requirements", "responsibilities", "conditions", "skills"]
    return " ".join(str(vacancy.get(k, "")) for k in fields).lower()


def _terms_match(text: str, terms: list[str], mode: str) -> bool:
    normalized = [t.lower().strip() for t in terms if str(t).strip()]
    if not normalized:
        return False
    if mode == "all":
        return all(t in text for t in normalized)
    return any(t in text for t in normalized)


def deterministic_prescore(vacancy: dict, criteria: dict) -> dict:
    text = _text(vacancy)
    scoring = criteria.get("scoring", {})
    max_score = int(scoring.get("max_score", 22))
    score = 0
    positive, missing, red_flags, caps = [], [], [], []

    hard_reject = False
    for rule in scoring.get("hard_reject_rules", []):
        terms = rule.get("terms") or rule.get("any_terms") or []
        if _terms_match(text, terms, "any"):
            hard_reject = True
            red_flags.append(rule.get("name", "hard_reject"))

    for rule in scoring.get("positive_rules", []):
        mode = "all" if rule.get("all_terms") else "any"
        terms = rule.get("all_terms") or rule.get("any_terms") or rule.get("terms") or []
        if _terms_match(text, terms, mode):
            weight = int(rule.get("weight", rule.get("score", 1)))
            score += max(0, weight)
            positive.append(rule.get("name", ", ".join(terms[:3]) or "positive"))
        else:
            missing.append(rule.get("name", ", ".join(terms[:3]) or "missing"))

    for rule in scoring.get("red_flag_rules", []):
        terms = rule.get("terms") or rule.get("any_terms") or []
        if _terms_match(text, terms, "any"):
            red_flags.append(rule.get("name", "red_flag"))
            penalty = int(rule.get("penalty", 0))
            if penalty:
                score -= abs(penalty)
            if rule.get("cap") is not None:
                caps.append(int(rule["cap"]))

    if hard_reject:
        caps.append(0)
    if caps:
        score = min(score, min(caps))
    score = max(0, min(max_score, score))
    return {"score": score, "positive_signals": positive, "missing_signals": missing, "red_flags": red_flags, "caps": caps, "decision": decision_for_score(score, criteria)}


def _filtered(scores, user_id, run_id):
    return [s for s in scores if s.get("user_id") == user_id and s.get("run_id") == run_id and s.get("has_full_description")]


def run_average(scores: list[dict], *, user_id: int, run_id: int) -> float:
    rows = _filtered(scores, user_id, run_id)
    if not rows:
        return 0.0
    return sum(s["prescore"] for s in rows) / len(rows)


def codex_candidates(scores: list[dict], *, user_id: int, run_id: int) -> list[str]:
    avg = run_average(scores, user_id=user_id, run_id=run_id)
    return [s["vacancy_id"] for s in _filtered(scores, user_id, run_id) if s["prescore"] > avg]
