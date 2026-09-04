#!/usr/bin/env bash
# M6 exit gate: the dispatcher is killed mid-run, restarted, and the work still
# reaches exactly one outcome. Offline, no provider CLIs, no quota.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
exec python3 "${ROOT}/scripts/agent_bus_dispatch.py" "$@"
