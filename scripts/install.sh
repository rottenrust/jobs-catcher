#!/usr/bin/env bash
set -euo pipefail
sudo useradd --system --home /var/lib/jobs-catcher --shell /usr/sbin/nologin jobscatcher || true
sudo mkdir -p /opt/jobs-catcher /var/lib/jobs-catcher/uploads /var/lib/jobs-catcher/runs
sudo chown -R jobscatcher:jobscatcher /var/lib/jobs-catcher
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
sudo cp deploy/systemd/jobs-catcher-*.service /etc/systemd/system/
sudo systemctl daemon-reload
echo "Create /etc/jobs-catcher.env from .env.example, then enable services."
