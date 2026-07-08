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

run_as_runtime ./scripts/backup.sh "${DATABASE_URL#sqlite:///}"
PREV=$(git rev-parse HEAD)
rollback() {
  echo "Health check failed; rolling back to $PREV" >&2
  run_as_app git reset --hard "$PREV"
  run_as_app .venv/bin/python -m pip install -e .
  run_as_runtime .venv/bin/alembic -c alembic.ini upgrade head
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
