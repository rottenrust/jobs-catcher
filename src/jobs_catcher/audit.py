from __future__ import annotations
SENSITIVE_KEYS = {"password", "session", "token", "session_token", "resume_text", "letter", "api_key", "secret"}

def _redact_value(value):
    if isinstance(value, dict):
        return redact_event(value)
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    return value

def redact_event(event: dict) -> dict:
    out={}
    for k,v in event.items():
        low=k.lower()
        out[k] = "[REDACTED]" if any(s in low for s in SENSITIVE_KEYS) else _redact_value(v)
    return out
