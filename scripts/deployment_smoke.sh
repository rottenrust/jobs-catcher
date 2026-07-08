#!/usr/bin/env bash
set -euo pipefail
ROOT=$(mktemp -d)
SRC_DIR=$(pwd)
APP_DIR=${APP_DIR:-$ROOT/opt/jobs-catcher}
DATA_DIR=${DATA_DIR:-$ROOT/var/lib/jobs-catcher}
ENV_FILE=${ENV_FILE:-$ROOT/etc/jobs-catcher.env}
SYSTEMD_DIR=${SYSTEMD_DIR:-$ROOT/etc/systemd/system}
FAKE_BIN="$ROOT/bin"
mkdir -p "$FAKE_BIN" "$DATA_DIR/uploads" "$DATA_DIR/runs" "$(dirname "$ENV_FILE")" "$SYSTEMD_DIR"
SESSION_SECRET=${SESSION_SECRET:-$(${PYTHON_BIN:-python3} -c 'import secrets; print(secrets.token_hex(32))')}
cat >"$ENV_FILE" <<ENV
APP_BASE_URL=http://127.0.0.1:8000
ALLOWED_HOSTS=127.0.0.1,localhost,testserver
SESSION_SECRET=$SESSION_SECRET
DATABASE_URL=sqlite:///$DATA_DIR/jobs-catcher.sqlite3
DATA_DIR=$DATA_DIR
UPLOAD_DIR=$DATA_DIR/uploads
RUN_DIR=$DATA_DIR/runs
CODEX_BIN=python3
ENVIRONMENT=production
ENV
cat >"$FAKE_BIN/sudo" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
while [[ $# -gt 0 && ( "$1" == "-E" || "$1" == "-u" ) ]]; do
  if [[ "$1" == "-u" ]]; then shift 2; else shift; fi
done
cmd=${1:-}; shift || true
case "$cmd" in
  systemctl) echo "systemctl $*" >>"${SMOKE_SYSTEMCTL_LOG:-/dev/null}"; exit 0 ;;
  useradd|chown) exit 0 ;;
  rsync)
    args=("$@")
    src="${args[-2]}"; dst="${args[-1]}"
    mkdir -p "$dst"
    cp -a "$src"/. "$dst"/
    exit 0 ;;
  cp) command cp "$@" ;;
  install) command install "$@" ;;
  mkdir) command mkdir "$@" ;;
  cat) command cat "$@" ;;
  *) command "$cmd" "$@" ;;
esac
SH
chmod +x "$FAKE_BIN/sudo"
cat >"$FAKE_BIN/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${SMOKE_MUTATE_DB_ON_CURL:-0}" == "1" && -n "${SMOKE_DB_PATH:-}" ]]; then
  python3 - "$SMOKE_DB_PATH" <<'PYDB'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
with con:
    con.execute("update smoke_marker set value='bad'")
PYDB
fi
if [[ "${FAKE_CURL_FAIL:-0}" == "1" ]]; then exit 22; fi
exit 0
SH
chmod +x "$FAKE_BIN/curl"
PATH="$FAKE_BIN:$PATH" APP_DIR="$APP_DIR" DATA_DIR="$DATA_DIR" ENV_FILE="$ENV_FILE" SYSTEMD_DIR="$SYSTEMD_DIR" APP_USER="$(id -un)" RUNTIME_USER="$(id -un)" SUDO="$FAKE_BIN/sudo" PYTHON_BIN="${PYTHON_BIN:-python3}" bash "$SRC_DIR/scripts/install.sh"
[[ -x "$APP_DIR/.venv/bin/python" ]]
[[ -f "$DATA_DIR/jobs-catcher.sqlite3" ]]
PATH="$FAKE_BIN:$PATH" APP_DIR="$APP_DIR" DATA_DIR="$DATA_DIR" ENV_FILE="$ENV_FILE" SYSTEMD_DIR="$SYSTEMD_DIR" APP_USER="$(id -un)" RUNTIME_USER="$(id -un)" SUDO="$FAKE_BIN/sudo" SKIP_GIT_PULL=1 bash "$APP_DIR/scripts/update.sh"
DB_PATH="$DATA_DIR/jobs-catcher.sqlite3"
"$APP_DIR/.venv/bin/python" - "$DB_PATH" <<'PYMARK'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
with con:
    con.execute("create table if not exists smoke_marker (value text not null)")
    con.execute("delete from smoke_marker")
    con.execute("insert into smoke_marker(value) values ('good')")
PYMARK
OLD_SHA=$(git -C "$APP_DIR" rev-parse HEAD)
set +e
PATH="$FAKE_BIN:$PATH" APP_DIR="$APP_DIR" DATA_DIR="$DATA_DIR" ENV_FILE="$ENV_FILE" SYSTEMD_DIR="$SYSTEMD_DIR" APP_USER="$(id -un)" RUNTIME_USER="$(id -un)" SUDO="$FAKE_BIN/sudo" SKIP_GIT_PULL=1 FAKE_CURL_FAIL=1 SMOKE_MUTATE_DB_ON_CURL=1 SMOKE_DB_PATH="$DB_PATH" SMOKE_SYSTEMCTL_LOG="$ROOT/systemctl.log" bash "$APP_DIR/scripts/update.sh"
FAILED_UPDATE=$?
set -e
[[ "$FAILED_UPDATE" -ne 0 ]]
[[ "$(git -C "$APP_DIR" rev-parse HEAD)" == "$OLD_SHA" ]]
grep -q "systemctl restart" "$ROOT/systemctl.log"
"$APP_DIR/.venv/bin/python" - "$DB_PATH" <<'PYROLLBACK'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
value = con.execute("select value from smoke_marker").fetchone()[0]
assert value == 'good', value
PYROLLBACK
DATA_DIR="$DATA_DIR" DATABASE_URL="sqlite:///$DATA_DIR/jobs-catcher.sqlite3" UPLOAD_DIR="$DATA_DIR/uploads" "$APP_DIR/.venv/bin/python" - <<'PYCHECK'
from pathlib import Path
from sqlalchemy import create_engine, text
import os
p = Path(os.environ['DATA_DIR']) / 'jobs-catcher.sqlite3'
assert p.exists(), p
engine = create_engine(os.environ['DATABASE_URL'])
with engine.begin() as conn:
    current = conn.execute(text('select version_num from alembic_version')).scalar()
    assert current == '0002_rich_vacancy_fields_and_worker_leases'
probe = Path(os.environ['UPLOAD_DIR']) / '.write-test'
probe.write_text('ok')
probe.unlink()
print('deployment_smoke_ok', p)
PYCHECK
