from __future__ import annotations
DECISIONS = ["Откликаться", "Адаптировать резюме", "Рассмотреть", "Мимо"]

def decision_for_score(score: int, criteria: dict) -> str:
    for row in criteria["scoring"]["decision_thresholds"]:
        if score >= row["min_score"]:
            return row["decision"]
    return "Мимо"

def deterministic_prescore(vacancy: dict, criteria: dict) -> dict:
    text = " ".join(str(vacancy.get(k, "")) for k in ["title", "description", "requirements", "responsibilities", "skills"]).lower()
    score, pos, miss, red, caps = 0, [], [], [], []
    signals = [("llm", 4), ("rag", 3), ("agent", 3), ("интеграц", 3), ("api", 2), ("анал", 3), ("требован", 2), ("prototype", 2), ("chatbot", 2)]
    for word, pts in signals:
        if word in text:
            score += pts; pos.append(word)
        else:
            miss.append(word)
    if any(w in text for w in ["qa", "support", "devops", "1c"]):
        red.append("non-target main function"); caps.append(8); score = min(score, 8)
    if not any(w in text for w in ["llm", "rag", "ai", "ии", "agent", "chatbot"]):
        caps.append(6); score = min(score, 6)
    score = max(0, min(criteria["scoring"].get("max_score", 22), score))
    return {"score": score, "positive_signals": pos, "missing_signals": miss, "red_flags": red, "caps": caps, "decision": decision_for_score(score, criteria)}

def _filtered(scores, user_id, run_id):
    return [s for s in scores if s.get("user_id") == user_id and s.get("run_id") == run_id and s.get("has_full_description")]

def run_average(scores: list[dict], *, user_id: int, run_id: int) -> float:
    rows = _filtered(scores, user_id, run_id)
    if not rows: return 0.0
    return sum(s["prescore"] for s in rows) / len(rows)

def codex_candidates(scores: list[dict], *, user_id: int, run_id: int) -> list[str]:
    avg = run_average(scores, user_id=user_id, run_id=run_id)
    return [s["vacancy_id"] for s in _filtered(scores, user_id, run_id) if s["prescore"] > avg]
