#!/usr/bin/env bash
set -euo pipefail

if PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -q >/dev/null 2>&1; then
  echo "PASS parser suite"
  exit 0
fi

echo "FAIL quoted separator: expected ['alpha', 'bravo;charlie', 'delta']"
exit 1
