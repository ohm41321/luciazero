#!/usr/bin/env bash
# Verify command for this repo. The doctrine says a missing verify command is
# the first bug — this file is how the repo passes its own rule. It parses the
# tier, builds the sandbox, then sources the gates under tests/gates/ in order.
#
# `--discipline` covers what a change to the hooks, the discipline report or
# a skill/agent prompt can break: syntax, bash 3.2 and ShellCheck over every
# shipped script and gate, the prompt and doctrine contracts, and the hook
# state machine — nothing else. `--fast` adds the agentd suite, Relay, bisect,
# and evidence integrity for intermediate loops. The default/`--full`
# continues through eval, packaging, and sandboxed install cycles for both
# harnesses.
# `--agent-bus-spike` runs only the local-first M0 feasibility gate (needs
# the provider CLIs). `--agent-bus-store` runs only the M1-M4 daemon suite.
# `--agent-bus-mcp` runs the M2 gate against the real CLIs (needs them).
# `--agent-bus-security` runs the M3 and M4.5 safety fixtures. `--agent-bus-e2e`
# runs the M4 pull-beta flow with the fake provider (also part of `--full`).
# `--agent-bus-workflow` runs the M5 task-graph gate (also part of `--full`).
# `--agent-bus-dispatch` runs the M6 dispatcher gate (also part of `--full`).
# `--agent-bus-chat` rehearses the autonomous chat: two managed agents
# answering each other, offline worker, no quota.
# `--agent-bus-live` runs the M6 live smoke gate: one real Codex turn and one
# real Claude turn. It needs the provider CLIs, spends quota, and refuses to
# run without --spend-quota, so it is never part of `--full`.
# Exits non-zero on the first failure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIER=full
# One tier per run, except the live gate, which passes its own flags through
# (--spend-quota is required, and belongs to that gate, not to this dispatcher).
if [ "$#" -gt 1 ] && [ "${1:-}" != "--agent-bus-live" ]; then
  echo "usage: ./test.sh [--discipline|--fast|--full|--agent-bus-spike|--agent-bus-store|--agent-bus-mcp|--agent-bus-security|--agent-bus-e2e|--agent-bus-workflow|--agent-bus-dispatch|--agent-bus-chat|--agent-bus-live]" >&2
  exit 64
fi
case "${1:-}" in
  ""|--full) ;;
  --discipline) TIER=discipline ;;
  --fast) TIER=fast ;;
  --agent-bus-spike) TIER=agent-bus-spike ;;
  --agent-bus-store) TIER=agent-bus-store ;;
  --agent-bus-mcp) TIER=agent-bus-mcp ;;
  --agent-bus-security) TIER=agent-bus-security ;;
  --agent-bus-e2e) TIER=agent-bus-e2e ;;
  --agent-bus-workflow) TIER=agent-bus-workflow ;;
  --agent-bus-dispatch) TIER=agent-bus-dispatch ;;
  --agent-bus-chat) TIER=agent-bus-chat ;;
  --agent-bus-live) TIER=agent-bus-live ;;
  *) echo "usage: ./test.sh [--discipline|--fast|--full|--agent-bus-spike|--agent-bus-store|--agent-bus-mcp|--agent-bus-security|--agent-bus-e2e|--agent-bus-workflow|--agent-bus-dispatch|--agent-bus-chat|--agent-bus-live]" >&2; exit 64 ;;
esac
fail() { echo "FAIL: $*" >&2; exit 1; }

# Called before anything runs uninstall.sh. That script stops and deletes the
# Agent Bus service it finds under LUCIAZERO_SERVICE_ROOT, falling back to
# $HOME when the variable is gone -- which is how a suite run removed the
# developer's own LaunchAgent. Assert the guard where it is spent, not only
# where it is set.
service_guard() {
  [ -n "${LUCIAZERO_SERVICE_ROOT:-}" ] \
    || fail "LUCIAZERO_SERVICE_ROOT is unset: uninstall.sh would look in \$HOME"
  [ "${LUCIAZERO_SERVICE_ROOT}" != "${HOME}" ] \
    || fail "LUCIAZERO_SERVICE_ROOT is \$HOME: uninstall.sh would remove the real service"
}

catalog() { sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "$1"; }
skill_inventory() {
  catalog "${ROOT}/skills/catalog.txt"
  catalog "${ROOT}/skills/aliases.txt"
}

if [ "${TIER}" = agent-bus-spike ]; then
  exec "${ROOT}/scripts/agent-bus-spike.sh"
fi
if [ "${TIER}" = agent-bus-mcp ]; then
  exec "${ROOT}/scripts/agent-bus-mcp.sh"
fi
if [ "${TIER}" = agent-bus-e2e ]; then
  exec "${ROOT}/scripts/agent-bus-e2e.sh"
fi
if [ "${TIER}" = agent-bus-workflow ]; then
  exec "${ROOT}/scripts/agent-bus-workflow.sh"
fi
if [ "${TIER}" = agent-bus-dispatch ]; then
  exec "${ROOT}/scripts/agent-bus-dispatch.sh"
fi
if [ "${TIER}" = agent-bus-chat ]; then
  # The autonomous chat, rehearsed against the offline worker: two managed
  # agents answering each other with no human turn and no quota. Pass
  # --spend-quota (and the rest) to `scripts/agent-bus-chat.sh` for the real
  # one; that is never part of a test tier.
  exec "${ROOT}/scripts/agent-bus-chat.sh" --rehearse
fi
if [ "${TIER}" = agent-bus-live ]; then
  # Passes the remaining arguments through: --spend-quota is required, and
  # without it the gate prints what it would spend and refuses.
  shift || true
  exec "${ROOT}/scripts/agent-bus-live.sh" "$@"
fi

# M1 exit gate: migrations, atomic claims, idempotent replays, append-only
# history, and kill-at-commit crash tests. Python only; no provider CLI.
agent_bus_store() {
  # No separate py_compile pass: importing the suite already proves syntax,
  # and py_compile writes __pycache__ regardless of PYTHONDONTWRITEBYTECODE.
  (cd "${ROOT}/agentd" && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t . >/dev/null 2>"${ROOT}/agentd/.last-store-run.log") \
    || { tail -30 "${ROOT}/agentd/.last-store-run.log" >&2; rm -f "${ROOT}/agentd/.last-store-run.log"; fail "agent bus M1 store suite"; }
  rm -f "${ROOT}/agentd/.last-store-run.log"
  echo "ok  agent bus M1-M6 daemon suite (store, crash transitions, MCP conformance, daemon CLI, security fixtures, task graph and budgets, dispatch leases and recovery, e2e outcome assertion)"

  # `luciazero bus status` (Node, core package) against a real daemon on a
  # throwaway state directory: proves the human-facing queue view end to end
  # without touching ~/.luciazero. Skipped without Node, like every other
  # Node fixture in this suite.
  if ! command -v node >/dev/null 2>&1; then
    echo "skip  luciazero bus status (node not installed)"
    return 0
  fi
  local BUS_STATE BUS_PID BUS_JSON
  BUS_STATE="$(mktemp -d "${TMPDIR:-/tmp}/luciazero-bus-state.XXXXXX")"
  # No subshell: BUS_PID must be the Python process itself so kill reaches it.
  PYTHONPATH="${ROOT}/agentd" PYTHONDONTWRITEBYTECODE=1 python3 -m luciazero_agentd serve --state-dir "${BUS_STATE}" --port 0 >/dev/null 2>&1 &
  BUS_PID=$!
  for _ in $(seq 1 100); do [ -f "${BUS_STATE}/endpoint.json" ] && break; sleep 0.05; done
  [ -f "${BUS_STATE}/endpoint.json" ] || { kill "${BUS_PID}" 2>/dev/null; rm -rf "${BUS_STATE}"; fail "agent bus daemon did not publish endpoint.json"; }
  BUS_JSON="$(LUCIAZERO_AGENT_BUS_HOME="${BUS_STATE}" node "${ROOT}/bin/luciazero.js" bus status --json)" \
    || { kill "${BUS_PID}" 2>/dev/null; rm -rf "${BUS_STATE}"; fail "luciazero bus status failed against a running daemon"; }
  printf '%s' "${BUS_JSON}" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["queued_deliveries"] == 0 and d["server"]["name"] == "luciazero-agentd", d' \
    || { kill "${BUS_PID}" 2>/dev/null; rm -rf "${BUS_STATE}"; fail "luciazero bus status returned an unexpected summary"; }
  LUCIAZERO_AGENT_BUS_HOME="${BUS_STATE}" node "${ROOT}/bin/luciazero.js" bus status | grep -q "queued deliveries: 0" \
    || { kill "${BUS_PID}" 2>/dev/null; rm -rf "${BUS_STATE}"; fail "luciazero bus status human output drift"; }
  kill "${BUS_PID}" 2>/dev/null; wait "${BUS_PID}" 2>/dev/null || true
  LUCIAZERO_AGENT_BUS_HOME="${BUS_STATE}" node "${ROOT}/bin/luciazero.js" bus status >/dev/null 2>&1 \
    && { rm -rf "${BUS_STATE}"; fail "luciazero bus status must fail once the daemon is gone"; }
  LUCIAZERO_AGENT_BUS_HOME="/nonexistent/luciazero-bus" node "${ROOT}/bin/luciazero.js" bus status >/dev/null 2>&1 \
    && fail "luciazero bus status must fail without a state directory"
  node "${ROOT}/bin/luciazero.js" bus nope >/dev/null 2>&1 && fail "luciazero bus must reject unknown subcommands"
  rm -rf "${BUS_STATE}"
  echo "ok  luciazero bus status (Node client against a throwaway daemon)"
}
if [ "${TIER}" = agent-bus-store ]; then
  agent_bus_store
  echo
  echo "PASS  agent bus M1-M6 daemon gate green"
  exit 0
fi

# The M3 and M4.5 exit gates on their own: worktree isolation, stale-identity
# refusal, approval provenance, path containment, secret redaction, bounded
# input, terminal bindings, session credentials, the actor-field matrix, and
# the invariant that an unattributed session is never labelled as proven.
# Both modules also run inside agent_bus_store, so --fast covers them.
if [ "${TIER}" = agent-bus-security ]; then
  (cd "${ROOT}/agentd" && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_security tests.test_identity >/dev/null 2>"${ROOT}/agentd/.last-store-run.log") \
    || { tail -30 "${ROOT}/agentd/.last-store-run.log" >&2; rm -f "${ROOT}/agentd/.last-store-run.log"; fail "agent bus M3+M4.5 security suite"; }
  rm -f "${ROOT}/agentd/.last-store-run.log"
  echo "ok  agent bus safety fixtures (worktree isolation, stale identity, approval provenance, path containment, redaction, bounded input)"
  echo "ok  agent bus identity fixtures (terminal bindings, session credentials, actor-field matrix, unattributed is never proven)"
  echo
  echo "PASS  agent bus M3+M4.5 security gate green"
  exit 0
fi

# The hooks append a stats line to ${CLAUDE_CONFIG_DIR:-~/.claude}; no test is
# ever allowed to touch the real one, so the whole run gets a sandbox default.
# Tests that set their own CLAUDE_CONFIG_DIR still override per invocation.
# mktmp <var>: a fresh directory in <var>, under TMPDIR, removed when the run
# ends however it ends — a fail() exits through the same EXIT trap. The
# explicit template matters: macOS mktemp ignores TMPDIR without one, and the
# suite proves cleanup by running a child under a private TMPDIR. Gates make
# their fixture directories with this, not with a bare mktemp.
TMP_DIRS=()
mktmp() {
  local D
  D="$(mktemp -d "${TMPDIR:-/tmp}/luciazero-test.XXXXXX")"
  printf -v "$1" '%s' "${D}"
  TMP_DIRS+=("${D}")
}
cleanup() { rm -rf ${TMP_DIRS[@]+"${TMP_DIRS[@]}"}; }
trap cleanup EXIT
mktmp CLAUDE_CONFIG_DIR
export CLAUDE_CONFIG_DIR

# Ambient LUCIAZERO_* configuration belongs to the developer's own install and
# would silently change what the hooks under test do — an exported
# LUCIAZERO_VERIFY_CMD flips the tracker into exact-match mode, so fixture
# commands stop counting as verify runs and this suite goes red on exactly the
# machines that dogfood the pack. Every test sets what it needs per invocation.
# Keep the boundary in a sourceable helper so its regression test can exercise
# the exact implementation without adding a bypass to this entrypoint.
# shellcheck source=scripts/sanitize-luciazero-env.sh
source "${ROOT}/scripts/sanitize-luciazero-env.sh"

# Where anything in this suite would look for a launchd or systemd service
# file. Pointed away from $HOME for the whole run: uninstall.sh stops the
# Agent Bus service before removing its launcher, and a suite that read the
# real $HOME would stop -- and delete -- a service the developer is using.
#
# Set *after* the sanitation above, which unsets every LUCIAZERO_* variable it
# finds and so wiped this guard when it was set earlier: the suite then ran
# every uninstall.sh with the fallback, and the developer's own LaunchAgent
# went with it. Nothing about the name is optional; uninstall.sh reads exactly
# this variable.
#
# Built from shell expansions only, and never created: section 2a re-runs this
# script with a forged PATH holding almost nothing, so a `mktemp` here would
# fail there. Nothing writes under it -- the paths are only ever read.
LUCIAZERO_SERVICE_ROOT="${TMPDIR:-/tmp}/luciazero-suite-no-service-$$"
export LUCIAZERO_SERVICE_ROOT

SCRIPTS=(install.sh uninstall.sh install-codex.sh uninstall-codex.sh test.sh
         demo.sh
         scripts/sanitize-luciazero-env.sh
         scripts/test-timings.sh
         scripts/agent-bus-spike.sh
         scripts/agent-bus-mcp.sh
         scripts/agent-bus-e2e.sh
         scripts/agent-bus-workflow.sh
         scripts/agent-bus-dispatch.sh
         scripts/agent-bus-live.sh
         scripts/agent-bus-chat.sh
         scripts/agent-bus-evidence.sh
         docs/assets/agent-bus-demo.sh
         scripts/stage-npm-package.sh
         docs/assets/statusline-demo.sh
         docs/assets/relay-demo.sh
         skills/ready/scripts/detect.sh
         skills/bisect/scripts/safe-bisect.sh
         skills/done/scripts/revert-probe.sh
         claude/hooks/luciazero-verify.sh claude/hooks/luciazero-statusline.sh
         eval/run.sh eval/report.sh eval/check-result.sh)
# every task grader, auto-discovered — a new task cannot skip the lint net
for G in "${ROOT}"/eval/tasks/*/grade.sh; do SCRIPTS+=("${G#"${ROOT}"/}"); done
# optional deterministic task setup runs in both real and offline evaluation
for S in "${ROOT}"/eval/tasks/*/setup.sh; do
  [ -f "${S}" ] && SCRIPTS+=("${S#"${ROOT}"/}")
done

# The checks live in tests/gates/*.sh, one file per subsystem, sourced into
# this shell in the order below. A gate sees the helpers, the sandbox
# environment and every variable an earlier gate set, exactly as when the
# suite was one file; a `fail` inside one ends the run the same way. The
# discipline tier runs DISCIPLINE_GATES and nothing else (agentd sits between
# syntax and core in every other tier, so its output keeps its place); the
# fast tier adds FAST_GATES; the full tier continues through FULL_GATES.
# Every gate is also lint input: syntax, bash 3.2 parse and ShellCheck.
# LZ_TEST_TIMINGS=1 prints `TIMING gate=<name> seconds=<n>` on stderr as each
# gate finishes; off, nothing about the run changes.
DISCIPLINE_GATES=(tests/gates/syntax.sh tests/gates/core.sh
                  tests/gates/contracts.sh tests/gates/hooks.sh)
FAST_GATES=(tests/gates/agentd.sh tests/gates/relay.sh tests/gates/bisect.sh
            tests/gates/evidence.sh tests/gates/astra-luna.sh)
FULL_GATES=(tests/gates/tiers.sh tests/gates/agent-bus.sh tests/gates/eval.sh
            tests/gates/packaging.sh tests/gates/install.sh
            tests/gates/codex-install.sh)
SCRIPTS+=("${DISCIPLINE_GATES[@]}" "${FAST_GATES[@]}" "${FULL_GATES[@]}")
gate() { # gate <name>: source tests/gates/<name>.sh, timing it when asked
  # The bash SECONDS counter: no process, nothing added to what it measures,
  # whole seconds — enough to rank gates of ten to a hundred seconds. Off,
  # this is a plain source. The name is dropped from the positional
  # parameters first, so a gate sees none, as at the top level of a script.
  local GATE_NAME="$1" GATE_T0="${SECONDS}"
  set --
  # shellcheck disable=SC1090
  source "${ROOT}/tests/gates/${GATE_NAME}.sh"
  if [ "${LZ_TEST_TIMINGS:-0}" = 1 ]; then
    echo "TIMING gate=${GATE_NAME} seconds=$((SECONDS - GATE_T0))" >&2
  fi
}

gate syntax
if [ "${TIER}" != discipline ]; then
  gate agentd
fi
gate core
gate contracts
gate hooks

if [ "${TIER}" = discipline ]; then
  echo
  echo "PASS  discipline checks green"
  exit 0
fi

gate relay
gate bisect
gate evidence
gate astra-luna

if [ "${TIER}" = fast ]; then
  echo
  echo "PASS  fast checks green"
  exit 0
fi

# The full-only gates. agent-bus runs first and alone: it writes
# agentd/.last-store-run.log like the agentd gate and must never overlap
# another writer. Then tiers, eval, packaging, install and codex-install run
# at once — each owns its sandboxes and only reads the checkout (the suite
# proves each is green in a clean subshell). Every one of the six runs as a
# background subshell that is waited for: a subshell in a || list would lose
# errexit for its whole body. In the parallel run each gate's stdout and
# stderr land in a buffer and are replayed in the original order once all are
# done, so both streams are the serial run's byte for byte; a red gate keeps
# its own FAIL line and the summary names every red gate. LZ_TEST_PARALLEL=0
# runs the same subshells one at a time, unbuffered.
FULL_ORDER=(tiers agent-bus eval packaging install codex-install)
gate_sub() { # gate_sub <name>: run a gate in this subshell, which does not run
  # the parent's EXIT trap; it arms its own over an empty list, so the gate's
  # mktmp directories go when the gate ends and the parent's stay until the run does
  TMP_DIRS=()
  trap cleanup EXIT
  gate "$1"
}
gate_bg() { # gate_bg <name> [<stdout file> <stderr file>]: start it; GATE_PID
  if [ $# -gt 1 ]; then
    ( gate_sub "$1" ) >"$2" 2>"$3" &
  else
    ( gate_sub "$1" ) &
  fi
  GATE_PID=$!
}
RED=""
if [ "${LZ_TEST_PARALLEL:-1}" = 0 ]; then
  for G in "${FULL_ORDER[@]}"; do
    gate_bg "${G}"
    wait "${GATE_PID}" || RED="${RED} ${G}"
  done
else
  mktmp BUF
  gate_bg agent-bus "${BUF}/agent-bus.out" "${BUF}/agent-bus.err"
  wait "${GATE_PID}" || RED="${RED} agent-bus"
  PARALLEL=(tiers eval packaging install codex-install)
  PIDS=()
  for G in "${PARALLEL[@]}"; do
    gate_bg "${G}" "${BUF}/${G}.out" "${BUF}/${G}.err"
    PIDS+=("${GATE_PID}")
  done
  I=0
  for G in "${PARALLEL[@]}"; do
    wait "${PIDS[${I}]}" || RED="${RED} ${G}"
    I=$((I + 1))
  done
  for G in "${FULL_ORDER[@]}"; do
    cat "${BUF}/${G}.out"
    cat "${BUF}/${G}.err" >&2
  done
  rm -rf "${BUF}"
fi
if [ -n "${RED}" ]; then
  SUMMARY=""
  for G in "${FULL_ORDER[@]}"; do
    case " ${RED} " in *" ${G} "*) SUMMARY="${SUMMARY} ${G}" ;; esac
  done
  fail "red gates:${SUMMARY}"
fi

echo
echo "PASS  all checks green"
