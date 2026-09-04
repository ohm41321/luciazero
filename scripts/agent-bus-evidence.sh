#!/usr/bin/env bash
# Export one workflow's record set from a bus state directory, for the M4
# decision log. Read-only: it never migrates or writes the database.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
exec python3 "${ROOT}/scripts/agent_bus_evidence.py" "$@"
