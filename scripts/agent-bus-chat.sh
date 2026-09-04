#!/usr/bin/env bash
# Two managed agents answering each other, printed as it happens.
#
# Every turn starts a real model, so it refuses to run without --spend-quota
# and stops at --turns. `--rehearse` runs the identical loop against the
# offline worker for no quota.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "${ROOT}/scripts/agent_bus_chat.py" "$@"
