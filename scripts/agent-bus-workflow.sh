#!/usr/bin/env bash
# M5 exit gate: the task graph, its stoppers, and artifact provenance end to
# end through the shipped daemon with a deterministic fake provider (no quota,
# no provider CLIs). Exits 3 with `skip:` when git is missing.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
exec python3 "${ROOT}/scripts/agent_bus_workflow.py" "$@"
