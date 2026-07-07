#!/usr/bin/env bash
set -euo pipefail
APP_DIR=${APP_DIR:-/opt/jobs-catcher}
cd "$APP_DIR"
./scripts/backup.sh
PREV=$(git rev-parse HEAD || true)
git pull --ff-only
.venv/bin/python -m pip install -e .
.venv/bin/alembic -c alembic.ini upgrade head
sudo systemctl restart jobs-catcher-web.service jobs-catcher-worker.service
sleep 2
curl -fsS http://127.0.0.1:8000/health/ready >/dev/null || { echo "Health check failed; previous revision was $PREV"; exit 1; }
