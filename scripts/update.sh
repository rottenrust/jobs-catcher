#!/usr/bin/env bash
set -euo pipefail
APP_DIR=${APP_DIR:-/opt/jobs-catcher}
ENV_FILE=${ENV_FILE:-/etc/jobs-catcher.env}
RUNTIME_USER=${RUNTIME_USER:-jobscatcher}
APP_USER=${APP_USER:-${SUDO_USER:-$(id -un)}}
SUDO=${SUDO:-sudo}
cd "$APP_DIR"

load_env() {
  set -a
  if [[ -r "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
  else
    # shellcheck disable=SC1090
    source <($SUDO cat "$ENV_FILE")
  fi
  set +a
}
run_as_runtime() { $SUDO -E -u "$RUNTIME_USER" "$@"; }
run_as_app() { $SUDO -E -u "$APP_USER" "$@"; }

if [[ ! -f "$ENV_FILE" ]]; then
  echo "$ENV_FILE is missing; cannot update safely" >&2
  exit 1
fi
load_env

DB_PATH="${DATABASE_URL#sqlite:///}"
BACKUP_PATH=$(run_as_runtime ./scripts/backup.sh "$DB_PATH")
PREV=$(git rev-parse HEAD)
PREV_REVISION=$(run_as_runtime .venv/bin/alembic -c alembic.ini current 2>/dev/null | awk '{print $1}' || true)
rollback() {
  trap - ERR
  echo "Health check failed; rolling back to $PREV" >&2
  $SUDO systemctl stop jobs-catcher-web.service jobs-catcher-worker.service 2>/dev/null || true
  run_as_app git reset --hard "$PREV"
  run_as_app .venv/bin/python -m pip install -e .
  if [[ "${DATABASE_URL:-}" == sqlite:///* && -n "${BACKUP_PATH:-}" && -f "$BACKUP_PATH" ]]; then
    run_as_runtime cp "$BACKUP_PATH" "$DB_PATH"
  elif [[ -n "${PREV_REVISION:-}" ]]; then
    run_as_runtime .venv/bin/alembic -c alembic.ini downgrade "$PREV_REVISION"
  fi
  $SUDO systemctl restart jobs-catcher-web.service jobs-catcher-worker.service
}
trap rollback ERR

if [[ "${SKIP_GIT_PULL:-0}" != "1" ]]; then
  run_as_app git pull --ff-only
fi
run_as_app .venv/bin/python -m pip install -e .
run_as_runtime .venv/bin/alembic -c alembic.ini upgrade head
$SUDO systemctl restart jobs-catcher-web.service jobs-catcher-worker.service
sleep 2
curl -fsS "${APP_BASE_URL:-http://127.0.0.1:8000}/health/ready" >/dev/null
trap - ERR
