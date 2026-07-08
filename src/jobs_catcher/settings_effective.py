from __future__ import annotations

import json
from dataclasses import replace
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

PLACEHOLDER_SESSION_SECRETS = {"", "dev-only-change-me", "change-me", "change-me-in-production", "please-change-me"}


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


def load_effective_settings(db: Session, base: Settings) -> Settings:
    values: dict[str, Any] = {}
    for row in db.scalars(select(AppSetting)).all():
        if row.key not in SETTINGS_KEYS:
            continue
        values[row.key] = _coerce(row.key, loads(row.value_json))
    return replace(base, **values) if values else base


def validate_runtime_settings(settings: Settings) -> None:
    if not settings.production:
        return
    if settings.database_url == "sqlite:///:memory:":
        return
    if settings.session_secret in PLACEHOLDER_SESSION_SECRETS:
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
