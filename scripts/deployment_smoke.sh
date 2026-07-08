#!/usr/bin/env bash
set -euo pipefail
ROOT=$(mktemp -d)
APP_DIR=${APP_DIR:-$(pwd)}
DATA_DIR=${DATA_DIR:-$ROOT/var/lib/jobs-catcher}
ENV_FILE=${ENV_FILE:-$ROOT/etc/jobs-catcher.env}
mkdir -p "$DATA_DIR/uploads" "$DATA_DIR/runs" "$(dirname "$ENV_FILE")"
cat >"$ENV_FILE" <<ENV
APP_BASE_URL=http://127.0.0.1:8000
ALLOWED_HOSTS=127.0.0.1,localhost,testserver
SESSION_SECRET=deployment-smoke-secret-not-production
DATABASE_URL=sqlite:///$DATA_DIR/jobs-catcher.sqlite3
DATA_DIR=$DATA_DIR
UPLOAD_DIR=$DATA_DIR/uploads
RUN_DIR=$DATA_DIR/runs
CODEX_BIN=python3
ENVIRONMENT=production
ENV
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
if [[ -x "$APP_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$APP_DIR/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python}"
fi
DATABASE_URL="$DATABASE_URL" "$PYTHON_BIN" -m alembic -c "$APP_DIR/alembic.ini" upgrade head
"$PYTHON_BIN" - <<'PYCHECK'
from pathlib import Path
from sqlalchemy import create_engine, text
import os
p = Path(os.environ['DATA_DIR']) / 'jobs-catcher.sqlite3'
assert p.exists(), p
engine = create_engine(os.environ['DATABASE_URL'])
with engine.begin() as conn:
    conn.execute(text("insert or replace into app_settings(key,value_json,updated_at) values('deployment_smoke','true',CURRENT_TIMESTAMP)"))
    value = conn.execute(text("select value_json from app_settings where key='deployment_smoke'")).scalar()
assert value == 'true'
probe = Path(os.environ['UPLOAD_DIR']) / '.write-test'
probe.write_text('ok')
probe.unlink()
print('deployment_smoke_ok', p)
PYCHECK
