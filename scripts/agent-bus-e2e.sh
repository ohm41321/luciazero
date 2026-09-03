#!/usr/bin/env bash
# M4 exit gate: the pull-beta outcome flow end to end through the shipped
# daemon with a deterministic fake provider (no quota, no provider CLIs).
# Exits 3 with `skip:` when git is missing. Live providers are opt-in:
#   LZ_AGENT_BUS_LIVE=1 scripts/agent-bus-e2e.sh --live
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
exec python3 "${ROOT}/scripts/agent_bus_e2e.py" "$@"
