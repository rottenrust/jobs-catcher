# Jobs Catcher

Jobs Catcher is a closed multi-user FastAPI service for resume-driven vacancy discovery, deterministic prescoring, Codex-assisted evaluation, plain-text shortlist export, and short cover-letter generation.

## Features
- Bootstrap `admin/admin` with mandatory password change.
- Admin-created users only; no self-registration.
- Argon2id password hashing, server-side sessions, CSRF, rate limiting, security headers.
- PDF/DOCX upload validation and DOCX/PDF text extraction boundaries.
- Onboarding, profile confirmation, versioned JSON/YAML criteria.
- Fixture-backed adapters for hh.ru, Habr Career, SuperJob, Работа.ру, GeekJob, GetMatch.
- Conservative deduplication, deterministic 0-22 prescore, `prescore > average` Codex candidate rule.
- Vacancy categories: Откликаться, Адаптировать резюме, Рассмотреть, Мимо.
- Viewed state, plain-text подборка, cover letters <=300 chars.
- Systemd web/worker units, Nginx reverse proxy, health endpoints.

## Local Run
```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/uvicorn jobs_catcher.asgi:app --reload
```

Open `/health/live` and login with `admin/admin`. Change the password immediately.

## Codex CLI
The Codex wrapper builds an argument list for `codex exec -m gpt-5.4-mini -c model_reasoning_effort="low" -C <run_dir>`; CI uses mocked/validated JSON and never calls live Codex.

## Tests
```bash
.venv/bin/python -m pytest
.venv/bin/python -m jobs_catcher.smoke
```

## Deployment
Copy `.env.example` to `/etc/jobs-catcher.env`, set a real `SESSION_SECRET`, install with `scripts/install.sh`, enable `jobs-catcher-web.service` and `jobs-catcher-worker.service`, and put Nginx in front of `127.0.0.1:8000`.

## Backup/Restore
Use `scripts/backup.sh /var/lib/jobs-catcher/jobs-catcher.sqlite3`. Restore by stopping services, replacing the SQLite file from a verified backup, fixing ownership to `jobscatcher`, and starting services.

## HTML Parsing Limits
Adapters use polite sequential HTML fetching in production and fixtures in CI. CAPTCHA, 403, 429, and anti-bot pages are treated as operational errors. The project must not bypass protections.

## Screenshots
Placeholders: `docs/screenshots/login.png`, `dashboard.png`, `vacancies.png`, `admin.png`.
