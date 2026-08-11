#!/usr/bin/env bash
# Verify command for this repo. The doctrine says a missing verify command is
# the first bug — this file is how the repo passes its own rule.
#
# Checks: shell syntax, shellcheck (when available), detect.sh smoke runs,
# example-settings JSON, skill + agent frontmatter, the doctrine word-count
# budget, then full install -> reinstall -> uninstall cycles for both
# harnesses in sandbox config dirs. Exits non-zero on the first failure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fail() { echo "FAIL: $*" >&2; exit 1; }

# The hooks append a stats line to ${CLAUDE_CONFIG_DIR:-~/.claude}; no test is
# ever allowed to touch the real one, so the whole run gets a sandbox default.
# Tests that set their own CLAUDE_CONFIG_DIR still override per invocation.
CLAUDE_CONFIG_DIR="$(mktemp -d)"
export CLAUDE_CONFIG_DIR

SCRIPTS=(install.sh uninstall.sh install-codex.sh uninstall-codex.sh test.sh
         demo.sh
         docs/assets/statusline-demo.sh
         skills/luciazero-bootstrap/scripts/detect.sh
         skills/done/scripts/revert-probe.sh
         claude/hooks/luciazero-verify.sh claude/hooks/luciazero-statusline.sh
         eval/run.sh eval/report.sh)
# every task grader, auto-discovered — a new task cannot skip the lint net
for G in "${ROOT}"/eval/tasks/*/grade.sh; do SCRIPTS+=("${G#"${ROOT}"/}"); done

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
OUT="$("${ROOT}/skills/luciazero-bootstrap/scripts/detect.sh" "${ROOT}")" \
  || fail "detect.sh exited non-zero"
echo "${OUT}" | grep -q 'test.sh' || fail "detect.sh did not surface test.sh from CI config"
echo "ok  detect.sh smoke run"

# 2c. detect.sh must also match the '- run:' list form, the most common
# GitHub Actions style (this repo's own CI happens not to use it)
FX="$(mktemp -d)"
mkdir -p "${FX}/.github/workflows"
printf 'jobs:\n  t:\n    steps:\n      - run: npm run canary-cmd\n' > "${FX}/.github/workflows/ci.yml"
# capture, then grep: grep -q on a pipe would SIGPIPE detect.sh under pipefail
OUT="$("${ROOT}/skills/luciazero-bootstrap/scripts/detect.sh" "${FX}")" \
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
for NAME in luciazero-bootstrap retro debug 'done' handoff experiment; do
  SKILL="${ROOT}/skills/${NAME}/SKILL.md"
  head -1 "${SKILL}" | grep -qx -- '---' || fail "${NAME}/SKILL.md missing frontmatter"
  grep -q "^name: ${NAME}\$" "${SKILL}" || fail "${NAME}/SKILL.md missing 'name: ${NAME}'"
  grep -q '^description: .' "${SKILL}" || fail "${NAME}/SKILL.md missing description"
done
AGENT="${ROOT}/claude/agents/reviewer.md"
head -1 "${AGENT}" | grep -qx -- '---' || fail "reviewer.md missing frontmatter"
grep -q '^name: reviewer$' "${AGENT}" || fail "reviewer.md missing 'name: reviewer'"
grep -q '^description: .' "${AGENT}" || fail "reviewer.md missing description"
grep -q '^model: inherit$' "${AGENT}" || fail "reviewer.md missing 'model: inherit' (reviewer must run on the authoring model)"
echo "ok  skill + agent frontmatter"

# 4b. doctrine budget — loaded on every turn of every session; this enforces "stays short"
DOCTRINE_FILE="${ROOT}/claude/luciazero.md"
W="$(wc -w < "${DOCTRINE_FILE}" | tr -d ' ')"
[ "${W}" -le 420 ] || fail "doctrine is ${W} words (limit 420) — every line costs context on every turn; cut a word to add a word"
! grep -qi 'subagent' "${DOCTRINE_FILE}" || fail "doctrine uses Claude-only 'subagent' vocabulary; phrase platform-neutrally"
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
# /done, /retro, /handoff, /experiment all write markdown after the final verify
echo '{"cwd":"/hook/test/proj","tool_input":{"command":"./test.sh"},"tool_response":{"exit_code":0}}' \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" bash
echo '{"cwd":"/hook/test/proj","tool_input":{"file_path":"/hook/test/proj/HANDOFF.md"}}' \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" edit
RC=0; echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.sh" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}"; fail "stop hook nudged on a docs-only write after green verify (rc=${RC})"; }
SL="$(echo '{"model":{"display_name":"M"},"workspace":{"current_dir":"/hook/test/proj"}}' \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-statusline.sh")"
printf '%s' "${SL}" | grep -q 'verify' || { rm -rf "${HT}"; fail "statusline missing verify status: ${SL}"; }
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

# 4c3. session subcommand: silent without a capsule, points at one when
# present, stale wording past the threshold, fails open on garbage stdin
SD="$(mktemp -d)"
OUT="$(printf '{"cwd":"%s"}' "${SD}" | "${ROOT}/claude/hooks/luciazero-verify.sh" session)"
[ -z "${OUT}" ] || { rm -rf "${HT}" "${SD}"; fail "session hook spoke without a capsule: ${OUT}"; }
echo x > "${SD}/HANDOFF.md"
OUT="$(printf '{"cwd":"%s"}' "${SD}" | "${ROOT}/claude/hooks/luciazero-verify.sh" session)"
echo "${OUT}" | grep -q 'HANDOFF.md exists' || { rm -rf "${HT}" "${SD}"; fail "session hook missed the capsule: ${OUT}"; }
touch -t 202001010000 "${SD}/HANDOFF.md"
OUT="$(printf '{"cwd":"%s"}' "${SD}" | "${ROOT}/claude/hooks/luciazero-verify.sh" session)"
echo "${OUT}" | grep -q 'stale' || { rm -rf "${HT}" "${SD}"; fail "session hook missed staleness: ${OUT}"; }
RC=0; printf 'not json' | "${ROOT}/claude/hooks/luciazero-verify.sh" session >/dev/null 2>&1 || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}" "${SD}"; fail "session hook not fail-open on garbage stdin (rc=${RC})"; }
rm -rf "${HT}" "${SD}"
echo "ok  session handoff pointer"

# 4c5. discipline stats: stop outcomes logged to the config dir, capped, and
# the learning-layer files survive uninstall
SC="$(mktemp -d)"
STMP="$(mktemp -d)"
SHK="${ROOT}/claude/hooks/luciazero-verify.sh"
SPJ1="${STMP}/proj"; SPJ2="${STMP}/boom"; SPJ3="${STMP}/third"
mkdir -p "${SPJ1}" "${SPJ2}" "${SPJ3}"
# clean stop (no edits) -> stop-clean
printf '{"cwd": "%s"}' "${SPJ1}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" stop \
  || fail "clean stop exited non-zero"
grep -q ' stop-clean proj$' "${SC}/luciazero-stats.log" || fail "stats missing stop-clean"
# edit then stop -> nudge (rc 2)
printf '{"cwd": "%s", "tool_input": {"file_path": "%s/a.py"}}' "${SPJ1}" "${SPJ1}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" edit
set +e
printf '{"cwd": "%s"}' "${SPJ1}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" stop 2>/dev/null
RC=$?
set -e
[ "${RC}" -eq 2 ] || fail "nudge stop: want rc 2, got ${RC}"
grep -q ' nudge proj$' "${SC}/luciazero-stats.log" || fail "stats missing nudge"
# strict red -> strict-block (rc 2)
printf '{"cwd": "%s", "tool_input": {"file_path": "%s/a.py"}}' "${SPJ2}" "${SPJ2}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" edit
set +e
printf '{"cwd": "%s"}' "${SPJ2}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" LUCIAZERO_STRICT_VERIFY_CMD="exit 3" "${SHK}" stop 2>/dev/null
RC=$?
set -e
[ "${RC}" -eq 2 ] || fail "strict red stop: want rc 2, got ${RC}"
grep -q ' strict-block boom$' "${SC}/luciazero-stats.log" || fail "stats missing strict-block"
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

# 4c6. learning layer stays wired through the skills that read/write it
grep -q 'docs/lessons.md' "${ROOT}/skills/debug/SKILL.md" || fail "debug skill lost the lesson-ledger lookup"
grep -q 'luciazero-heuristics.md' "${ROOT}/skills/debug/SKILL.md" || fail "debug skill lost the heuristics lookup"
grep -q 'docs/lessons.md' "${ROOT}/skills/retro/SKILL.md" || fail "retro skill lost the lesson-ledger routing"
grep -q 'luciazero-heuristics.md' "${ROOT}/skills/retro/SKILL.md" || fail "retro skill lost the heuristics routing"
grep -q 'luciazero-stats.log' "${ROOT}/skills/retro/SKILL.md" || fail "retro skill lost the stats review"
echo "ok  learning-layer skill wiring"

# 4d. eval graders stay honest — auto-discovered, so no task can ship without
# its proofs: PROMPT.md present, grader executable and following the output
# contract, reference/ passes, unfixed project/ fails, and any checked-in
# gamed/ cheat tree is rejected
for TDIR in "${ROOT}/eval/tasks"/*/; do
  TN="$(basename "${TDIR}")"
  [ -f "${TDIR}PROMPT.md" ] || fail "eval task ${TN}: missing PROMPT.md"
  [ -x "${TDIR}grade.sh" ] || fail "eval task ${TN}: grade.sh missing or not executable"
  [ -d "${TDIR}reference" ] || fail "eval task ${TN}: missing reference/"
  [ -d "${TDIR}project" ] || fail "eval task ${TN}: missing project/"
  OUT="$("${TDIR}grade.sh" "${TDIR}reference" 2>&1)" \
    || fail "eval grader ${TN} rejects its own reference solution: ${OUT}"
  echo "${OUT}" | grep -q '^SCORE ' || fail "eval grader ${TN} breaks the CRIT/SCORE output contract: ${OUT}"
  ! "${TDIR}grade.sh" "${TDIR}project" >/dev/null 2>&1 \
    || fail "eval grader ${TN} passes the unfixed project (grader cannot go red)"
  # every gamed*/ cheat variant must be rejected, and at least one must exist —
  # an untested "cannot be gamed" grader may not ship
  GAMED_SEEN=0
  for GD in "${TDIR}"gamed*/; do
    [ -d "${GD}" ] || continue
    GAMED_SEEN=1
    ! "${TDIR}grade.sh" "${GD}" >/dev/null 2>&1 \
      || fail "eval grader ${TN} passes its checked-in cheat tree ($(basename "${GD}")/)"
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
rm -f "${RPT}"
echo "ok  eval report fixture + malformed input"

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
for p in [plug["skills"], plug["hooks"]] + plug["agents"]:
    assert os.path.exists(os.path.join(root, p)), f"plugin.json path missing: {p}"
mkt = json.load(open(os.path.join(root, ".claude-plugin", "marketplace.json")))
assert mkt["name"] == "luciazero" and mkt["owner"]["name"], "marketplace name/owner"
assert mkt["plugins"][0]["name"] == "luciazero", "marketplace plugin entry"
assert mkt["plugins"][0]["source"] == "./", "marketplace plugin source"
hooks = json.load(open(os.path.join(root, "claude", "hooks", "hooks.json")))
cmds = [h["command"]
        for entries in hooks["hooks"].values()
        for e in entries for h in e["hooks"]]
for sub in ("edit", "bash", "stop", "session", "doctrine"):
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
for need in ("bin", "claude", "skills", "install.sh", "uninstall.sh",
             "install-codex.sh", "uninstall-codex.sh", "CHANGELOG.md"):
    assert need in files, f"files allowlist missing {need} — npx install would ship a broken payload"
with open(os.path.join(root, pkg["bin"]["luciazero"])) as f:
    assert f.readline().startswith("#!/usr/bin/env node"), "bin shebang"
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
  echo "ok  npm wrapper package + routing"
else
  echo "ok  npm wrapper package (routing skipped: node not installed)"
fi

# 5. sandbox install cycle — never touches the real ~/.claude
SB="$(mktemp -d)"
CX="$(mktemp -d)"
trap 'rm -rf "${SB}" "${CX}"' EXIT
printf '@RTK.md\n\n# pre-existing user content\n' > "${SB}/CLAUDE.md"

CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/install.sh" >/dev/null
[ -f "${SB}/luciazero.md" ] || fail "doctrine not installed"
[ -f "${SB}/skills/luciazero-bootstrap/SKILL.md" ] || fail "bootstrap skill not installed"
[ -x "${SB}/skills/luciazero-bootstrap/scripts/detect.sh" ] || fail "detect.sh not installed or not executable"
[ -x "${SB}/skills/done/scripts/revert-probe.sh" ] || fail "revert-probe.sh not installed or not executable"
[ -f "${SB}/.luciazero-version" ] || fail "version sidecar not written"
[ -f "${SB}/skills/retro/SKILL.md" ] || fail "retro skill not installed"
for NS in debug 'done' handoff experiment; do
  [ -f "${SB}/skills/${NS}/SKILL.md" ] || fail "${NS} skill not installed"
done
[ -f "${SB}/agents/reviewer.md" ] || fail "reviewer agent not installed"
[ ! -d "${SB}/hooks" ] || fail "hooks installed without --with-hooks"
[ "$(grep -cxF '@luciazero.md' "${SB}/CLAUDE.md")" = 1 ] || fail "import line not added"

CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/install.sh" >/dev/null
[ "$(grep -cxF '@luciazero.md' "${SB}/CLAUDE.md")" = 1 ] || fail "install is not idempotent"
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

CLAUDE_CONFIG_DIR="${SB}" "${ROOT}/uninstall.sh" >/dev/null
[ ! -f "${SB}/luciazero.md" ] || fail "doctrine left behind"
[ ! -d "${SB}/skills/luciazero-bootstrap" ] || fail "bootstrap skill left behind"
[ ! -d "${SB}/skills/retro" ] || fail "retro skill left behind"
for NS in debug 'done' handoff experiment; do
  [ ! -d "${SB}/skills/${NS}" ] || fail "${NS} skill left behind"
done
[ ! -f "${SB}/agents/reviewer.md" ] || fail "reviewer agent left behind"
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
assert len(s["hooks"]["PostToolUse"]) == 2 and len(s["hooks"]["Stop"]) == 1
assert len(s["hooks"]["SessionStart"]) == 1, "session hook not wired"
assert len(s["hooks"]["PreToolUse"]) == 1, "user's own hook disturbed by install"
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
pre = s["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
assert pre == "/Users/someone/dotfiles/hooks/luciazero-verify.sh precheck", \
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

CODEX_HOME="${CX}" "${ROOT}/install-codex.sh" >/dev/null
grep -q '^# Luciazero' "${CX}/AGENTS.md" || fail "doctrine not in AGENTS.md"
[ "$(grep -cF 'luciazero:start' "${CX}/AGENTS.md")" = 1 ] || fail "marker block not added"
[ -f "${CX}/skills/luciazero-bootstrap/SKILL.md" ] || fail "codex bootstrap skill not installed"
[ -x "${CX}/skills/luciazero-bootstrap/scripts/detect.sh" ] || fail "codex detect.sh not installed or not executable"
[ -x "${CX}/skills/done/scripts/revert-probe.sh" ] || fail "codex revert-probe.sh not installed or not executable"
[ -f "${CX}/.luciazero-version" ] || fail "codex version sidecar not written"
[ -f "${CX}/skills/retro/SKILL.md" ] || fail "codex retro skill not installed"
for NS in debug 'done' handoff experiment; do
  [ -f "${CX}/skills/${NS}/SKILL.md" ] || fail "codex ${NS} skill not installed"
done
[ -f "${CX}/skills/reviewer/SKILL.md" ] || fail "codex reviewer skill not installed"
[ ! -d "${CX}/hooks" ] || fail "Claude-only hooks leaked into codex install"
grep -q '^name: reviewer$' "${CX}/skills/reviewer/SKILL.md" || fail "reviewer skill lost frontmatter"
! grep -q '^tools: ' "${CX}/skills/reviewer/SKILL.md" || fail "Claude-only tools: line leaked into codex skill"
! grep -q '^model: ' "${CX}/skills/reviewer/SKILL.md" || fail "Claude-only model: line leaked into codex skill"

cp "${CX}/AGENTS.md" "${CX}/AGENTS.md.snap"
CODEX_HOME="${CX}" "${ROOT}/install-codex.sh" >/dev/null
[ "$(grep -cF 'luciazero:start' "${CX}/AGENTS.md")" = 1 ] || fail "codex install is not idempotent"
cmp -s "${CX}/AGENTS.md" "${CX}/AGENTS.md.snap" \
  || fail "codex reinstall changed AGENTS.md content (regression: accumulating blank lines)"
echo "ok  codex install + idempotent reinstall"

CODEX_HOME="${CX}" "${ROOT}/uninstall-codex.sh" >/dev/null
[ ! -d "${CX}/skills/luciazero-bootstrap" ] || fail "codex bootstrap skill left behind"
[ ! -d "${CX}/skills/retro" ] || fail "codex retro skill left behind"
for NS in debug 'done' handoff experiment; do
  [ ! -d "${CX}/skills/${NS}" ] || fail "codex ${NS} skill left behind"
done
[ ! -d "${CX}/skills/reviewer" ] || fail "codex reviewer skill left behind"
[ ! -f "${CX}/.luciazero-version" ] || fail "codex version sidecar left behind"
grep -qxF '# pre-existing codex rules' "${CX}/AGENTS.md" || fail "pre-existing AGENTS.md content damaged"
! grep -qF 'luciazero:start' "${CX}/AGENTS.md" || fail "marker block left behind"
echo "ok  codex uninstall restores AGENTS.md"

echo
echo "PASS  all checks green"
