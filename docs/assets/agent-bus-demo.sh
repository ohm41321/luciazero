#!/usr/bin/env bash
# Demonstrates the shipped Agent Bus pull beta: three agents, two worktrees,
# one daemon (restarted mid-flow), no manual message copying. Runs the same
# driver as `./test.sh --agent-bus-e2e`, so the demo cannot drift from what
# the gate proves. Everything lives in a temporary directory that is removed
# at the end; the real ~/.luciazero, ~/.codex and ~/.claude are never touched.
#
#   bash docs/assets/agent-bus-demo.sh              # fake provider, no quota
#   LZ_AGENT_BUS_LIVE=1 bash docs/assets/agent-bus-demo.sh --live   # real models
#   bash docs/assets/agent-bus-demo.sh --live --dry-run             # print the plan
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIM=$'\033[2m'; OFF=$'\033[0m'
printf '%s# Luciazero Agent Bus — pull-beta demo (%s)%s\n' "${DIM}" "$(python3 --version 2>&1)" "${OFF}"
export PYTHONDONTWRITEBYTECODE=1
exec python3 "${ROOT}/scripts/agent_bus_e2e.py" --narrate "$@"
