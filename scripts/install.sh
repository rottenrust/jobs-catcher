#!/usr/bin/env bash
set -euo pipefail
APP_DIR=${APP_DIR:-/opt/jobs-catcher}
DATA_DIR=${DATA_DIR:-/var/lib/jobs-catcher}
ENV_FILE=${ENV_FILE:-/etc/jobs-catcher.env}
RUNTIME_USER=${RUNTIME_USER:-jobscatcher}

if [[ "$(pwd)" != "$APP_DIR" ]]; then
  sudo mkdir -p "$APP_DIR"
  sudo rsync -a --delete --exclude .venv --exclude data --exclude uploads ./ "$APP_DIR"/
  cd "$APP_DIR"
fi

sudo useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$RUNTIME_USER" 2>/dev/null || true
sudo mkdir -p "$DATA_DIR/uploads" "$DATA_DIR/runs"
sudo chown -R "$RUNTIME_USER:$RUNTIME_USER" "$DATA_DIR"
python3.12 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install -e "$APP_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  sudo install -m 600 -o root -g root .env.example "$ENV_FILE"
  echo "Created $ENV_FILE. Edit SESSION_SECRET, APP_BASE_URL, ALLOWED_HOSTS and DATABASE_URL, then rerun scripts/install.sh." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

sudo cp deploy/systemd/jobs-catcher-*.service /etc/systemd/system/
sudo systemctl daemon-reload
"$APP_DIR/.venv/bin/alembic" -c "$APP_DIR/alembic.ini" upgrade head
sudo systemctl enable jobs-catcher-web.service jobs-catcher-worker.service
sudo systemctl restart jobs-catcher-web.service jobs-catcher-worker.service
sleep 2
curl -fsS "${APP_BASE_URL:-http://127.0.0.1:8000}/health/ready" >/dev/null || curl -fsS http://127.0.0.1:8000/health/ready >/dev/null
