from __future__ import annotations

import json
from dataclasses import replace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AppSetting
from .settings import Settings
from .source_adapters import ADAPTERS

SETTINGS_KEYS = {
    "enabled_sources", "min_schedule_interval_days", "max_schedule_interval_days", "timezone",
    "http_delay_seconds", "http_jitter_seconds", "http_timeout_seconds", "http_retries",
    "max_search_queries", "max_results_per_source", "max_vacancies_per_run",
    "max_llm_candidates", "codex_batch_size", "resume_size_limit",
    "artifact_retention_days", "global_search_enabled", "codex_bin",
}

PLACEHOLDER_SESSION_SECRETS = {"", "dev-only-change-me", "change-me", "change-me-in-production", "please-change-me", "change-me-with-openssl-rand-hex-32"}


def loads(text: str | None, default: Any = None) -> Any:
    if not text:
        return {} if default is None else default
    return json.loads(text)


def _coerce(key: str, value: Any) -> Any:
    if key == "enabled_sources":
        if not isinstance(value, (list, tuple)):
            raise ValueError("enabled_sources must be a list")
        return tuple(x for x in value if x in ADAPTERS)
    if key in {"min_schedule_interval_days", "max_schedule_interval_days", "http_retries", "max_search_queries", "max_results_per_source", "max_vacancies_per_run", "max_llm_candidates", "codex_batch_size", "resume_size_limit", "artifact_retention_days"}:
        value = int(value)
        if value < 0:
            raise ValueError(f"{key} must be non-negative")
        return value
    if key in {"http_delay_seconds", "http_jitter_seconds", "http_timeout_seconds"}:
        value = float(value)
        if value < 0:
            raise ValueError(f"{key} must be non-negative")
        return value
    if key == "global_search_enabled":
        return bool(value)
    if key in {"timezone", "codex_bin"}:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
        return value.strip()
    raise KeyError(key)


def validate_settings_values(settings: Settings) -> Settings:
    if not settings.enabled_sources or any(source not in ADAPTERS for source in settings.enabled_sources):
        raise ValueError("enabled_sources must contain known sources")
    if settings.min_schedule_interval_days < 1:
        raise ValueError("min_schedule_interval_days must be at least 1")
    if settings.max_schedule_interval_days < settings.min_schedule_interval_days:
        raise ValueError("max_schedule_interval_days must be >= min_schedule_interval_days")
    try:
        ZoneInfo(settings.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be an IANA timezone") from exc
    positive_ints = {
        "http_retries": (0, 10),
        "max_search_queries": (1, 100),
        "max_results_per_source": (1, 500),
        "max_vacancies_per_run": (1, 5000),
        "max_llm_candidates": (0, 5000),
        "codex_batch_size": (1, 1000),
        "resume_size_limit": (1, 100 * 1024 * 1024),
        "artifact_retention_days": (1, 3650),
    }
    for key, (minimum, maximum) in positive_ints.items():
        value = getattr(settings, key)
        if value < minimum or value > maximum:
            raise ValueError(f"{key} must be between {minimum} and {maximum}")
    for key, maximum in {"http_delay_seconds": 60.0, "http_jitter_seconds": 60.0, "http_timeout_seconds": 120.0}.items():
        value = getattr(settings, key)
        if value < 0 or value > maximum:
            raise ValueError(f"{key} must be between 0 and {maximum}")
    if not settings.codex_bin.strip():
        raise ValueError("codex_bin must be non-empty")
    return settings


def build_effective_settings(base: Settings, raw_values: dict[str, Any]) -> Settings:
    values = {key: _coerce(key, value) for key, value in raw_values.items() if key in SETTINGS_KEYS}
    return validate_settings_values(replace(base, **values) if values else base)


def load_effective_settings(db: Session, base: Settings) -> Settings:
    values: dict[str, Any] = {}
    for row in db.scalars(select(AppSetting)).all():
        if row.key not in SETTINGS_KEYS:
            continue
        values[row.key] = loads(row.value_json)
    return build_effective_settings(base, values) if values else validate_settings_values(base)


def validate_runtime_settings(settings: Settings) -> None:
    if not settings.production:
        return
    if settings.database_url == "sqlite:///:memory:":
        return
    lowered = settings.session_secret.strip().lower()
    if lowered in PLACEHOLDER_SESSION_SECRETS or lowered.startswith(("change-me", "please-change", "dev-only")):
        raise RuntimeError("SESSION_SECRET must be changed before production startup")
    if len(settings.session_secret) < 32:
        raise RuntimeError("SESSION_SECRET must be at least 32 characters in production")


def cleanup_old_run_artifacts(settings: Settings, *, now=None) -> int:
    import time
    cutoff = (time.time() if now is None else now.timestamp()) - max(1, settings.artifact_retention_days) * 86400
    root = Path(settings.run_dir)
    if not root.exists():
        return 0
    removed = 0
    for child in root.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                import shutil
                shutil.rmtree(child)
                removed += 1
        except FileNotFoundError:
            continue
    return removed
