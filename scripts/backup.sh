#!/usr/bin/env bash
set -euo pipefail
DB=${1:-/var/lib/jobs-catcher/jobs-catcher.sqlite3}
OUT=${2:-jobs-catcher-backup-$(date +%Y%m%d%H%M%S).sqlite3}
sqlite3 "$DB" ".backup '$OUT'"
echo "$OUT"
