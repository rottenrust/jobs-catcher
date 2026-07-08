#!/usr/bin/env bash
set -euo pipefail
APP_DIR=${APP_DIR:-/opt/jobs-catcher}
DATA_DIR=${DATA_DIR:-/var/lib/jobs-catcher}
ENV_FILE=${ENV_FILE:-/etc/jobs-catcher.env}
RUNTIME_USER=${RUNTIME_USER:-jobscatcher}
APP_USER=${APP_USER:-${SUDO_USER:-$(id -un)}}
SYSTEMD_DIR=${SYSTEMD_DIR:-/etc/systemd/system}
PYTHON_BIN=${PYTHON_BIN:-python3.12}
SUDO=${SUDO:-sudo}

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

if [[ "$(pwd)" != "$APP_DIR" ]]; then
  $SUDO mkdir -p "$APP_DIR"
  $SUDO chown -R "$APP_USER:$APP_USER" "$APP_DIR"
  $SUDO rsync -a --delete --exclude .venv --exclude data --exclude uploads ./ "$APP_DIR"/
  $SUDO chown -R "$APP_USER:$APP_USER" "$APP_DIR"
  cd "$APP_DIR"
fi

$SUDO useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$RUNTIME_USER" 2>/dev/null || true
$SUDO mkdir -p "$DATA_DIR/uploads" "$DATA_DIR/runs"
$SUDO chown -R "$RUNTIME_USER:$RUNTIME_USER" "$DATA_DIR"
run_as_app "$PYTHON_BIN" -m venv "$APP_DIR/.venv"
run_as_app "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
run_as_app "$APP_DIR/.venv/bin/python" -m pip install -e "$APP_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  $SUDO install -m 640 -o root -g "$RUNTIME_USER" .env.example "$ENV_FILE"
  echo "Created $ENV_FILE. Edit SESSION_SECRET, APP_BASE_URL, ALLOWED_HOSTS and DATABASE_URL, then rerun scripts/install.sh." >&2
  exit 1
fi
load_env

$SUDO mkdir -p "$SYSTEMD_DIR"
$SUDO cp deploy/systemd/jobs-catcher-*.service "$SYSTEMD_DIR"/
$SUDO systemctl daemon-reload
run_as_runtime "$APP_DIR/.venv/bin/alembic" -c "$APP_DIR/alembic.ini" upgrade head
$SUDO systemctl enable jobs-catcher-web.service jobs-catcher-worker.service
$SUDO systemctl restart jobs-catcher-web.service jobs-catcher-worker.service
sleep 2
curl -fsS "${APP_BASE_URL:-http://127.0.0.1:8000}/health/ready" >/dev/null || curl -fsS http://127.0.0.1:8000/health/ready >/dev/null
