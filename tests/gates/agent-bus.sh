# tests/gates/agent-bus.sh — Agent Bus M4 pull-beta, M5 workflow, M6 dispatch gates (fake provider).
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# M4 exit gate (fake provider, deterministic): the pull-beta outcome flow end
# to end through the shipped daemon, including a daemon restart mid-flow.
# Never a live provider: --full stays free of quota by roadmap rule (M8).
"${ROOT}/scripts/agent-bus-e2e.sh" >"${ROOT}/agentd/.last-store-run.log" 2>&1 \
  || { tail -30 "${ROOT}/agentd/.last-store-run.log" >&2; rm -f "${ROOT}/agentd/.last-store-run.log"; fail "agent bus M4 pull-beta slice"; }
grep -q "^PASS  agent bus M4 pull-beta vertical slice (fake provider)" "${ROOT}/agentd/.last-store-run.log" \
  || { rm -f "${ROOT}/agentd/.last-store-run.log"; fail "agent bus M4 slice printed no PASS line"; }
rm -f "${ROOT}/agentd/.last-store-run.log"
echo "ok  agent bus M4 pull-beta slice (fake provider, daemon restart, two worktrees)"

# M5 exit gate (fake provider, deterministic): a dependency graph executes, a
# cycle is refused, a reply loop stops at the hop cap, a spent budget stops a
# task, and artifact provenance survives being cited by another agent.
"${ROOT}/scripts/agent-bus-workflow.sh" >"${ROOT}/agentd/.last-store-run.log" 2>&1 \
  || { tail -30 "${ROOT}/agentd/.last-store-run.log" >&2; rm -f "${ROOT}/agentd/.last-store-run.log"; fail "agent bus M5 workflow gate"; }
grep -q "^PASS  agent bus M5 workflow gate (fake provider)" "${ROOT}/agentd/.last-store-run.log" \
  || { rm -f "${ROOT}/agentd/.last-store-run.log"; fail "agent bus M5 workflow gate printed no PASS line"; }
rm -f "${ROOT}/agentd/.last-store-run.log"
echo "ok  agent bus M5 workflow gate (task graph, cycle refused, loop stopped, budget stop, provenance)"

# M6 exit gate (fake provider, deterministic): the dispatcher is killed
# mid-turn, restarted, and the work still reaches exactly one outcome, with no
# lease or credential outliving the turn that took it.
"${ROOT}/scripts/agent-bus-dispatch.sh" >"${ROOT}/agentd/.last-store-run.log" 2>&1 \
  || { tail -30 "${ROOT}/agentd/.last-store-run.log" >&2; rm -f "${ROOT}/agentd/.last-store-run.log"; fail "agent bus M6 dispatch gate"; }
grep -q "^PASS  agent bus M6 dispatch gate (fake provider)" "${ROOT}/agentd/.last-store-run.log" \
  || { rm -f "${ROOT}/agentd/.last-store-run.log"; fail "agent bus M6 dispatch gate printed no PASS line"; }
rm -f "${ROOT}/agentd/.last-store-run.log"
echo "ok  agent bus M6 dispatch gate (killed mid-turn, recovered, fenced, one outcome)"
