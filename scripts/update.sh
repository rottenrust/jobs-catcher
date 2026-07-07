#!/usr/bin/env bash
set -euo pipefail
git pull --ff-only
.venv/bin/python -m pip install -e .
.venv/bin/alembic upgrade head || true
sudo systemctl restart jobs-catcher-web jobs-catcher-worker
