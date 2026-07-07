from __future__ import annotations
GROUPS = [("Откликаться", "ОТКЛИКАТЬСЯ", "Что подсветить"), ("Адаптировать резюме", "АДАПТИРОВАТЬ РЕЗЮМЕ", "Что изменить"), ("Рассмотреть", "РАССМОТРЕТЬ", "На что обратить внимание")]

def plain_text_selection(vacancies: list[dict]) -> str:
    parts=[]
    for decision, heading, label in GROUPS:
        rows=[v for v in vacancies if v.get("decision")==decision]
        if not rows: continue
        parts.append(heading)
        for i,v in enumerate(rows,1):
            parts.append(f"\n{i}. {v.get('title','')} — {v.get('company','')}\n{v.get('url') or v.get('canonical_url','')}\nПочему подходит: {v.get('why') or v.get('why_fits','')}\n{label}: {v.get('resume_angle') or v.get('what_to_check','')}")
    return "\n".join(parts).strip()

def validate_cover_letter(text: str, max_chars: int = 300) -> str:
    text = " ".join(text.split())
    if len(text) > max_chars: raise ValueError("cover letter is too long")
    return text
