#!/usr/bin/env bash
# Verify command for this repo. The doctrine says a missing verify command is
# the first bug — this file is how the repo passes its own rule.
#
# `--fast` covers core doctrine, hooks/report, Relay, bisect, and evidence
# integrity for intermediate loops. The default/`--full` continues through
# eval, packaging, and sandboxed install cycles for both harnesses.
# Exits non-zero on the first failure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIER=full
if [ "$#" -gt 1 ]; then
  echo "usage: ./test.sh [--fast|--full]" >&2
  exit 64
fi
case "${1:-}" in
  ""|--full) ;;
  --fast) TIER=fast ;;
  *) echo "usage: ./test.sh [--fast|--full]" >&2; exit 64 ;;
esac
fail() { echo "FAIL: $*" >&2; exit 1; }
catalog() { sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "$1"; }
skill_inventory() {
  catalog "${ROOT}/skills/catalog.txt"
  catalog "${ROOT}/skills/aliases.txt"
}

# The hooks append a stats line to ${CLAUDE_CONFIG_DIR:-~/.claude}; no test is
# ever allowed to touch the real one, so the whole run gets a sandbox default.
# Tests that set their own CLAUDE_CONFIG_DIR still override per invocation.
CLAUDE_CONFIG_DIR="$(mktemp -d)"
export CLAUDE_CONFIG_DIR
trap 'rm -rf "${CLAUDE_CONFIG_DIR}"' EXIT

SCRIPTS=(install.sh uninstall.sh install-codex.sh uninstall-codex.sh test.sh
         demo.sh
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

# 2. shellcheck when available (CI always has it)
if command -v shellcheck >/dev/null 2>&1; then
  (cd "${ROOT}" && shellcheck "${SCRIPTS[@]}")
  echo "ok  shellcheck"
else
  echo "skip shellcheck (not installed)"
fi

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
while IFS= read -r NAME; do
  SKILL="${ROOT}/skills/${NAME}/SKILL.md"
  head -1 "${SKILL}" | grep -qx -- '---' || fail "${NAME}/SKILL.md missing frontmatter"
  grep -q "^name: ${NAME}\$" "${SKILL}" || fail "${NAME}/SKILL.md missing 'name: ${NAME}'"
  grep -q '^description: .' "${SKILL}" || fail "${NAME}/SKILL.md missing description"
done < <(skill_inventory)
while IFS= read -r AGENT_NAME; do
  AGENT="${ROOT}/claude/agents/${AGENT_NAME}.md"
  head -1 "${AGENT}" | grep -qx -- '---' || fail "${AGENT_NAME}.md missing frontmatter"
  grep -q "^name: ${AGENT_NAME}\$" "${AGENT}" || fail "${AGENT_NAME}.md missing name"
  grep -q '^description: .' "${AGENT}" || fail "${AGENT_NAME}.md missing description"
  grep -q '^model: inherit$' "${AGENT}" || fail "${AGENT_NAME}.md must inherit the authoring model"
done < <(catalog "${ROOT}/claude/agents/catalog.txt")
cmp -s "${ROOT}/agents/reviewer.md" "${ROOT}/claude/agents/reviewer.md" \
  || fail "plugin agents/reviewer.md drifted from the classic reviewer source"
python3 -c 'compile(open(__import__("sys").argv[1], encoding="utf-8").read(), __import__("sys").argv[1], "exec")' \
  "${ROOT}/skills/lucia-relay/scripts/relay.py" || fail "relay.py syntax"
python3 -c 'compile(open(__import__("sys").argv[1], encoding="utf-8").read(), __import__("sys").argv[1], "exec")' \
  "${ROOT}/eval/evidence.py" || fail "evidence.py syntax"
python3 -c 'compile(open(__import__("sys").argv[1], encoding="utf-8").read(), __import__("sys").argv[1], "exec")' \
  "${ROOT}/eval/result_schema.py" || fail "result_schema.py syntax"
echo "ok  skill + agent frontmatter"

# Routine edits with obvious scope/proof must not pay for planning/debugging
# ceremony. The descriptions are the auto-trigger contract exposed to agents.
grep -q 'Not for routine edits whose scope and proof are already clear' \
  "${ROOT}/skills/plan/SKILL.md" || fail "plan skill still auto-triggers on routine edits"
grep -q 'Not for a first obvious failure' "${ROOT}/skills/debug/SKILL.md" \
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
EVILKEY="$(printf '%s' "${SPJ4}" | python3 -c 'import hashlib,sys; print(hashlib.md5(sys.stdin.buffer.read()).hexdigest()[:12])')"
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

# Cross-machine routing must be an explicit, mechanically portable decision:
# pushed clean tree + no source-machine paths. Local knowledge travels inline.
RR="$(mktemp -d)"
RREMOTE="$(mktemp -d)"
git -C "${RREMOTE}" init -q --bare
git -C "${RR}" init -q -b main
git -C "${RR}" config user.name test
git -C "${RR}" config user.email test@example.invalid
mkdir -p "${RR}/docs"
echo base > "${RR}/work.txt"
echo portable > "${RR}/docs/notes.md"
git -C "${RR}" add work.txt docs/notes.md && git -C "${RR}" commit -qm base
git -C "${RR}" remote add origin "${RREMOTE}"
git -C "${RR}" push -qu -u origin main
write_cross_relay() {
  "${RELAY}" draft --root "${RR}" --recipient cross-machine > "${RR}/LUCIA_RELAY.json"
  python3 - "${RR}/LUCIA_RELAY.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p))
d["goal"]="Move the parser knowledge to another machine"
d["state"]["done"]=["Confirmed the receiver location"]
d["state"]["in_progress"]=["Implementation remains untouched"]
d["state"]["next_step"]={"kind":"command","value":"./verify.sh"}
d["verification"]=[{"command":"./verify.sh","exit_code":1,"decisive_line":"parser case fails","run_at":"2026-08-12T12:00:00+00:00"}]
d["knowledge"]["read_first"]=["docs/notes.md — portable note"]
d["knowledge"]["hypotheses"]=[{"id":"H1","claim":"encoding","status":"refuted","evidence":"ASCII fails too"}]
open(p,"w").write(json.dumps(d, indent=2)+"\n")
PY
}
write_cross_relay
"${RELAY}" validate --root "${RR}" >/dev/null \
  || { rm -rf "${RR}" "${RREMOTE}"; fail "clean pushed cross-machine relay rejected"; }
PYTHONDONTWRITEBYTECODE=1 python3 - "${RELAY}" "${RR}/LUCIA_RELAY.json" <<'PY'
import copy, importlib.util, json, sys
spec=importlib.util.spec_from_file_location("relay_under_test", sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
data=json.load(open(sys.argv[2]))
assert module.machine_paths({"note":"compare parser / renderer"}) == []
assert module.machine_paths({"note":"file:///Users/sender/notes.md"})
assert module.machine_paths({"note":r"\\server\share\notes.md"})
legacy=copy.deepcopy(data)
legacy["schema"]=1
legacy.pop("route")
legacy["repository"].pop("known_remote_refs")
legacy["knowledge"].pop("inline")
errors, warnings=module.validate(legacy)
assert errors == [] and any("legacy schema 1" in warning for warning in warnings)
rendered=module.render_markdown(legacy)
assert "Recipient:" not in rendered and "## Inline knowledge" not in rendered
PY
python3 - "${RR}/LUCIA_RELAY.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p))
d["knowledge"]["read_first"]=["docs/missing.md"]
open(p,"w").write(json.dumps(d, indent=2)+"\n")
PY
RC=0; OUT="$("${RELAY}" validate --root "${RR}" 2>&1)" || RC=$?
if ! { [ "${RC}" -eq 1 ] && echo "${OUT}" | grep -q 'not present in the pushed relay commit'; }; then
  rm -rf "${RR}" "${RREMOTE}"; fail "cross-machine relay accepted a missing repo-relative pointer"
fi
write_cross_relay
python3 - "${RR}/LUCIA_RELAY.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p))
assert d["route"]["recipient"] == "cross-machine"
assert d["repository"]["known_remote_refs"] == ["origin/main"]
d["knowledge"]["read_first"]=["/Users/sender/private/notes.md"]
open(p,"w").write(json.dumps(d, indent=2)+"\n")
PY
RC=0; OUT="$("${RELAY}" validate --root "${RR}" 2>&1)" || RC=$?
if ! { [ "${RC}" -eq 1 ] && echo "${OUT}" | grep -q 'machine-only paths'; }; then
  rm -rf "${RR}" "${RREMOTE}"; fail "cross-machine relay accepted a source-machine path"
fi
python3 - "${RR}/LUCIA_RELAY.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p))
d["knowledge"]["read_first"]=["docs/notes.md — portable note"]
d["knowledge"]["inline"]=[{"label":"sender note","content":"Use the public parser contract"}]
open(p,"w").write(json.dumps(d, indent=2)+"\n")
PY
"${RELAY}" validate --root "${RR}" >/dev/null \
  || { rm -rf "${RR}" "${RREMOTE}"; fail "cross-machine relay rejected inline knowledge"; }
cp "${RR}/LUCIA_RELAY.json" "${RREMOTE}/stale-relay.json"
echo pushed-later >> "${RR}/work.txt"
git -C "${RR}" add work.txt && git -C "${RR}" commit -qm pushed-later
git -C "${RR}" push -qu
cp "${RREMOTE}/stale-relay.json" "${RR}/LUCIA_RELAY.json"
RC=0; OUT="$("${RELAY}" validate --root "${RR}" 2>&1)" || RC=$?
if ! { [ "${RC}" -eq 1 ] && echo "${OUT}" | grep -q 'fingerprint is stale'; }; then
  rm -rf "${RR}" "${RREMOTE}"; fail "cross-machine relay accepted stale repository state"
fi
git -C "${RR}" reset -q --hard HEAD~1
echo dirty >> "${RR}/work.txt"
write_cross_relay
RC=0; OUT="$("${RELAY}" validate --root "${RR}" 2>&1)" || RC=$?
if ! { [ "${RC}" -eq 1 ] && echo "${OUT}" | grep -q 'dirty worktree'; }; then
  rm -rf "${RR}" "${RREMOTE}"; fail "cross-machine relay accepted an uncommitted task tree"
fi
git -C "${RR}" add work.txt && git -C "${RR}" commit -qm local-ahead
write_cross_relay
RC=0; OUT="$("${RELAY}" validate --root "${RR}" 2>&1)" || RC=$?
if ! { [ "${RC}" -eq 1 ] && echo "${OUT}" | grep -q 'push it before routing'; }; then
  rm -rf "${RR}" "${RREMOTE}"; fail "cross-machine relay accepted an unpushed HEAD"
fi
rm -rf "${RR}" "${RREMOTE}"
echo "ok  lucia relay lifecycle"

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
import json, os, sys
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
files = set(pkg["files"])
for need in ("bin", "agents", "claude", "skills", "install.sh", "uninstall.sh",
             "install-codex.sh", "uninstall-codex.sh", "migrations", "CHANGELOG.md"):
    assert need in files, f"files allowlist missing {need} — npx install would ship a broken payload"
for base in ("bin", "agents", "claude", "skills", "migrations"):
    for directory, subdirs, names in os.walk(os.path.join(root, base)):
        assert "__pycache__" not in subdirs, f"npm payload contains Python cache dir: {directory}"
        assert not any(name.endswith((".pyc", ".pyo")) for name in names), \
            f"npm payload contains Python bytecode: {directory}"
with open(os.path.join(root, pkg["bin"]["luciazero"])) as f:
    assert f.readline().startswith("#!/usr/bin/env node"), "bin shebang"
assert os.access(os.path.join(root, pkg["bin"]["luciazero"]), os.X_OK), "bin must be executable"
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
assert len(skills) == 11, f"expected 11 cataloged skills, found {len(skills)}"
assert aliases == ["luciazero-bootstrap"], f"unexpected compatibility aliases: {aliases}"
for metadata in ("package.json", ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
    assert "11 skills" in open(os.path.join(root, metadata)).read(), f"{metadata} skill count drift"
show = open(os.path.join(root, "skills/show/SKILL.md")).read()
for contract in ("What connects to what?", "What changed?", "What proves it?", "exit code", "Unknowns"):
    assert contract in show, f"show skill missing output contract: {contract}"
imouto = open(os.path.join(root, "skills/imouto-mode/SKILL.md")).read()
for contract in ("Default: off", "on", "focus", "off", "work first", "non-romantic", "Never auto-trigger",
                 "tsundere", "care through useful action", "Never insult", "Never withhold"):
    assert contract in imouto, f"imouto-mode missing contract: {contract}"
assert "disable-model-invocation: true" in imouto, "imouto-mode must disable Claude model invocation"
imouto_meta = open(os.path.join(root, "skills/imouto-mode/agents/openai.yaml")).read()
assert "allow_implicit_invocation: false" in imouto_meta, "imouto-mode must be explicit-only"
PY
if command -v node >/dev/null 2>&1; then
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
grep -Fq "renamed to \`/ready\`" "${SB}/skills/luciazero-bootstrap/SKILL.md" \
  || fail "classic compatibility alias missing rename guidance"
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
CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/install.sh" >/dev/null
[ "$(grep -cxF '@luciazero.md' "${SB}/CLAUDE.md")" = 1 ] || fail "install is not idempotent"
grep -q 'user customization' "${SB}/skills/handoff/SKILL.md" || fail "install deleted a customized legacy handoff"
! grep -q 'customized managed plan' "${SB}/skills/plan/SKILL.md" \
  || fail "classic reinstall did not restore the shipped plan skill"
grep -q 'customized managed plan' "${SB}/.luciazero-backups"/skills/plan.bak.*/SKILL.md \
  || fail "classic reinstall did not back up a customized managed skill"
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

# 6. sandbox Codex install cycle — never touches the real ~/.codex
printf '# pre-existing codex rules\n' > "${CX}/AGENTS.md"
mkdir -p "${CX}/skills/plan"
printf '%s\n' '---' 'name: plan' '---' '# pre-existing codex plan' > "${CX}/skills/plan/SKILL.md"

CODEX_HOME="${CX}" "${ROOT}/install-codex.sh" >/dev/null
grep -q '^# Luciazero' "${CX}/AGENTS.md" || fail "doctrine not in AGENTS.md"
[ "$(grep -cF 'luciazero:start' "${CX}/AGENTS.md")" = 1 ] || fail "marker block not added"
while IFS= read -r NS; do
  [ -f "${CX}/skills/${NS}/SKILL.md" ] || fail "codex ${NS} skill not installed"
done < <(skill_inventory)
[ -x "${CX}/skills/ready/scripts/detect.sh" ] || fail "codex detect.sh not installed or not executable"
grep -Fq "renamed to \`/ready\`" "${CX}/skills/luciazero-bootstrap/SKILL.md" \
  || fail "codex compatibility alias missing rename guidance"
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
COUT="$(CODEX_HOME="${CX}" "${ROOT}/uninstall-codex.sh" 2>&1)"
while IFS= read -r NS; do
  if [ "${NS}" = bisect ]; then
    grep -q 'keep customized codex bisect' "${CX}/skills/bisect/SKILL.md" \
      || fail "codex uninstall deleted a customized managed skill"
  else
    [ ! -d "${CX}/skills/${NS}" ] || fail "codex ${NS} skill left behind"
  fi
done < <(skill_inventory)
[ ! -d "${CX}/skills/reviewer" ] || fail "codex reviewer skill left behind"
echo "${COUT}" | grep -q 'not the exact Luciazero-managed copy; left untouched' \
  || fail "codex uninstall did not explain preserved customizations"
[ ! -f "${CX}/.luciazero-version" ] || fail "codex version sidecar left behind"
grep -qxF '# pre-existing codex rules' "${CX}/AGENTS.md" || fail "pre-existing AGENTS.md content damaged"
! grep -qF 'luciazero:start' "${CX}/AGENTS.md" || fail "marker block left behind"
echo "ok  codex uninstall restores AGENTS.md"

echo
echo "PASS  all checks green"
