#!/usr/bin/env bash
# M6 live smoke gate: one real Codex turn and one real Claude turn started by
# the dispatcher. Needs the provider CLIs and SPENDS QUOTA, so it refuses to
# run without --spend-quota and is never part of --full.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
exec python3 "${ROOT}/scripts/agent_bus_live.py" "$@"
