#!/usr/bin/env bash
set -euo pipefail
DB=${1:-/var/lib/jobs-catcher/jobs-catcher.sqlite3}
OUT=${2:-$(dirname "$DB")/backup-$(date +%Y%m%d%H%M%S).sqlite3}
python3 - "$DB" "$OUT" <<PY
import sqlite3, sys
src, out = sys.argv[1], sys.argv[2]
con = sqlite3.connect(src)
dst = sqlite3.connect(out)
with dst:
    con.backup(dst)
print(out)
PY
