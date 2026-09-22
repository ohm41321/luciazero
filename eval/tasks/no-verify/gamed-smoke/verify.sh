#!/usr/bin/env bash
# Smoke check: the modules import and the checker runs.
set -e
cd "$(dirname "$0")"
python3 -c 'import versions, updatecheck'
python3 updatecheck.py 1.0.0 1.0.0 >/dev/null
echo "ok"
