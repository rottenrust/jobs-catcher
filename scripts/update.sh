#!/usr/bin/env bash
set -euo pipefail
APP_DIR=${APP_DIR:-/opt/jobs-catcher}
ENV_FILE=${ENV_FILE:-/etc/jobs-catcher.env}
cd "$APP_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "$ENV_FILE is missing; cannot update safely" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

./scripts/backup.sh "${DATABASE_URL#sqlite:///}"
PREV=$(git rev-parse HEAD)
rollback() {
  echo "Health check failed; rolling back to $PREV" >&2
  git reset --hard "$PREV"
  .venv/bin/python -m pip install -e .
  .venv/bin/alembic -c alembic.ini upgrade head
  sudo systemctl restart jobs-catcher-web.service jobs-catcher-worker.service
}
trap rollback ERR

git pull --ff-only
.venv/bin/python -m pip install -e .
.venv/bin/alembic -c alembic.ini upgrade head
sudo systemctl restart jobs-catcher-web.service jobs-catcher-worker.service
sleep 2
curl -fsS http://127.0.0.1:8000/health/ready >/dev/null
trap - ERR
