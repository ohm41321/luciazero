# tests/gates/agentd.sh — Agent Bus M0 Python syntax and the M1-M6 daemon suite (store, MCP conformance, security, task graph, dispatch), plus the Node bus status client.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# The daemon suite is the one long check of the fast tier; the discipline
# tier skips this gate, every other tier runs it here, right after syntax.
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  "${ROOT}/scripts/agent_bus_spike.py" || fail "agent bus M0 Python syntax"
echo "ok  agent bus M0 Python syntax"
agent_bus_store
