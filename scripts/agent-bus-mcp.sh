#!/usr/bin/env bash
# M2 exit gate for the Luciazero Agent Bus: real Codex and Claude CLIs
# discover the shipped daemon and one structured message crosses it.
# Offline by default; LZ_AGENT_BUS_LIVE=1 or --live spends provider quota.
# Exit codes: 0 pass, 1 fail, 3 skip (provider CLI missing), 64 usage.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIVE=""
ONLY=""
if [ "${LZ_AGENT_BUS_LIVE:-0}" = 1 ]; then
  LIVE="--live"
fi
for ARG in "$@"; do
  case "${ARG}" in
    --live) LIVE="--live" ;;
    --only=codex|--only=claude) ONLY="${ARG}" ;;
    --offline) ;;
    *) echo "usage: scripts/agent-bus-mcp.sh [--offline|--live] [--only=codex|--only=claude]" >&2; exit 64 ;;
  esac
done

# Plain strings, not arrays: an empty array under `set -u` is an unbound
# variable on the bash 3.2 that stock macOS ships.
MISSING=""
command -v codex >/dev/null 2>&1 || MISSING="${MISSING} codex"
command -v claude >/dev/null 2>&1 || MISSING="${MISSING} claude"
if [ -n "${MISSING}" ]; then
  echo "skip: required CLI not found:${MISSING}" >&2
  exit 3
fi

# shellcheck disable=SC2086  # LIVE/ONLY are single flags or empty on purpose
PYTHONDONTWRITEBYTECODE=1 exec python3 "${ROOT}/scripts/agent_bus_mcp_gate.py" ${LIVE} ${ONLY}
