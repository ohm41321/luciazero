#!/usr/bin/env bash
# M0 feasibility gate for the Luciazero Agent Bus. The default path is
# offline and never invokes a model. Set LZ_AGENT_BUS_LIVE=1, or pass --live,
# only after approving provider quota use.
# Exit codes: 0 pass, 1 fail, 3 skip (provider CLI missing), 64 usage.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE=offline

if [ "${LZ_AGENT_BUS_LIVE:-0}" = 1 ]; then
  MODE=live
fi

if [ "$#" -gt 1 ]; then
  echo "usage: scripts/agent-bus-spike.sh [--offline|--live]" >&2
  exit 64
fi

case "${1:-}" in
  ""|--offline) ;;
  --live) MODE=live ;;
  *)
    echo "usage: scripts/agent-bus-spike.sh [--offline|--live]" >&2
    exit 64
    ;;
esac

# A gate that cannot run is not green: missing provider CLIs exit 3 with a
# "skip:" reason so a caller can tell "not provable here" from "failed".
# Plain strings, not arrays: an empty array under `set -u` is an unbound
# variable on the bash 3.2 that stock macOS ships.
MISSING=""
command -v codex >/dev/null 2>&1 || MISSING="${MISSING} codex"
command -v claude >/dev/null 2>&1 || MISSING="${MISSING} claude"
if [ -n "${MISSING}" ]; then
  echo "skip: required CLI not found:${MISSING}" >&2
  exit 3
fi

PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  "${ROOT}/scripts/agent_bus_spike.py"

ARGS=(--root "${ROOT}")
if [ "${MODE}" = live ]; then
  ARGS+=(--live)
fi

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT}/scripts/agent_bus_spike.py" "${ARGS[@]}"
