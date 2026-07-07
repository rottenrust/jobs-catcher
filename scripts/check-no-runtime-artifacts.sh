#!/usr/bin/env bash
set -euo pipefail
bad=$(git ls-files | grep -E "(^|/)(\.env$|.*\.sqlite|.*\.db|uploads/|data/|runs/|\.venv/|__pycache__/|\.pytest_cache/)" || true)
if [[ -n "$bad" ]]; then echo "$bad"; exit 1; fi
if git grep -nE "(gho_[A-Za-z0-9_]+|BEGIN (RSA|OPENSSH) PRIVATE KEY)" -- . ":!.env.example"; then exit 1; fi
