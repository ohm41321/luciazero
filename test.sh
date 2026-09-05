#!/usr/bin/env bash
# Verify command for this repo. The doctrine says a missing verify command is
# the first bug — this file is how the repo passes its own rule.
#
# `--fast` covers core doctrine, hooks/report, Relay, bisect, and evidence
# integrity for intermediate loops. The default/`--full` continues through
# eval, packaging, and sandboxed install cycles for both harnesses.
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
  echo "usage: ./test.sh [--fast|--full|--agent-bus-spike|--agent-bus-store|--agent-bus-mcp|--agent-bus-security|--agent-bus-e2e|--agent-bus-workflow|--agent-bus-dispatch|--agent-bus-chat|--agent-bus-live]" >&2
  exit 64
fi
case "${1:-}" in
  ""|--full) ;;
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
  *) echo "usage: ./test.sh [--fast|--full|--agent-bus-spike|--agent-bus-store|--agent-bus-mcp|--agent-bus-security|--agent-bus-e2e|--agent-bus-workflow|--agent-bus-dispatch|--agent-bus-chat|--agent-bus-live]" >&2; exit 64 ;;
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
CLAUDE_CONFIG_DIR="$(mktemp -d)"
export CLAUDE_CONFIG_DIR
trap 'rm -rf "${CLAUDE_CONFIG_DIR}"' EXIT

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

# 1. shell syntax
for S in "${SCRIPTS[@]}"; do bash -n "${ROOT}/${S}"; done
echo "ok  shell syntax"

PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  "${ROOT}/scripts/agent_bus_spike.py" || fail "agent bus M0 Python syntax"
echo "ok  agent bus M0 Python syntax"
agent_bus_store

# 1b. The hooks run under whatever /bin/bash the user has — bash 3.2 on stock
# macOS. Verified against a real 3.2: a here-document inside a command
# substitution whose command also carries a quoted expansion and a trailing
# redirection breaks its parser, and it fails the WHOLE file at load time with
# an error pointing at some unrelated later line. A modern `bash -n` accepts
# it, so the hooks simply must not contain the construct at all.
for S in claude/hooks/luciazero-verify.sh claude/hooks/luciazero-statusline.sh; do
  if grep -qE '\$\([^)]*<<' "${ROOT}/${S}"; then
    fail "${S} has a here-document inside \$( ) — bash 3.2 fails to parse the file"
  fi
done
# and when a real bash 3.2 is available (LZ_BASH32=/path/to/bash-3.2), parse
# every script with it instead of trusting the textual rule
if [ -n "${LZ_BASH32:-}" ] && [ -x "${LZ_BASH32}" ]; then
  for S in "${SCRIPTS[@]}"; do
    "${LZ_BASH32}" -n "${ROOT}/${S}" || fail "${S} does not parse under ${LZ_BASH32}"
  done
  echo "ok  bash 3.2 parse (${LZ_BASH32})"
else
  echo "ok  hooks free of here-documents inside \$( ) (bash 3.2; set LZ_BASH32 to parse for real)"
fi

# 2. shellcheck: required where it must run (CI, or LZ_REQUIRE_LINT=1), because
# a silent skip lets a local green disagree with the CI that gates the release.
if command -v shellcheck >/dev/null 2>&1; then
  (cd "${ROOT}" && shellcheck "${SCRIPTS[@]}")
  echo "ok  shellcheck"
elif [ -n "${CI:-}" ] || [ -n "${LZ_REQUIRE_LINT:-}" ]; then
  fail "shellcheck is required here (CI or LZ_REQUIRE_LINT=1) but is not installed"
else
  echo "skip shellcheck (not installed — local only; CI fails without it)"
fi

# 2a. ambient LUCIAZERO_* must not change this suite's outcome. A tiny child
# sources the same sanitation helper under every poisoned knob; the test
# entrypoint itself has no environment-controlled early exit.
CHILD_RC=0
CHILD_OUT="$(LUCIAZERO_VERIFY_CMD='never-the-fixture-command' \
  LUCIAZERO_VERIFY_REGEX='^zzz-never-matches$' \
  LUCIAZERO_STRICT_VERIFY_CMD='false' \
  LUCIAZERO_DOC_REGEX='.' \
  LUCIAZERO_CHANNEL='plugin' \
  bash -c '
    source "$1"
    LEFTOVER_LZ="$(env | sed -n '\''s/^\(LUCIAZERO_[A-Za-z0-9_]*\)=.*/\1/p'\'')"
    [ -z "${LEFTOVER_LZ}" ] || {
      echo "ambient Luciazero variables survived sanitation: ${LEFTOVER_LZ}" >&2
      exit 1
    }
  ' _ "${ROOT}/scripts/sanitize-luciazero-env.sh" 2>&1)" || CHILD_RC=$?
[ "${CHILD_RC}" = 0 ] \
  || fail "ambient LUCIAZERO_* sanitation failed: ${CHILD_OUT:-child exited ${CHILD_RC}}"
# A historical probe variable must not bypass the real entrypoint. Put a
# failing bash shim at the first syntax check so this assertion stays tiny.
FORGE_BIN="$(mktemp -d)"
# The fixture intentionally writes a literal shell parameter expansion.
# shellcheck disable=SC2016
printf '#!/bin/sh\n[ -z "${LUCIAZERO_VERIFY_CMD+x}" ] || exit 8\nexit 7\n' > "${FORGE_BIN}/bash"
chmod +x "${FORGE_BIN}/bash"
FORGE_RC=0
PATH="${FORGE_BIN}:/usr/bin:/bin" LZ_SANITATION_PROBE=1 \
  LUCIAZERO_VERIFY_CMD='must-be-removed-before-syntax-checks' \
  /bin/bash "${ROOT}/test.sh" --fast >/dev/null 2>&1 || FORGE_RC=$?
rm -rf "${FORGE_BIN}"
[ "${FORGE_RC}" = 7 ] || fail "environment variable bypassed the verification entrypoint (rc=${FORGE_RC})"
echo "ok  ambient LUCIAZERO_* sanitation"

# 2b. detect.sh runs green against this repo and finds the CI verify command
OUT="$("${ROOT}/skills/ready/scripts/detect.sh" "${ROOT}")" \
  || fail "detect.sh exited non-zero"
echo "${OUT}" | grep -q 'test.sh' || fail "detect.sh did not surface test.sh from CI config"
echo "ok  detect.sh smoke run"

# 2c. detect.sh must also match the '- run:' list form, the most common
# GitHub Actions style (this repo's own CI happens not to use it)
FX="$(mktemp -d)"
mkdir -p "${FX}/.github/workflows"
printf 'jobs:\n  t:\n    steps:\n      - run: npm run canary-cmd\n' > "${FX}/.github/workflows/ci.yml"
# capture, then grep: grep -q on a pipe would SIGPIPE detect.sh under pipefail
OUT="$("${ROOT}/skills/ready/scripts/detect.sh" "${FX}")" \
  || { rm -rf "${FX}"; fail "detect.sh exited non-zero on the fixture"; }
echo "${OUT}" | grep -q 'canary-cmd' \
  || { rm -rf "${FX}"; fail "detect.sh missed the '- run:' CI form"; }
rm -rf "${FX}"
echo "ok  detect.sh '- run:' form"

# 3. example settings must parse as JSON
python3 -m json.tool "${ROOT}/examples/project-settings.example.json" >/dev/null \
  || fail "examples/project-settings.example.json is not valid JSON"
echo "ok  example settings JSON"

# 4. skill + agent frontmatter: name + description drive discovery and auto-trigger
SKILL_DESC_WORDS=0
while IFS= read -r NAME; do
  SKILL="${ROOT}/skills/${NAME}/SKILL.md"
  head -1 "${SKILL}" | grep -qx -- '---' || fail "${NAME}/SKILL.md missing frontmatter"
  grep -q "^name: ${NAME}\$" "${SKILL}" || fail "${NAME}/SKILL.md missing 'name: ${NAME}'"
  grep -q '^description: .' "${SKILL}" || fail "${NAME}/SKILL.md missing description"
  DESC_WORDS="$(sed -n 's/^description:[[:space:]]*//p' "${SKILL}" | wc -w | tr -d '[:space:]')"
  [ "${DESC_WORDS}" -le 40 ] \
    || fail "${NAME}/SKILL.md description is ${DESC_WORDS} words (limit 40)"
  SKILL_DESC_WORDS=$((SKILL_DESC_WORDS + DESC_WORDS))
done < <(skill_inventory)
while IFS= read -r AGENT_NAME; do
  AGENT="${ROOT}/claude/agents/${AGENT_NAME}.md"
  head -1 "${AGENT}" | grep -qx -- '---' || fail "${AGENT_NAME}.md missing frontmatter"
  grep -q "^name: ${AGENT_NAME}\$" "${AGENT}" || fail "${AGENT_NAME}.md missing name"
  grep -q '^description: .' "${AGENT}" || fail "${AGENT_NAME}.md missing description"
  AGENT_DESC_WORDS="$(sed -n 's/^description:[[:space:]]*//p' "${AGENT}" | wc -w | tr -d '[:space:]')"
  [ "${AGENT_DESC_WORDS}" -le 40 ] \
    || fail "${AGENT_NAME}.md description is ${AGENT_DESC_WORDS} words (limit 40)"
  grep -q '^model: inherit$' "${AGENT}" || fail "${AGENT_NAME}.md must inherit the authoring model"
done < <(catalog "${ROOT}/claude/agents/catalog.txt")
cmp -s "${ROOT}/agents/reviewer.md" "${ROOT}/claude/agents/reviewer.md" \
  || fail "plugin agents/reviewer.md drifted from the classic reviewer source"
python3 - "${ROOT}" <<'PY' || fail "reviewer/ready prompt budget or contract drift"
import pathlib, re, sys

root = pathlib.Path(sys.argv[1])
reviewer = (root / "claude/agents/reviewer.md").read_text()
ready = (root / "skills/ready/SKILL.md").read_text()

def normalized(text):
    return " ".join(text.casefold().split())

def section_bodies(text, expected, strip_fences):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    if strip_fences:
        text = re.sub(r"(?ms)^(?:```|~~~).*?^(?:```|~~~)[ \t]*$", "", text)
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    matches = list(re.finditer(r"(?m)^## (.+?)[ \t]*$", text))
    names = [match.group(1) for match in matches]
    assert all(names.count(name) == 1 for name in expected), f"lost or duplicated sections: {expected}"
    indices = [names.index(name) for name in expected]
    assert indices == sorted(indices), f"sections out of order: {expected}"
    bodies = {"__intro__": text[:matches[0].start()] if matches else text}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        bodies[match.group(1)] = text[match.end():end]
    return bodies

def frontmatter(text, label, expected_name, expected_fields):
    match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.S)
    assert match, f"{label} lost frontmatter block"
    block = match.group(1)
    fields = {"name": expected_name, **expected_fields}
    for field, expected in fields.items():
        values = re.findall(rf"(?m)^{re.escape(field)}:[ \t]*(.+)$", block)
        assert values == [expected], f"{label} frontmatter {field} drift: {values}"
        assert not re.search(rf"(?m)^{re.escape(field)}:[ \t]*", text[match.end():]), \
            f"{label} has {field} outside frontmatter"
    descriptions = re.findall(r"(?m)^description:[ \t]*(.+)$", block)
    assert len(descriptions) == 1, f"{label} needs one frontmatter description"
    assert not re.search(r"(?m)^description:[ \t]*", text[match.end():]), \
        f"{label} has description outside frontmatter"
    return descriptions[0]

def validate(text, label, expected_name, expected_fields, expected, contracts, code_contracts, budget):
    prose = section_bodies(text, expected, strip_fences=True)
    raw = section_bodies(text, expected, strip_fences=False)
    prose["__description__"] = frontmatter(text, label, expected_name, expected_fields)
    for section, clauses in contracts.items():
        body = normalized(prose[section])
        missing = [clause for clause in clauses if normalized(clause) not in body]
        assert not missing, f"{label} {section} lost behavioral clauses: {missing}"
    for section, literal in code_contracts:
        assert literal in raw[section], f"{label} {section} lost code contract"
    assert len(text.split()) <= budget, f"{label} prompt is {len(text.split())} words (budget {budget})"

reviewer_sections = ("Route the search", "Evidence discipline", "Output")
reviewer_contracts = {
    "__description__": ("Prefer built-in review; otherwise use this agent independently.",),
    "__intro__": ("Refute the change; do not approve or praise it.",),
    "Route the search": (
        "rank risks by impact and reachability",
        "trace each changed trust boundary from external input to a sensitive sink",
        "identify the old observable shape, then search callers, consumers, fixtures, docs, serializers, migrations, and compatibility code",
        "prioritize error paths, state transitions, concurrency, resource cleanup, and material edge cases",
        "A changed test is suspect if it would still pass when the implementation is reverted.",
    ),
    "Evidence discipline": (
        "Confirm each suspected defect in source before reporting it.",
        "Never edit, commit, or push.", "Stay inside the diff's causal scope.",
        "Report every verified `blocker`/`major`; report at most three `minor` findings",
    ),
    "Output": ("output exactly `No findings.`",),
}
ready_sections = (
    "1. Detect", "2. Establish verification", "3. Add smoke tests only when absent",
    "4. Add only paying guardrails", "5. Record project knowledge", "6. Prove the loop",
)
ready_contracts = {
    "1. Detect": ("Run the bundled scan first", "CI config: use what CI runs."),
    "2. Establish verification": (
        "exit non-zero on failure and run unattended", "work offline without credentials, GPU, network, or secrets",
        "Run `verify` on every edit loop; run `verify-full` at closeout and before a PR.",
        "root full suite as fallback", "references/smart-verification.md",
        "ask first before offering exact-match", "Never commit this variable",
        "This setting caches CI truth; update it whenever CI's verify command changes.",
    ),
    "3. Add smoke tests only when absent": (
        "Add 3–6 small tests for catastrophic failures", "never the user's real data paths",
        "enforce a hard timeout and cleanup",
    ),
    "4. Add only paying guardrails": (
        "on Codex or another harness, put necessary constraints in AGENTS.md instead",
        "Never add a hook that deploys, pushes, deletes, or writes outside the repository.",
    ),
    "5. Record project knowledge": ("Every line becomes future context cost.",),
    "6. Prove the loop": ("Flake check", "Red check", "restore exactly that edit", "does not cover"),
}

reviewer_code = (("Output", "```\npath:line — severity — problem. Concrete fix.\n```"),)
ready_code = (("1. Detect", "```\n<this-skill-dir>/scripts/detect.sh <repo-root>\n```"),)
reviewer_fields = {"tools": "Read, Grep, Glob, Bash", "model": "inherit"}
validate(reviewer, "reviewer", "reviewer", reviewer_fields, reviewer_sections,
         reviewer_contracts, reviewer_code, 400)
validate(ready, "ready", "ready", {}, ready_sections, ready_contracts, ready_code, 1000)

def assert_rejected(text, label, expected_name, expected_fields, expected, contracts, code_contracts, budget):
    try:
        validate(text, label, expected_name, expected_fields, expected, contracts, code_contracts, budget)
    except AssertionError:
        return
    raise AssertionError(f"{label} validator accepted adversarial stuffing")

all_reviewer_clauses = " ".join(clause for clauses in reviewer_contracts.values() for clause in clauses)
reviewer_frame = ("---\nname: reviewer\n"
                  "description: Prefer built-in review; otherwise use this agent independently.\n"
                  "tools: Read, Grep, Glob, Bash\nmodel: inherit\n---\n")
reviewer_headings = "\n".join(f"## {section}" for section in reviewer_sections)
assert_rejected(reviewer_frame + reviewer_headings + f"\n<!-- {all_reviewer_clauses} -->",
                "reviewer comment bag", "reviewer", reviewer_fields, reviewer_sections,
                reviewer_contracts, reviewer_code, 400)
assert_rejected(reviewer_frame + reviewer_headings + f"\n```\n{all_reviewer_clauses}\n```",
                "reviewer code bag", "reviewer", reviewer_fields, reviewer_sections,
                reviewer_contracts, reviewer_code, 400)
wrong_section = (reviewer_frame + "\nRefute the change; do not approve or praise it.\n"
                 + f"## Route the search\n{all_reviewer_clauses}\n"
                 + "## Evidence discipline\n\n## Output\n```\npath:line — severity — problem. Concrete fix.\n```\n")
assert_rejected(wrong_section, "reviewer wrong-section bag", "reviewer", reviewer_fields, reviewer_sections,
                reviewer_contracts, reviewer_code, 400)
fenced_description = reviewer.replace(
    "description: Adversarial reviewer with general, security, and contract routes. Use for diffs or risky closeout. Prefer built-in review; otherwise use this agent independently. Verifies callers and consumers, never edits, and prefers no finding over a false one.\n",
    "",
).replace("# Reviewer\n", "```yaml\ndescription: moved outside frontmatter\n```\n\n# Reviewer\n")
assert_rejected(fenced_description, "reviewer fenced description", "reviewer", reviewer_fields, reviewer_sections,
                reviewer_contracts, reviewer_code, 400)
fenced_tools = reviewer.replace("tools: Read, Grep, Glob, Bash\n", "").replace(
    "# Reviewer\n", "```yaml\ntools: Read, Grep, Glob, Bash\n```\n\n# Reviewer\n",
)
assert_rejected(fenced_tools, "reviewer fenced tools", "reviewer", reviewer_fields, reviewer_sections,
                reviewer_contracts, reviewer_code, 400)
print(f"ok  prompt budgets (reviewer {len(reviewer.split())}/400; ready {len(ready.split())}/1000 words)")
PY
python3 "${ROOT}/scripts/check-skill-prompts.py" \
  || fail "remaining skill prompt budget or contract drift"
python3 -c 'compile(open(__import__("sys").argv[1], encoding="utf-8").read(), __import__("sys").argv[1], "exec")' \
  "${ROOT}/skills/lucia-relay/scripts/relay.py" || fail "relay.py syntax"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT}/test_lucia_relay.py" >/dev/null \
  || fail "focused lucia-relay trust regressions"
echo "ok  focused lucia-relay trust regressions"
python3 -c 'compile(open(__import__("sys").argv[1], encoding="utf-8").read(), __import__("sys").argv[1], "exec")' \
  "${ROOT}/scripts/check-skill-prompts.py" || fail "skill prompt checker syntax"
python3 -c 'compile(open(__import__("sys").argv[1], encoding="utf-8").read(), __import__("sys").argv[1], "exec")' \
  "${ROOT}/eval/evidence.py" || fail "evidence.py syntax"
python3 -c 'compile(open(__import__("sys").argv[1], encoding="utf-8").read(), __import__("sys").argv[1], "exec")' \
  "${ROOT}/eval/result_schema.py" || fail "result_schema.py syntax"
echo "ok  skill + agent frontmatter (descriptions ${SKILL_DESC_WORDS} words; max 40 each)"

# Routine edits with obvious scope/proof must not pay for planning/debugging
# ceremony. The descriptions are the auto-trigger contract exposed to agents.
grep -q 'skip routine edits with clear scope and proof' \
  "${ROOT}/skills/plan/SKILL.md" || fail "plan skill still auto-triggers on routine edits"
grep -q 'Not for routine obvious failures' "${ROOT}/skills/debug/SKILL.md" \
  || fail "debug skill still auto-triggers on a first obvious failure"
echo "ok  routine-task skill trigger boundaries"

# 4b. doctrine budget — loaded on every turn of every session; this enforces "stays short"
DOCTRINE_FILE="${ROOT}/claude/luciazero.md"
W="$(wc -w < "${DOCTRINE_FILE}" | tr -d ' ')"
[ "${W}" -le 420 ] || fail "doctrine is ${W} words (limit 420) — every line costs context on every turn; cut a word to add a word"
! grep -qi 'subagent' "${DOCTRINE_FILE}" || fail "doctrine uses Claude-only 'subagent' vocabulary; phrase platform-neutrally"
grep -q 'fastest relevant check' "${DOCTRINE_FILE}" \
  || fail "doctrine does not prefer targeted intermediate verification"
grep -q 'full verification once at closeout' "${DOCTRINE_FILE}" \
  || fail "doctrine does not reserve full verification for closeout"
echo "ok  doctrine budget (${W}/420 words)"

# 4c. enforcement-pack hook state machine (isolated TMPDIR; fails open by design)
HT="$(mktemp -d)"
HJ='{"cwd":"/hook/test/proj"}'
echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
RC=0; echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>/dev/null || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${HT}"; fail "stop hook did not nudge on unverified edits (rc=${RC})"; }
RC=0; echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}"; fail "stop nudge is not one-shot (rc=${RC})"; }
echo '{"cwd":"/hook/test/proj","tool_input":{"command":"./test.sh"},"tool_response":{"exit_code":0}}' \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" bash
echo '{"cwd":"/hook/test/proj"}' | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
echo '{"cwd":"/hook/test/proj","tool_input":{"command":"./test.sh"},"tool_response":{"exit_code":0}}' \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" bash
RC=0; echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}"; fail "stop hook nudged despite verify after edit (rc=${RC})"; }
# edit immediately after a verify (same wall-clock second): must still nudge —
# regression for bash 3.2's whole-second [ -nt ] missing sub-second ordering
echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
RC=0; echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>/dev/null || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${HT}"; fail "stop hook missed an edit made right after verify (rc=${RC})"; }
# a documentation write after a green verify must NOT re-arm the nudge —
# Closeout docs and relay artifacts written after final verify must not re-arm
echo '{"cwd":"/hook/test/proj","tool_input":{"command":"./test.sh"},"tool_response":{"exit_code":0}}' \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" bash
echo '{"cwd":"/hook/test/proj","tool_input":{"file_path":"/hook/test/proj/LUCIA_RELAY.json"}}' \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
RC=0; echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}"; fail "stop hook nudged on a docs-only write after green verify (rc=${RC})"; }
SL="$(echo '{"model":{"display_name":"M"},"workspace":{"current_dir":"/hook/test/proj"}}' \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-statusline.sh")"
printf '%s' "${SL}" | grep -q '✅ verify' || { rm -rf "${HT}"; fail "statusline missed green verify state: ${SL}"; }
# exact-match mode: with LUCIAZERO_VERIFY_CMD set, reading the test file is no
# longer counted as running it (regression: `cat test.sh` flipped state green)
EJ='{"cwd":"/hook/test/exact"}'
echo "${EJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
echo '{"cwd":"/hook/test/exact","tool_input":{"command":"cat test.sh"},"tool_response":{"exit_code":0}}' \
  | TMPDIR="${HT}" LUCIAZERO_VERIFY_CMD='./test.sh' "${ROOT}/claude/hooks/luciazero-verify.sh" bash
RC=0; echo "${EJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>/dev/null || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${HT}"; fail "exact-match mode counted 'cat test.sh' as a verify run (rc=${RC})"; }
echo '{"cwd":"/hook/test/exact","tool_input":{"command":"./test.sh -q"},"tool_response":{"exit_code":0}}' \
  | TMPDIR="${HT}" LUCIAZERO_VERIFY_CMD='./test.sh' "${ROOT}/claude/hooks/luciazero-verify.sh" bash
RC=0; echo "${EJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}"; fail "exact-match mode missed the real verify command (rc=${RC})"; }
echo "ok  enforcement-pack hook state machine"

# 4c1. a repository cannot reconfigure the hook from its committed settings:
# a widened regex must not count an arbitrary command as a verify run, a
# committed strict command must not be executed at stop, and the personal
# settings.local.json must keep working.
PEJ_DIR="$(mktemp -d)"
mkdir -p "${PEJ_DIR}/.claude"
cat > "${PEJ_DIR}/.claude/settings.json" <<'JSON'
{"env": {"LUCIAZERO_VERIFY_REGEX": ".", "LUCIAZERO_STRICT_VERIFY_CMD": "touch strict-ran"}}
JSON
PEJ="$(printf '{"cwd":"%s"}' "${PEJ_DIR}")"
echo "${PEJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
printf '{"cwd":"%s","tool_input":{"command":"echo hello"},"tool_response":{"exit_code":0}}\n' "${PEJ_DIR}" \
  | TMPDIR="${HT}" LUCIAZERO_VERIFY_REGEX='.' "${ROOT}/claude/hooks/luciazero-verify.sh" bash
RC=0; PERR="$(echo "${PEJ}" | TMPDIR="${HT}" \
  LUCIAZERO_VERIFY_REGEX='.' LUCIAZERO_STRICT_VERIFY_CMD="touch ${PEJ_DIR}/strict-ran" \
  "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>&1)" || RC=$?
[ "${RC}" = 2 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}"; fail "project-scoped verify regex still counted 'echo hello' as a verify run (rc=${RC})"; }
if printf '%s' "${PERR}" | grep -q 'Strict verify gate'; then
  rm -rf "${HT}" "${PEJ_DIR}"; fail "project-scoped strict command reached the strict gate"
fi
if [ -e "${PEJ_DIR}/strict-ran" ]; then
  rm -rf "${HT}" "${PEJ_DIR}"; fail "project-scoped strict command was executed at stop"
fi
SESS_OUT="$(echo "${PEJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" session)"
printf '%s' "${SESS_OUT}" | grep -q 'LUCIAZERO_VERIFY_REGEX' \
  || { rm -rf "${HT}" "${PEJ_DIR}"; fail "SessionStart did not warn about the committed LUCIAZERO_* env block"; }
# the lookup runs on every Bash call, so a repository must not be able to hang
# it (fifo) or make it chew a huge file: both refuse the knobs, neither blocks
rm -f "${PEJ_DIR}/.claude/settings.json"
# timeout(1) is not on stock macOS; without it a regressed guard would hang the
# suite forever instead of failing it, so skip rather than risk that
if command -v timeout >/dev/null 2>&1; then
  mkfifo "${PEJ_DIR}/.claude/settings.json"
  RC=0; timeout 10 env TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" session \
    <<< "${PEJ}" >/dev/null 2>&1 || RC=$?
  [ "${RC}" != 124 ] || { rm -rf "${HT}" "${PEJ_DIR}"; fail "a fifo .claude/settings.json hung the hook"; }
  rm -f "${PEJ_DIR}/.claude/settings.json"
else
  echo "skip fifo settings guard (no timeout(1))"
fi
python3 -c 'import sys; open(sys.argv[1], "w").write("{\"env\": {}}" + " " * 1_100_000)' \
  "${PEJ_DIR}/.claude/settings.json"
# the oversized case also drops CLAUDE_CONFIG_DIR, so this invocation falls back
# to $HOME/.claude — point HOME somewhere empty instead of the developer's own
# install, whose wired classic hook would make this copy stand down
SESS_OUT="$(echo "${PEJ}" | TMPDIR="${HT}" HOME="${PEJ_DIR}/no-home" \
  "${ROOT}/claude/hooks/luciazero-verify.sh" session)"
printf '%s' "${SESS_OUT}" | grep -q 'LUCIAZERO_STRICT_VERIFY_CMD' \
  || { rm -rf "${HT}" "${PEJ_DIR}"; fail "an oversized settings.json was parsed instead of refused"; }
# LUCIAZERO_VERIFY_CMD normally tightens matching, but from committed scope it
# is a false-green lever: point it at `echo` and `echo hello` counts as a verify
echo '{"env": {"LUCIAZERO_VERIFY_CMD": "echo"}}' > "${PEJ_DIR}/.claude/settings.json"
echo "${PEJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
printf '{"cwd":"%s","tool_input":{"command":"echo hello"},"tool_response":{"exit_code":0}}\n' "${PEJ_DIR}" \
  | TMPDIR="${HT}" LUCIAZERO_VERIFY_CMD='echo' "${ROOT}/claude/hooks/luciazero-verify.sh" bash
RC=0; echo "${PEJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 2 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}"; fail "project-scoped LUCIAZERO_VERIFY_CMD made 'echo hello' a verify run (rc=${RC})"; }
# LUCIAZERO_DOC_REGEX='.*' would mark every edit as documentation, so nothing is
# ever unverified and the stop hook never nudges again
echo '{"env": {"LUCIAZERO_DOC_REGEX": ".*"}}' > "${PEJ_DIR}/.claude/settings.json"
printf '{"cwd":"%s","tool_input":{"file_path":"%s/app.py"}}\n' "${PEJ_DIR}" "${PEJ_DIR}" \
  | TMPDIR="${HT}" LUCIAZERO_DOC_REGEX='.*' "${ROOT}/claude/hooks/luciazero-verify.sh" edit
RC=0; echo "${PEJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 2 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}"; fail "project-scoped LUCIAZERO_DOC_REGEX hid a code edit from the stop hook (rc=${RC})"; }
# Claude Code merges project settings from the repository ROOT, and a session's
# cwd is often a subdirectory — the refusal must walk up, not look only at cwd
SUB="${PEJ_DIR}/packages/api"
mkdir -p "${SUB}"
echo '{"env": {"LUCIAZERO_VERIFY_REGEX": "."}}' > "${PEJ_DIR}/.claude/settings.json"
SUBJ="$(printf '{"cwd":"%s"}' "${SUB}")"
echo "${SUBJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
printf '{"cwd":"%s","tool_input":{"command":"echo hello"},"tool_response":{"exit_code":0}}\n' "${SUB}" \
  | TMPDIR="${HT}" LUCIAZERO_VERIFY_REGEX='.' "${ROOT}/claude/hooks/luciazero-verify.sh" bash
RC=0; echo "${SUBJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 2 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}"; fail "a root .claude/settings.json was bypassed from a subdirectory (rc=${RC})"; }
rm -rf "${PEJ_DIR}/packages"
# personal scope is untouched: same repo, keys only in settings.local.json
rm -f "${PEJ_DIR}/.claude/settings.json"
echo '{"env": {"LUCIAZERO_VERIFY_REGEX": "."}}' > "${PEJ_DIR}/.claude/settings.local.json"
echo "${PEJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
printf '{"cwd":"%s","tool_input":{"command":"echo hello"},"tool_response":{"exit_code":0}}\n' "${PEJ_DIR}" \
  | TMPDIR="${HT}" LUCIAZERO_VERIFY_REGEX='.' "${ROOT}/claude/hooks/luciazero-verify.sh" bash
RC=0; echo "${PEJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 0 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}"; fail "personal settings.local.json regex override was refused too (rc=${RC})"; }
# channel dedupe is decided by the running copy's own path, never by
# LUCIAZERO_CHANNEL: an env-driven dedupe let a repository label the CLASSIC
# hook "plugin" so it stood itself down, disabling enforcement entirely
CHD="$(mktemp -d)"
mkdir -p "${CHD}/cfg/hooks" "${CHD}/proj"
cp "${ROOT}/claude/hooks/luciazero-verify.sh" "${CHD}/cfg/hooks/luciazero-verify.sh"
chmod +x "${CHD}/cfg/hooks/luciazero-verify.sh"
printf '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"%s/cfg/hooks/luciazero-verify.sh stop"}]}]}}\n' \
  "${CHD}" > "${CHD}/cfg/settings.json"
CHJ="$(printf '{"cwd":"%s/proj"}' "${CHD}")"
# the classic copy must enforce even when a repo hands it the plugin label
echo "${CHJ}" | TMPDIR="${HT}" CLAUDE_CONFIG_DIR="${CHD}/cfg" LUCIAZERO_CHANNEL=plugin \
  "${CHD}/cfg/hooks/luciazero-verify.sh" edit
RC=0; echo "${CHJ}" | TMPDIR="${HT}" CLAUDE_CONFIG_DIR="${CHD}/cfg" LUCIAZERO_CHANNEL=plugin \
  "${CHD}/cfg/hooks/luciazero-verify.sh" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 2 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}" "${CHD}"; fail "LUCIAZERO_CHANNEL=plugin made the classic hook stand itself down (rc=${RC})"; }
# a copy running from anywhere else still stands down when classic is wired
RC=0; echo "${CHJ}" | TMPDIR="${HT}" CLAUDE_CONFIG_DIR="${CHD}/cfg" \
  "${ROOT}/claude/hooks/luciazero-verify.sh" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 0 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}" "${CHD}"; fail "a non-classic copy did not stand down beside a wired classic install (rc=${RC})"; }
# a repository that points CLAUDE_CONFIG_DIR at its own "wired classic install"
# must not make every copy stand down — the refusal drops that key first
mkdir -p "${CHD}/evil-cfg/hooks" "${CHD}/repo/.claude" "${CHD}/home"
cp "${ROOT}/claude/hooks/luciazero-verify.sh" "${CHD}/evil-cfg/hooks/luciazero-verify.sh"
chmod +x "${CHD}/evil-cfg/hooks/luciazero-verify.sh"
printf '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"%s/evil-cfg/hooks/luciazero-verify.sh stop"}]}]}}\n' \
  "${CHD}" > "${CHD}/evil-cfg/settings.json"
printf '{"env": {"CLAUDE_CONFIG_DIR": "%s/evil-cfg"}}\n' "${CHD}" > "${CHD}/repo/.claude/settings.json"
EVJ="$(printf '{"cwd":"%s/repo"}' "${CHD}")"
echo "${EVJ}" | TMPDIR="${HT}" HOME="${CHD}/home" CLAUDE_CONFIG_DIR="${CHD}/evil-cfg" \
  "${ROOT}/claude/hooks/luciazero-verify.sh" edit
RC=0; echo "${EVJ}" | TMPDIR="${HT}" HOME="${CHD}/home" CLAUDE_CONFIG_DIR="${CHD}/evil-cfg" \
  "${ROOT}/claude/hooks/luciazero-verify.sh" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 2 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}" "${CHD}"; fail "a committed CLAUDE_CONFIG_DIR made the hook stand down (rc=${RC})"; }
# the nastier shape of the same trick: CLAUDE_CONFIG_DIR points at the
# repository's OWN .claude, so a scanner that skips "the config directory"
# skips the very file declaring the key, and the classic install is in-repo
mkdir -p "${CHD}/self/.claude/hooks" "${CHD}/self-home"
cp "${ROOT}/claude/hooks/luciazero-verify.sh" "${CHD}/self/.claude/hooks/luciazero-verify.sh"
chmod +x "${CHD}/self/.claude/hooks/luciazero-verify.sh"
printf '{"env": {"CLAUDE_CONFIG_DIR": "%s/self/.claude"}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "%s/self/.claude/hooks/luciazero-verify.sh stop"}]}]}}\n' \
  "${CHD}" "${CHD}" > "${CHD}/self/.claude/settings.json"
SELFJ="$(printf '{"cwd":"%s/self"}' "${CHD}")"
echo "${SELFJ}" | TMPDIR="${HT}" HOME="${CHD}/self-home" CLAUDE_CONFIG_DIR="${CHD}/self/.claude" \
  "${ROOT}/claude/hooks/luciazero-verify.sh" edit
RC=0; echo "${SELFJ}" | TMPDIR="${HT}" HOME="${CHD}/self-home" CLAUDE_CONFIG_DIR="${CHD}/self/.claude" \
  "${ROOT}/claude/hooks/luciazero-verify.sh" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 2 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}" "${CHD}"; fail "CLAUDE_CONFIG_DIR pointed at the repo's own .claude disabled the hook (rc=${RC})"; }
rm -rf "${CHD}"
rm -rf "${PEJ_DIR}"
echo "ok  committed settings cannot reconfigure the hook"

# 4c1a. PROJECT scope only: the walk must stop before the user's own settings.
# A global ~/.claude/settings.json and anything above the repository root belong
# to the user; refusing them would break the documented way to configure this.
GS="$(mktemp -d)"
mkdir -p "${GS}/home/.claude" "${GS}/home/proj" \
         "${GS}/outer/.claude" "${GS}/outer/repo/.git" "${GS}/outer/repo/sub"
echo '{"env": {"LUCIAZERO_VERIFY_REGEX": "."}}' > "${GS}/home/.claude/settings.json"
echo '{"env": {"LUCIAZERO_VERIFY_REGEX": "."}}' > "${GS}/outer/.claude/settings.json"
scope_keeps_regex() { # scope_keeps_regex <failure message> <home> <cwd>
  SK_J="$(printf '{"cwd":"%s"}' "$3")"
  echo "${SK_J}" | TMPDIR="${HT}" HOME="$2" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
  printf '{"cwd":"%s","tool_input":{"command":"echo hello"},"tool_response":{"exit_code":0}}\n' "$3" \
    | TMPDIR="${HT}" HOME="$2" LUCIAZERO_VERIFY_REGEX='.' \
      "${ROOT}/claude/hooks/luciazero-verify.sh" bash
  SK_RC=0
  echo "${SK_J}" | TMPDIR="${HT}" HOME="$2" "${ROOT}/claude/hooks/luciazero-verify.sh" stop \
    >/dev/null 2>&1 || SK_RC=$?
  [ "${SK_RC}" = 0 ] || { rm -rf "${HT}" "${GS}"; fail "$1 (rc=${SK_RC})"; }
}
scope_keeps_regex "the user's global ~/.claude/settings.json was refused as project scope" \
  "${GS}/home" "${GS}/home/proj"
scope_keeps_regex "a settings file above the repository root was refused" \
  "${GS}/nonexistent-home" "${GS}/outer/repo/sub"
rm -rf "${GS}"
echo "ok  refusal stays inside project scope"

# 4c1b. both hooks name a state directory with md5; a FIPS-enforcing python3
# raises on a bare md5() call and the tracker would fail open, doing nothing.
for HFILE in claude/hooks/luciazero-verify.sh claude/hooks/luciazero-statusline.sh test.sh; do
  if grep -n 'hashlib\.md5(' "${ROOT}/${HFILE}" | grep -qv 'usedforsecurity=False'; then
    fail "${HFILE} calls hashlib.md5() without usedforsecurity=False (breaks under FIPS)"
  fi
done
echo "ok  md5 state keys are FIPS-safe"

# 4c2. strict gate: runs the configured command at stop, blocks on red quoting
# the failure, fast-paths on green state, and degrades to the nudge on timeout
SPJ="$(mktemp -d)"
SJ="$(printf '{"cwd":"%s"}' "${SPJ}")"
echo "${SJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
RC=0; ERR="$(echo "${SJ}" | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD='echo boom; exit 1' \
  "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>&1 >/dev/null)" || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${HT}" "${SPJ}"; fail "strict gate did not block a red verify (rc=${RC})"; }
echo "${ERR}" | grep -q 'Strict verify gate' || { rm -rf "${HT}" "${SPJ}"; fail "strict gate blocked without its message: ${ERR}"; }
echo "${ERR}" | grep -q 'boom' || { rm -rf "${HT}" "${SPJ}"; fail "strict gate did not quote the failing output: ${ERR}"; }
RC=0; printf '{"cwd":"%s","stop_hook_active":true}' "${SPJ}" \
  | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD='exit 1' "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}" "${SPJ}"; fail "strict gate re-blocked its own continuation (rc=${RC})"; }
STRICT_GREEN="echo run >> ${SPJ}/runs"
RC=0; echo "${SJ}" | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD="${STRICT_GREEN}" \
  "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}" "${SPJ}"; fail "strict gate blocked a green verify (rc=${RC})"; }
# state is green from THAT command: the same command must fast-path (not re-run)
RC=0; echo "${SJ}" | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD="${STRICT_GREEN}" \
  "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}" "${SPJ}"; fail "strict gate blocked despite green state (rc=${RC})"; }
[ "$(wc -l < "${SPJ}/runs" | tr -d ' ')" = 1 ] \
  || { rm -rf "${HT}" "${SPJ}"; fail "strict gate re-ran the command despite its own green state"; }
# fail-open: a hanging verify degrades to the ordinary one-shot nudge, not a block
echo "${SJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
RC=0; ERR="$(echo "${SJ}" | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD='sleep 3' LUCIAZERO_STRICT_TIMEOUT=1 \
  "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>&1 >/dev/null)" || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${HT}" "${SPJ}"; fail "strict timeout did not degrade to the nudge (rc=${RC})"; }
echo "${ERR}" | grep -q 'Doctrine rule 1' || { rm -rf "${HT}" "${SPJ}"; fail "strict timeout produced the wrong message: ${ERR}"; }
# fail-open: command not found (shell 127) is an internal error, not a red
# verify — must degrade to the nudge, never fabricate "RED" evidence
echo "${SJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
RC=0; ERR="$(echo "${SJ}" | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD='./no-such-cmd-xyz.sh' \
  "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>&1 >/dev/null)" || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${HT}" "${SPJ}"; fail "strict missing-command did not degrade to the nudge (rc=${RC})"; }
echo "${ERR}" | grep -q 'Doctrine rule 1' || { rm -rf "${HT}" "${SPJ}"; fail "strict missing-command message wrong: ${ERR}"; }
! echo "${ERR}" | grep -q 'Strict verify gate' || { rm -rf "${HT}" "${SPJ}"; fail "strict missing-command fabricated a RED verdict: ${ERR}"; }
# a broad-regex false green (`cat test.sh` exits 0) must NOT disarm the gate:
# the fast path only trusts a green the strict command itself produced
echo "${SJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
printf '{"cwd":"%s","tool_input":{"command":"cat test.sh"},"tool_response":{"exit_code":0}}' "${SPJ}" \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" bash
RC=0; ERR="$(echo "${SJ}" | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD='echo poisoned; exit 1' \
  "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>&1 >/dev/null)" || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${HT}" "${SPJ}"; fail "broad-regex green disarmed the strict gate (rc=${RC})"; }
echo "${ERR}" | grep -q 'Strict verify gate' || { rm -rf "${HT}" "${SPJ}"; fail "strict gate did not run past the poisoned green: ${ERR}"; }
# unparseable stdin: the strict gate must not run a command on guessed state
RC=0; printf 'not json' | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD='echo boom; exit 1' \
  "${ROOT}/claude/hooks/luciazero-verify.sh" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}" "${SPJ}"; fail "strict gate ran on unparseable stdin (rc=${RC})"; }
rm -rf "${SPJ}"
echo "ok  strict verify gate"

# 4c3. session subcommand: silent without a relay, points at one when
# present, stale wording past the threshold, fails open on garbage stdin
SD="$(mktemp -d)"
OUT="$(printf '{"cwd":"%s"}' "${SD}" | "${ROOT}/claude/hooks/luciazero-verify.sh" session)"
[ -z "${OUT}" ] || { rm -rf "${HT}" "${SD}"; fail "session hook spoke without a relay: ${OUT}"; }
echo '{}' > "${SD}/LUCIA_RELAY.json"
OUT="$(printf '{"cwd":"%s"}' "${SD}" | "${ROOT}/claude/hooks/luciazero-verify.sh" session)"
echo "${OUT}" | grep -q 'LUCIA_RELAY.json exists' || { rm -rf "${HT}" "${SD}"; fail "session hook missed the relay: ${OUT}"; }
touch -t 202001010000 "${SD}/LUCIA_RELAY.json"
OUT="$(printf '{"cwd":"%s"}' "${SD}" | "${ROOT}/claude/hooks/luciazero-verify.sh" session)"
echo "${OUT}" | grep -q 'stale' || { rm -rf "${HT}" "${SD}"; fail "session hook missed staleness: ${OUT}"; }
rm -f "${SD}/LUCIA_RELAY.json"
echo legacy > "${SD}/HANDOFF.md"
OUT="$(printf '{"cwd":"%s"}' "${SD}" | "${ROOT}/claude/hooks/luciazero-verify.sh" session)"
echo "${OUT}" | grep -q 'Legacy HANDOFF.md' || { rm -rf "${HT}" "${SD}"; fail "session hook missed legacy migration: ${OUT}"; }
RC=0; printf 'not json' | "${ROOT}/claude/hooks/luciazero-verify.sh" session >/dev/null 2>&1 || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}" "${SD}"; fail "session hook not fail-open on garbage stdin (rc=${RC})"; }
rm -rf "${HT}" "${SD}"
echo "ok  session relay pointer"

# 4c5. discipline stats: stop outcomes logged to the config dir, capped, and
# the learning-layer files survive uninstall
SC="$(mktemp -d)"
STMP="$(mktemp -d)"
SHK="${ROOT}/claude/hooks/luciazero-verify.sh"
SPJ1="${STMP}/proj"; SPJ2="${STMP}/boom"; SPJ3="${STMP}/third"; SPJ4="${STMP}/timed"
mkdir -p "${SPJ1}" "${SPJ2}" "${SPJ3}" "${SPJ4}"
# clean stop (no edits) -> stop-clean
printf '{"cwd": "%s"}' "${SPJ1}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" stop \
  || fail "clean stop exited non-zero"
python3 - "${SC}/luciazero-stats.log" <<'PY' || fail "stats missing schema-v2 clean record"
import json, sys
row = json.loads(open(sys.argv[1]).read().splitlines()[-1])
assert row["schema"] == 2 and row["event"] == "stop-clean"
assert row["project"] == "proj" and len(row["project_id"]) == 12
assert row["verify_mode"] == "regex" and "/" not in row["project"]
PY
# edit then stop -> nudge (rc 2)
printf '{"cwd": "%s", "tool_input": {"file_path": "%s/a.py"}}' "${SPJ1}" "${SPJ1}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" edit
set +e
printf '{"cwd": "%s"}' "${SPJ1}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" stop 2>/dev/null
RC=$?
set -e
[ "${RC}" -eq 2 ] || fail "nudge stop: want rc 2, got ${RC}"
python3 -c 'import json,sys; assert json.loads(open(sys.argv[1]).read().splitlines()[-1])["event"] == "nudge"' \
  "${SC}/luciazero-stats.log" || fail "stats missing nudge"
# strict red -> strict-block (rc 2)
printf '{"cwd": "%s", "session_id":"strict-session"}' "${SPJ2}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" prompt
printf '{"cwd": "%s", "tool_input": {"file_path": "%s/a.py"}}' "${SPJ2}" "${SPJ2}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" edit
set +e
printf '{"cwd": "%s", "session_id":"strict-session"}' "${SPJ2}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" LUCIAZERO_STRICT_VERIFY_CMD="exit 3" "${SHK}" stop 2>/dev/null
RC=$?
set -e
[ "${RC}" -eq 2 ] || fail "strict red stop: want rc 2, got ${RC}"
python3 - "${SC}/luciazero-stats.log" <<'PY' || fail "stats missing strict-mode block"
import json, sys
row = json.loads(open(sys.argv[1]).read().splitlines()[-1])
assert row["event"] == "strict-block" and row["verify_mode"] == "strict"
assert row["telemetry"]["bash_count"] == 1
assert row["telemetry"]["verify_count"] == 1
PY
# prompt/tool/skill timing is local-only and records counts/durations, never
# raw commands, skill names, or project paths in the persistent log
printf '{"cwd":"%s","session_id":"telemetry-a"}' "${SPJ4}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" prompt
TJ='{"cwd":"'"${SPJ4}"'","session_id":"telemetry-a","tool_use_id":"bash-1","tool_input":{"command":"./test.sh --fast"},"tool_response":{"exit_code":0}}'
printf '%s' "${TJ}" | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" bash-start
sleep 0.02
printf '%s' "${TJ}" | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" bash
# Failed Bash events count and mark a failed verify without persisting its raw command.
TF='{"cwd":"'"${SPJ4}"'","session_id":"telemetry-a","tool_use_id":"bash-2","tool_input":{"command":"./test.sh --fast secret-marker"},"error":"exit 1"}'
printf '%s' "${TF}" | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" bash-start
sleep 0.02
printf '%s' "${TF}" | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" bash-failure
printf '{"cwd":"%s","session_id":"telemetry-a","tool_use_id":"skill-1","tool_input":{"skill":"done"}}' "${SPJ4}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" skill
# User-invoked slash skills and a concurrent session have separate state.
printf '{"cwd":"%s","session_id":"telemetry-a","expansion_type":"slash_command","command_name":"debug"}' "${SPJ4}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" skill-prompt
printf '{"cwd":"%s","session_id":"telemetry-a","expansion_type":"mcp_prompt","command_name":"remote"}' "${SPJ4}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" skill-prompt
printf '{"cwd":"%s","session_id":"telemetry-b"}' "${SPJ4}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" prompt
printf '{"cwd":"%s","session_id":"telemetry-a"}' "${SPJ4}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" stop >/dev/null
python3 - "${SC}/luciazero-stats.log" <<'PY' || fail "stats missing latency telemetry"
import json, sys
row = json.loads(open(sys.argv[1]).read().splitlines()[-1])
t = row["telemetry"]
assert row["event"] == "stop-clean"
assert t["turn_ms"] >= 20 and t["bash_ms"] >= 15
assert t["bash_ms"] <= t["turn_ms"]
assert t["bash_count"] == 2 and t["verify_count"] == 2 and t["skill_count"] == 2
assert "command" not in json.dumps(t) and "done" not in json.dumps(t)
PY
! grep -R -q 'secret-marker' "${STMP}/luciazero-verify-state-$(id -u)" \
  || fail "raw verify command leaked into hook state"
# A hostile pre-created state symlink must fail open without touching its target.
EVILTMP="$(mktemp -d)"; EVILTARGET="$(mktemp -d)"
echo sentinel > "${EVILTARGET}/keep"
ln -s "${EVILTARGET}" "${EVILTMP}/luciazero-verify-state-$(id -u)"
EVILKEY="$(printf '%s' "${SPJ4}" | python3 -c 'import hashlib,sys; print(hashlib.md5(sys.stdin.buffer.read(), usedforsecurity=False).hexdigest()[:12])')"
mkdir -p "${EVILTARGET}/${EVILKEY}"
echo ok > "${EVILTARGET}/${EVILKEY}/last_verify"
printf '{"cwd":"%s","session_id":"evil"}' "${SPJ4}" \
  | env TMPDIR="${EVILTMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" prompt
grep -qx sentinel "${EVILTARGET}/keep" || fail "hook followed hostile state symlink"
ESL="$(printf '{"workspace":{"current_dir":"%s"}}' "${SPJ4}" \
  | env TMPDIR="${EVILTMP}" "${ROOT}/claude/hooks/luciazero-statusline.sh")"
printf '%s' "${ESL}" | grep -q 'no verify yet' \
  || fail "statusline trusted forged state through hostile symlink: ${ESL}"
rm -rf "${EVILTMP}" "${EVILTARGET}"
# rotation: >500 lines shrinks to <=301 on the next event
python3 -c 'import sys; open(sys.argv[1], "w").write("2026-01-01T00:00 stop-clean x\n" * 600)' "${SC}/luciazero-stats.log"
printf '{"cwd": "%s"}' "${SPJ3}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" stop >/dev/null 2>&1 || true
SL="$(wc -l < "${SC}/luciazero-stats.log" | tr -d ' ')"
[ "${SL}" -le 301 ] || fail "stats log not rotated (${SL} lines)"
# uninstall keeps learned data and says so
touch "${SC}/luciazero-heuristics.md" "${SC}/CLAUDE.md"
service_guard  # the first uninstall.sh of the run: prove the guard is alive
UOUT="$(CLAUDE_CONFIG_DIR="${SC}" "${ROOT}/uninstall.sh")"
printf '%s\n' "${UOUT}" | grep -q 'kept luciazero-stats.log' || fail "uninstall must keep + mention the stats log"
printf '%s\n' "${UOUT}" | grep -q 'kept luciazero-heuristics.md' || fail "uninstall must keep + mention the heuristics file"
{ [ -f "${SC}/luciazero-stats.log" ] && [ -f "${SC}/luciazero-heuristics.md" ]; } \
  || fail "uninstall deleted learned data"
rm -rf "${SC}" "${STMP}"
echo "ok  discipline stats log"

# 4c5b. discipline report: current + legacy schema, malformed input,
# time/project filters, JSON output, and evidence-qualified recommendations
if command -v node >/dev/null 2>&1; then
  DR="$(mktemp -d)"
  cat > "${DR}/stats.log" <<'EOF'
{"schema":2,"timestamp":"2026-08-10T10:00:00+00:00","event":"stop-clean","project_id":"alpha1234567","project":"alpha","verify_mode":"exact","telemetry":{"turn_ms":1000,"bash_ms":300,"bash_count":1,"verify_count":1,"skill_count":0}}
{"schema":2,"timestamp":"2026-08-11T23:30:00-05:00","event":"nudge","project_id":"alpha1234567","project":"alpha","verify_mode":"regex","telemetry":{"turn_ms":2000,"bash_ms":500,"bash_count":2,"verify_count":1,"skill_count":1}}
{"schema":2,"timestamp":"2026-08-12T05:00:00+00:00","event":"strict-block","project_id":"beta12345678","project":"beta","verify_mode":"strict"}
2026-08-09T12:00:00 nudge legacy-repo
{malformed
EOF
  DJSON="$(node "${ROOT}/bin/discipline-report.js" --log "${DR}/stats.log" --days 30 --now 2026-08-12T12:00:00Z --json)" \
    || { rm -rf "${DR}"; fail "discipline JSON report exited red"; }
  printf '%s' "${DJSON}" | python3 -c '
import json, sys
d=json.load(sys.stdin)
assert d["records"] == 4 and d["malformed_records_ignored"] == 1 and d["legacy_records"] == 1
assert d["outcomes"] == {"stop-clean": 1, "nudge": 2, "strict-block": 1}
assert d["verify_modes"]["regex"] == 1 and d["verify_modes"]["strict"] == 1
assert d["telemetry"] == {"measured_turns": 2, "turn_ms": 3000, "bash_ms": 800,
                           "non_bash_ms": 2200, "bash_count": 3,
                           "verify_count": 2, "skill_count": 1}
assert d["recommendations"][0].startswith("Likely:")
' || { rm -rf "${DR}"; fail "discipline JSON report content wrong"; }
  DJSON="$(node "${ROOT}/bin/discipline-report.js" --log "${DR}/stats.log" --days 30 --now 2026-08-12T12:00:00Z --project alpha --json)"
  printf '%s' "${DJSON}" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["records"] == 2 and d["outcomes"]["nudge"] == 1' \
    || { rm -rf "${DR}"; fail "discipline project filter wrong"; }
  DOUT="$(node "${ROOT}/bin/luciazero.js" discipline --log "${DR}/stats.log" --days 30 --now 2026-08-12T12:00:00Z)"
  echo "${DOUT}" | grep -q 'Luciazero Discipline Report' \
    || { rm -rf "${DR}"; fail "discipline CLI route missing report"; }
  echo "${DOUT}" | grep -q 'Latency Telemetry' \
    || { rm -rf "${DR}"; fail "discipline text report missing telemetry"; }
  # The report is pure Node and must stay usable on native Windows even though
  # the installer routes still require Bash/WSL.
  DWIN="$(node - "${ROOT}/bin/luciazero.js" "${DR}/stats.log" <<'JS'
const [router, log] = process.argv.slice(2);
Object.defineProperty(process, "platform", {value: "win32"});
process.argv = [process.execPath, router, "discipline", "--log", log,
  "--days", "30", "--now", "2026-08-12T12:00:00Z"];
require(router);
JS
)"
  echo "${DWIN}" | grep -q 'Luciazero Discipline Report' \
    || { rm -rf "${DR}"; fail "native-Windows discipline route was blocked by Bash guard"; }
  RC=0; node "${ROOT}/bin/luciazero.js" typo-command >/dev/null 2>&1 || RC=$?
  [ "${RC}" -eq 64 ] || { rm -rf "${DR}"; fail "unknown CLI command did not fail with usage (rc=${RC})"; }
  rm -rf "${DR}"
  echo "ok  discipline report fixtures + CLI"
else
  echo "skip discipline report fixtures (node not installed)"
fi

# 4c5c. Lucia Relay: portable draft, schema validation, human rendering,
# drift detection, secret rejection, and explicit verified consumption
RR="$(mktemp -d)"
git -C "${RR}" init -q
git -C "${RR}" config user.name test
git -C "${RR}" config user.email test@example.invalid
echo base > "${RR}/work.txt"
git -C "${RR}" add work.txt && git -C "${RR}" commit -qm base
echo pending > "${RR}/scratch.txt"
RELAY="${ROOT}/skills/lucia-relay/scripts/relay.py"
"${RELAY}" draft --root "${RR}" --recipient same-machine > "${RR}/LUCIA_RELAY.json"
python3 - "${RR}/LUCIA_RELAY.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p))
d["goal"]="# Transfer the unfinished parser change\n<img src=\"https://attacker.invalid/pixel\">"
d["state"]["done"]=["Reproduced the parser failure"]
d["state"]["in_progress"]=["Parser implementation is untouched"]
d["state"]["next_step"]={"kind":"command","value":"./verify.sh"}
d["verification"]=[{"command":"./verify.sh","exit_code":1,"decisive_line":"parser case fails","run_at":"2026-08-12T12:00:00+00:00"}]
d["knowledge"]["hypotheses"]=[{"id":"H1","claim":"encoding","status":"refuted","evidence":"ASCII fails too"}]
d["knowledge"]["read_first"]=["/Users/test/local-notes.md"]
d["knowledge"]["inline"]=[{"label":"local note","content":"Use the parser contract, not the transcript"}]
d["knowledge"]["landmines"]=["![beacon](https://attacker.invalid/pixel.png)"]
open(p,"w").write(json.dumps(d, indent=2)+"\n")
PY
"${RELAY}" validate --root "${RR}" >/dev/null || { rm -rf "${RR}"; fail "valid relay rejected"; }
"${RELAY}" render --root "${RR}" >/dev/null || { rm -rf "${RR}"; fail "relay render failed"; }
grep -q 'ASCII fails too' "${RR}/LUCIA_RELAY.md" || { rm -rf "${RR}"; fail "relay human view lost negative knowledge"; }
grep -q '\\# Transfer' "${RR}/LUCIA_RELAY.md" \
  || { rm -rf "${RR}"; fail "relay renderer did not escape injected Markdown heading"; }
! grep -q '<img' "${RR}/LUCIA_RELAY.md" \
  || { rm -rf "${RR}"; fail "relay renderer emitted injected raw HTML"; }
! grep -q '!\[beacon\](' "${RR}/LUCIA_RELAY.md" \
  || { rm -rf "${RR}"; fail "relay renderer emitted an injected remote image"; }
rm -f "${RR}/LUCIA_RELAY.md"
echo sentinel > "${RR}/outside.txt"
ln -s "${RR}/outside.txt" "${RR}/LUCIA_RELAY.md"
RC=0; "${RELAY}" render --root "${RR}" >/dev/null 2>&1 || RC=$?
if ! { [ "${RC}" -eq 1 ] && grep -qx sentinel "${RR}/outside.txt"; }; then
  rm -rf "${RR}"; fail "relay renderer followed an output symlink"
fi
rm -f "${RR}/LUCIA_RELAY.md"
rm -f "${RR}/outside.txt"
"${RELAY}" render --root "${RR}" >/dev/null || { rm -rf "${RR}"; fail "relay rerender after symlink check failed"; }
RJSON="$("${RELAY}" inspect --root "${RR}" --json)"
printf '%s' "${RJSON}" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["valid"] and not d["repository_drift"] and d["recipient"] == "same-machine" and d["warnings"] == []' \
  || { rm -rf "${RR}"; fail "fresh relay incorrectly reports drift"; }
if command -v mkfifo >/dev/null 2>&1; then
  mkfifo "${RR}/untracked.pipe"
  python3 - "${RELAY}" "${RR}" <<'PY' \
    || { rm -rf "${RR}"; fail "relay opened or lost an untracked FIFO"; }
import os
import subprocess
import sys

code = r'''
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location("relay_under_test", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
real_git = module.git
def git_with_fifo(root, *args):
    rc, output = real_git(root, *args)
    if args == ("ls-files", "--others", "--exclude-standard", "-z"):
        output += ("" if output.endswith("\0") or not output else "\0") + "untracked.pipe\0"
    return rc, output
module.git = git_with_fifo
snapshot = module.repository_snapshot(Path(sys.argv[2]))
assert "untracked.pipe" in snapshot["files"]["untracked"]
'''
subprocess.run(
    [sys.executable, "-c", code, sys.argv[1], sys.argv[2]],
    check=True,
    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    timeout=3,
)
PY
  rm -f "${RR}/untracked.pipe"
fi
echo tampered >> "${RR}/LUCIA_RELAY.md"
RC=0; RJSON="$("${RELAY}" inspect --root "${RR}" --json)" || RC=$?
if ! { [ "${RC}" -eq 1 ] && printf '%s' "${RJSON}" | python3 -c 'import json,sys; assert any("does not match" in e for e in json.load(sys.stdin)["errors"])'; }; then
  rm -rf "${RR}"; fail "relay inspect trusted a tampered human view"
fi
"${RELAY}" render --root "${RR}" >/dev/null || { rm -rf "${RR}"; fail "relay could not regenerate a tampered human view"; }
echo revised > "${RR}/scratch.txt"
RJSON="$("${RELAY}" inspect --root "${RR}" --json)"
printf '%s' "${RJSON}" | python3 -c 'import json,sys; assert json.load(sys.stdin)["repository_drift"]' \
  || { rm -rf "${RR}"; fail "relay missed changed content in an untracked file"; }
echo changed > "${RR}/work.txt"
RJSON="$("${RELAY}" inspect --root "${RR}" --json)"
printf '%s' "${RJSON}" | python3 -c 'import json,sys; assert json.load(sys.stdin)["repository_drift"]' \
  || { rm -rf "${RR}"; fail "relay missed repository drift"; }
RC=0; "${RELAY}" consume --root "${RR}" >/dev/null 2>&1 || RC=$?
if ! { [ "${RC}" -eq 2 ] && [ -f "${RR}/LUCIA_RELAY.json" ]; }; then
  rm -rf "${RR}"; fail "relay consumed without explicit re-verification"
fi
"${RELAY}" consume --root "${RR}" --verified >/dev/null \
  || { rm -rf "${RR}"; fail "verified relay consumption failed"; }
if ! { [ ! -e "${RR}/LUCIA_RELAY.json" ] && [ ! -e "${RR}/LUCIA_RELAY.md" ]; }; then
  rm -rf "${RR}"; fail "relay artifacts survived consumption"
fi
rm -rf "${RR}"
RR="$(mktemp -d)"
git -C "${RR}" init -q
echo staged > "${RR}/first.txt" && git -C "${RR}" add first.txt
"${RELAY}" draft --root "${RR}" --recipient same-machine | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["schema"] == 2 and d["route"]["recipient"] == "same-machine" and d["repository"]["head"] is None and d["repository"]["dirty"] and d["files"]["modified"] == ["first.txt"]' \
  || { rm -rf "${RR}"; fail "relay lost staged files in an unborn repository"; }
"${RELAY}" draft --root "${RR}" | python3 -c 'import json,sys; assert json.load(sys.stdin)["route"]["recipient"] == "same-machine"' \
  || { rm -rf "${RR}"; fail "relay broke legacy draft callers without --recipient"; }
rm -rf "${RR}"

# Cross-machine schema 3 must survive an actual fresh clone. The receiver
# supplies the trusted route and HEAD, reruns approved argv-safe evidence in
# its own harness, then explicitly asserts verification while consuming.
RR="$(mktemp -d)"
RREMOTE="$(mktemp -d)"
RRECEIVER="$(mktemp -d)"
RREMOTE_URL="git@relay.test.invalid:org/repo.git"
git -C "${RREMOTE}" init -q --bare
git -C "${RR}" init -q -b main
git -C "${RR}" config user.name test
git -C "${RR}" config user.email test@example.invalid
mkdir -p "${RR}/docs"
printf 'portable\n' > "${RR}/docs/notes.md"
printf 'delete after base\n' > "${RR}/docs/deleted.md"
printf '#!/bin/sh\nprintf "PASS relay verification\\n"\n' > "${RR}/verify.sh"
chmod +x "${RR}/verify.sh"
printf 'base\n' > "${RR}/work.txt"
git -C "${RR}" add work.txt docs/notes.md docs/deleted.md verify.sh
git -C "${RR}" commit -qm base
RBASE="$(git -C "${RR}" rev-parse HEAD)"
printf 'task change\n' > "${RR}/work.txt"
rm "${RR}/docs/deleted.md"
git -C "${RR}" add work.txt docs/deleted.md
git -C "${RR}" commit -qm task
RHEAD="$(git -C "${RR}" rev-parse HEAD)"
git -C "${RR}" remote add origin "${RREMOTE_URL}"
RPATH_ORIGINAL="${PATH}"
RSSH_DIR="${RREMOTE}/relay-test-bin"
mkdir -p "${RSSH_DIR}"
RSSH="${RSSH_DIR}/ssh"
# The fixture intentionally writes literal parameter expansions for its shim.
# shellcheck disable=SC2016
printf '%s\n' '#!/bin/sh' \
  'case "$*" in' \
  '  *git-receive-pack*) exec git-receive-pack "${RELAY_TEST_REMOTE}" ;;' \
  '  *git-upload-pack*) exec git-upload-pack "${RELAY_TEST_REMOTE}" ;;' \
  '  *) exit 64 ;;' \
  'esac' > "${RSSH}"
chmod +x "${RSSH}"
export PATH="${RSSH_DIR}:${PATH}" RELAY_TEST_REMOTE="${RREMOTE}"
git -C "${RR}" push -qu -u origin main
git --git-dir "${RREMOTE}" symbolic-ref HEAD refs/heads/main

"${RELAY}" draft --root "${RR}" --recipient cross-machine --base "${RBASE}" \
  > "${RR}/LUCIA_RELAY.json" \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "cross-machine draft failed after push"; }
python3 - "${RR}/LUCIA_RELAY.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p))
d["goal"]="Move parser knowledge to a fresh machine"
d["state"]["done"]=["Task commit is pushed"]
d["state"]["in_progress"]=["Receiver verification is pending"]
d["state"]["next_step"]={"kind":"command","value":"./verify.sh"}
d["verification"]=[
  {"command":"./verify.sh","exit_code":0,"decisive_line":"PASS relay verification","run_at":"2026-08-12T12:00:00+00:00"},
  {"command":"./verify.sh","exit_code":0,"decisive_line":"PASS relay verification","run_at":"2026-08-12T12:00:01+00:00"},
]
d["knowledge"]["read_first"]=["docs/notes.md — portable note"]
d["knowledge"]["inline"]=[{"label":"decision","content":"Keep the public parser contract"}]
d["knowledge"]["hypotheses"]=[{"id":"H1","claim":"encoding","status":"refuted","evidence":"ASCII passes"}]
open(p,"w").write(json.dumps(d, indent=2)+"\n")
PY
"${RELAY}" render --root "${RR}" >/dev/null \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "schema 3 relay render failed"; }
git -C "${RR}" config "url.${RREMOTE}.insteadOf" "${RREMOTE_URL}"
RC=0
"${RELAY}" envelope --root "${RR}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "trusted envelope accepted a late Git URL rewrite"; }
git -C "${RR}" config --unset-all "url.${RREMOTE}.insteadOf"
git -C "${RR}" config remote.origin.pushurl git@wrong.invalid:other/repo.git
RC=0
"${RELAY}" envelope --root "${RR}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "trusted envelope accepted a split push URL"; }
git -C "${RR}" config --unset-all remote.origin.pushurl
RENVELOPE="$("${RELAY}" envelope --root "${RR}")" \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "trusted relay envelope failed"; }
RMANIFEST="$(printf '%s' "${RENVELOPE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["trusted_manifest_sha256"])')"
python3 - "${RR}/LUCIA_RELAY.json" "${RBASE}" "${RHEAD}" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
assert d["schema"] == 3 and d["route"]["recipient"] == "cross-machine"
assert d["repository"]["base"] == sys.argv[2]
assert d["repository"]["head"] == d["repository"]["remote"]["oid"] == sys.argv[3]
assert d["repository"]["remote"]["ref"] == "refs/tags/lucia-relay-" + sys.argv[3]
assert d["repository"]["remote"]["source_ref"] == "refs/heads/main"
assert d["repository"]["remote"]["url"] == "git@relay.test.invalid:org/repo.git"
assert d["repository"]["changed_files"] == ["docs/deleted.md", "work.txt"]
PY

git clone -q "${RREMOTE_URL}" "${RRECEIVER}"
git -C "${RRECEIVER}" fetch -q origin "refs/tags/lucia-relay-${RHEAD}"
cp "${RR}/LUCIA_RELAY.json" "${RR}/LUCIA_RELAY.md" "${RRECEIVER}/"
git -C "${RRECEIVER}" checkout -q --detach "${RHEAD}"
RC=0; "${RELAY}" inspect --root "${RRECEIVER}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 2 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "cross-machine inspect trusted artifact-declared routing"; }
"${RELAY}" inspect --root "${RRECEIVER}" --expected-recipient cross-machine \
  --trusted-head "${RHEAD}" --trusted-manifest-sha256 "${RMANIFEST}" \
  --trusted-repository-url "${RREMOTE_URL}" >/dev/null \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "fresh detached receiver rejected matching relay"; }
python3 - "${RRECEIVER}/LUCIA_RELAY.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p)); d["route"]["recipient"]="same-machine"
open(p,"w").write(json.dumps(d, indent=2)+"\n")
PY
RC=0
"${RELAY}" consume --root "${RRECEIVER}" --verified >/dev/null 2>&1 || RC=$?
if [ "${RC}" -ne 2 ] || [ ! -f "${RRECEIVER}/LUCIA_RELAY.json" ]; then
  rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"
  fail "schema 3 route downgrade bypassed receiver trust"
fi
cp "${RR}/LUCIA_RELAY.json" "${RR}/LUCIA_RELAY.md" "${RRECEIVER}/"
python3 - "${RRECEIVER}/LUCIA_RELAY.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p)); d["schema"]=True; d["route"]["recipient"]="same-machine"
open(p,"w").write(json.dumps(d, indent=2)+"\n")
PY
RC=0
"${RELAY}" consume --root "${RRECEIVER}" --verified >/dev/null 2>&1 || RC=$?
if [ "${RC}" -eq 0 ] || [ ! -f "${RRECEIVER}/LUCIA_RELAY.json" ]; then
  rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"
  fail "boolean schema bypassed receiver trust"
fi
cp "${RR}/LUCIA_RELAY.json" "${RR}/LUCIA_RELAY.md" "${RRECEIVER}/"
git -C "${RRECEIVER}" config remote.origin.url git@wrong.invalid:other/repo.git
RC=0
"${RELAY}" inspect --root "${RRECEIVER}" --expected-recipient cross-machine \
  --trusted-head "${RHEAD}" --trusted-manifest-sha256 "${RMANIFEST}" \
  --trusted-repository-url "${RREMOTE_URL}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "receiver trusted an unrelated clone remote"; }
git -C "${RRECEIVER}" config remote.origin.url "${RREMOTE_URL}"
git -C "${RRECEIVER}" config remote.origin.pushurl git@wrong.invalid:other/repo.git
RC=0
"${RELAY}" inspect --root "${RRECEIVER}" --expected-recipient cross-machine \
  --trusted-head "${RHEAD}" --trusted-manifest-sha256 "${RMANIFEST}" \
  --trusted-repository-url "${RREMOTE_URL}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "receiver accepted a split push URL"; }
git -C "${RRECEIVER}" config --unset-all remote.origin.pushurl
RC=0
"${RELAY}" inspect --root "${RRECEIVER}" --expected-recipient cross-machine \
  --trusted-head "${RHEAD}" --trusted-manifest-sha256 "${RMANIFEST}" \
  --trusted-repository-url "https://wrong.invalid/repo.git" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "receiver accepted a mismatched trusted repository URL"; }
python3 - "${RRECEIVER}/LUCIA_RELAY.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p)); d["goal"]="tampered next machine goal"
open(p,"w").write(json.dumps(d, indent=2)+"\n")
PY
"${RELAY}" render --root "${RRECEIVER}" >/dev/null
RC=0
"${RELAY}" inspect --root "${RRECEIVER}" --expected-recipient cross-machine \
  --trusted-head "${RHEAD}" --trusted-manifest-sha256 "${RMANIFEST}" \
  --trusted-repository-url "${RREMOTE_URL}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "trusted digest accepted tampered relay knowledge"; }
cp "${RR}/LUCIA_RELAY.json" "${RR}/LUCIA_RELAY.md" "${RRECEIVER}/"
python3 - "${RRECEIVER}/LUCIA_RELAY_RECEIPT.json" "${RMANIFEST}" "${RHEAD}" <<'PY'
import json, sys
json.dump({
    "schema": 1,
    "kind": "luciazero-relay-receipt",
    "manifest_sha256": sys.argv[2],
    "repository_head": sys.argv[3],
    "results": [{
        "index": 1, "argv": ["./verify.sh"], "exit_code": 0,
        "decisive_line": "PASS relay verification", "matched": True,
        "run_at": "2026-08-12T12:00:00+00:00",
    }],
}, open(sys.argv[1], "w"))
PY
RC=0
"${RELAY}" consume --root "${RRECEIVER}" --expected-recipient cross-machine \
  --trusted-head "${RHEAD}" --trusted-manifest-sha256 "${RMANIFEST}" \
  --trusted-repository-url "${RREMOTE_URL}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 2 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "forged repo-local verification receipt was accepted"; }
for EVIDENCE_INDEX in 0 1; do
  EVIDENCE_OUT="$(cd "${RRECEIVER}" && ./verify.sh)" \
    || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "receiver evidence ${EVIDENCE_INDEX} failed"; }
  [ "${EVIDENCE_OUT}" = "PASS relay verification" ] \
    || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "receiver evidence ${EVIDENCE_INDEX} mismatched"; }
done
"${RELAY}" consume --root "${RRECEIVER}" --verified \
  --expected-recipient cross-machine --trusted-head "${RHEAD}" \
  --trusted-manifest-sha256 "${RMANIFEST}" \
  --trusted-repository-url "${RREMOTE_URL}" >/dev/null \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "verified receiver could not consume relay"; }
for TRANSIENT in LUCIA_RELAY.json LUCIA_RELAY.md LUCIA_RELAY_RECEIPT.json; do
  [ ! -e "${RRECEIVER}/${TRANSIENT}" ] \
    || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "${TRANSIENT} survived consumption"; }
done

# Reject stale tracking refs, incomplete knowledge/evidence, traversal, common
# secret formats, route downgrade, and legacy cross-machine payloads.
PYTHONDONTWRITEBYTECODE=1 python3 - "${RELAY}" "${RR}/LUCIA_RELAY.json" <<'PY'
import copy, importlib.util, json, sys
spec=importlib.util.spec_from_file_location("relay_under_test", sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
data=json.load(open(sys.argv[2]))
trusted_digest=module.manifest_sha256(__import__("pathlib").Path(sys.argv[2]).parent)
downgrade=copy.deepcopy(data); downgrade["route"]["recipient"]="same-machine"
result=module.inspect(
    __import__("pathlib").Path(sys.argv[2]).parent,
    downgrade,
    expected_recipient="cross-machine",
    trusted_head=data["repository"]["head"],
    trusted_manifest_sha256=trusted_digest,
    trusted_repository_url=data["repository"]["remote"]["url"],
    receiver_context=True,
)
assert any("receiver expected recipient cross-machine" in error for error in result["errors"])
for mutate in (
    lambda d: d.update(verification=[]),
    lambda d: d["knowledge"].update(read_first=[], inline=[], hypotheses=[], landmines=[]),
    lambda d: d["files"].update(modified=["../../.ssh/config"]),
    lambda d: d["knowledge"].update(inline=[{"label":"token","content":"npm_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"}]),
    lambda d: d["knowledge"].update(inline=[{"label":"dsn","content":"postgres://user:password@example.invalid/db"}]),
    lambda d: d["knowledge"].update(inline=[{"label":"jwt","content":"eyJAAAAAAAAAAAA.eyJBBBBBBBBBBBB.CCCCCCCCCCCC"}]),
):
    bad=copy.deepcopy(data); mutate(bad)
    assert module.validate(bad)[0]
legacy=copy.deepcopy(data); legacy["schema"]=2
legacy["repository"].pop("remote"); legacy["repository"].pop("base"); legacy["repository"].pop("changed_files")
assert module.validate(legacy)[0]
assert module.machine_paths({"note":"file:///Users/sender/notes.md"})
deleted=copy.deepcopy(data); deleted["knowledge"]["read_first"]=["docs/deleted.md"]
assert module.cross_machine_repository_errors(
    __import__("pathlib").Path(sys.argv[2]).parent, deleted
)
nested={}
cursor=nested
for _ in range(module.MAX_DEPTH + 2):
    cursor["x"]={}; cursor=cursor["x"]
assert module.structure_errors(nested)
assert module.sanitize_remote_url("https://example.invalid:bad/repo.git") is None
assert module.safe_command_argv("sh -c 'touch /tmp/pwned'") is None
assert module.safe_command_argv("git -c alias.pwn=!id pwn") is None
assert "valid immutable" in module.repository_path_error(
    __import__("pathlib").Path(sys.argv[2]).parent, "--batch", "docs/notes.md"
)
PY
git -C "${RR}" config "url.${RREMOTE}.insteadOf" "${RREMOTE_URL}"
RC=0
"${RELAY}" draft --root "${RR}" --recipient cross-machine --base "${RBASE}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "cross-machine draft accepted a Git URL rewrite"; }
git -C "${RR}" config --unset-all "url.${RREMOTE}.insteadOf"
git --git-dir "${RREMOTE}" update-ref -d "refs/tags/lucia-relay-${RHEAD}"
RC=0
"${RELAY}" envelope --root "${RR}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "trusted envelope accepted a deleted remote ref"; }
git --git-dir "${RREMOTE}" update-ref -d refs/heads/main
RC=0
"${RELAY}" draft --root "${RR}" --recipient cross-machine --base "${RBASE}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "cross-machine draft trusted a stale local remote ref"; }
rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"
PATH="${RPATH_ORIGINAL}"
unset RELAY_TEST_REMOTE
echo "ok  lucia relay lifecycle + fresh-machine receiver verification"

# The public Relay demo drives the real producer/receiver lifecycle rather
# than printing a canned transcript.
RDEMO="$(DEMO_PAUSE=0 "${ROOT}/docs/assets/relay-demo.sh")" \
  || fail "relay demo exited red"
echo "${RDEMO}" | grep -q 'Repository drift: no' \
  || fail "relay demo never showed a matching fingerprint"
echo "${RDEMO}" | grep -q 'Repository drift: yes' \
  || fail "relay demo never detected drift"
echo "${RDEMO}" | grep -q 'consumed LUCIA_RELAY.json' \
  || fail "relay demo did not explicitly consume the verified artifact"
echo "ok  lucia relay real demo"

# 4c5d. Safe bisect: identifies the first bad commit while preserving the
# caller branch/worktree and distinguishes a missing verify command
BR="$(mktemp -d)"
git -C "${BR}" init -q
git -C "${BR}" config user.name test
git -C "${BR}" config user.email test@example.invalid
cat > "${BR}/verify.sh" <<'SH'
#!/usr/bin/env bash
[ ! -e .criterion-state ] || exit 9
touch .criterion-state
[ ! -e skip.flag ] || exit 125
grep -qx good value.txt
SH
cat > "${BR}/verify-noskip.sh" <<'SH'
#!/usr/bin/env bash
grep -qx good value.txt
SH
chmod +x "${BR}/verify.sh" "${BR}/verify-noskip.sh"
echo good > "${BR}/value.txt"
git -C "${BR}" add . && git -C "${BR}" commit -qm good
BGOOD="$(git -C "${BR}" rev-parse HEAD)"
echo neutral > "${BR}/note.txt" && git -C "${BR}" add note.txt && git -C "${BR}" commit -qm neutral
echo skip > "${BR}/skip.flag" && git -C "${BR}" add skip.flag && git -C "${BR}" commit -qm untestable
rm -f "${BR}/skip.flag"
echo bad > "${BR}/value.txt" && git -C "${BR}" add -u && git -C "${BR}" commit -qm regression
BFIRST="$(git -C "${BR}" rev-parse HEAD)"
echo later >> "${BR}/note.txt" && git -C "${BR}" commit -qam later
BBAD="$(git -C "${BR}" rev-parse HEAD)"
BHEAD="${BBAD}"
BOUT="$(cd "${BR}" && "${ROOT}/skills/bisect/scripts/safe-bisect.sh" --good "${BGOOD}" --bad "${BBAD}" -- ./verify-noskip.sh)" \
  || { rm -rf "${BR}"; fail "safe bisect exited red"; }
echo "${BOUT}" | grep -q "FIRST_BAD ${BFIRST}" || { rm -rf "${BR}"; fail "safe bisect found wrong commit: ${BOUT}"; }
if ! { [ "$(git -C "${BR}" rev-parse HEAD)" = "${BHEAD}" ] && [ "$(git -C "${BR}" status --porcelain)" = "" ]; }; then
  rm -rf "${BR}"; fail "safe bisect mutated caller worktree"
fi
[ "$(git -C "${BR}" worktree list --porcelain | grep -c '^worktree ')" -eq 1 ] \
  || { rm -rf "${BR}"; fail "safe bisect leaked a temporary worktree"; }
RC=0; BERR="$(cd "${BR}" && "${ROOT}/skills/bisect/scripts/safe-bisect.sh" --good "${BGOOD}" --bad "${BBAD}" -- ./verify.sh 2>&1)" || RC=$?
if ! { [ "${RC}" -eq 2 ] && echo "${BERR}" | grep -q 'could not identify a unique first bad commit'; }; then
  rm -rf "${BR}"; fail "safe bisect did not preserve ambiguous exit-125 semantics (rc=${RC}): ${BERR}"
fi
RC=0; BERR="$(cd "${BR}" && "${ROOT}/skills/bisect/scripts/safe-bisect.sh" --good "${BGOOD}" --bad "${BBAD}" -- ./missing-verify 2>&1)" || RC=$?
if ! { [ "${RC}" -eq 66 ] && echo "${BERR}" | grep -q 'could not be evaluated'; }; then
  rm -rf "${BR}"; fail "safe bisect treated missing command as a bad revision (rc=${RC}): ${BERR}"
fi
rm -rf "${BR}"
echo "ok  safe regression bisect"

# 4c6. learning layer stays wired through the skills that read/write it
grep -q 'docs/lessons.md' "${ROOT}/skills/debug/SKILL.md" || fail "debug skill lost the lesson-ledger lookup"
grep -q 'luciazero-heuristics.md' "${ROOT}/skills/debug/SKILL.md" || fail "debug skill lost the heuristics lookup"
grep -q 'docs/lessons.md' "${ROOT}/skills/retro/SKILL.md" || fail "retro skill lost the lesson-ledger routing"
grep -q 'luciazero-heuristics.md' "${ROOT}/skills/retro/SKILL.md" || fail "retro skill lost the heuristics routing"
grep -q 'luciazero discipline' "${ROOT}/skills/retro/SKILL.md" || fail "retro skill lost the discipline-report integration"
echo "ok  learning-layer skill wiring"

# 4c7. published benchmark tables are generated from immutable, digest-checked
# raw campaigns. A stale table or edited JSONL must turn CI red.
python3 "${ROOT}/eval/evidence.py" --check >/dev/null \
  || fail "benchmark evidence digest or generated documentation drift"
python3 - "${ROOT}/eval" <<'PY' \
  || fail "benchmark evidence accepted duplicate schema-v2 invocations"
import hashlib, pathlib, sys
sys.path.insert(0, sys.argv[1])
from evidence import validate_campaign_rows

campaign = {
    "expected_result_schema": 2, "expected_runs_per_cell": 2,
    "expected_invalid": {}, "expected_model_rows": 4,
    "id": "c", "tasks": ["t"], "lessons_tasks": [], "observed_model": "m",
    "expected_task_sha256": {"t": {"task": "a" * 64, "prompt": "b" * 64}},
}
base = {"result_schema": 2, "task": "t", "invalid": False,
        "model": "m", "requested_model": "m", "criteria": {"ok": True},
        "campaign_id": "c", "repository_dirty": False, "seed": "s",
        "repository_commit": "abc", "runner_profile": "runner",
        "reasoning_effort": "medium", "cli_version": "cli",
        "system": "system", "architecture": "arch",
        "campaign_started_at": "2026-08-12T00:00:00+00:00",
        "task_sha256": "a" * 64, "prompt_sha256": "b" * 64}
rows = [
    {**base, "arm": "doctrine", "run": 1, "pair_id": "c/t/1",
     "arm_order": ["doctrine", "bare"], "invocation_id": "c/t/1/doctrine"},
    {**base, "arm": "doctrine", "run": 1, "pair_id": "c/t/1",
     "arm_order": ["doctrine", "bare"], "invocation_id": "c/t/1/doctrine"},
    {**base, "arm": "bare", "run": 1, "pair_id": "c/t/1",
     "arm_order": ["doctrine", "bare"], "invocation_id": "c/t/1/bare"},
    {**base, "arm": "bare", "run": 2, "pair_id": "c/t/2",
     "arm_order": ["bare", "doctrine"], "invocation_id": "c/t/2/bare"},
]
try:
    validate_campaign_rows(campaign, rows, pathlib.Path("synthetic.jsonl"))
except SystemExit as exc:
    assert "duplicate" in str(exc)
else:
    raise AssertionError("duplicate invocation IDs were accepted")

def expected_order(run):
    return sorted(("doctrine", "bare"), key=lambda arm: hashlib.sha256(
        f"s\0t\0{run}\0{arm}".encode()).digest())

valid = [
    {**base, "arm": arm, "run": run, "pair_id": f"c/t/{run}",
     "arm_order": expected_order(run),
     "invocation_id": f"c/t/{run}/{arm}"}
    for run in (1, 2) for arm in ("doctrine", "bare")
]
valid[0]["repository_dirty"] = True
try:
    validate_campaign_rows(campaign, valid, pathlib.Path("synthetic.jsonl"))
except SystemExit as exc:
    assert "dirty-checkout" in str(exc)
else:
    raise AssertionError("dirty evidence rows were accepted")
valid[0]["repository_dirty"] = False
for row in valid:
    if row["run"] == 1:
        row["arm_order"] = list(reversed(expected_order(1)))
try:
    validate_campaign_rows(campaign, valid, pathlib.Path("synthetic.jsonl"))
except SystemExit as exc:
    assert "does not match seed" in str(exc)
else:
    raise AssertionError("tampered deterministic arm order was accepted")
PY
echo "ok  benchmark evidence digests + generated docs"

if [ "${TIER}" = fast ]; then
  echo
  echo "PASS  fast checks green"
  exit 0
fi

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

# 4d. eval graders stay honest — auto-discovered, so no task can ship without
# its proofs: PROMPT.md present, grader executable and following the output
# contract, reference/ passes, unfixed project/ fails, and any checked-in
# gamed/ cheat tree is rejected
for TDIR in "${ROOT}/eval/tasks"/*/; do
  TN="$(basename "${TDIR}")"
  [ -f "${TDIR}PROMPT.md" ] || fail "eval task ${TN}: missing PROMPT.md"
  [ -x "${TDIR}grade.sh" ] || fail "eval task ${TN}: grade.sh missing or not executable"
  if [ -f "${TDIR}setup.sh" ] && [ ! -x "${TDIR}setup.sh" ]; then
    fail "eval task ${TN}: setup.sh is not executable"
  fi
  [ -d "${TDIR}reference" ] || fail "eval task ${TN}: missing reference/"
  [ -d "${TDIR}project" ] || fail "eval task ${TN}: missing project/"
  # Mirror run.sh: project is the base tree, optional setup creates dynamic
  # local state, and reference/gamed directories are solution overlays.
  EWORK="$(mktemp -d)"
  cp -R "${TDIR}project/." "${EWORK}/"
  if [ -x "${TDIR}setup.sh" ]; then
    "${TDIR}setup.sh" "${EWORK}"
    "${TDIR}setup.sh" "${EWORK}"
  fi
  cp -R "${TDIR}reference/." "${EWORK}/"
  OUT="$("${TDIR}grade.sh" "${EWORK}" 2>&1)" \
    || { rm -rf "${EWORK}"; fail "eval grader ${TN} rejects its own reference solution: ${OUT}"; }
  rm -rf "${EWORK}"
  echo "${OUT}" | grep -q '^SCORE ' || fail "eval grader ${TN} breaks the CRIT/SCORE output contract: ${OUT}"
  EWORK="$(mktemp -d)"
  cp -R "${TDIR}project/." "${EWORK}/"
  if [ -x "${TDIR}setup.sh" ]; then
    "${TDIR}setup.sh" "${EWORK}"
    "${TDIR}setup.sh" "${EWORK}"
  fi
  if "${TDIR}grade.sh" "${EWORK}" >/dev/null 2>&1; then
    rm -rf "${EWORK}"
    fail "eval grader ${TN} passes the unfixed project (grader cannot go red)"
  fi
  rm -rf "${EWORK}"
  # every gamed*/ cheat variant must be rejected, and at least one must exist —
  # an untested "cannot be gamed" grader may not ship
  GAMED_SEEN=0
  for GD in "${TDIR}"gamed*/; do
    [ -d "${GD}" ] || continue
    GAMED_SEEN=1
    EWORK="$(mktemp -d)"
    cp -R "${TDIR}project/." "${EWORK}/"
    if [ -x "${TDIR}setup.sh" ]; then
      "${TDIR}setup.sh" "${EWORK}"
      "${TDIR}setup.sh" "${EWORK}"
    fi
    cp -R "${GD}." "${EWORK}/"
    if "${TDIR}grade.sh" "${EWORK}" >/dev/null 2>&1; then
      rm -rf "${EWORK}"
      fail "eval grader ${TN} passes its checked-in cheat tree ($(basename "${GD}")/)"
    fi
    rm -rf "${EWORK}"
  done
  [ "${GAMED_SEEN}" = 1 ] || fail "eval task ${TN}: missing gamed/ cheat tree"
  echo "ok  eval grader ${TN} red/green/anti-gamed"
done

# 4d2. report.sh renders the frozen fixtures byte-exactly and rejects garbage
RPT="$(mktemp)"
"${ROOT}/eval/report.sh" "${ROOT}/eval/testdata/sample-results.jsonl" > "${RPT}" \
  || { rm -f "${RPT}"; fail "report.sh failed on the checked-in fixture"; }
cmp -s "${RPT}" "${ROOT}/eval/testdata/sample-report.md" \
  || { rm -f "${RPT}"; fail "report.sh output drifted from eval/testdata/sample-report.md"; }
# the three-arm + usage fixture: lessons column, per-arm deltas, resource means
"${ROOT}/eval/report.sh" "${ROOT}/eval/testdata/sample-results-lessons.jsonl" > "${RPT}" \
  || { rm -f "${RPT}"; fail "report.sh failed on the lessons fixture"; }
cmp -s "${RPT}" "${ROOT}/eval/testdata/sample-report-lessons.md" \
  || { rm -f "${RPT}"; fail "report.sh output drifted from eval/testdata/sample-report-lessons.md"; }
printf 'not json\n' > "${RPT}"
if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
  rm -f "${RPT}"; fail "report.sh accepted malformed input"
fi
# criteria must be an object — a JSON array of pairs coerces via dict() into
# fake criteria and would render a confident 100% table (regression)
printf '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":["ab","cd"],"score":null,"duration_s":1}\n' > "${RPT}"
if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
  rm -f "${RPT}"; fail "report.sh accepted a non-object criteria field"
fi
# Appended rows from unlike run configurations must never become one rate.
printf '%s\n' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex","model":"model-a","reasoning_effort":"medium","cli_version":"codex 1"}' \
  '{"task":"t","arm":"bare","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex","model":"model-b","reasoning_effort":"medium","cli_version":"codex 1"}' \
  > "${RPT}"
if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
  rm -f "${RPT}"; fail "report.sh combined different models"
fi
printf '%s\n' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"claude"}' \
  '{"task":"t","arm":"bare","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex"}' \
  > "${RPT}"
if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
  rm -f "${RPT}"; fail "report.sh combined different providers"
fi
printf '%s\n' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex","model":"m","campaign_id":"a"}' \
  '{"task":"t","arm":"bare","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex","model":"m","campaign_id":"b"}' \
  > "${RPT}"
if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
  rm -f "${RPT}"; fail "report.sh combined different campaigns"
fi
printf '%s\n' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex","model":"m","task_sha256":"aaa"}' \
  '{"task":"t","arm":"bare","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex","model":"m","task_sha256":"bbb"}' \
  > "${RPT}"
if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
  rm -f "${RPT}"; fail "report.sh combined changed task fixtures"
fi
printf '%s\n' \
  '{"result_schema":2,"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex","model":"m"}' \
  > "${RPT}"
if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
  rm -f "${RPT}"; fail "report.sh accepted incomplete schema-v2 metadata"
fi
for BAD_ROW in \
  '{"result_schema":3,"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1}' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":"false","criteria":{"ok":true},"score":"1/1","duration_s":1}' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":"fail"},"score":"1/1","duration_s":1}' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":"fast"}'; do
  printf '%s\n' "${BAD_ROW}" > "${RPT}"
  if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
    rm -f "${RPT}"; fail "report.sh accepted a type-invalid result row"
  fi
done
rm -f "${RPT}"
echo "ok  eval report fixture + malformed input"

# 4d2b. check-result.sh: exit 0 does not prove the agent ran — the CLI has
# wrapped a "Not logged in" error in subtype "success" (2026-08-11); each
# rejection and acceptance path is proven against a fixture log
CRF="$(mktemp -d)"
CR="${ROOT}/eval/check-result.sh"
printf '{"subtype":"success","is_error":true,"terminal_reason":"api_error","result":"Not logged in · Please run /login"}' > "${CRF}/notlogged.json"
printf '{"result":"Not logged in · Please run /login"}' > "${CRF}/sneaky.json"
printf '{"subtype":"success","is_error":false,"result":"fixed the bug"}' > "${CRF}/good.json"
printf 'plain text transcript\n' > "${CRF}/text.log"
printf '%s\n' \
  '{"type":"thread.started","thread_id":"t"}' \
  '{"type":"turn.completed","usage":{"input_tokens":12,"cached_input_tokens":4,"output_tokens":3,"reasoning_output_tokens":1}}' \
  > "${CRF}/codex-good.jsonl"
printf '%s\n' \
  '{"type":"turn.started"}' \
  '{"type":"turn.failed","error":{"message":"rate limit"}}' \
  > "${CRF}/codex-failed.jsonl"
printf '{"type":"turn.started"}\n' > "${CRF}/codex-partial.jsonl"
printf '%s\n' \
  '{"type":"turn.started"}' \
  '{"type":"turn.completed","usage":{"input_tokens":null,"output_tokens":"3"}}' \
  > "${CRF}/codex-bad-usage.jsonl"
RC=0; OUT="$("${CR}" "${CRF}/notlogged.json" 2>&1)" || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result accepted a not-logged-in result"; }
echo "${OUT}" | grep -q 'Not logged in' || { rm -rf "${CRF}"; fail "check-result rejection lost the reason: ${OUT}"; }
RC=0; "${CR}" "${CRF}/sneaky.json" >/dev/null 2>&1 || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result accepted a login error without is_error"; }
"${CR}" "${CRF}/good.json" >/dev/null 2>&1 || { rm -rf "${CRF}"; fail "check-result rejected a healthy result"; }
"${CR}" "${CRF}/text.log" >/dev/null 2>&1 || { rm -rf "${CRF}"; fail "check-result rejected plain-text output"; }
"${CR}" --provider codex "${CRF}/codex-good.jsonl" >/dev/null 2>&1 \
  || { rm -rf "${CRF}"; fail "check-result rejected a completed Codex run"; }
RC=0; "${CR}" --provider codex "${CRF}/codex-failed.jsonl" >/dev/null 2>&1 || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result accepted a failed Codex turn"; }
RC=0; "${CR}" --provider codex "${CRF}/codex-partial.jsonl" >/dev/null 2>&1 || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result accepted an incomplete Codex stream"; }
RC=0; "${CR}" --provider codex "${CRF}/codex-bad-usage.jsonl" >/dev/null 2>&1 || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result accepted malformed Codex usage"; }
RC=0; "${CR}" "${CRF}/absent.json" >/dev/null 2>&1 || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result accepted a missing log"; }
rm -rf "${CRF}"
echo "ok  check-result rejects error payloads behind exit 0"

# The non-zero Codex path must preserve the structured error in JSONL, not
# reduce a useful capacity/auth reason to only "codex exited 1". A fake CLI
# proves this without inference or credentials.
CFX="$(mktemp -d)"
mkdir -p "${CFX}/bin"
cat > "${CFX}/bin/codex" <<'FAKECODEX'
#!/bin/sh
if [ "${1:-}" = --version ]; then
  echo 'codex-cli test'
  exit 0
fi
printf '%s\n' \
  '{"type":"turn.started"}' \
  '{"type":"error","message":"Selected model is at capacity."}' \
  '{"type":"turn.failed","error":{"message":"Selected model is at capacity."}}'
exit 1
FAKECODEX
chmod +x "${CFX}/bin/codex"
PATH="${CFX}/bin:${PATH}" "${ROOT}/eval/run.sh" --provider codex \
  --model gpt-5.6-terra --reasoning-effort medium --allow-dirty \
  --out "${CFX}/result.jsonl" false-green >/dev/null 2>&1 \
  || { rm -rf "${CFX}"; fail "run.sh rejected a recorded invalid Codex run"; }
python3 - "${CFX}/result.jsonl" <<'PY' \
  || { rm -rf "${CFX}"; fail "Codex invalid reason was not preserved"; }
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 2
assert all(row["invalid"] is True for row in rows)
assert all("Selected model is at capacity" in row["invalid_reason"] for row in rows)
PY
rm -rf "${CFX}"
echo "ok  Codex non-zero result preserves structured reason"

# A successful fake Codex run proves the actual adapter boundary: auth is
# copied into both disposable homes, only doctrine gets the pack, and every
# safety/model flag reaches the CLI. A malformed usage variant proves paid
# inference still records INVALID instead of crashing the harness.
SFX="$(mktemp -d)"
mkdir -p "${SFX}/bin" "${SFX}/real-home" "${SFX}/audit"
printf '{"fake":"auth"}\n' > "${SFX}/real-home/auth.json"
cat > "${SFX}/bin/codex" <<'FAKECODEXOK'
#!/bin/sh
if [ "${1:-}" = --version ]; then
  echo 'codex-cli test-success'
  exit 0
fi
ARM=bare
PACK=no
if [ -f "${CODEX_HOME}/AGENTS.md" ] && [ -d "${CODEX_HOME}/skills" ]; then
  ARM=doctrine
  PACK=yes
fi
AUTH=no
[ -s "${CODEX_HOME}/auth.json" ] && AUTH=yes
{
  printf 'auth=%s\npack=%s\nparent-key=%s\n' \
    "${AUTH}" "${PACK}" "${CODEX_API_KEY:+present}"
  for ARG in "$@"; do printf 'arg=%s\n' "${ARG}"; done
} > "${FAKE_CODEX_AUDIT_DIR}/${ARM}.txt"
if [ "${FAKE_CODEX_BAD_USAGE:-0}" = 1 ]; then
  printf '%s\n' \
    '{"type":"turn.started"}' \
    '{"type":"turn.completed","usage":{"input_tokens":null,"output_tokens":"bad"}}'
elif [ "${FAKE_CODEX_BAD_USAGE:-0}" = 2 ]; then
  printf '%s\n' '[]'
else
  printf '%s\n' \
    '{"type":"turn.started"}' \
    '{"type":"turn.completed","usage":{"input_tokens":12,"cached_input_tokens":4,"output_tokens":3,"reasoning_output_tokens":1}}'
fi
FAKECODEXOK
chmod +x "${SFX}/bin/codex"
CODEX_HOME="${SFX}/real-home" CODEX_API_KEY='test-key-never-log' \
  FAKE_CODEX_AUDIT_DIR="${SFX}/audit" PATH="${SFX}/bin:${PATH}" \
  "${ROOT}/eval/run.sh" --provider codex --model gpt-5.6-terra \
  --reasoning-effort medium --use-login --allow-dirty \
  --out "${SFX}/ok.jsonl" false-green \
  >/dev/null 2>&1 \
  || { rm -rf "${SFX}"; fail "successful fake Codex adapter run failed"; }
for ARM in doctrine bare; do
  AUDIT="${SFX}/audit/${ARM}.txt"
  [ -f "${AUDIT}" ] || { rm -rf "${SFX}"; fail "missing ${ARM} Codex audit"; }
  grep -qx 'auth=yes' "${AUDIT}" \
    || { rm -rf "${SFX}"; fail "Codex auth not copied into ${ARM} home"; }
  grep -qx 'parent-key=present' "${AUDIT}" \
    || { rm -rf "${SFX}"; fail "fake Codex parent did not receive auth key"; }
  grep -Fqx 'arg=--model' "${AUDIT}" \
    || { rm -rf "${SFX}"; fail "Codex model flag missing"; }
  grep -Fqx 'arg=gpt-5.6-terra' "${AUDIT}" \
    || { rm -rf "${SFX}"; fail "Codex model value missing"; }
  grep -Fqx 'arg=model_reasoning_effort="medium"' "${AUDIT}" \
    || { rm -rf "${SFX}"; fail "Codex reasoning config missing"; }
  grep -Fqx 'arg=shell_environment_policy.inherit="core"' "${AUDIT}" \
    || { rm -rf "${SFX}"; fail "Codex core environment policy missing"; }
  grep -Fqx 'arg=shell_environment_policy.ignore_default_excludes=false' "${AUDIT}" \
    || { rm -rf "${SFX}"; fail "Codex secret exclusion policy missing"; }
  for FLAG in --sandbox workspace-write --ephemeral --ignore-user-config \
    --ignore-rules --skip-git-repo-check --json; do
    grep -Fqx "arg=${FLAG}" "${AUDIT}" \
      || { rm -rf "${SFX}"; fail "Codex adapter missing ${FLAG}"; }
  done
done
grep -qx 'pack=yes' "${SFX}/audit/doctrine.txt" \
  || { rm -rf "${SFX}"; fail "doctrine Codex home lacks installed pack"; }
grep -qx 'pack=no' "${SFX}/audit/bare.txt" \
  || { rm -rf "${SFX}"; fail "bare Codex home inherited the pack"; }
if grep -R -q 'test-key-never-log' "${SFX}/audit" "${SFX}/ok.jsonl"; then
  rm -rf "${SFX}"; fail "Codex credential value leaked into eval artifacts"
fi
python3 - "${SFX}/ok.jsonl" <<'PY' \
  || { rm -rf "${SFX}"; fail "successful fake Codex rows wrong"; }
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 2
assert all(row["invalid"] is False for row in rows)
assert all(row["tokens_in"] == 12 and row["tokens_out"] == 3 for row in rows)
PY
CODEX_HOME="${SFX}/real-home" CODEX_API_KEY='test-key-never-log' \
  FAKE_CODEX_AUDIT_DIR="${SFX}/audit" FAKE_CODEX_BAD_USAGE=1 \
  PATH="${SFX}/bin:${PATH}" "${ROOT}/eval/run.sh" --provider codex \
  --model gpt-5.6-terra --reasoning-effort medium --use-login --allow-dirty \
  --out "${SFX}/bad.jsonl" false-green >/dev/null 2>&1 \
  || { rm -rf "${SFX}"; fail "malformed Codex usage aborted run.sh"; }
python3 - "${SFX}/bad.jsonl" <<'PY' \
  || { rm -rf "${SFX}"; fail "malformed Codex usage rows wrong"; }
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 2
assert all(row["invalid"] is True for row in rows)
assert all(row["tokens_in"] is None and row["tokens_out"] is None for row in rows)
assert all("usage.input_tokens" in row["invalid_reason"] for row in rows)
PY
CODEX_HOME="${SFX}/real-home" CODEX_API_KEY='test-key-never-log' \
  FAKE_CODEX_AUDIT_DIR="${SFX}/audit" FAKE_CODEX_BAD_USAGE=2 \
  PATH="${SFX}/bin:${PATH}" "${ROOT}/eval/run.sh" --provider codex \
  --model gpt-5.6-terra --reasoning-effort medium --use-login --allow-dirty \
  --out "${SFX}/nonobject.jsonl" false-green >/dev/null 2>&1 \
  || { rm -rf "${SFX}"; fail "non-object Codex event aborted run.sh"; }
python3 - "${SFX}/nonobject.jsonl" <<'PY' \
  || { rm -rf "${SFX}"; fail "non-object Codex event rows wrong"; }
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 2
assert all(row["invalid"] is True for row in rows)
assert all(row["tokens_in"] is None and row["tokens_out"] is None for row in rows)
assert all("not an object" in row["invalid_reason"] for row in rows)
PY
rm -rf "${SFX}"
echo "ok  Codex success path isolates auth, config, arms, and usage errors"

# 4d2c. offline smoke mode: full copy -> grade -> JSONL -> report loop with
# zero API; rows must be branded offline and the report must say SYNTHETIC
OFJ="$(mktemp -d)"
"${ROOT}/eval/run.sh" --offline --with-lessons --seed fixture-seed \
  --campaign-id fixture-campaign --out "${OFJ}/r.jsonl" false-green >/dev/null 2>&1 \
  || { rm -rf "${OFJ}"; fail "run.sh --offline exited non-zero"; }
python3 - "${OFJ}/r.jsonl" <<'PY' || { rm -rf "${OFJ}"; fail "offline JSONL rows wrong"; }
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
assert len(rows) == 3, f"want 3 arms, got {len(rows)}"
assert {r["arm"] for r in rows} == {"doctrine", "bare", "lessons"}
assert all(r["offline"] is True for r in rows), "rows not branded offline"
assert all(r["provider"] == "claude" for r in rows), "default provider drifted"
assert all(r["invalid"] is False for r in rows), "offline rows marked invalid"
assert all(r["result_schema"] == 2 for r in rows)
assert all(r["campaign_id"] == "fixture-campaign" for r in rows)
assert len({r["pair_id"] for r in rows}) == 1
assert [r["arm"] for r in rows] == rows[0]["arm_order"]
assert all(r["seed"] == "fixture-seed" for r in rows)
assert all(len(r["task_sha256"]) == 64 and len(r["prompt_sha256"]) == 64 for r in rows)
assert all(r["repository_commit"] and r["system"] and r["architecture"] for r in rows)
assert all(r["runner_profile"].startswith("claude -p ") for r in rows)
assert len({r["invocation_id"] for r in rows}) == 3
by = {r["arm"]: r for r in rows}
assert by["doctrine"]["score"] == "6/6", by["doctrine"]["score"]
assert by["bare"]["score"] != "6/6", "bare arm must keep the planted bug"
PY
"${ROOT}/eval/run.sh" --offline --seed relay-fixture-seed \
  --campaign-id relay-fixture-campaign --out "${OFJ}/relay.jsonl" \
  relay-transfer >/dev/null 2>&1 \
  || { rm -rf "${OFJ}"; fail "run.sh skipped or broke task setup"; }
python3 - "${OFJ}/relay.jsonl" <<'PY' \
  || { rm -rf "${OFJ}"; fail "relay offline setup/overlay rows wrong"; }
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 2
by = {row["arm"]: row for row in rows}
assert by["doctrine"]["score"] == "6/6"
assert by["bare"]["score"] == "1/6"
assert all(row["invalid"] is False and row["offline"] is True for row in rows)
PY
if "${ROOT}/eval/run.sh" --offline --model gpt-5.6-terra false-green \
  >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh accepted Codex-only flags for Claude"
fi
if "${ROOT}/eval/run.sh" --offline --runs 0 false-green >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh accepted zero repetitions"
fi
if "${ROOT}/eval/run.sh" --offline --run-offset nope false-green >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh accepted a non-numeric run offset"
fi
if "${ROOT}/eval/run.sh" --offline --resume --out "${OFJ}/missing.jsonl" \
  false-green >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh resumed without explicit campaign ID and seed"
fi
if "${ROOT}/eval/run.sh" --offline --resume --seed resume-seed \
  --campaign-id resume-campaign --out "${OFJ}/missing.jsonl" \
  false-green >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh resumed a missing output file"
fi
: > "${OFJ}/empty.jsonl"
if "${ROOT}/eval/run.sh" --offline --resume --seed resume-seed \
  --campaign-id resume-campaign --out "${OFJ}/empty.jsonl" \
  false-green >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh resumed an empty output file"
fi
"${ROOT}/eval/run.sh" --offline --seed resume-seed --campaign-id resume-campaign \
  --runs 1 --out "${OFJ}/resume.jsonl" false-green >/dev/null 2>&1 \
  || { rm -rf "${OFJ}"; fail "run.sh initial resumable batch exited non-zero"; }
# Simulate an interruption after the first arm: resume must skip that exact
# invocation and fill only its missing pair mate.
python3 - "${OFJ}/resume.jsonl" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
path.write_text(path.read_text().splitlines()[0] + "\n")
PY
"${ROOT}/eval/run.sh" --offline --resume --seed resume-seed \
  --campaign-id resume-campaign --runs 1 --out "${OFJ}/resume.jsonl" \
  false-green >/dev/null 2>&1 \
  || { rm -rf "${OFJ}"; fail "run.sh resumed batch exited non-zero"; }
python3 - "${OFJ}/resume.jsonl" <<'PY' \
  || { rm -rf "${OFJ}"; fail "run.sh resumed batch reused invocation IDs"; }
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 2
assert {row["run"] for row in rows} == {1}
assert len({row["pair_id"] for row in rows}) == 1
assert len({row["invocation_id"] for row in rows}) == 2
PY
"${ROOT}/eval/report.sh" "${OFJ}/resume.jsonl" >/dev/null \
  || { rm -rf "${OFJ}"; fail "report.sh rejected a correctly resumed campaign"; }
# Appending to a final JSON object without a newline would corrupt JSONL.
cp "${OFJ}/resume.jsonl" "${OFJ}/no-newline.jsonl"
python3 - "${OFJ}/no-newline.jsonl" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
path.write_bytes(path.read_bytes().rstrip(b"\n"))
PY
cp "${OFJ}/no-newline.jsonl" "${OFJ}/no-newline.before"
if "${ROOT}/eval/run.sh" --offline --resume --seed resume-seed \
  --campaign-id resume-campaign --runs 1 --out "${OFJ}/no-newline.jsonl" \
  false-green >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh resumed a JSONL file without a final newline"
fi
cmp -s "${OFJ}/no-newline.before" "${OFJ}/no-newline.jsonl" \
  || { rm -rf "${OFJ}"; fail "failed resume mutated no-newline JSONL"; }
# Drift in a later task must abort before an earlier missing arm is appended.
python3 - "${OFJ}/resume.jsonl" "${OFJ}/preflight.jsonl" <<'PY'
import json, pathlib, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
first = rows[0]
later = dict(first, task="slugify", pair_id="resume-campaign/slugify/1",
             invocation_id="resume-campaign/slugify/1/" + first["arm"],
             task_sha256="0" * 64, prompt_sha256="0" * 64)
pathlib.Path(sys.argv[2]).write_text(
    "\n".join(json.dumps(row) for row in (first, later)) + "\n"
)
PY
BEFORE_LINES="$(wc -l < "${OFJ}/preflight.jsonl" | tr -d ' ')"
if "${ROOT}/eval/run.sh" --offline --resume --seed resume-seed \
  --campaign-id resume-campaign --runs 1 --out "${OFJ}/preflight.jsonl" \
  false-green slugify >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh resumed after a later task failed preflight"
fi
[ "${BEFORE_LINES}" = "$(wc -l < "${OFJ}/preflight.jsonl" | tr -d ' ')" ] \
  || { rm -rf "${OFJ}"; fail "resume spent/appended before full task preflight"; }
# A tampered deterministic order must also fail before filling a missing mate.
python3 - "${OFJ}/resume.jsonl" "${OFJ}/order-drift.jsonl" <<'PY'
import json, pathlib, sys
row = json.loads(open(sys.argv[1]).readline())
row["arm_order"] = list(reversed(row["arm_order"]))
pathlib.Path(sys.argv[2]).write_text(json.dumps(row) + "\n")
PY
if "${ROOT}/eval/run.sh" --offline --resume --seed resume-seed \
  --campaign-id resume-campaign --runs 1 --out "${OFJ}/order-drift.jsonl" \
  false-green >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh resumed after deterministic arm-order drift"
fi
[ "$(wc -l < "${OFJ}/order-drift.jsonl" | tr -d ' ')" = 1 ] \
  || { rm -rf "${OFJ}"; fail "arm-order drift appended before preflight"; }
"${ROOT}/eval/report.sh" "${OFJ}/r.jsonl" | grep -q 'SYNTHETIC OFFLINE SMOKE' \
  || { rm -rf "${OFJ}"; fail "report.sh did not brand offline rows SYNTHETIC"; }
"${ROOT}/eval/report.sh" "${ROOT}/eval/testdata/sample-results-offline.jsonl" > "${OFJ}/off.md" \
  || { rm -rf "${OFJ}"; fail "report.sh failed on the offline fixture"; }
cmp -s "${OFJ}/off.md" "${ROOT}/eval/testdata/sample-report-offline.md" \
  || { rm -rf "${OFJ}"; fail "report.sh output drifted from eval/testdata/sample-report-offline.md"; }
# Codex adapter takes the same zero-quota route and records its locked model
# settings even when no Codex CLI is installed in CI.
mkdir -p "${OFJ}/codex-home"
printf '{"fake":"codex-auth"}\n' > "${OFJ}/codex-home/auth.json"
CODEX_HOME="${OFJ}/codex-home" "${ROOT}/eval/run.sh" --offline \
  --provider codex --model gpt-5.6-terra --reasoning-effort medium \
  --use-login --out "${OFJ}/codex.jsonl" false-green >/dev/null 2>&1 \
  || { rm -rf "${OFJ}"; fail "Codex offline adapter exited non-zero"; }
python3 - "${OFJ}/codex.jsonl" <<'PY' \
  || { rm -rf "${OFJ}"; fail "Codex offline adapter rows wrong"; }
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 2
assert all(row["provider"] == "codex" for row in rows)
assert all(row["model"] == "gpt-5.6-terra" for row in rows)
assert all(row["reasoning_effort"] == "medium" for row in rows)
assert all(row["offline"] is True for row in rows)
PY
rm -rf "${OFJ}"
echo "ok  offline smoke mode end to end"

# 4d2d. --use-login plumbing: with login state under a fake HOME the sandbox
# seed line must appear once per arm; with an empty fake HOME the flag must
# warn instead of failing the run. Both offline — no CLI, no auth, no spend.
UL="$(mktemp -d)"
mkdir -p "${UL}/home/.claude"
printf '{"fake": "login-state"}\n' > "${UL}/home/.claude.json"
printf '{"fake": "credentials"}\n' > "${UL}/home/.claude/.credentials.json"
HOME="${UL}/home" "${ROOT}/eval/run.sh" --offline --use-login --out "${UL}/r.jsonl" false-green \
  > "${UL}/out.log" 2>"${UL}/err.log" \
  || { rm -rf "${UL}"; fail "run.sh --use-login exited non-zero"; }
[ "$(grep -c 'login state seeded into sandbox config' "${UL}/out.log")" = 2 ] \
  || { rm -rf "${UL}"; fail "--use-login did not seed both arms' sandboxes"; }
# fake `security` binaries make the macOS Keychain branch deterministic on
# any OS: one that answers with a credential blob, one that always denies
mkdir -p "${UL}/bin" "${UL}/nobin" "${UL}/empty-home"
cat > "${UL}/bin/security" <<'FAKESEC'
#!/bin/sh
[ "$1" = find-generic-password ] || exit 1
printf '%s' '{}'
FAKESEC
printf '#!/bin/sh\nexit 1\n' > "${UL}/nobin/security"
chmod +x "${UL}/bin/security" "${UL}/nobin/security"
HOME="${UL}/empty-home" PATH="${UL}/bin:${PATH}" \
  "${ROOT}/eval/run.sh" --offline --use-login false-green > "${UL}/out2.log" 2>&1 \
  || { rm -rf "${UL}"; fail "run.sh --use-login (keychain path) exited non-zero"; }
[ "$(grep -c 'keychain credentials exported into sandbox config' "${UL}/out2.log")" = 2 ] \
  || { rm -rf "${UL}"; fail "--use-login did not export keychain credentials"; }
HOME="${UL}/empty-home" PATH="${UL}/nobin:${PATH}" \
  "${ROOT}/eval/run.sh" --offline --use-login false-green \
  > /dev/null 2>"${UL}/err2.log" \
  || { rm -rf "${UL}"; fail "run.sh --use-login with no login state exited non-zero"; }
grep -q 'warn: --use-login found no login state' "${UL}/err2.log" \
  || { rm -rf "${UL}"; fail "--use-login did not warn on missing login state"; }
rm -rf "${UL}"
echo "ok  --use-login seeds sandboxes and warns when no login state exists"

# 4d3. revert-probe: a biting test passes, a vacuous test fails, non-git is
# unassessable — all in throwaway git fixtures, never the caller's tree
RP="${ROOT}/skills/done/scripts/revert-probe.sh"
RPX="$(mktemp -d)"
# fixture: committed bug + committed always-green test, fix left uncommitted
mkdir -p "${RPX}/bites/tests"
(
  cd "${RPX}/bites"
  git init -q .
  printf 'def add(a, b):\n    return a - b if a == 2 else a + b\n' > calc.py
  printf 'import calc\nassert calc.add(0, 0) == 0\nprint("ok")\n' > tests/test_calc.py
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm 'plant bug'
)
cp -R "${RPX}/bites" "${RPX}/vacuous"
# (i) working-tree fix + a new test that bites -> probe exits 0
(
  cd "${RPX}/bites"
  printf 'def add(a, b):\n    return a + b\n' > calc.py
  printf 'import calc\nassert calc.add(0, 0) == 0\nassert calc.add(2, 2) == 4\nprint("ok")\n' > tests/test_calc.py
)
ST1="$(cd "${RPX}/bites" && git status --porcelain)"
RC=0; OUT="$(cd "${RPX}/bites" && PYTHONDONTWRITEBYTECODE=1 "${RP}" 'PYTHONPATH=. python3 tests/test_calc.py')" || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${RPX}"; fail "revert-probe rc=${RC} on a biting test: ${OUT}"; }
echo "${OUT}" | grep -q '^PASS' || { rm -rf "${RPX}"; fail "revert-probe did not print PASS: ${OUT}"; }
ST2="$(cd "${RPX}/bites" && git status --porcelain)"
[ "${ST1}" = "${ST2}" ] || { rm -rf "${RPX}"; fail "revert-probe touched the caller's working tree"; }
[ "$(cd "${RPX}/bites" && git worktree list | wc -l | tr -d ' ')" = 1 ] \
  || { rm -rf "${RPX}"; fail "revert-probe left a worktree behind"; }
# (ii) added test is vacuous (green with and without the fix) -> probe exits 1
(
  cd "${RPX}/vacuous"
  printf 'def add(a, b):\n    return a + b\n' > calc.py
  printf 'import calc\nassert calc.add(0, 0) == 0\nassert calc.add(1, 1) == 2\nprint("ok")\n' > tests/test_calc.py
)
RC=0; OUT="$(cd "${RPX}/vacuous" && PYTHONDONTWRITEBYTECODE=1 "${RP}" 'PYTHONPATH=. python3 tests/test_calc.py')" || RC=$?
[ "${RC}" = 1 ] || { rm -rf "${RPX}"; fail "revert-probe rc=${RC} on a vacuous test (want 1): ${OUT}"; }
echo "${OUT}" | grep -q 'stay green' || { rm -rf "${RPX}"; fail "vacuous-test verdict wrong: ${OUT}"; }
# (iii) not a git repo -> UNASSESSABLE, exit 2
mkdir -p "${RPX}/nogit"
RC=0; OUT="$(cd "${RPX}/nogit" && "${RP}" 'true')" || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${RPX}"; fail "revert-probe rc=${RC} outside git (want 2): ${OUT}"; }
echo "${OUT}" | grep -q '^UNASSESSABLE' || { rm -rf "${RPX}"; fail "missing UNASSESSABLE marker: ${OUT}"; }
# (iv) a non-ASCII test filename (C-quoted in git's plain output, raw with
# -z) must still be collected — regression: it was silently dropped
mkdir -p "${RPX}/uni/tests"
(
  cd "${RPX}/uni"
  git init -q .
  printf 'def add(a, b):\n    return a - b if a == 2 else a + b\n' > calc.py
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm 'plant bug'
  printf 'def add(a, b):\n    return a + b\n' > calc.py
  printf 'import calc\nassert calc.add(2, 2) == 4\nprint("ok")\n' > 'tests/test_héllo.py'
)
RC=0; OUT="$(cd "${RPX}/uni" && PYTHONDONTWRITEBYTECODE=1 "${RP}" 'PYTHONPATH=. python3 tests/test_h*.py')" || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${RPX}"; fail "revert-probe rc=${RC} on a non-ASCII test filename: ${OUT}"; }
# (v) this repository and many small projects keep assertions in root test.sh
mkdir -p "${RPX}/root-script"
(
  cd "${RPX}/root-script"
  git init -q .
  printf 'bad\n' > value
  printf '#!/bin/sh\ngrep -qx bad value\n' > test.sh
  chmod +x test.sh
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm 'plant bug'
  printf 'good\n' > value
  printf '#!/bin/sh\ngrep -qx good value\n' > test.sh
)
RC=0; OUT="$(cd "${RPX}/root-script" && "${RP}" './test.sh')" || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${RPX}"; fail "revert-probe ignored root test.sh: ${OUT}"; }
rm -rf "${RPX}"
echo "ok  revert-probe bites/vacuous/unassessable"

# 4d4. demo.sh scaffolds the demo outside the repo; grader red on the untouched copy
DT="$(mktemp -d)"
"${ROOT}/demo.sh" "${DT}/demo" >/dev/null
[ -f "${DT}/demo/slugify.py" ] || { rm -rf "${DT}"; fail "demo target missing slugify.py"; }
[ -f "${DT}/demo/test_slugify.py" ] || { rm -rf "${DT}"; fail "demo target missing test_slugify.py"; }
[ -d "${DT}/demo/.git" ] || { rm -rf "${DT}"; fail "demo target is not a git repo"; }
# capture, then grep: grep -q on a pipe would SIGPIPE grade.sh under pipefail
RC=0
GOUT="$("${ROOT}/eval/tasks/slugify/grade.sh" "${DT}/demo" 2>&1)" || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${DT}"; fail "grader passed the untouched demo target: ${GOUT}"; }
echo "${GOUT}" | grep -q ' fail' \
  || { rm -rf "${DT}"; fail "grader exit ${RC} but no CRIT fail line in output: ${GOUT}"; }
# a symlinked path into the repo must not slip past the in-repo refusal
ln -s "${ROOT}" "${DT}/repolink"
RC=0; "${DT}/repolink/demo.sh" "${DT}/repolink/scaffold-target" >/dev/null 2>&1 || RC=$?
if [ "${RC}" -eq 0 ] || [ -e "${ROOT}/scaffold-target" ]; then
  rm -rf "${ROOT}/scaffold-target" "${DT}"
  fail "demo.sh scaffolded through a symlink into the repo (rc=${RC})"
fi
rm -rf "${DT}"
echo "ok  demo.sh scaffold + red grader"

# 4d5. the Thai README exists, cross-links, and stays structurally in sync
# with the English default (a silently rotten translation is worse than none)
[ -f "${ROOT}/README.th.md" ] || fail "README.th.md missing"
grep -q 'README.th.md' "${ROOT}/README.md" || fail "README.md lost its link to the Thai version"
grep -qF '](README.md)' "${ROOT}/README.th.md" || fail "README.th.md lost its link back to English"
EN_H="$(grep -c '^## ' "${ROOT}/README.md")"
TH_H="$(grep -c '^## ' "${ROOT}/README.th.md")"
[ "${EN_H}" -eq $((TH_H + 1)) ] \
  || fail "README section drift: ${EN_H} EN sections vs ${TH_H} TH (EN must be TH+1 for its ภาษาไทย pointer) — update README.th.md alongside README.md"
echo "ok  Thai README present + in sync"

# 4e. luciazero-ci example stays inert and shaped right
CI_EX="${ROOT}/examples/luciazero-ci.example.yml"
[ -f "${CI_EX}" ] || fail "examples/luciazero-ci.example.yml missing"
grep -q 'workflow_run' "${CI_EX}" || fail "luciazero-ci example lost its workflow_run trigger"
grep -q 'REPLACE-ME' "${CI_EX}" || fail "luciazero-ci example must ship with REPLACE-ME gates"
[ ! -e "${ROOT}/.github/workflows/luciazero-ci.yml" ] || fail "luciazero-ci example must not be active in this repo"
echo "ok  luciazero-ci example inert"

# 4f. plugin + marketplace manifests stay valid and point at real files
python3 - "${ROOT}" <<'PY' || fail "plugin/marketplace manifest check failed"
import json, os, sys
root = sys.argv[1]
ver = None
for line in open(os.path.join(root, "CHANGELOG.md")):
    if line.startswith("## [") and line[4].isdigit():
        ver = line.split("[", 1)[1].split("]", 1)[0]
        break
plug = json.load(open(os.path.join(root, ".claude-plugin", "plugin.json")))
assert plug["name"] == "luciazero", "plugin.json name"
assert plug["version"] == ver, f"plugin.json version {plug['version']} != CHANGELOG {ver}"
assert "agents" not in plug, "plugin must use default root agents/ discovery"
for p in [plug["skills"], plug["hooks"]]:
    assert os.path.exists(os.path.join(root, p)), f"plugin.json path missing: {p}"
assert os.path.isfile(os.path.join(root, "agents", "reviewer.md")), "default plugin reviewer missing"
mkt = json.load(open(os.path.join(root, ".claude-plugin", "marketplace.json")))
assert mkt["name"] == "luciazero" and mkt["owner"]["name"], "marketplace name/owner"
assert mkt["plugins"][0]["name"] == "luciazero", "marketplace plugin entry"
assert mkt["plugins"][0]["source"] == "./", "marketplace plugin source"
hooks = json.load(open(os.path.join(root, "claude", "hooks", "hooks.json")))
cmds = [h["command"]
        for entries in hooks["hooks"].values()
        for e in entries for h in e["hooks"]]
for sub in ("prompt", "skill-prompt", "bash-start", "edit", "bash",
            "bash-failure", "skill", "stop", "session", "doctrine"):
    assert any(c.endswith("luciazero-verify.sh " + sub) for c in cmds), f"hooks.json missing {sub} wiring"
for c in cmds:
    assert c.startswith("LUCIAZERO_CHANNEL=plugin ${CLAUDE_PLUGIN_ROOT}/"), \
        f"hook command must carry the plugin channel marker (double-install dedupe depends on it): {c}"
    rel = c.split("${CLAUDE_PLUGIN_ROOT}/", 1)[1].rsplit(" ", 1)[0]
    assert os.access(os.path.join(root, rel), os.X_OK), f"hook script not executable: {rel}"
PY
echo "ok  plugin manifests valid + wired"

# 4g. plugin doctrine mode: emits the doctrine once, never twice
DCT="$(mktemp -d)"
OUT="$(CLAUDE_CONFIG_DIR="${DCT}" "${ROOT}/claude/hooks/luciazero-verify.sh" doctrine </dev/null)" \
  || fail "doctrine mode exited non-zero"
[ "${OUT}" = "$(cat "${ROOT}/claude/luciazero.md")" ] \
  || fail "doctrine mode output does not match claude/luciazero.md"
touch "${DCT}/luciazero.md"
OUT2="$(CLAUDE_CONFIG_DIR="${DCT}" "${ROOT}/claude/hooks/luciazero-verify.sh" doctrine </dev/null)" \
  || fail "doctrine mode (classic install present) exited non-zero"
[ -z "${OUT2}" ] || fail "doctrine mode must stay silent when a classic install exists (double-load)"
rm -rf "${DCT}"
echo "ok  plugin doctrine session context"

# 4g2. plugin/classic double-install: the plugin-channel copy stands down
# exactly when classic wiring exists (dedupe), and runs normally otherwise
DD="$(mktemp -d)"
DTMP="$(mktemp -d)"
mkdir -p "${DD}/hooks"
cp "${ROOT}/claude/hooks/luciazero-verify.sh" "${DD}/hooks/luciazero-verify.sh"
printf '{"hooks": {"x": "%s/hooks/luciazero-verify.sh"}}\n' "${DD}" > "${DD}/settings.json"
printf '{"cwd": "%s", "tool_input": {"file_path": "%s/a.py"}}' "${DD}" "${DD}" \
  | env TMPDIR="${DTMP}" CLAUDE_CONFIG_DIR="${DD}" LUCIAZERO_CHANNEL=plugin \
    "${ROOT}/claude/hooks/luciazero-verify.sh" edit \
  || fail "deduped plugin edit exited non-zero"
[ -z "$(ls -A "${DTMP}" 2>/dev/null)" ] \
  || fail "plugin copy must stand down when classic wiring exists (state was written)"
rm -f "${DD}/settings.json"
printf '{"cwd": "%s", "tool_input": {"file_path": "%s/a.py"}}' "${DD}" "${DD}" \
  | env TMPDIR="${DTMP}" CLAUDE_CONFIG_DIR="${DD}" LUCIAZERO_CHANNEL=plugin \
    "${ROOT}/claude/hooks/luciazero-verify.sh" edit \
  || fail "plugin edit (no classic wiring) exited non-zero"
[ -n "$(ls -A "${DTMP}" 2>/dev/null)" ] \
  || fail "plugin copy must run normally when classic wiring is absent"
rm -rf "${DD}" "${DTMP}"
echo "ok  plugin channel dedupe"

# 4g3. mutating installers reject unknown options instead of silently acting
# (pre-fix, `npx luciazero codex --status` performed a full install)
AR="$(mktemp -d)"
set +e
OUT_A="$(CODEX_HOME="${AR}/cx" bash "${ROOT}/install-codex.sh" --status 2>&1)"; RC_A=$?
OUT_B="$(CLAUDE_CONFIG_DIR="${AR}/cl" bash "${ROOT}/uninstall.sh" --force 2>&1)"; RC_B=$?
OUT_C="$(CODEX_HOME="${AR}/cx2" bash "${ROOT}/uninstall-codex.sh" -q 2>&1)"; RC_C=$?
set -e
{ [ "${RC_A}" -ne 0 ] && [ ! -e "${AR}/cx" ]; } \
  || fail "install-codex.sh must reject unknown options without installing (rc=${RC_A})"
printf '%s\n' "${OUT_A}" | grep -q 'unknown option' || fail "install-codex.sh rejection message missing"
[ "${RC_B}" -ne 0 ] || fail "uninstall.sh must reject unknown options (rc=${RC_B})"
printf '%s\n' "${OUT_B}" | grep -q 'unknown option' || fail "uninstall.sh rejection message missing"
[ "${RC_C}" -ne 0 ] || fail "uninstall-codex.sh must reject unknown options (rc=${RC_C})"
printf '%s\n' "${OUT_C}" | grep -q 'unknown option' || fail "uninstall-codex.sh rejection message missing"
rm -rf "${AR}"
echo "ok  installers reject unknown options"

# 4h. npm wrapper package: parseable, complete payload, no lifecycle scripts
python3 - "${ROOT}" <<'PY' || fail "package.json check failed"
import json, os, re, sys
root = sys.argv[1]
pkg = json.load(open(os.path.join(root, "package.json")))
assert pkg["name"] == "luciazero", "package name"
ver = None
for line in open(os.path.join(root, "CHANGELOG.md")):
    if line.startswith("## [") and line[4].isdigit():
        ver = line.split("[", 1)[1].split("]", 1)[0]
        break
assert pkg["version"] == ver, f"package.json version {pkg['version']} != CHANGELOG {ver}"
for bad in ("preinstall", "install", "postinstall", "prepare"):
    assert bad not in pkg.get("scripts", {}), f"lifecycle script '{bad}' forbidden (npm v12 blocks them; scanners flag them)"
assert not pkg.get("dependencies"), "npm wrapper must remain dependency-free"
files = set(pkg["files"])
for need in ("bin", "agents", "claude", "skills", "install.sh", "uninstall.sh",
             "install-codex.sh", "uninstall-codex.sh", "migrations"):
    assert need in files, f"files allowlist missing {need} — npx install would ship a broken payload"
assert "CHANGELOG.md" not in files, "release changelog must not inflate the npm runtime payload"
for base in ("bin", "agents", "claude", "skills", "migrations"):
    for directory, subdirs, names in os.walk(os.path.join(root, base)):
        assert "__pycache__" not in subdirs, f"npm payload contains Python cache dir: {directory}"
        assert not any(name.endswith((".pyc", ".pyo")) for name in names), \
            f"npm payload contains Python bytecode: {directory}"
with open(os.path.join(root, pkg["bin"]["luciazero"])) as f:
    assert f.readline().startswith("#!/usr/bin/env node"), "bin shebang"
assert os.access(os.path.join(root, pkg["bin"]["luciazero"]), os.X_OK), "bin must be executable"
shim = os.path.join(root, "bin", "luciazero-agentd")
assert os.access(shim, os.X_OK), "the agentd launcher must be executable"
with open(shim) as f:
    head = f.read(4096)
assert head.startswith("#!/bin/sh"), "the agentd launcher must be POSIX sh, not bash"
assert "luciazero-managed: agentd-launcher" in head, "the launcher must carry its ownership marker"
assert not any(line.lstrip().startswith("cd ") for line in head.splitlines()), \
    "the launcher must not change the caller's directory (attach records it)"
assert not any(re.match(r"\s*(export\s+)?PYTHONPATH=", line) for line in head.splitlines()), \
    "PYTHONPATH is colon-separated: a checkout path containing ':' would split into two entries"
def catalog(rel):
    return [x.strip() for x in open(os.path.join(root, rel)) if x.strip() and not x.lstrip().startswith("#")]
skills = catalog("skills/catalog.txt")
aliases = catalog("skills/aliases.txt")
agents = catalog("claude/agents/catalog.txt")
actual_skills = sorted(name for name in os.listdir(os.path.join(root, "skills"))
                       if os.path.isfile(os.path.join(root, "skills", name, "SKILL.md")))
actual_agents = sorted(os.path.splitext(name)[0] for name in os.listdir(os.path.join(root, "claude", "agents"))
                       if name.endswith(".md"))
assert sorted(skills + aliases) == actual_skills, \
    f"skill inventory drift: {skills + aliases} != {actual_skills}"
assert sorted(agents) == actual_agents, f"agent catalog drift: {agents} != {actual_agents}"
assert len(skills) == 13, f"expected 13 cataloged skills, found {len(skills)}"
assert aliases == [], f"unexpected compatibility aliases: {aliases}"
for metadata in ("package.json", ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
    assert "13 skills" in open(os.path.join(root, metadata)).read(), f"{metadata} skill count drift"
publishing = open(os.path.join(root, "docs/publishing.md")).read()
assert "carries the 13 skills" in publishing, "publishing channel skill count drift"
release_workflow = open(os.path.join(root, ".github/workflows/release.yml")).read()
gate = release_workflow.find("- name: Validate release versions")
publish = release_workflow.find("- name: Publish GitHub Release")
assert 0 <= gate < publish, "release version gate must run before GitHub publishing"
gate_end = release_workflow.find("\n      - name:", gate + 1)
assert gate_end > gate, "release version gate boundary missing"
gate_block = release_workflow[gate:gate_end]
for token in ("RELEASE_TAG: ${{ github.ref_name }}", "package.json",
              ".claude-plugin/plugin.json", "CHANGELOG.md"):
    assert token in gate_block, f"release version gate missing {token}"
assert "\\d+\\.\\d+\\.\\d+" in gate_block, \
    "release version gate must skip the Unreleased changelog heading"
stage = release_workflow.find("scripts/stage-npm-package.sh")
npm_publish = release_workflow.find('npm publish "${PACKAGE_DIR}"')
assert 0 <= stage < npm_publish, "npm release must publish the English-README staging package"
show = open(os.path.join(root, "skills/show/SKILL.md")).read()
for contract in ("What connects to what?", "What changed?", "What proves it?", "exit code", "Unknowns"):
    assert contract in show, f"show skill missing output contract: {contract}"
imouto = open(os.path.join(root, "skills/imouto-mode/SKILL.md")).read()
imouto_normalized = " ".join(imouto.split())
for contract in ("Default: off", "on", "focus", "off", "work first", "non-romantic", "Never auto-trigger",
                 "tsundere", "care through useful action", "Never insult", "Never withhold"):
    assert contract in imouto_normalized, f"imouto-mode missing contract: {contract}"
assert "disable-model-invocation: true" in imouto, "imouto-mode must disable Claude model invocation"
imouto_meta = open(os.path.join(root, "skills/imouto-mode/agents/openai.yaml")).read()
assert "allow_implicit_invocation: false" in imouto_meta, "imouto-mode must be explicit-only"
PY
if command -v node >/dev/null 2>&1; then
  NP_GUARD="$(mktemp -d)"
  printf 'keep\n' > "${NP_GUARD}/sentinel"
  NRC=0
  "${ROOT}/scripts/stage-npm-package.sh" "${NP_GUARD}" >/dev/null 2>&1 || NRC=$?
  if [ "${NRC}" -ne 64 ] || ! grep -qx keep "${NP_GUARD}/sentinel"; then
    rm -rf "${NP_GUARD}"
    fail "npm staging accepted or changed a non-empty directory"
  fi
  rm -rf "${NP_GUARD}"

  NP_STAGE="$(mktemp -d)"
  NP_CACHE="$(mktemp -d)"
  NP_DIR="$(NPM_CONFIG_CACHE="${NP_CACHE}" \
    "${ROOT}/scripts/stage-npm-package.sh" "${NP_STAGE}")" \
    || { rm -rf "${NP_STAGE}" "${NP_CACHE}"; fail "npm staging script failed"; }
  NP_JSON="$(NPM_CONFIG_CACHE="${NP_CACHE}" npm pack "${NP_DIR}" --dry-run --json)" \
    || { rm -rf "${NP_STAGE}" "${NP_CACHE}"; fail "staged npm payload could not be packed"; }
  printf '%s' "${NP_JSON}" | python3 -c '
import json, os, sys
pkg = json.load(sys.stdin)[0]
paths = [item["path"] for item in pkg["files"]]
readmes = [path for path in paths if os.path.basename(path).upper().startswith("README")]
assert readmes == ["README.md"], f"staged npm README selection is ambiguous: {readmes}"
assert "README.th.md" not in paths, "Thai README leaked into staged npm package"
assert "CHANGELOG.md" not in paths, "changelog leaked into staged npm package"
for required in ("bin/luciazero.js", "bin/luciazero-agentd", "install.sh",
                 "install-codex.sh", "claude/luciazero.md"):
    assert required in paths, f"staged npm package lost {required}"
' || { rm -rf "${NP_STAGE}" "${NP_CACHE}"; fail "staged npm payload contract failed"; }
  NP_VERSION="$(node -p "require('${NP_DIR}/package.json').version")"
  NP_CLAUDE="$(mktemp -d)"
  NP_CODEX="$(mktemp -d)"
  CLAUDE_CONFIG_DIR="${NP_CLAUDE}" bash "${NP_DIR}/install.sh" >/dev/null \
    || { rm -rf "${NP_STAGE}" "${NP_CACHE}" "${NP_CLAUDE}" "${NP_CODEX}"; fail "staged Claude installer failed"; }
  CODEX_HOME="${NP_CODEX}" bash "${NP_DIR}/install-codex.sh" >/dev/null \
    || { rm -rf "${NP_STAGE}" "${NP_CACHE}" "${NP_CLAUDE}" "${NP_CODEX}"; fail "staged Codex installer failed"; }
  if [ "$(cat "${NP_CLAUDE}/.luciazero-version")" != "${NP_VERSION}" ] \
    || [ "$(cat "${NP_CODEX}/.luciazero-version")" != "${NP_VERSION}" ]; then
    rm -rf "${NP_STAGE}" "${NP_CACHE}" "${NP_CLAUDE}" "${NP_CODEX}"
    fail "staged installers lost the package version sidecar"
  fi
  rm -rf "${NP_CLAUDE}" "${NP_CODEX}"
  rm -rf "${NP_STAGE}" "${NP_CACHE}"
  echo "ok  npm staging selects README.md + trims docs + installs with version"

  NB="$(mktemp -d)"
  set +e
  NOUT="$(CLAUDE_CONFIG_DIR="${NB}" node "${ROOT}/bin/luciazero.js" --status 2>&1)"
  NRC=$?
  set -e
  [ "${NRC}" -eq 1 ] || fail "npx wrapper --status on empty config dir: want rc 1, got ${NRC}"
  printf '%s\n' "${NOUT}" | grep -q 'MISS' || fail "npx wrapper --status lost install.sh's MISS output"
  rm -rf "${NB}"

  # Explicit update checks are deterministic under an injected registry
  # response. Merely requiring the module must never perform network or writes.
  UC="$(mktemp -d)"
  mkdir -p "${UC}/claude/hooks" "${UC}/codex"
  printf '1.9.0\n' > "${UC}/claude/.luciazero-version"
  printf '{"hooks":{"Stop":[{"hooks":[{"command":"%s/hooks/luciazero-verify.sh stop"}]}]}}\n' \
    "${UC}/claude" > "${UC}/claude/settings.json"
  printf '2.0.0\n' > "${UC}/codex/.luciazero-version"
  node - "${ROOT}" "${UC}" <<'JS' \
    || { rm -rf "${UC}"; fail "update helper unit checks failed"; }
const assert = require("node:assert");
const path = require("node:path");
const [root, fixture] = process.argv.slice(2);
const updater = require(path.join(root, "bin/update.js"));
const currentVersion = require(path.join(root, "package.json")).version;
const futureVersion = `${Number(currentVersion.split(".")[0]) + 1}.0.0`;

assert.strictEqual(updater.compareSemver("1.9.0", "2.0.0"), -1);
assert.strictEqual(updater.compareSemver("2.0.0", "2.0.0"), 0);
assert.strictEqual(updater.compareSemver("2.1.0", "2.0.0"), 1);
assert.strictEqual(updater.compareSemver("2.0.0-beta.2", "2.0.0-beta.10"), -1);
assert.strictEqual(updater.compareSemver("not-a-version", "2.0.0"), null);

const installations = updater.detectInstallations({
  claudeDir: path.join(fixture, "claude"),
  codexDir: path.join(fixture, "codex"),
});
assert.strictEqual(installations.length, 2);
assert.strictEqual(installations[0].channel, "claude-classic");
assert.strictEqual(installations[0].hooks, true, "dangling hook wiring must preserve hook mode");
assert.strictEqual(installations[1].channel, "codex");

const out = [];
const err = [];
(async () => {
  let requestedUrl = "";
  let requestSignal;
  const fetchedVersion = await updater.fetchLatestVersion({
    registry: "https://registry.example.test/npm/",
    fetch: async (url, options) => {
      requestedUrl = String(url);
      requestSignal = options.signal;
      return {ok: true, json: async () => ({version: futureVersion})};
    },
  });
  assert.strictEqual(fetchedVersion, futureVersion);
  assert.strictEqual(requestedUrl, "https://registry.example.test/npm/luciazero/latest");
  assert.ok(requestSignal instanceof AbortSignal, "registry request must carry an AbortSignal");
  await assert.rejects(
    updater.fetchLatestVersion({
      timeoutMs: 5,
      fetch: (_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => {
          const error = new Error("aborted");
          error.name = "AbortError";
          reject(error);
        });
      }),
    }),
    /timed out/
  );
  await assert.rejects(
    updater.fetchLatestVersion({fetch: async () => ({ok: false, status: 503})}),
    /HTTP 503/
  );
  await assert.rejects(
    updater.fetchLatestVersion({fetch: async () => ({ok: true, json: async () => ({version: "bad"})})}),
    /invalid version/
  );

  const rc = await updater.runCheck(["--json"], {
    detectInstallations: () => installations,
    fetchLatestVersion: async () => futureVersion,
    stdout: {write: (value) => out.push(String(value))},
    stderr: {write: (value) => err.push(String(value))},
  });
  assert.strictEqual(rc, 0);
  assert.strictEqual(err.join(""), "");
  const report = JSON.parse(out.join(""));
  assert.strictEqual(report.latestVersion, futureVersion);
  assert.strictEqual(report.cliUpdateAvailable, true);
  assert.strictEqual(report.updateAvailable, true);
  assert.deepStrictEqual(report.installations.map((item) => item.status), [
    "update-available", "update-available",
  ]);

  const malformedCheckOut = [];
  const malformedCheckRc = await updater.runCheck([], {
    detectInstallations: () => [{
      channel: "codex", configDir: fixture, installedVersion: "broken", versionFilePresent: true,
      hooks: false,
    }],
    fetchLatestVersion: async () => futureVersion,
    stdout: {write: (value) => malformedCheckOut.push(String(value))},
    stderr: {write: () => {}},
  });
  assert.strictEqual(malformedCheckRc, 0);
  assert.match(malformedCheckOut.join(""), /Cannot update installs with a malformed/);
  assert.doesNotMatch(malformedCheckOut.join(""), /Update detected classic\/Codex installs/);

  let spawnCount = 0;
  const downgradeErrors = [];
  const downgradeRc = updater.runUpdate([], {
    detectInstallations: () => [{
      channel: "codex", configDir: fixture, installedVersion: "99.0.0", hooks: false,
    }],
    spawnSync: () => { spawnCount += 1; return {status: 0}; },
    stdout: {write: () => {}},
    stderr: {write: (value) => downgradeErrors.push(String(value))},
  });
  assert.strictEqual(downgradeRc, 1);
  assert.strictEqual(spawnCount, 0, "an older updater must not overwrite a newer install");
  assert.match(downgradeErrors.join(""), /Refusing to downgrade Codex/);

  const malformedErrors = [];
  const malformedRc = updater.runUpdate([], {
    detectInstallations: () => [{
      channel: "codex", configDir: fixture, installedVersion: "broken", versionFilePresent: true,
      hooks: false,
    }],
    spawnSync: () => { spawnCount += 1; return {status: 0}; },
    stdout: {write: () => {}},
    stderr: {write: (value) => malformedErrors.push(String(value))},
  });
  assert.strictEqual(malformedRc, 1);
  assert.strictEqual(spawnCount, 0, "malformed version metadata must fail before writes");
  assert.match(malformedErrors.join(""), /version is malformed/);

  let legacySpawnCount = 0;
  const legacyRc = updater.runUpdate([], {
    detectInstallations: () => [{
      channel: "codex", configDir: fixture, installedVersion: null, versionFilePresent: false,
      hooks: false,
    }],
    spawnSync: () => { legacySpawnCount += 1; return {status: 0}; },
    stdout: {write: () => {}},
    stderr: {write: () => {}},
  });
  assert.strictEqual(legacyRc, 0, "legacy installs without a sidecar must remain updatable");
  assert.strictEqual(legacySpawnCount, 1);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
JS
  node "${ROOT}/bin/luciazero.js" check-update --help | grep -q 'never changes files' \
    || { rm -rf "${UC}"; fail "check-update CLI route/help missing"; }
  node "${ROOT}/bin/luciazero.js" update --help | grep -q 'preserves Claude hook mode' \
    || { rm -rf "${UC}"; fail "update CLI route/help missing"; }
  rm -rf "${UC}"

  # The updater repairs every detected channel, preserves both possible
  # classic modes, and refuses to turn "update" into a fresh install.
  UU="$(mktemp -d)"
  mkdir -p "${UU}/plain" "${UU}/hooks" "${UU}/codex" "${UU}/empty-claude" "${UU}/empty-codex"
  CLAUDE_CONFIG_DIR="${UU}/plain" "${ROOT}/install.sh" >/dev/null
  printf '1.0.0\n' > "${UU}/plain/.luciazero-version"
  printf '# customized doctrine\n' >> "${UU}/plain/luciazero.md"
  CLAUDE_CONFIG_DIR="${UU}/plain" CODEX_HOME="${UU}/empty-codex" \
    node "${ROOT}/bin/luciazero.js" update >/dev/null \
    || { rm -rf "${UU}"; fail "update failed for classic-without-hooks"; }
  [ ! -d "${UU}/plain/hooks" ] \
    || { rm -rf "${UU}"; fail "update enabled hooks for a no-hooks install"; }
  cmp -s "${UU}/plain/luciazero.md" "${ROOT}/claude/luciazero.md" \
    || { rm -rf "${UU}"; fail "update did not refresh the doctrine"; }
  grep -q 'customized doctrine' "${UU}/plain/.luciazero-backups"/luciazero.md.bak.* \
    || { rm -rf "${UU}"; fail "update overwrote a customized doctrine without backup"; }

  CLAUDE_CONFIG_DIR="${UU}/hooks" "${ROOT}/install.sh" --with-hooks >/dev/null
  CODEX_HOME="${UU}/codex" "${ROOT}/install-codex.sh" >/dev/null
  printf '1.0.0\n' > "${UU}/hooks/.luciazero-version"
  printf '1.0.0\n' > "${UU}/codex/.luciazero-version"
  printf '# stale hook\n' >> "${UU}/hooks/hooks/luciazero-verify.sh"
  UOUT="$(CLAUDE_CONFIG_DIR="${UU}/hooks" CODEX_HOME="${UU}/codex" \
    node "${ROOT}/bin/luciazero.js" update)" \
    || { rm -rf "${UU}"; fail "multi-channel update failed"; }
  cmp -s "${UU}/hooks/hooks/luciazero-verify.sh" "${ROOT}/claude/hooks/luciazero-verify.sh" \
    || { rm -rf "${UU}"; fail "update did not refresh a stale hook"; }
  PV="$(node -p "require('${ROOT}/package.json').version")"
  [ "$(cat "${UU}/hooks/.luciazero-version")" = "${PV}" ] \
    || { rm -rf "${UU}"; fail "Claude update did not refresh version sidecar"; }
  [ "$(cat "${UU}/codex/.luciazero-version")" = "${PV}" ] \
    || { rm -rf "${UU}"; fail "Codex update did not refresh version sidecar"; }
  printf '%s\n' "${UOUT}" | grep -q 'Claude classic + hooks' \
    || { rm -rf "${UU}"; fail "update output omitted detected hook mode"; }
  printf '%s\n' "${UOUT}" | grep -q 'Codex' \
    || { rm -rf "${UU}"; fail "update output omitted detected Codex install"; }
  RC=0
  CLAUDE_CONFIG_DIR="${UU}/empty-claude" CODEX_HOME="${UU}/empty-codex" \
    node "${ROOT}/bin/luciazero.js" update >/dev/null 2>&1 || RC=$?
  [ "${RC}" -eq 1 ] \
    || { rm -rf "${UU}"; fail "update without an installation must refuse (rc=${RC})"; }
  if [ -e "${UU}/empty-claude/.luciazero-version" ] \
    || [ -e "${UU}/empty-codex/.luciazero-version" ]; then
    rm -rf "${UU}"
    fail "update without an installation wrote files"
  fi
  rm -rf "${UU}"
  echo "ok  npm wrapper package + update/check routing"
else
  echo "ok  npm wrapper package (routing skipped: node not installed)"
fi

# 5. sandbox install cycle — never touches the real ~/.claude
SB="$(mktemp -d)"
CX="$(mktemp -d)"
trap 'rm -rf "${CLAUDE_CONFIG_DIR}" "${SB}" "${CX}"' EXIT
printf '@RTK.md\n\n# pre-existing user content\n' > "${SB}/CLAUDE.md"
mkdir -p "${SB}/skills/handoff"
cp "${ROOT}/migrations/handoff-v1.5.0.SKILL.md" "${SB}/skills/handoff/SKILL.md"
# A v2.2 install may still have the untouched compatibility alias. The v2.3
# installer must remove it, while preserving a customized copy.
mkdir -p "${SB}/skills/luciazero-bootstrap"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${SB}/skills/luciazero-bootstrap/SKILL.md"
mkdir -p "${SB}/.luciazero-managed/skills/luciazero-bootstrap"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${SB}/.luciazero-managed/skills/luciazero-bootstrap/SKILL.md"
# Generic names may already belong to the user or another plugin. The install
# must preserve the collision outside the discoverable skills directory.
mkdir -p "${SB}/skills/plan"
printf '%s\n' '---' 'name: plan' '---' '# pre-existing plan owner' > "${SB}/skills/plan/SKILL.md"

CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/install.sh" >/dev/null
[ -f "${SB}/luciazero.md" ] || fail "doctrine not installed"
while IFS= read -r NS; do
  [ -f "${SB}/skills/${NS}/SKILL.md" ] || fail "${NS} skill not installed"
done < <(skill_inventory)
[ -x "${SB}/skills/ready/scripts/detect.sh" ] || fail "detect.sh not installed or not executable"
[ ! -e "${SB}/skills/luciazero-bootstrap" ] \
  || fail "classic install did not migrate the retired compatibility alias"
[ -x "${SB}/skills/done/scripts/revert-probe.sh" ] || fail "revert-probe.sh not installed or not executable"
[ -x "${SB}/skills/bisect/scripts/safe-bisect.sh" ] || fail "safe-bisect.sh not installed or not executable"
[ -x "${SB}/skills/lucia-relay/scripts/relay.py" ] || fail "relay.py not installed or not executable"
[ -f "${SB}/.luciazero-version" ] || fail "version sidecar not written"
[ ! -d "${SB}/skills/handoff" ] || fail "managed legacy handoff was not migrated"
[ -f "${SB}/agents/reviewer.md" ] || fail "reviewer agent not installed"
[ ! -d "${SB}/hooks" ] || fail "hooks installed without --with-hooks"
[ "$(grep -cxF '@luciazero.md' "${SB}/CLAUDE.md")" = 1 ] || fail "import line not added"
grep -q 'pre-existing plan owner' "${SB}/.luciazero-backups"/skills/plan.bak.*/SKILL.md \
  || fail "classic install did not back up a colliding generic skill"

mkdir -p "${SB}/skills/handoff"
printf '%s\n' '---' 'name: handoff' '---' '# user customization' > "${SB}/skills/handoff/SKILL.md"
# Customizing a managed copy before an update must also be backed up, then the
# update may safely restore the shipped version.
echo '# customized managed plan' >> "${SB}/skills/plan/SKILL.md"
mkdir -p "${SB}/skills/luciazero-bootstrap"
printf '%s\n' '---' 'name: luciazero-bootstrap' '---' '# user-owned alias' \
  > "${SB}/skills/luciazero-bootstrap/SKILL.md"
CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/install.sh" >/dev/null
[ "$(grep -cxF '@luciazero.md' "${SB}/CLAUDE.md")" = 1 ] || fail "install is not idempotent"
grep -q 'user customization' "${SB}/skills/handoff/SKILL.md" || fail "install deleted a customized legacy handoff"
! grep -q 'customized managed plan' "${SB}/skills/plan/SKILL.md" \
  || fail "classic reinstall did not restore the shipped plan skill"
grep -q 'customized managed plan' "${SB}/.luciazero-backups"/skills/plan.bak.*/SKILL.md \
  || fail "classic reinstall did not back up a customized managed skill"
grep -q 'user-owned alias' "${SB}/skills/luciazero-bootstrap/SKILL.md" \
  || fail "classic migration deleted a customized retired alias"
rm -rf "${SB}/skills/handoff"
echo "ok  install + idempotent reinstall"

# --status: green on a complete install, red (and specific) once a piece is gone
CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/install.sh" --status >/dev/null \
  || fail "--status red on a complete install"
rm -rf "${SB}/skills/debug"
RC=0; SOUT="$(CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/install.sh" --status 2>&1)" || RC=$?
[ "${RC}" -ne 0 ] || fail "--status green with a skill missing"
echo "${SOUT}" | grep -q 'MISS.*debug' || fail "--status did not name the missing skill: ${SOUT}"
CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/install.sh" >/dev/null   # restore for the uninstall checks
echo "ok  --status green/red"

# Uninstall removes only byte-for-byte managed components; edits made after
# install are user data and must survive.
echo '# keep customized bisect' >> "${SB}/skills/bisect/SKILL.md"
echo '# keep customized reviewer' >> "${SB}/agents/reviewer.md"
echo '# keep customized doctrine' >> "${SB}/luciazero.md"
UOUT="$(CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/uninstall.sh" 2>&1)"
grep -q 'keep customized doctrine' "${SB}/luciazero.md" \
  || fail "classic uninstall deleted a customized doctrine"
while IFS= read -r NS; do
  if [ "${NS}" = bisect ]; then
    grep -q 'keep customized bisect' "${SB}/skills/bisect/SKILL.md" \
      || fail "classic uninstall deleted a customized managed skill"
  else
    [ ! -d "${SB}/skills/${NS}" ] || fail "${NS} skill left behind"
  fi
done < <(skill_inventory)
grep -q 'user-owned alias' "${SB}/skills/luciazero-bootstrap/SKILL.md" \
  || fail "classic uninstall deleted a customized retired alias"
grep -q 'keep customized reviewer' "${SB}/agents/reviewer.md" \
  || fail "classic uninstall deleted a customized managed agent"
echo "${UOUT}" | grep -q 'not the exact Luciazero-managed copy; left untouched' \
  || fail "classic uninstall did not explain preserved customizations"
[ ! -f "${SB}/.luciazero-version" ] || fail "version sidecar left behind"
grep -qxF '@RTK.md' "${SB}/CLAUDE.md" || fail "pre-existing CLAUDE.md content damaged"
grep -qxF '# pre-existing user content' "${SB}/CLAUDE.md" || fail "pre-existing CLAUDE.md content damaged"
! grep -qxF '@luciazero.md' "${SB}/CLAUDE.md" || fail "import line left behind"
echo "ok  uninstall restores CLAUDE.md"

# 5b. fresh-user cycle: no pre-existing CLAUDE.md at all — uninstall must not
# abort on the import-line-only file (regression: grep no-match + set -e)
SB2="$(mktemp -d)"
CLAUDE_CONFIG_DIR="${SB2}" "${ROOT}/install.sh" >/dev/null
CLAUDE_CONFIG_DIR="${SB2}" "${ROOT}/uninstall.sh" >/dev/null \
  || { rm -rf "${SB2}"; fail "uninstall failed on a fresh install (import-line-only CLAUDE.md)"; }
[ ! -f "${SB2}/CLAUDE.md.tmp" ] || { rm -rf "${SB2}"; fail "uninstall left CLAUDE.md.tmp behind"; }
if [ -f "${SB2}/CLAUDE.md" ]; then
  ! grep -qxF '@luciazero.md' "${SB2}/CLAUDE.md" \
    || { rm -rf "${SB2}"; fail "dangling import line after fresh-user uninstall"; }
fi
rm -rf "${SB2}"
echo "ok  fresh-user install + uninstall"

# 5c. enforcement pack: --with-hooks wiring is additive, idempotent, and
# fully removed by uninstall while user settings survive
SB3="$(mktemp -d)"
# fixture includes sentinel unknown keys (must round-trip untouched) and a
# user hook whose path merely LOOKS like ours (must never be removed)
cat > "${SB3}/settings.json" <<'JSON'
{
  "permissions": {"allow": ["Bash(ls:*)"]},
  "statusLine": {"type": "command", "command": "/my/custom.sh"},
  "env": {"SENTINEL": "1"},
  "model": "opusplan",
  "feedbackSurveyState": {"x": 1},
  "hooks": {
    "PreToolUse": [
      {"matcher": "Bash", "hooks": [{"type": "command", "command": "/Users/someone/dotfiles/hooks/luciazero-verify.sh precheck"}]}
    ]
  }
}
JSON
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" --with-hooks >/dev/null
[ -x "${SB3}/hooks/luciazero-verify.sh" ] || { rm -rf "${SB3}"; fail "verify hook not installed by --with-hooks"; }
[ -x "${SB3}/hooks/luciazero-statusline.sh" ] || { rm -rf "${SB3}"; fail "statusline script not installed by --with-hooks"; }
python3 - "${SB3}/settings.json" <<'PY' || { rm -rf "${SB3}"; fail "settings.json wiring wrong after --with-hooks"; }
import json, sys
s = json.load(open(sys.argv[1]))
assert s["permissions"]["allow"] == ["Bash(ls:*)"], "user permissions lost"
assert s["statusLine"]["command"] == "/my/custom.sh", "custom statusLine clobbered"
assert s["env"] == {"SENTINEL": "1"} and s["model"] == "opusplan", "sentinel keys lost"
assert s["feedbackSurveyState"] == {"x": 1}, "nested unknown key lost"
assert len(s["hooks"]["PostToolUse"]) == 3 and len(s["hooks"]["Stop"]) == 1
assert len(s["hooks"]["PostToolUseFailure"]) == 1, "failed Bash hook not wired"
assert len(s["hooks"]["SessionStart"]) == 1, "session hook not wired"
assert len(s["hooks"]["UserPromptSubmit"]) == 1, "prompt timing hook not wired"
assert len(s["hooks"]["UserPromptExpansion"]) == 1, "slash-skill hook not wired"
assert len(s["hooks"]["PreToolUse"]) == 2, "bash timing hook or user's hook missing"
PY
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" --status >/dev/null \
  || { rm -rf "${SB3}"; fail "--status red on a complete --with-hooks install"; }
# the hooks pass hashlib's usedforsecurity= (python 3.9+); installing them
# against an older or broken python3 must fail loudly, not leave hooks that
# fail open silently
OLDPY="$(mktemp -d)"; mkdir -p "${OLDPY}/bin" "${OLDPY}/cfg"
printf '#!/bin/sh\nexit 1\n' > "${OLDPY}/bin/python3"; chmod +x "${OLDPY}/bin/python3"
RC=0; OUT_OLDPY="$(PATH="${OLDPY}/bin:${PATH}" CLAUDE_CONFIG_DIR="${OLDPY}/cfg" \
  "${ROOT}/install.sh" --with-hooks 2>&1)" || RC=$?
[ "${RC}" != 0 ] \
  || { rm -rf "${SB3}" "${OLDPY}"; fail "--with-hooks installed against a python3 that cannot run the hooks"; }
printf '%s' "${OUT_OLDPY}" | grep -q 'python3 >= 3.9' \
  || { rm -rf "${SB3}" "${OLDPY}"; fail "--with-hooks did not name the python3 requirement: ${OUT_OLDPY}"; }
[ ! -e "${OLDPY}/cfg/hooks/luciazero-verify.sh" ] \
  || { rm -rf "${SB3}" "${OLDPY}"; fail "--with-hooks left hook files behind after refusing to install"; }
rm -rf "${OLDPY}"
cp "${SB3}/settings.json" "${SB3}/settings.snap"
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" --with-hooks >/dev/null
cmp -s "${SB3}/settings.json" "${SB3}/settings.snap" \
  || { rm -rf "${SB3}"; fail "--with-hooks reinstall changed settings.json (not idempotent)"; }
# --status must catch a stale hook file (the `git pull && ./install.sh`
# without --with-hooks failure mode: sidecar fresh, hook file old)
echo '# stale marker' >> "${SB3}/hooks/luciazero-verify.sh"
RC=0; SOUT="$(CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" --status 2>&1)" || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${SB3}"; fail "--status green with a stale hook file"; }
echo "${SOUT}" | grep -q 'differs from this checkout' \
  || { rm -rf "${SB3}"; fail "--status did not name the stale hook: ${SOUT}"; }
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/install.sh" --with-hooks >/dev/null   # restore
CLAUDE_CONFIG_DIR="${SB3}" "${ROOT}/uninstall.sh" >/dev/null 2>&1
[ ! -f "${SB3}/hooks/luciazero-verify.sh" ] || { rm -rf "${SB3}"; fail "hook file left behind"; }
python3 - "${SB3}/settings.json" "${SB3}" <<'PY' || { rm -rf "${SB3}"; fail "settings.json not cleaned correctly by uninstall"; }
import json, sys
s = json.load(open(sys.argv[1]))
ours = sys.argv[2] + "/hooks/luciazero-"
assert ours not in json.dumps(s), "our entries left behind"
assert s["permissions"]["allow"] == ["Bash(ls:*)"], "user permissions lost on uninstall"
assert s["statusLine"]["command"] == "/my/custom.sh", "custom statusLine removed"
assert s["env"] == {"SENTINEL": "1"} and s["model"] == "opusplan", "sentinel keys lost on uninstall"
pre = [h["command"] for e in s["hooks"]["PreToolUse"] for h in e["hooks"]]
assert pre == ["/Users/someone/dotfiles/hooks/luciazero-verify.sh precheck"], \
    "user's lookalike hook was deleted: " + json.dumps(s["hooks"])
PY
rm -rf "${SB3}"
echo "ok  enforcement pack install + idempotent + clean uninstall"

# 5d. failed settings cleanup must NOT delete the hook files (no dangling refs)
SB4="$(mktemp -d)"
CLAUDE_CONFIG_DIR="${SB4}" "${ROOT}/install.sh" --with-hooks >/dev/null
# corrupt the JSON while KEEPING a reference to our hook — the dangerous case:
# cleanup cannot run, so deleting the files would leave dangling references
printf '{broken json "%s/hooks/luciazero-verify.sh stop"\n' "${SB4}" > "${SB4}/settings.json"
CLAUDE_CONFIG_DIR="${SB4}" "${ROOT}/uninstall.sh" >/dev/null 2>&1 || true
[ -f "${SB4}/hooks/luciazero-verify.sh" ] \
  || { rm -rf "${SB4}"; fail "hook files deleted although settings cleanup failed (dangling references)"; }
rm -rf "${SB4}"
echo "ok  uninstall keeps hook files when settings cleanup fails"

# 5e. --status flags dangling hook references (files deleted by hand while
# settings.json still wires them — worse than not installed, never "ok")
SB5="$(mktemp -d)"
CLAUDE_CONFIG_DIR="${SB5}" "${ROOT}/install.sh" --with-hooks >/dev/null
rm -rf "${SB5}/hooks"
RC=0; SOUT="$(CLAUDE_CONFIG_DIR="${SB5}" "${ROOT}/install.sh" --status 2>&1)" || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${SB5}"; fail "--status green with dangling hook references"; }
echo "${SOUT}" | grep -q 'dangling' || { rm -rf "${SB5}"; fail "--status did not name the dangling references: ${SOUT}"; }
rm -rf "${SB5}"
echo "ok  --status flags dangling hook references"

# 5f. non-ASCII config path: settings.json must store the hook paths raw
# (ensure_ascii=False) or --status's byte-level greps can never match them
SB6R="$(mktemp -d)"
SB6="${SB6R}/claudé"
mkdir -p "${SB6}"
CLAUDE_CONFIG_DIR="${SB6}" "${ROOT}/install.sh" --with-hooks >/dev/null
CLAUDE_CONFIG_DIR="${SB6}" "${ROOT}/install.sh" --status >/dev/null \
  || { rm -rf "${SB6R}"; fail "--status red on a healthy non-ASCII config dir"; }
CLAUDE_CONFIG_DIR="${SB6}" "${ROOT}/uninstall.sh" >/dev/null 2>&1
[ ! -f "${SB6}/hooks/luciazero-verify.sh" ] || { rm -rf "${SB6R}"; fail "non-ASCII-path uninstall left hook files"; }
rm -rf "${SB6R}"
echo "ok  non-ASCII config dir install + status + uninstall"

# 5g. Agent Bus launcher: the public `luciazero-agentd` command. Everything
# here runs in a temporary home whose paths contain a space, from outside the
# repository, because that is where the two ways a shim breaks live: an
# unquoted expansion, and a package found relative to the caller's cwd.
if python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  LB_ROOT="$(mktemp -d)"
  LB_HOME="${LB_ROOT}/home dir"
  LB_BIN="${LB_ROOT}/path bin"
  LB_STATE="${LB_ROOT}/bus state"
  mkdir -p "${LB_HOME}" "${LB_STATE}"
  lb_fail() { rm -rf "${LB_ROOT}"; fail "$1"; }

  CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" LUCIAZERO_BIN_DIR="${LB_BIN}" \
    "${ROOT}/install.sh" >/dev/null || lb_fail "install.sh failed with LUCIAZERO_BIN_DIR"
  [ -x "${LB_BIN}/luciazero-agentd" ] || lb_fail "launcher not installed as an executable"
  grep -qF 'luciazero-managed: agentd-launcher' "${LB_BIN}/luciazero-agentd" \
    || lb_fail "installed launcher carries no ownership marker"
  [ "$(cat "${LB_HOME}/.claude/.luciazero-agentd-home")" = "${ROOT}/agentd" ] \
    || lb_fail "the launcher was not told where the agentd package is"

  # The store is created here rather than by a daemon: this section is about
  # the shim, and a live daemon would make it about ports and timing.
  PYTHONPATH="${ROOT}/agentd" python3 -c '
import sys
from luciazero_agentd.store import Store
with Store.open(sys.argv[1] + "/bus.sqlite3") as store:
    store.migrate()
' "${LB_STATE}" || lb_fail "could not create a temporary bus database"

  # From / with nothing but PATH: no cwd, no repository, no PYTHONPATH.
  ( cd / && PATH="${LB_BIN}:${PATH}" CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" \
      luciazero-agentd roster add lb-architect codex architect --state-dir "${LB_STATE}" >/dev/null ) \
    || lb_fail "the installed launcher cannot run from outside the checkout"

  # `next` renders the short command when the launcher is on PATH...
  LB_NEXT="$( cd / && PATH="${LB_BIN}:${PATH}" CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" \
    luciazero-agentd next --state-dir "${LB_STATE}" )" \
    || lb_fail "next failed through the installed launcher"
  printf '%s' "${LB_NEXT}" | grep -q '^    luciazero-agentd ' \
    || lb_fail "next did not render the short command with the launcher installed: ${LB_NEXT}"
  # ...and falls back to the module form when it is not, so a user who has not
  # installed it is never handed a command that is not on their PATH.
  # A PATH with a python3 on it and provably no launcher anywhere: the
  # directory holding the real python3 may itself be ~/.local/bin, which is
  # exactly where install.sh's help tells people to put the launcher.
  LB_PYBIN="${LB_ROOT}/python only"
  mkdir -p "${LB_PYBIN}"
  ln -s "$(command -v python3)" "${LB_PYBIN}/python3"
  LB_NEXT_BARE="$( cd / && PATH="${LB_PYBIN}" PYTHONPATH="${ROOT}/agentd" \
    CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" \
    python3 -m luciazero_agentd next --state-dir "${LB_STATE}" )" \
    || lb_fail "next failed without the launcher"
  printf '%s' "${LB_NEXT_BARE}" | grep -q 'python3 -m luciazero_agentd' \
    || lb_fail "next did not fall back to the python form: ${LB_NEXT_BARE}"

  # A directory of the caller's must never be able to supply the package.
  # `python -m pkg` puts the working directory first on sys.path, ahead of
  # PYTHONPATH, so a decoy next to the caller would shadow the real daemon.
  mkdir -p "${LB_ROOT}/decoy/luciazero_agentd"
  printf 'print("HIJACKED")\n' > "${LB_ROOT}/decoy/luciazero_agentd/__main__.py"
  # A regular package (one with __init__.py) beats a namespace portion found
  # earlier on sys.path, so the decoy needs one to be a real threat.
  : > "${LB_ROOT}/decoy/luciazero_agentd/__init__.py"
  LB_DECOY="$( cd "${LB_ROOT}/decoy" && PATH="${LB_BIN}:${PATH}" \
    CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" luciazero-agentd sessions --state-dir "${LB_STATE}" )" \
    || lb_fail "the launcher failed next to a decoy package"
  printf '%s' "${LB_DECOY}" | grep -q HIJACKED \
    && lb_fail "the caller's working directory supplied the package"

  # A ':' in the package path must not split it into two PYTHONPATH entries,
  # the tail of which resolves against the caller's directory.
  mkdir -p "${LB_ROOT}/co:lon" "${LB_ROOT}/split/lon/agentd/luciazero_agentd"
  ln -s "${ROOT}/agentd" "${LB_ROOT}/co:lon/agentd"
  printf 'print("HIJACKED")\n' > "${LB_ROOT}/split/lon/agentd/luciazero_agentd/__main__.py"
  : > "${LB_ROOT}/split/lon/agentd/luciazero_agentd/__init__.py"
  LB_COLON="$( cd "${LB_ROOT}/split" && LUCIAZERO_AGENTD_HOME="${LB_ROOT}/co:lon/agentd" \
    "${LB_BIN}/luciazero-agentd" sessions --state-dir "${LB_STATE}" )" \
    || lb_fail "the launcher failed with a ':' in the package path"
  printf '%s' "${LB_COLON}" | grep -q HIJACKED \
    && lb_fail "a ':' in the package path let the caller's directory supply the package"

  # An executable somebody else put there is never replaced, and never removed.
  printf '#!/bin/sh\nexit 3\n' > "${LB_BIN}/luciazero-agentd"
  LB_OUT="$(CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" LUCIAZERO_BIN_DIR="${LB_BIN}" \
    "${ROOT}/install.sh" 2>&1)" || lb_fail "install.sh must not fail on a foreign launcher"
  printf '%s' "${LB_OUT}" | grep -q 'not the Luciazero launcher' \
    || lb_fail "install.sh replaced or ignored a foreign luciazero-agentd silently"
  grep -qF 'exit 3' "${LB_BIN}/luciazero-agentd" || lb_fail "install.sh overwrote a foreign launcher"
  CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" LUCIAZERO_BIN_DIR="${LB_BIN}" \
    "${ROOT}/uninstall.sh" >/dev/null 2>&1
  grep -qF 'exit 3' "${LB_BIN}/luciazero-agentd" || lb_fail "uninstall.sh deleted a foreign luciazero-agentd"

  # Ours is removed, together with the record of where the package was.
  rm -f "${LB_BIN}/luciazero-agentd"
  CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" LUCIAZERO_BIN_DIR="${LB_BIN}" \
    "${ROOT}/install.sh" >/dev/null
  CLAUDE_CONFIG_DIR="${LB_HOME}/.claude" LUCIAZERO_BIN_DIR="${LB_BIN}" \
    "${ROOT}/uninstall.sh" >/dev/null
  [ ! -e "${LB_BIN}/luciazero-agentd" ] || lb_fail "uninstall.sh left its own launcher behind"
  [ ! -e "${LB_HOME}/.claude/.luciazero-agentd-home" ] || lb_fail "uninstall.sh left the package pointer behind"

  # The service subcommand must be inspectable without installing anything:
  # this suite may never leave a launchd or systemd unit on the machine.
  LB_SVC="$( cd / && PYTHONPATH="${ROOT}/agentd" python3 -m luciazero_agentd service install \
    --dry-run --root "${LB_ROOT}/svc root" --state-dir "${LB_STATE}" )" \
    || lb_fail "service install --dry-run failed"
  printf '%s' "${LB_SVC}" | grep -q 'dry run' || lb_fail "service dry run did not say so"
  if printf '%s' "${LB_SVC}" | grep -q -- '--allow-unattributed'; then
    lb_fail "a service must never be planned with --allow-unattributed"
  fi
  [ -z "$(find "${LB_ROOT}/svc root" -type f 2>/dev/null)" ] \
    || lb_fail "service install --dry-run wrote a file"

  rm -rf "${LB_ROOT}"
  echo "ok  luciazero-agentd launcher installs, runs from anywhere, and stays ownership-safe"
else
  echo "skip  luciazero-agentd launcher (python3 is older than 3.10)"
fi

# 6. sandbox Codex install cycle — never touches the real ~/.codex
printf '# pre-existing codex rules\n' > "${CX}/AGENTS.md"
mkdir -p "${CX}/skills/plan"
printf '%s\n' '---' 'name: plan' '---' '# pre-existing codex plan' > "${CX}/skills/plan/SKILL.md"
mkdir -p "${CX}/skills/luciazero-bootstrap"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${CX}/skills/luciazero-bootstrap/SKILL.md"
mkdir -p "${CX}/.luciazero-managed/skills/luciazero-bootstrap"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${CX}/.luciazero-managed/skills/luciazero-bootstrap/SKILL.md"

CODEX_HOME="${CX}" "${ROOT}/install-codex.sh" >/dev/null
grep -q '^# Luciazero' "${CX}/AGENTS.md" || fail "doctrine not in AGENTS.md"
[ "$(grep -cF 'luciazero:start' "${CX}/AGENTS.md")" = 1 ] || fail "marker block not added"
while IFS= read -r NS; do
  [ -f "${CX}/skills/${NS}/SKILL.md" ] || fail "codex ${NS} skill not installed"
done < <(skill_inventory)
[ -x "${CX}/skills/ready/scripts/detect.sh" ] || fail "codex detect.sh not installed or not executable"
[ ! -e "${CX}/skills/luciazero-bootstrap" ] \
  || fail "codex install did not migrate the retired compatibility alias"
[ -x "${CX}/skills/done/scripts/revert-probe.sh" ] || fail "codex revert-probe.sh not installed or not executable"
[ -x "${CX}/skills/bisect/scripts/safe-bisect.sh" ] || fail "codex safe-bisect.sh not installed or not executable"
[ -x "${CX}/skills/lucia-relay/scripts/relay.py" ] || fail "codex relay.py not installed or not executable"
[ -f "${CX}/.luciazero-version" ] || fail "codex version sidecar not written"
[ -f "${CX}/skills/reviewer/SKILL.md" ] || fail "codex reviewer skill not installed"
[ ! -d "${CX}/hooks" ] || fail "Claude-only hooks leaked into codex install"
grep -q '^name: reviewer$' "${CX}/skills/reviewer/SKILL.md" || fail "reviewer skill lost frontmatter"
! grep -q '^tools: ' "${CX}/skills/reviewer/SKILL.md" || fail "Claude-only tools: line leaked into codex skill"
! grep -q '^model: ' "${CX}/skills/reviewer/SKILL.md" || fail "Claude-only model: line leaked into codex skill"
grep -q 'pre-existing codex plan' "${CX}/.luciazero-backups"/skills/plan.bak.*/SKILL.md \
  || fail "codex install did not back up a colliding generic skill"

cp "${CX}/AGENTS.md" "${CX}/AGENTS.md.snap"
CODEX_HOME="${CX}" "${ROOT}/install-codex.sh" >/dev/null
[ "$(grep -cF 'luciazero:start' "${CX}/AGENTS.md")" = 1 ] || fail "codex install is not idempotent"
cmp -s "${CX}/AGENTS.md" "${CX}/AGENTS.md.snap" \
  || fail "codex reinstall changed AGENTS.md content (regression: accumulating blank lines)"
echo "ok  codex install + idempotent reinstall"

echo '# keep customized codex bisect' >> "${CX}/skills/bisect/SKILL.md"
# Simulate an older managed install and ensure uninstall removes the alias by
# comparing with its ownership snapshot.
mkdir -p "${CX}/skills/luciazero-bootstrap"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${CX}/skills/luciazero-bootstrap/SKILL.md"
mkdir -p "${CX}/.luciazero-managed/skills/luciazero-bootstrap"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${CX}/.luciazero-managed/skills/luciazero-bootstrap/SKILL.md"
COUT="$(CODEX_HOME="${CX}" "${ROOT}/uninstall-codex.sh" 2>&1)"
while IFS= read -r NS; do
  if [ "${NS}" = bisect ]; then
    grep -q 'keep customized codex bisect' "${CX}/skills/bisect/SKILL.md" \
      || fail "codex uninstall deleted a customized managed skill"
  else
    [ ! -d "${CX}/skills/${NS}" ] || fail "codex ${NS} skill left behind"
  fi
done < <(skill_inventory)
[ ! -e "${CX}/skills/luciazero-bootstrap" ] \
  || fail "codex uninstall left the retired compatibility alias"
[ ! -d "${CX}/skills/reviewer" ] || fail "codex reviewer skill left behind"
echo "${COUT}" | grep -q 'not the exact Luciazero-managed copy; left untouched' \
  || fail "codex uninstall did not explain preserved customizations"
[ ! -f "${CX}/.luciazero-version" ] || fail "codex version sidecar left behind"
grep -qxF '# pre-existing codex rules' "${CX}/AGENTS.md" || fail "pre-existing AGENTS.md content damaged"
! grep -qF 'luciazero:start' "${CX}/AGENTS.md" || fail "marker block left behind"
echo "ok  codex uninstall restores AGENTS.md"

# Retired-alias migration must not delete an exact-looking collision without a
# managed ownership snapshot, and must refuse symlinked skill parents.
SM="$(mktemp -d)"
mkdir -p "${SM}/skills/luciazero-bootstrap"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${SM}/skills/luciazero-bootstrap/SKILL.md"
CLAUDE_CONFIG_DIR="${SM}" "${ROOT}/install.sh" >/dev/null 2>&1
[ -f "${SM}/skills/luciazero-bootstrap/SKILL.md" ] \
  || { rm -rf "${SM}"; fail "install deleted an exact-looking alias collision without ownership snapshot"; }
rm -rf "${SM}"

SM="$(mktemp -d)"
mkdir -p "${SM}/outside/luciazero-bootstrap" "${SM}/.luciazero-managed/skills/luciazero-bootstrap"
ln -s "${SM}/outside" "${SM}/skills"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${SM}/outside/luciazero-bootstrap/SKILL.md"
cp "${ROOT}/migrations/luciazero-bootstrap-v2.2.0/SKILL.md" \
  "${SM}/.luciazero-managed/skills/luciazero-bootstrap/SKILL.md"
CLAUDE_CONFIG_DIR="${SM}" "${ROOT}/install.sh" >/dev/null 2>&1
[ -f "${SM}/outside/luciazero-bootstrap/SKILL.md" ] \
  || { rm -rf "${SM}"; fail "install followed a symlinked skill parent during alias migration"; }
CLAUDE_CONFIG_DIR="${SM}" "${ROOT}/uninstall.sh" >/dev/null 2>&1
[ -f "${SM}/outside/luciazero-bootstrap/SKILL.md" ] \
  || { rm -rf "${SM}"; fail "uninstall followed a symlinked skill parent during alias migration"; }
rm -rf "${SM}"
echo "ok  retired alias ownership + symlink safety"

echo
echo "PASS  all checks green"
