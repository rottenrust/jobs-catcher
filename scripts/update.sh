#!/usr/bin/env bash
set -euo pipefail
APP_DIR=${APP_DIR:-/opt/jobs-catcher}
ENV_FILE=${ENV_FILE:-/etc/jobs-catcher.env}
RUNTIME_USER=${RUNTIME_USER:-jobscatcher}
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

if [[ ! -f "$ENV_FILE" ]]; then
  echo "$ENV_FILE is missing; cannot update safely" >&2
  exit 1
fi
load_env

run_as_runtime ./scripts/backup.sh "${DATABASE_URL#sqlite:///}"
PREV=$(git rev-parse HEAD)
rollback() {
  echo "Health check failed; rolling back to $PREV" >&2
  git reset --hard "$PREV"
  .venv/bin/python -m pip install -e .
  run_as_runtime .venv/bin/alembic -c alembic.ini upgrade head
  $SUDO systemctl restart jobs-catcher-web.service jobs-catcher-worker.service
}
trap rollback ERR

git pull --ff-only
.venv/bin/python -m pip install -e .
run_as_runtime .venv/bin/alembic -c alembic.ini upgrade head
$SUDO systemctl restart jobs-catcher-web.service jobs-catcher-worker.service
sleep 2
curl -fsS http://127.0.0.1:8000/health/ready >/dev/null
trap - ERR
