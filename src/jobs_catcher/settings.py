from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Settings:
    app_base_url: str = "http://127.0.0.1:8000"
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "testserver")
    session_secret: str = "dev-only-change-me"
    database_url: str = "sqlite:///./jobs-catcher.sqlite3"
    data_dir: Path = Path("data")
    upload_dir: Path = Path("data/uploads")
    run_dir: Path = Path("data/runs")
    codex_bin: str = "codex"
    environment: str = "development"
    min_schedule_interval_days: int = 1
    max_schedule_interval_days: int = 30
    enabled_sources: tuple[str, ...] = ("hh", "habr", "superjob", "rabota", "geekjob", "getmatch")
    http_delay_seconds: float = 1.0
    http_jitter_seconds: float = 0.5
    http_timeout_seconds: float = 15.0
    http_retries: int = 2
    max_search_queries: int = 8
    max_results_per_source: int = 20
    max_vacancies_per_run: int = 100
    max_llm_candidates: int = 25
    codex_batch_size: int = 10
    resume_size_limit: int = 10 * 1024 * 1024
    artifact_retention_days: int = 30
    global_search_enabled: bool = True

    @property
    def production(self) -> bool:
        return self.environment.lower() == "production"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)


def _tuple_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if not raw:
        return default
    return tuple(x.strip() for x in raw.split(",") if x.strip())


def load_settings() -> Settings:
    return Settings(
        app_base_url=os.getenv("APP_BASE_URL", "http://127.0.0.1:8000"),
        allowed_hosts=_tuple_env("ALLOWED_HOSTS", ("127.0.0.1", "localhost")),
        session_secret=os.getenv("SESSION_SECRET", "dev-only-change-me"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./jobs-catcher.sqlite3"),
        data_dir=Path(os.getenv("DATA_DIR", "data")),
        upload_dir=Path(os.getenv("UPLOAD_DIR", "data/uploads")),
        run_dir=Path(os.getenv("RUN_DIR", os.getenv("DATA_DIR", "data") + "/runs")),
        codex_bin=os.getenv("CODEX_BIN", "codex"),
        environment=os.getenv("ENVIRONMENT", "development"),
    )
