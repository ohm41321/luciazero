# tests/gates/hooks.sh — enforcement hook state machine, committed-settings refusal, strict gate, session, stats schema, discipline report.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# 4c. enforcement-pack hook state machine (isolated TMPDIR; fails open by design)
mktmp HT
HJ='{"cwd":"/hook/test/proj"}'
echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
RC=0; echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>/dev/null || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${HT}"; fail "stop hook did not nudge on unverified edits (rc=${RC})"; }
RC=0; echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}"; fail "stop nudge is not one-shot (rc=${RC})"; }
echo '{"cwd":"/hook/test/proj","tool_input":{"command":"./test.sh"},"tool_response":{"exit_code":0}}' \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
echo '{"cwd":"/hook/test/proj"}' | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
echo '{"cwd":"/hook/test/proj","tool_input":{"command":"./test.sh"},"tool_response":{"exit_code":0}}' \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
RC=0; echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}"; fail "stop hook nudged despite verify after edit (rc=${RC})"; }
# edit immediately after a verify (same wall-clock second): must still nudge —
# regression for bash 3.2's whole-second [ -nt ] missing sub-second ordering
echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
RC=0; echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>/dev/null || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${HT}"; fail "stop hook missed an edit made right after verify (rc=${RC})"; }
# a documentation write after a green verify must NOT re-arm the nudge —
# Closeout docs and relay artifacts written after final verify must not re-arm
echo '{"cwd":"/hook/test/proj","tool_input":{"command":"./test.sh"},"tool_response":{"exit_code":0}}' \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
echo '{"cwd":"/hook/test/proj","tool_input":{"file_path":"/hook/test/proj/LUCIA_RELAY.json"}}' \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
RC=0; echo "${HJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}"; fail "stop hook nudged on a docs-only write after green verify (rc=${RC})"; }
SL="$(echo '{"model":{"display_name":"M"},"workspace":{"current_dir":"/hook/test/proj"}}' \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-statusline.cjs")"
grep -q '✅ verify' <<<"${SL}" || { rm -rf "${HT}"; fail "statusline missed green verify state: ${SL}"; }
# Markdown is documentation; a .txt file may be a build input
# (requirements.txt, CMakeLists.txt) and re-arms like code.
DJ='{"cwd":"/hook/test/docs"}'
for DOC in README.md requirements.txt CMakeLists.txt; do
  echo '{"cwd":"/hook/test/docs","tool_input":{"command":"./test.sh"},"tool_response":{"exit_code":0}}' \
    | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
  printf '{"cwd":"/hook/test/docs","tool_input":{"file_path":"/hook/test/docs/%s"}}\n' "${DOC}" \
    | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
  RC=0; echo "${DJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>/dev/null || RC=$?
  if [ "${DOC}" = README.md ]; then WANT=0; else WANT=2; fi
  [ "${RC}" = "${WANT}" ] || { rm -rf "${HT}"; fail "stop hook after a write to ${DOC} following green verify: rc=${RC}, want ${WANT}"; }
done
# The stop nudge belongs to the session whose edit is unverified, once each:
# a session that edited nothing stops clean, and another session's nudge does
# not use up this one's. Any session's verify run covers every session's edit.
sess_hook() { # sess_hook <session> <mode> [extra-json-fields]: exit code in SH_RC
  SH_RC=0
  printf '{"cwd":"%s","session_id":"%s"%s}\n' "${SESS_CWD}" "$1" "${3:-}" \
    | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" "$2" 2>/dev/null || SH_RC=$?
}
sess_stop() { # sess_stop <session> <want rc> <failure message>
  sess_hook "$1" stop
  [ "${SH_RC}" = "$2" ] || { rm -rf "${HT}"; fail "$3 (session $1 stop: rc=${SH_RC}, want $2)"; }
}
sess_state() { # the hook's state directory for SESS_CWD
  printf '%s/luciazero-verify-state-%s/%s' "${HT}" "$(id -u)" \
    "$(python3 -c 'import hashlib,sys; print(hashlib.md5(sys.argv[1].encode(), usedforsecurity=False).hexdigest()[:12])' "${SESS_CWD}")"
}
SESS_EDIT=',"tool_input":{"file_path":"/hook/test/sessions/a.py"}'
SESS_GREEN=',"tool_input":{"command":"./test.sh"},"tool_response":{"exit_code":0}'
SESS_CWD=/hook/test/sessions
sess_hook A edit "${SESS_EDIT}"
sess_stop B 0 "a session that made no edit was nudged for another session's edit"
sess_stop A 2 "the session that edited was not nudged after another session stopped first"
sess_stop A 0 "the per-session nudge is not one-shot"
sess_hook B edit "${SESS_EDIT}"
sess_stop B 2 "one session's nudge used up another's"
sess_hook B bash "${SESS_GREEN}"
sess_hook A edit "${SESS_EDIT}"
sess_stop B 0 "a green run did not cover the edit made before it"
sess_stop A 2 "an edit after a green run in another session did not re-arm this session's nudge"
# A verify run vouches for the code as it was when it started, so it does
# not cover an edit made while it ran, nor re-arm the nudge that edit caused.
SESS_RUN=',"tool_use_id":"slow-verify","tool_input":{"command":"./test.sh"}'
sess_hook B bash-start "${SESS_RUN}"
sess_hook A edit "${SESS_EDIT}"
sess_stop A 2 "an edit made while another session's verify ran was not nudged"
sess_hook B bash "${SESS_RUN}"',"tool_response":{"exit_code":0}'
sess_stop A 0 "a verify run that started before an edit re-armed the nudge that edit had caused"
# State an older copy left -- last_edit with no edited/ yet, and its one
# plain nudged file -- still nudges each session once, before and after
# another session's first edit under this copy. That edit re-arms the older
# copy's file, as an edit always did.
SESS_CWD=/hook/test/sessions-legacy
mkdir -p "$(sess_state)"; chmod 700 "$(sess_state)"
touch "$(sess_state)/last_edit" "$(sess_state)/nudged"
sess_stop C 2 "an older copy's project-wide nudged file silenced a session that was never nudged"
sess_stop C 0 "the nudge after an older copy's state is not one-shot"
sess_hook P edit "${SESS_EDIT}"
sess_stop D 2 "an edit only an older copy recorded was dropped once another session edited"
sess_stop C 0 "a session nudged for an older copy's edit was nudged for it again"
sess_stop P 2 "the session that edited under this copy was not nudged"
if [ -e "$(sess_state)/nudged" ]; then
  rm -rf "${HT}"; fail "an edit left the older copy's nudged file in place, so that copy stays silent"
fi
sess_hook P bash "${SESS_GREEN}"
sess_stop D 0 "a green run did not cover the older copy's edit"
# An older copy's edit made while this copy's verify ran is not covered by
# that run either.
SESS_CWD=/hook/test/sessions-changeover
sess_hook N bash-start "${SESS_RUN}"
touch "$(sess_state)/last_edit"
sess_hook P edit "${SESS_EDIT}"
sess_stop C 2 "an older copy's edit made while a verify ran was not nudged"
sess_hook N bash "${SESS_RUN}"',"tool_response":{"exit_code":0}'
sess_stop C 0 "a verify run that started before an older copy's edit re-armed the nudge that edit had caused"
# Overlapping verify runs finish in any order. The one that started last
# tested the newest code, so one that started earlier and finishes later
# does not take its place: neither its green nor its red un-covers an edit
# the later run covered.
SESS_CWD=/hook/test/sessions-overlap
SESS_EARLY=',"tool_use_id":"verify-early","tool_input":{"command":"./test.sh"}'
SESS_LATE=',"tool_use_id":"verify-late","tool_input":{"command":"./test.sh"}'
for ENDED in '"tool_response":{"exit_code":0}' '"tool_response":{"exit_code":1}'; do
  sess_hook A bash-start "${SESS_EARLY}"
  sess_hook A edit "${SESS_EDIT}"
  sess_hook B bash-start "${SESS_LATE}"
  sess_hook B bash "${SESS_LATE}"',"tool_response":{"exit_code":0}'
  sess_hook A bash "${SESS_EARLY},${ENDED}"
  sess_stop A 0 "a verify run that started first and ended last un-covered an edit a later green covered (${ENDED})"
  if [ "$(cat "$(sess_state)/last_verify")" != ok ]; then
    rm -rf "${HT}"; fail "a verify run that started first and ended last replaced a later green (${ENDED})"
  fi
done
# A recorded start in the future means the clock stepped back; it must not
# hold off every result until the wall clock passes it.
python3 -c 'import os,sys; t=1893456000; open(sys.argv[2],"w").write("%d000\n" % t); os.utime(sys.argv[1], (t, t))' \
  "$(sess_state)/last_verify" "$(sess_state)/last_verify_start"
sess_hook A bash-start "${SESS_EARLY}"
sess_hook A bash "${SESS_EARLY}"',"tool_response":{"exit_code":1}'
if [ "$(cat "$(sess_state)/last_verify")" != fail ]; then
  rm -rf "${HT}"; fail "a recorded start in the future held off a later red"
fi
# The released hook itself (v2.6.0, byte for byte) beside this one on one
# project, as when a session started before an update keeps the old copy:
# neither copy's nudge silences the other's, an edit under either arms both,
# and a green run under either covers both.
mkdir -p "${HT}/released-config"
old_hook() { # old_hook <session> <mode> [extra-json-fields]: exit code in OH_RC
  OH_RC=0
  printf '{"cwd":"%s","session_id":"%s"%s}\n' "${SESS_CWD}" "$1" "${3:-}" \
    | TMPDIR="${HT}" CLAUDE_CONFIG_DIR="${HT}/released-config" \
      bash "${ROOT}/tests/fixtures/legacy-luciazero-verify.sh" "$2" 2>/dev/null || OH_RC=$?
}
old_stop() { # old_stop <session> <want rc> <failure message>
  old_hook "$1" stop
  [ "${OH_RC}" = "$2" ] || { rm -rf "${HT}"; fail "$3 (released copy, session $1 stop: rc=${OH_RC}, want $2)"; }
}
SESS_CWD=/hook/test/sessions-released
old_hook O edit "${SESS_EDIT}"
sess_stop N 2 "an edit the released copy recorded did not nudge a session on this copy"
sess_stop N 0 "the nudge for the released copy's edit is not one-shot"
old_stop O 2 "this copy's nudge used up the released copy's"
old_stop O 0 "the released copy's nudge is not one-shot beside this copy"
sess_hook N edit "${SESS_EDIT}"
old_stop O 2 "an edit under this copy did not re-arm the released copy's nudge"
sess_stop N 2 "the released copy's nudge used up this copy's"
sess_hook N edit "${SESS_EDIT}"
old_hook O bash "${SESS_GREEN}"
sess_stop N 0 "a green run under the released copy did not cover this copy's edit"
old_hook O edit "${SESS_EDIT}"
sess_hook N bash "${SESS_GREEN}"
old_stop O 0 "a green run under this copy did not cover the released copy's edit"
sess_hook N edit "${SESS_EDIT}"
old_stop O 2 "an edit under this copy after a green run did not arm the released copy"
# The released copy stamps last_verify when its run finishes and records no
# start, so which run saw newer code is unknown and the overlap guard stands
# aside: a run on this copy that finishes after it is recorded, red or green.
for ENDS in '0 1 fail' '1 0 ok'; do
  read -r OLD_EXIT NEW_EXIT WANT <<<"${ENDS}"
  sess_hook N bash-start "${SESS_LATE}"
  old_hook O bash ',"tool_input":{"command":"./test.sh"},"tool_response":{"exit_code":'"${OLD_EXIT}"'}'
  sess_hook N bash "${SESS_LATE}"',"tool_response":{"exit_code":'"${NEW_EXIT}"'}'
  if [ "$(cat "$(sess_state)/last_verify")" != "${WANT}" ]; then
    rm -rf "${HT}"; fail "a run that started before the released copy's run finished was not recorded (want ${WANT})"
  fi
done
# exact-match mode: with LUCIAZERO_VERIFY_CMD set, reading the test file is no
# longer counted as running it (regression: `cat test.sh` flipped state green)
EJ='{"cwd":"/hook/test/exact"}'
echo "${EJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
echo '{"cwd":"/hook/test/exact","tool_input":{"command":"cat test.sh"},"tool_response":{"exit_code":0}}' \
  | TMPDIR="${HT}" LUCIAZERO_VERIFY_CMD='./test.sh' "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
RC=0; echo "${EJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>/dev/null || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${HT}"; fail "exact-match mode counted 'cat test.sh' as a verify run (rc=${RC})"; }
echo '{"cwd":"/hook/test/exact","tool_input":{"command":"./test.sh -q"},"tool_response":{"exit_code":0}}' \
  | TMPDIR="${HT}" LUCIAZERO_VERIFY_CMD='./test.sh' "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
RC=0; echo "${EJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}"; fail "exact-match mode missed the real verify command (rc=${RC})"; }
echo "ok  enforcement-pack hook state machine"

# 4c1. a repository cannot reconfigure the hook from its committed settings:
# a widened regex must not count an arbitrary command as a verify run, a
# committed strict command must not be executed at stop, and the personal
# settings.local.json must keep working.
mktmp PEJ_DIR
mkdir -p "${PEJ_DIR}/.claude"
cat > "${PEJ_DIR}/.claude/settings.json" <<'JSON'
{"env": {"LUCIAZERO_VERIFY_REGEX": ".", "LUCIAZERO_STRICT_VERIFY_CMD": "touch strict-ran"}}
JSON
PEJ="$(printf '{"cwd":"%s"}' "${PEJ_DIR}")"
echo "${PEJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
printf '{"cwd":"%s","tool_input":{"command":"echo hello"},"tool_response":{"exit_code":0}}\n' "${PEJ_DIR}" \
  | TMPDIR="${HT}" LUCIAZERO_VERIFY_REGEX='.' "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
RC=0; PERR="$(echo "${PEJ}" | TMPDIR="${HT}" \
  LUCIAZERO_VERIFY_REGEX='.' LUCIAZERO_STRICT_VERIFY_CMD="touch ${PEJ_DIR}/strict-ran" \
  "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>&1)" || RC=$?
[ "${RC}" = 2 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}"; fail "project-scoped verify regex still counted 'echo hello' as a verify run (rc=${RC})"; }
if grep -q 'Strict verify gate' <<<"${PERR}"; then
  rm -rf "${HT}" "${PEJ_DIR}"; fail "project-scoped strict command reached the strict gate"
fi
if [ -e "${PEJ_DIR}/strict-ran" ]; then
  rm -rf "${HT}" "${PEJ_DIR}"; fail "project-scoped strict command was executed at stop"
fi
SESS_OUT="$(echo "${PEJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" session)"
grep -q 'LUCIAZERO_VERIFY_REGEX' <<<"${SESS_OUT}" \
  || { rm -rf "${HT}" "${PEJ_DIR}"; fail "SessionStart did not warn about the committed LUCIAZERO_* env block"; }
# the lookup runs on every Bash call, so a repository must not be able to hang
# it (fifo) or make it chew a huge file: both refuse the knobs, neither blocks
rm -f "${PEJ_DIR}/.claude/settings.json"
# timeout(1) is not on stock macOS; without it a regressed guard would hang the
# suite forever instead of failing it, so skip rather than risk that
if command -v timeout >/dev/null 2>&1; then
  mkfifo "${PEJ_DIR}/.claude/settings.json"
  RC=0; timeout 10 env TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" session \
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
  "${ROOT}/claude/hooks/luciazero-verify.cjs" session)"
grep -q 'LUCIAZERO_STRICT_VERIFY_CMD' <<<"${SESS_OUT}" \
  || { rm -rf "${HT}" "${PEJ_DIR}"; fail "an oversized settings.json was parsed instead of refused"; }
# LUCIAZERO_VERIFY_CMD normally tightens matching, but from committed scope it
# is a false-green lever: point it at `echo` and `echo hello` counts as a verify
echo '{"env": {"LUCIAZERO_VERIFY_CMD": "echo"}}' > "${PEJ_DIR}/.claude/settings.json"
echo "${PEJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
printf '{"cwd":"%s","tool_input":{"command":"echo hello"},"tool_response":{"exit_code":0}}\n' "${PEJ_DIR}" \
  | TMPDIR="${HT}" LUCIAZERO_VERIFY_CMD='echo' "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
RC=0; echo "${PEJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 2 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}"; fail "project-scoped LUCIAZERO_VERIFY_CMD made 'echo hello' a verify run (rc=${RC})"; }
# LUCIAZERO_DOC_REGEX='.*' would mark every edit as documentation, so nothing is
# ever unverified and the stop hook never nudges again
echo '{"env": {"LUCIAZERO_DOC_REGEX": ".*"}}' > "${PEJ_DIR}/.claude/settings.json"
printf '{"cwd":"%s","tool_input":{"file_path":"%s/app.py"}}\n' "${PEJ_DIR}" "${PEJ_DIR}" \
  | TMPDIR="${HT}" LUCIAZERO_DOC_REGEX='.*' "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
RC=0; echo "${PEJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 2 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}"; fail "project-scoped LUCIAZERO_DOC_REGEX hid a code edit from the stop hook (rc=${RC})"; }
# Claude Code merges project settings from the repository ROOT, and a session's
# cwd is often a subdirectory — the refusal must walk up, not look only at cwd
SUB="${PEJ_DIR}/packages/api"
mkdir -p "${SUB}"
echo '{"env": {"LUCIAZERO_VERIFY_REGEX": "."}}' > "${PEJ_DIR}/.claude/settings.json"
SUBJ="$(printf '{"cwd":"%s"}' "${SUB}")"
echo "${SUBJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
printf '{"cwd":"%s","tool_input":{"command":"echo hello"},"tool_response":{"exit_code":0}}\n' "${SUB}" \
  | TMPDIR="${HT}" LUCIAZERO_VERIFY_REGEX='.' "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
RC=0; echo "${SUBJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 2 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}"; fail "a root .claude/settings.json was bypassed from a subdirectory (rc=${RC})"; }
rm -rf "${PEJ_DIR}/packages"
# personal scope is untouched: same repo, keys only in settings.local.json
rm -f "${PEJ_DIR}/.claude/settings.json"
echo '{"env": {"LUCIAZERO_VERIFY_REGEX": "."}}' > "${PEJ_DIR}/.claude/settings.local.json"
echo "${PEJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
printf '{"cwd":"%s","tool_input":{"command":"echo hello"},"tool_response":{"exit_code":0}}\n' "${PEJ_DIR}" \
  | TMPDIR="${HT}" LUCIAZERO_VERIFY_REGEX='.' "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
RC=0; echo "${PEJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 0 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}"; fail "personal settings.local.json regex override was refused too (rc=${RC})"; }
# channel dedupe is decided by the running copy's own path, never by
# LUCIAZERO_CHANNEL: an env-driven dedupe let a repository label the CLASSIC
# hook "plugin" so it stood itself down, disabling enforcement entirely
mktmp CHD
mkdir -p "${CHD}/cfg/hooks" "${CHD}/proj"
cp "${ROOT}/claude/hooks/luciazero-verify.cjs" "${CHD}/cfg/hooks/luciazero-verify.cjs"
chmod +x "${CHD}/cfg/hooks/luciazero-verify.cjs"
printf '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"%s/cfg/hooks/luciazero-verify.cjs stop"}]}]}}\n' \
  "${CHD}" > "${CHD}/cfg/settings.json"
CHJ="$(printf '{"cwd":"%s/proj"}' "${CHD}")"
# the classic copy must enforce even when a repo hands it the plugin label
echo "${CHJ}" | TMPDIR="${HT}" CLAUDE_CONFIG_DIR="${CHD}/cfg" LUCIAZERO_CHANNEL=plugin \
  "${CHD}/cfg/hooks/luciazero-verify.cjs" edit
RC=0; echo "${CHJ}" | TMPDIR="${HT}" CLAUDE_CONFIG_DIR="${CHD}/cfg" LUCIAZERO_CHANNEL=plugin \
  "${CHD}/cfg/hooks/luciazero-verify.cjs" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 2 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}" "${CHD}"; fail "LUCIAZERO_CHANNEL=plugin made the classic hook stand itself down (rc=${RC})"; }
# a copy running from anywhere else still stands down when classic is wired;
# the classic stop above fired the one-shot nudge, which alone would make this
# stop exit 0, so re-arm it first
rm -rf "${HT}/luciazero-verify-state-$(id -u)/"*/nudged-sessions
RC=0; echo "${CHJ}" | TMPDIR="${HT}" CLAUDE_CONFIG_DIR="${CHD}/cfg" \
  "${ROOT}/claude/hooks/luciazero-verify.cjs" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 0 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}" "${CHD}"; fail "a non-classic copy did not stand down beside a wired classic install (rc=${RC})"; }
# a repository that points CLAUDE_CONFIG_DIR at its own "wired classic install"
# must not make every copy stand down — the refusal drops that key first
mkdir -p "${CHD}/evil-cfg/hooks" "${CHD}/repo/.claude" "${CHD}/home"
cp "${ROOT}/claude/hooks/luciazero-verify.cjs" "${CHD}/evil-cfg/hooks/luciazero-verify.cjs"
chmod +x "${CHD}/evil-cfg/hooks/luciazero-verify.cjs"
printf '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"%s/evil-cfg/hooks/luciazero-verify.cjs stop"}]}]}}\n' \
  "${CHD}" > "${CHD}/evil-cfg/settings.json"
printf '{"env": {"CLAUDE_CONFIG_DIR": "%s/evil-cfg"}}\n' "${CHD}" > "${CHD}/repo/.claude/settings.json"
EVJ="$(printf '{"cwd":"%s/repo"}' "${CHD}")"
echo "${EVJ}" | TMPDIR="${HT}" HOME="${CHD}/home" CLAUDE_CONFIG_DIR="${CHD}/evil-cfg" \
  "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
RC=0; echo "${EVJ}" | TMPDIR="${HT}" HOME="${CHD}/home" CLAUDE_CONFIG_DIR="${CHD}/evil-cfg" \
  "${ROOT}/claude/hooks/luciazero-verify.cjs" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 2 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}" "${CHD}"; fail "a committed CLAUDE_CONFIG_DIR made the hook stand down (rc=${RC})"; }
# the nastier shape of the same trick: CLAUDE_CONFIG_DIR points at the
# repository's OWN .claude, so a scanner that skips "the config directory"
# skips the very file declaring the key, and the classic install is in-repo
mkdir -p "${CHD}/self/.claude/hooks" "${CHD}/self-home"
cp "${ROOT}/claude/hooks/luciazero-verify.cjs" "${CHD}/self/.claude/hooks/luciazero-verify.cjs"
chmod +x "${CHD}/self/.claude/hooks/luciazero-verify.cjs"
printf '{"env": {"CLAUDE_CONFIG_DIR": "%s/self/.claude"}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "%s/self/.claude/hooks/luciazero-verify.cjs stop"}]}]}}\n' \
  "${CHD}" "${CHD}" > "${CHD}/self/.claude/settings.json"
SELFJ="$(printf '{"cwd":"%s/self"}' "${CHD}")"
echo "${SELFJ}" | TMPDIR="${HT}" HOME="${CHD}/self-home" CLAUDE_CONFIG_DIR="${CHD}/self/.claude" \
  "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
RC=0; echo "${SELFJ}" | TMPDIR="${HT}" HOME="${CHD}/self-home" CLAUDE_CONFIG_DIR="${CHD}/self/.claude" \
  "${ROOT}/claude/hooks/luciazero-verify.cjs" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 2 ] \
  || { rm -rf "${HT}" "${PEJ_DIR}" "${CHD}"; fail "CLAUDE_CONFIG_DIR pointed at the repo's own .claude disabled the hook (rc=${RC})"; }
# a classic install from before the Node port is wired to luciazero-verify.sh;
# it still enforces, so this copy must stand down beside it -- but only when it
# can run (executable) and is actually wired
mkdir -p "${CHD}/legacy/hooks" "${CHD}/legacy-proj" "${CHD}/none"
printf '#!/bin/sh\nexit 0\n' > "${CHD}/legacy/hooks/luciazero-verify.sh"
LGJ="$(printf '{"cwd":"%s/legacy-proj"}' "${CHD}")"
echo "${LGJ}" | TMPDIR="${HT}" CLAUDE_CONFIG_DIR="${CHD}/none" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
legacy_rc() { # legacy_rc <settings.json body>: stop exit code beside a legacy install
  printf '%s\n' "$1" > "${CHD}/legacy/settings.json"
  LG_RC=0; echo "${LGJ}" | TMPDIR="${HT}" CLAUDE_CONFIG_DIR="${CHD}/legacy" \
    "${ROOT}/claude/hooks/luciazero-verify.cjs" stop >/dev/null 2>&1 || LG_RC=$?
  rm -rf "${HT}/luciazero-verify-state-$(id -u)/"*/nudged-sessions
}
LGW="$(printf '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"%s/legacy/hooks/luciazero-verify.sh stop"}]}]}}' "${CHD}")"
chmod -x "${CHD}/legacy/hooks/luciazero-verify.sh"
legacy_rc "${LGW}"
[ "${LG_RC}" = 2 ] || { rm -rf "${HT}" "${PEJ_DIR}" "${CHD}"; fail "a legacy hook that cannot run made this copy stand down (rc=${LG_RC})"; }
chmod +x "${CHD}/legacy/hooks/luciazero-verify.sh"
legacy_rc '{"hooks":{}}'
[ "${LG_RC}" = 2 ] || { rm -rf "${HT}" "${PEJ_DIR}" "${CHD}"; fail "an unwired legacy hook made this copy stand down (rc=${LG_RC})"; }
legacy_rc "${LGW}"
[ "${LG_RC}" = 0 ] || { rm -rf "${HT}" "${PEJ_DIR}" "${CHD}"; fail "this copy did not stand down beside a wired legacy luciazero-verify.sh (rc=${LG_RC})"; }
rm -rf "${CHD}"
rm -rf "${PEJ_DIR}"
echo "ok  committed settings cannot reconfigure the hook"

# 4c1a. PROJECT scope only: the walk must stop before the user's own settings.
# A global ~/.claude/settings.json and anything above the repository root belong
# to the user; refusing them would break the documented way to configure this.
mktmp GS
mkdir -p "${GS}/home/.claude" "${GS}/home/proj" \
         "${GS}/outer/.claude" "${GS}/outer/repo/.git" "${GS}/outer/repo/sub"
echo '{"env": {"LUCIAZERO_VERIFY_REGEX": "."}}' > "${GS}/home/.claude/settings.json"
echo '{"env": {"LUCIAZERO_VERIFY_REGEX": "."}}' > "${GS}/outer/.claude/settings.json"
scope_keeps_regex() { # scope_keeps_regex <failure message> <home> <cwd>
  SK_J="$(printf '{"cwd":"%s"}' "$3")"
  echo "${SK_J}" | TMPDIR="${HT}" HOME="$2" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
  printf '{"cwd":"%s","tool_input":{"command":"echo hello"},"tool_response":{"exit_code":0}}\n' "$3" \
    | TMPDIR="${HT}" HOME="$2" LUCIAZERO_VERIFY_REGEX='.' \
      "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
  SK_RC=0
  echo "${SK_J}" | TMPDIR="${HT}" HOME="$2" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop \
    >/dev/null 2>&1 || SK_RC=$?
  [ "${SK_RC}" = 0 ] || { rm -rf "${HT}" "${GS}"; fail "$1 (rc=${SK_RC})"; }
}
scope_keeps_regex "the user's global ~/.claude/settings.json was refused as project scope" \
  "${GS}/home" "${GS}/home/proj"
scope_keeps_regex "a settings file above the repository root was refused" \
  "${GS}/nonexistent-home" "${GS}/outer/repo/sub"
rm -rf "${GS}"
echo "ok  refusal stays inside project scope"

# 4c1b. the suite recomputes the hooks' md5 state keys in inline python3; a
# FIPS-enforcing python3 raises on a bare md5() call. The hooks themselves
# are Node, and their sha256 fallback when md5 is refused is proven in
# tests/node/hooks.test.js.
for HFILE in test.sh "${DISCIPLINE_GATES[@]}" "${FAST_GATES[@]}" "${FULL_GATES[@]}"; do
  if HITS="$(grep -n 'hashlib\.md5(' "${ROOT}/${HFILE}")" && grep -qv 'usedforsecurity=False' <<<"${HITS}"; then
    fail "${HFILE} calls hashlib.md5() without usedforsecurity=False (breaks under FIPS)"
  fi
done
echo "ok  the suite's md5 state keys are FIPS-safe"

# 4c2. strict gate: runs the configured command at stop, blocks on red quoting
# the failure, fast-paths on green state, and degrades to the nudge on timeout
mktmp SPJ
SJ="$(printf '{"cwd":"%s"}' "${SPJ}")"
echo "${SJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
RC=0; ERR="$(echo "${SJ}" | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD='echo boom; exit 1' \
  "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>&1 >/dev/null)" || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${HT}" "${SPJ}"; fail "strict gate did not block a red verify (rc=${RC})"; }
grep -q 'Strict verify gate' <<<"${ERR}" || { rm -rf "${HT}" "${SPJ}"; fail "strict gate blocked without its message: ${ERR}"; }
grep -q 'boom' <<<"${ERR}" || { rm -rf "${HT}" "${SPJ}"; fail "strict gate did not quote the failing output: ${ERR}"; }
RC=0; printf '{"cwd":"%s","stop_hook_active":true}' "${SPJ}" \
  | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD='exit 1' "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}" "${SPJ}"; fail "strict gate re-blocked its own continuation (rc=${RC})"; }
STRICT_GREEN="echo run >> ${SPJ}/runs"
RC=0; echo "${SJ}" | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD="${STRICT_GREEN}" \
  "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}" "${SPJ}"; fail "strict gate blocked a green verify (rc=${RC})"; }
# state is green from THAT command: the same command must fast-path (not re-run)
RC=0; echo "${SJ}" | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD="${STRICT_GREEN}" \
  "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}" "${SPJ}"; fail "strict gate blocked despite green state (rc=${RC})"; }
[ "$(wc -l < "${SPJ}/runs" | tr -d ' ')" = 1 ] \
  || { rm -rf "${HT}" "${SPJ}"; fail "strict gate re-ran the command despite its own green state"; }
# fail-open: a hanging verify degrades to the ordinary one-shot nudge, not a block
echo "${SJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
RC=0; ERR="$(echo "${SJ}" | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD='sleep 3' LUCIAZERO_STRICT_TIMEOUT=1 \
  "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>&1 >/dev/null)" || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${HT}" "${SPJ}"; fail "strict timeout did not degrade to the nudge (rc=${RC})"; }
grep -q 'Doctrine rule 1' <<<"${ERR}" || { rm -rf "${HT}" "${SPJ}"; fail "strict timeout produced the wrong message: ${ERR}"; }
# fail-open: command not found (shell 127) is an internal error, not a red
# verify — must degrade to the nudge, never fabricate "RED" evidence
echo "${SJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
RC=0; ERR="$(echo "${SJ}" | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD='./no-such-cmd-xyz.sh' \
  "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>&1 >/dev/null)" || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${HT}" "${SPJ}"; fail "strict missing-command did not degrade to the nudge (rc=${RC})"; }
grep -q 'Doctrine rule 1' <<<"${ERR}" || { rm -rf "${HT}" "${SPJ}"; fail "strict missing-command message wrong: ${ERR}"; }
! grep -q 'Strict verify gate' <<<"${ERR}" || { rm -rf "${HT}" "${SPJ}"; fail "strict missing-command fabricated a RED verdict: ${ERR}"; }
# a broad-regex false green (`cat test.sh` exits 0) must NOT disarm the gate:
# the fast path only trusts a green the strict command itself produced
echo "${SJ}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
printf '{"cwd":"%s","tool_input":{"command":"cat test.sh"},"tool_response":{"exit_code":0}}' "${SPJ}" \
  | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
RC=0; ERR="$(echo "${SJ}" | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD='echo poisoned; exit 1' \
  "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>&1 >/dev/null)" || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${HT}" "${SPJ}"; fail "broad-regex green disarmed the strict gate (rc=${RC})"; }
grep -q 'Strict verify gate' <<<"${ERR}" || { rm -rf "${HT}" "${SPJ}"; fail "strict gate did not run past the poisoned green: ${ERR}"; }
# unparseable stdin: the strict gate must not run a command on guessed state
RC=0; printf 'not json' | TMPDIR="${HT}" LUCIAZERO_STRICT_VERIFY_CMD='echo boom; exit 1' \
  "${ROOT}/claude/hooks/luciazero-verify.cjs" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}" "${SPJ}"; fail "strict gate ran on unparseable stdin (rc=${RC})"; }
rm -rf "${SPJ}"
echo "ok  strict verify gate"

# 4c3. session subcommand: silent without a relay, points at one when
# present, stale wording past the threshold, fails open on garbage stdin
mktmp SD
OUT="$(printf '{"cwd":"%s"}' "${SD}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" session)"
[ -z "${OUT}" ] || { rm -rf "${HT}" "${SD}"; fail "session hook spoke without a relay: ${OUT}"; }
echo '{}' > "${SD}/LUCIA_RELAY.json"
OUT="$(printf '{"cwd":"%s"}' "${SD}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" session)"
grep -q 'LUCIA_RELAY.json exists' <<<"${OUT}" || { rm -rf "${HT}" "${SD}"; fail "session hook missed the relay: ${OUT}"; }
touch -t 202001010000 "${SD}/LUCIA_RELAY.json"
OUT="$(printf '{"cwd":"%s"}' "${SD}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" session)"
grep -q 'stale' <<<"${OUT}" || { rm -rf "${HT}" "${SD}"; fail "session hook missed staleness: ${OUT}"; }
rm -f "${SD}/LUCIA_RELAY.json"
echo legacy > "${SD}/HANDOFF.md"
OUT="$(printf '{"cwd":"%s"}' "${SD}" | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" session)"
grep -q 'Legacy HANDOFF.md' <<<"${OUT}" || { rm -rf "${HT}" "${SD}"; fail "session hook missed legacy migration: ${OUT}"; }
RC=0; printf 'not json' | TMPDIR="${HT}" "${ROOT}/claude/hooks/luciazero-verify.cjs" session >/dev/null 2>&1 || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${HT}" "${SD}"; fail "session hook not fail-open on garbage stdin (rc=${RC})"; }
rm -rf "${HT}" "${SD}"
echo "ok  session relay pointer"

# 4c5. discipline stats: stop outcomes logged to the config dir, capped, and
# the learning-layer files survive uninstall
mktmp SC
mktmp STMP
SHK="${ROOT}/claude/hooks/luciazero-verify.cjs"
SPJ1="${STMP}/proj"; SPJ2="${STMP}/boom"; SPJ3="${STMP}/third"; SPJ4="${STMP}/timed"
mkdir -p "${SPJ1}" "${SPJ2}" "${SPJ3}" "${SPJ4}"
# clean stop (no edits) -> stop-clean
printf '{"cwd": "%s"}' "${SPJ1}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" stop \
  || fail "clean stop exited non-zero"
python3 - "${SC}/luciazero-stats.log" <<'PY' || fail "stats missing schema-v3 clean record"
import json, sys
row = json.loads(open(sys.argv[1]).read().splitlines()[-1])
assert row["schema"] == 3 and row["event"] == "stop-clean"
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
# A green verify that follows a green with no code edit between them is
# redundant (schema 3). Green after the red above is the fix landing (not
# redundant); green again straight after is (1); green after an edit is not.
# The responses carry the harness's real Bash shape, which has no exit code:
# PostToolUse itself means exit 0 (a non-zero exit fires PostToolUseFailure),
# while an interrupted command proves nothing and is neither green nor red.
verify_bash() { # verify_bash <tool_use_id> <tool_response json>
  VG='{"cwd":"'"${SPJ4}"'","session_id":"telemetry-a","tool_use_id":"'"$1"'","tool_input":{"command":"./test.sh --fast"},"tool_response":'"$2"'}'
  printf '%s' "${VG}" | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" bash-start
  sleep 0.02
  printf '%s' "${VG}" | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" bash
}
HARNESS_GREEN='{"stdout":"PASS","stderr":"","interrupted":false,"isImage":false}'
verify_bash bash-3 "${HARNESS_GREEN}"
verify_bash bash-4 "${HARNESS_GREEN}"
printf '{"cwd":"%s","session_id":"telemetry-a","tool_input":{"file_path":"%s/a.py"}}' "${SPJ4}" "${SPJ4}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" edit
verify_bash bash-5 "${HARNESS_GREEN}"
LV="${STMP}/luciazero-verify-state-$(id -u)/$(python3 -c 'import hashlib,sys; print(hashlib.md5(sys.argv[1].encode(), usedforsecurity=False).hexdigest()[:12])' "${SPJ4}")/last_verify"
[ "$(cat "${LV}")" = ok ] || fail "a completed Bash response without an exit code was not read as green (got '$(cat "${LV}")')"
verify_bash bash-6 '{"stdout":"","stderr":"","interrupted":true,"isImage":false}'
[ "$(cat "${LV}")" = ran ] || fail "an interrupted Bash response was read as '$(cat "${LV}")', not ran"
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
assert t["bash_count"] == 6 and t["verify_count"] == 6 and t["skill_count"] == 2
assert t["redundant_green_count"] == 1, t
assert 60 <= t["verify_ms"] <= t["bash_ms"], t
assert "command" not in json.dumps(t) and "done" not in json.dumps(t)
PY
! grep -R -q 'secret-marker' "${STMP}/luciazero-verify-state-$(id -u)" \
  || fail "raw verify command leaked into hook state"
# A turn stays open from its first prompt until a stop lets it end. The
# harness delivers a background task's completion as another UserPromptSubmit;
# such a prompt inside an open turn must keep the counters and turn_start_ms,
# a stop that blocks (nudge, strict red) keeps the turn open, and a clean stop
# closes it so the next prompt starts fresh. A session start clears a marker
# a crashed session left behind, except a compaction, which can be mid-turn.
tdir() { # tdir <session-id> -> this session's telemetry directory under STMP
  python3 - "${STMP}" "${SPJ4}" "$1" <<'PY'
import hashlib, os, sys
tmp, cwd, session = sys.argv[1:]
key = hashlib.md5(cwd.encode(), usedforsecurity=False).hexdigest()[:12]
print(os.path.join(tmp, f"luciazero-verify-state-{os.getuid()}", key, "telemetry",
                   hashlib.sha256(session.encode()).hexdigest()[:16]))
PY
}
turn_hook() { # turn_hook <session-id> <mode> [extra-json-fields]
  printf '{"cwd":"%s","session_id":"%s"%s}' "${SPJ4}" "$1" "${3:-}" \
    | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" "$2"
}
# 1. prompt -> Bash + Skill -> prompt (notification): everything kept
turn_hook turn-1 prompt
TD1="$(tdir turn-1)"; T1_START="$(cat "${TD1}/turn_start_ms")"
turn_hook turn-1 bash-start ',"tool_use_id":"t1-bash","tool_input":{"command":"echo hi"}'
turn_hook turn-1 bash ',"tool_use_id":"t1-bash","tool_input":{"command":"echo hi"},"tool_response":{"exit_code":0}'
turn_hook turn-1 skill ',"tool_use_id":"t1-skill","tool_input":{"skill":"done"}'
sleep 0.01
turn_hook turn-1 prompt
[ "$(cat "${TD1}/turn_start_ms")" = "${T1_START}" ] || fail "a prompt inside an open turn reset turn_start_ms"
[ "$(find "${TD1}/bash_count" -type f | wc -l | tr -d ' ')" = 1 ] || fail "a prompt inside an open turn dropped the Bash counter"
[ "$(find "${TD1}/skill_count" -type f | wc -l | tr -d ' ')" = 1 ] || fail "a prompt inside an open turn dropped the skill counter"
# 2. prompt -> clean stop -> prompt: the next turn starts fresh
turn_hook turn-1 stop >/dev/null || fail "clean stop of turn-1 exited non-zero"
[ ! -f "${TD1}/turn_open" ] || fail "a clean stop left the turn open"
python3 -c 'import json,sys; t=json.loads(open(sys.argv[1]).read().splitlines()[-1])["telemetry"]; assert t["bash_count"] == 1 and t["skill_count"] == 1, t' \
  "${SC}/luciazero-stats.log" || fail "the stop row lost counters gathered before the notification"
sleep 0.01
turn_hook turn-1 prompt
[ "$(cat "${TD1}/turn_start_ms")" != "${T1_START}" ] || fail "a prompt after a clean stop kept the old turn_start_ms"
[ ! -d "${TD1}/bash_count" ] || fail "a prompt after a clean stop kept the old counters"
turn_hook turn-1 stop >/dev/null
# 3a. prompt -> edit -> nudge (rc 2) -> prompt (notification): kept
turn_hook turn-2 prompt
TD2="$(tdir turn-2)"; T2_START="$(cat "${TD2}/turn_start_ms")"
turn_hook turn-2 edit ',"tool_input":{"file_path":"'"${SPJ4}"'/b.py"}'
set +e; turn_hook turn-2 stop 2>/dev/null; RC=$?; set -e
[ "${RC}" -eq 2 ] || fail "turn-2 stop: want nudge rc 2, got ${RC}"
sleep 0.01
turn_hook turn-2 prompt
[ "$(cat "${TD2}/turn_start_ms")" = "${T2_START}" ] || fail "a prompt after a nudge reset the turn"
# the continuation's stop (stop_hook_active) ends the turn without a row
turn_hook turn-2 stop ',"stop_hook_active":true' >/dev/null
[ ! -f "${TD2}/turn_open" ] || fail "the stop after a nudge continuation left the turn open"
# 3b. prompt -> edit -> strict red (rc 2) -> prompt (notification): kept
turn_hook turn-3 prompt
TD3="$(tdir turn-3)"; T3_START="$(cat "${TD3}/turn_start_ms")"
turn_hook turn-3 edit ',"tool_input":{"file_path":"'"${SPJ4}"'/c.py"}'
set +e
printf '{"cwd":"%s","session_id":"turn-3"}' "${SPJ4}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" LUCIAZERO_STRICT_VERIFY_CMD="exit 3" "${SHK}" stop 2>/dev/null
RC=$?
set -e
[ "${RC}" -eq 2 ] || fail "turn-3 stop: want strict-block rc 2, got ${RC}"
sleep 0.01
turn_hook turn-3 prompt
[ "$(cat "${TD3}/turn_start_ms")" = "${T3_START}" ] || fail "a prompt after a strict block reset the turn"
[ -f "${TD3}/turn_open" ] || fail "a strict block closed the turn"
# 4. a session start clears a marker a crashed session left, unless it is a
# compaction, which happens inside a live session
turn_hook turn-3 session ',"source":"compact"' >/dev/null
[ -f "${TD3}/turn_open" ] || fail "a compaction start closed an open turn"
turn_hook turn-3 session ',"source":"startup"' >/dev/null
[ ! -f "${TD3}/turn_open" ] || fail "a session start kept a stale turn marker"
sleep 0.01
turn_hook turn-3 prompt
[ "$(cat "${TD3}/turn_start_ms")" != "${T3_START}" ] || fail "the first prompt after a session start was taken for a notification"
# A hostile pre-created state symlink must fail open without touching its target.
mktmp EVILTMP; mktmp EVILTARGET
echo sentinel > "${EVILTARGET}/keep"
ln -s "${EVILTARGET}" "${EVILTMP}/luciazero-verify-state-$(id -u)"
EVILKEY="$(printf '%s' "${SPJ4}" | python3 -c 'import hashlib,sys; print(hashlib.md5(sys.stdin.buffer.read(), usedforsecurity=False).hexdigest()[:12])')"
mkdir -p "${EVILTARGET}/${EVILKEY}"
echo ok > "${EVILTARGET}/${EVILKEY}/last_verify"
printf '{"cwd":"%s","session_id":"evil"}' "${SPJ4}" \
  | env TMPDIR="${EVILTMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" prompt
grep -qx sentinel "${EVILTARGET}/keep" || fail "hook followed hostile state symlink"
ESL="$(printf '{"workspace":{"current_dir":"%s"}}' "${SPJ4}" \
  | env TMPDIR="${EVILTMP}" "${ROOT}/claude/hooks/luciazero-statusline.cjs")"
grep -q 'no verify yet' <<<"${ESL}" \
  || fail "statusline trusted forged state through hostile symlink: ${ESL}"
rm -rf "${EVILTMP}" "${EVILTARGET}"
# a config directory may sit inside a project whose package.json declares ES
# modules; copied there, both programs must still run as CommonJS
mktmp ESM; mktmp ESM_TMP
mkdir -p "${ESM}/proj/.claude/hooks"
echo '{"type": "module"}' > "${ESM}/proj/package.json"
cp "${ROOT}/claude/hooks/luciazero-verify.cjs" "${ROOT}/claude/hooks/luciazero-statusline.cjs" \
  "${ESM}/proj/.claude/hooks/"
ESMJ="$(printf '{"cwd":"%s/proj"}' "${ESM}")"
RC=0; echo "${ESMJ}" | TMPDIR="${ESM_TMP}" CLAUDE_CONFIG_DIR="${ESM}/proj/.claude" \
  node "${ESM}/proj/.claude/hooks/luciazero-verify.cjs" edit || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${ESM}" "${ESM_TMP}"; fail "the hook did not run inside a type=module project (rc=${RC})"; }
ESL="$(printf '{"workspace":{"current_dir":"%s/proj"}}' "${ESM}" \
  | TMPDIR="${ESM_TMP}" node "${ESM}/proj/.claude/hooks/luciazero-statusline.cjs" 2>&1)" \
  || { rm -rf "${ESM}" "${ESM_TMP}"; fail "the statusline did not run inside a type=module project: ${ESL}"; }
grep -q 'unverified' <<<"${ESL}" \
  || { rm -rf "${ESM}" "${ESM_TMP}"; fail "inside a type=module project the statusline missed the tracked edit: ${ESL}"; }
RC=0; echo "${ESMJ}" | TMPDIR="${ESM_TMP}" CLAUDE_CONFIG_DIR="${ESM}/proj/.claude" \
  node "${ESM}/proj/.claude/hooks/luciazero-verify.cjs" stop >/dev/null 2>&1 || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${ESM}" "${ESM_TMP}"; fail "inside a type=module project the stop hook did not nudge (rc=${RC})"; }
rm -rf "${ESM}" "${ESM_TMP}"
# rotation: >500 lines shrinks to <=301 on the next event
python3 -c 'import sys; open(sys.argv[1], "w").write("2026-01-01T00:00 stop-clean x\n" * 600)' "${SC}/luciazero-stats.log"
printf '{"cwd": "%s"}' "${SPJ3}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" stop >/dev/null 2>&1 || true
SL="$(wc -l < "${SC}/luciazero-stats.log" | tr -d ' ')"
[ "${SL}" -le 301 ] || fail "stats log not rotated (${SL} lines)"
# rotation never writes through a name planted beside the log (roadmap R21)
python3 -c 'import sys; open(sys.argv[1], "w").write("2026-01-01T00:00 stop-clean x\n" * 600)' "${SC}/luciazero-stats.log"
echo sentinel > "${STMP}/rotation-target"
ln -s "${STMP}/rotation-target" "${SC}/luciazero-stats.log.tmp"
printf '{"cwd": "%s"}' "${SPJ3}" \
  | env TMPDIR="${STMP}" CLAUDE_CONFIG_DIR="${SC}" "${SHK}" stop >/dev/null 2>&1 || true
grep -qx sentinel "${STMP}/rotation-target" || fail "stats rotation wrote through a planted .tmp symlink"
[ ! -L "${SC}/luciazero-stats.log" ] || fail "stats rotation replaced the log with the planted symlink"
SL="$(wc -l < "${SC}/luciazero-stats.log" | tr -d ' ')"
[ "${SL}" -le 301 ] || fail "stats log not rotated beside a planted .tmp (${SL} lines)"
rm -f "${SC}/luciazero-stats.log.tmp" "${STMP}/rotation-target"
# uninstall keeps learned data and says so
touch "${SC}/luciazero-heuristics.md" "${SC}/CLAUDE.md"
service_guard  # the first uninstall.sh of the run: prove the guard is alive
UOUT="$(CLAUDE_CONFIG_DIR="${SC}" "${ROOT}/uninstall.sh")"
grep -q 'kept luciazero-stats.log' <<<"${UOUT}" || fail "uninstall must keep + mention the stats log"
grep -q 'kept luciazero-heuristics.md' <<<"${UOUT}" || fail "uninstall must keep + mention the heuristics file"
{ [ -f "${SC}/luciazero-stats.log" ] && [ -f "${SC}/luciazero-heuristics.md" ]; } \
  || fail "uninstall deleted learned data"
rm -rf "${SC}" "${STMP}"
echo "ok  discipline stats log"

# 4c5b. discipline report: current + legacy schema, malformed input,
# time/project filters, JSON output, and evidence-qualified recommendations
if command -v node >/dev/null 2>&1; then
  mktmp DR
  cat > "${DR}/stats.log" <<'EOF'
{"schema":2,"timestamp":"2026-08-10T10:00:00+00:00","event":"stop-clean","project_id":"alpha1234567","project":"alpha","verify_mode":"exact","telemetry":{"turn_ms":1000,"bash_ms":300,"bash_count":1,"verify_count":1,"skill_count":0}}
{"schema":2,"timestamp":"2026-08-11T23:30:00-05:00","event":"nudge","project_id":"alpha1234567","project":"alpha","verify_mode":"regex","telemetry":{"turn_ms":2000,"bash_ms":500,"bash_count":2,"verify_count":1,"skill_count":1}}
{"schema":2,"timestamp":"2026-08-12T05:00:00+00:00","event":"strict-block","project_id":"beta12345678","project":"beta","verify_mode":"strict"}
{"schema":3,"timestamp":"2026-08-12T06:00:00+00:00","event":"stop-clean","project_id":"beta12345678","project":"beta","verify_mode":"exact","telemetry":{"turn_ms":4000,"bash_ms":1000,"bash_count":3,"verify_count":2,"skill_count":0,"verify_ms":700,"redundant_green_count":1}}
{"schema":3,"timestamp":"2026-08-12T07:00:00+00:00","event":"stop-clean","project_id":"beta12345678","project":"beta","verify_mode":"exact","telemetry":{"turn_ms":500,"bash_ms":100,"bash_count":1,"verify_count":0,"skill_count":0,"verify_ms":"garbled"}}
{"schema":4,"timestamp":"2026-08-12T08:00:00+00:00","event":"stop-clean","project_id":"beta12345678","project":"beta","verify_mode":"exact"}
2026-08-09T12:00:00 nudge legacy-repo
{malformed
EOF
  DJSON="$(node "${ROOT}/bin/discipline-report.js" --log "${DR}/stats.log" --days 30 --now 2026-08-12T12:00:00Z --json)" \
    || { rm -rf "${DR}"; fail "discipline JSON report exited red"; }
  printf '%s' "${DJSON}" | python3 -c '
import json, sys
d=json.load(sys.stdin)
# schema 2 and 3 rows are both read; a schema-3 row whose verify aggregates
# are missing or garbled still counts for everything else; an unknown schema
# (4) and the broken line are ignored, never guessed at
assert d["records"] == 6 and d["malformed_records_ignored"] == 2 and d["legacy_records"] == 1
assert d["outcomes"] == {"stop-clean": 3, "nudge": 2, "strict-block": 1}
assert d["verify_modes"]["regex"] == 1 and d["verify_modes"]["strict"] == 1
assert d["telemetry"] == {"measured_turns": 4, "turn_ms": 7500, "bash_ms": 1900,
                           "non_bash_ms": 5600, "bash_count": 7,
                           "verify_count": 4, "skill_count": 1,
                           "verify_measured_turns": 1, "verify_ms": 700,
                           "redundant_green_count": 1}, d["telemetry"]
assert d["recommendations"][0].startswith("Likely:")
assert any("redundant" in item or "no edit since the previous green" in item for item in d["recommendations"]), d["recommendations"]
' || { rm -rf "${DR}"; fail "discipline JSON report content wrong"; }
  DJSON="$(node "${ROOT}/bin/discipline-report.js" --log "${DR}/stats.log" --days 30 --now 2026-08-12T12:00:00Z --project alpha --json)"
  printf '%s' "${DJSON}" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["records"] == 2 and d["outcomes"]["nudge"] == 1' \
    || { rm -rf "${DR}"; fail "discipline project filter wrong"; }
  DOUT="$(node "${ROOT}/bin/luciazero.js" discipline --log "${DR}/stats.log" --days 30 --now 2026-08-12T12:00:00Z)"
  grep -q 'Luciazero Discipline Report' <<<"${DOUT}" \
    || { rm -rf "${DR}"; fail "discipline CLI route missing report"; }
  grep -q 'Latency Telemetry' <<<"${DOUT}" \
    || { rm -rf "${DR}"; fail "discipline text report missing telemetry"; }
  grep -q '1 redundant green' <<<"${DOUT}" \
    || { rm -rf "${DR}"; fail "discipline text report missing the verify line"; }
  # The report is pure Node and must route on native Windows too, where the
  # router runs every route under Node rather than Bash.
  DWIN="$(node - "${ROOT}/bin/luciazero.js" "${DR}/stats.log" <<'JS'
const [router, log] = process.argv.slice(2);
Object.defineProperty(process, "platform", {value: "win32"});
process.argv = [process.execPath, router, "discipline", "--log", log,
  "--days", "30", "--now", "2026-08-12T12:00:00Z"];
require(router);
JS
)"
  grep -q 'Luciazero Discipline Report' <<<"${DWIN}" \
    || { rm -rf "${DR}"; fail "native-Windows discipline route was blocked by Bash guard"; }
  RC=0; node "${ROOT}/bin/luciazero.js" typo-command >/dev/null 2>&1 || RC=$?
  [ "${RC}" -eq 64 ] || { rm -rf "${DR}"; fail "unknown CLI command did not fail with usage (rc=${RC})"; }
  rm -rf "${DR}"
  echo "ok  discipline report fixtures + CLI"
else
  echo "skip discipline report fixtures (node not installed)"
fi

# 4c6. default verify detection knows `python -m unittest` and this
# repository's timing collector, and knows that the collector's --report runs
# nothing. A regex somebody set themselves is left alone: the carve-out
# belongs to the default. Each case: an edit, the command, then a stop that
# must nudge (rc 2) or stay quiet (rc 0).
mktmp VD
verify_counts() { # verify_counts <command> <want rc: 0 counted, 2 not> <label>
  local CJ='{"cwd":"/hook/test/detect"}'
  echo "${CJ}" | TMPDIR="${VD}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
  printf '{"cwd":"/hook/test/detect","tool_input":{"command":%s}}\n' "$(printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
    | TMPDIR="${VD}" "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
  local RC=0
  echo "${CJ}" | TMPDIR="${VD}" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>/dev/null || RC=$?
  [ "${RC}" = "$2" ] || fail "$3 (stop rc=${RC}, want $2): $1"
}
verify_counts 'cd agentd && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_nudge' 0 "python3 -m unittest was not read as a verify run"
verify_counts 'python -m unittest discover -s tests -t .' 0 "python -m unittest discover was not read as a verify run"
# shellcheck disable=SC2016  # the literal is the command as typed, $PATH and all
verify_counts 'PATH=/x/bin:$PATH LZ_BASH32=/bin/bash scripts/test-timings.sh --full' 0 "the timing collector was not read as a verify run"
verify_counts 'scripts/test-timings.sh' 0 "the collector with no tier (full) was not read as a verify run"
verify_counts 'scripts/test-timings.sh --report' 2 "the collector's --report, which runs nothing, was read as a verify run"
verify_counts 'scripts/test-timings.sh --report | head -20' 2 "the collector's --report in a pipeline was read as a verify run"
# a regex of one's own keeps its own meaning, carve-out included
CJ='{"cwd":"/hook/test/detect"}'
echo "${CJ}" | TMPDIR="${VD}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
echo '{"cwd":"/hook/test/detect","tool_input":{"command":"scripts/test-timings.sh --report"}}' \
  | TMPDIR="${VD}" LUCIAZERO_VERIFY_REGEX='test-timings' "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
RC=0; echo "${CJ}" | TMPDIR="${VD}" "${ROOT}/claude/hooks/luciazero-verify.cjs" stop 2>/dev/null || RC=$?
[ "${RC}" = 0 ] || fail "the --report carve-out leaked into a regex the user set (stop rc=${RC})"
echo "ok  default verify detection covers unittest and the timing collector, not its --report"

# 4c6b. Input that arrives late is still read. Opening process.stdin made the
# pipe non-blocking, so a hook started before its writer had written read
# EAGAIN, took the event for empty and exited -- the writer then died of a
# broken pipe, and a verify run or a statusline was silently lost.
# The verify run is read back from the state it writes, not from a stop: a
# stop whose own input was dropped also exits 0.
mktmp SW
SW_STATE="$(TMPDIR="${SW}" node -e 'const v = require(process.argv[1]); console.log(require("path").join(v.stateBase(), v.stateKey("/hook/test/slow")))' \
  "${ROOT}/claude/hooks/luciazero-verify.cjs")"
{ sleep 1; printf '%s\n' '{"cwd":"/hook/test/slow","tool_input":{"command":"python -m unittest discover -s tests -t ."}}'; } \
  | TMPDIR="${SW}" "${ROOT}/claude/hooks/luciazero-verify.cjs" bash
[ "$(cat "${SW_STATE}/last_verify" 2>/dev/null)" = ok ] \
  || fail "the verify hook dropped a bash event whose input arrived late"
SWS="$({ sleep 1; printf '%s' '{"cwd":"/hook/test/slow","model":{"display_name":"LateModel"}}'; } \
  | TMPDIR="${SW}" "${ROOT}/claude/hooks/luciazero-statusline.cjs")"
case "${SWS}" in LateModel*) ;; *) fail "the statusline dropped input that arrived late: ${SWS}" ;; esac
echo "ok  hooks read input that arrives after they start"

# 4c7. LUCIAZERO_EDIT_DIAG=1 writes one line per edit event next to
# last_edit -- tool name, opaque key, whether file_path was missing, empty or
# present, its suffix, whether it lay under cwd, whether the edit counted --
# and never the path or the content. Off by default: no file at all.
mktmp ED
EDJ='{"cwd":"/hook/test/diag"'
ED_STATE="${ED}/luciazero-verify-state-$(id -u)/$(python3 -c 'import hashlib,sys; print(hashlib.md5(sys.argv[1].encode(), usedforsecurity=False).hexdigest()[:12])' /hook/test/diag)"
echo "${EDJ},\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"/hook/test/diag/a.py\"}}" \
  | TMPDIR="${ED}" "${ROOT}/claude/hooks/luciazero-verify.cjs" edit
[ ! -e "${ED_STATE}/edit-diag.log" ] || fail "the edit diagnostic wrote a log without being asked"
diag_edit() { printf '%s\n' "$1" | TMPDIR="${ED}" LUCIAZERO_EDIT_DIAG=1 "${ROOT}/claude/hooks/luciazero-verify.cjs" edit; }
diag_edit "${EDJ},\"tool_name\":\"Write\"}"
diag_edit "${EDJ},\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"\"}}"
diag_edit "${EDJ},\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"/hook/test/diag/src/a.py\"}}"
diag_edit "${EDJ},\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"/elsewhere/notes.md\"}}"
diag_edit "${EDJ},\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"/hook/test/diag/Makefile\"}}"
DIAG_LINES="$( (wc -l < "${ED_STATE}/edit-diag.log" 2>/dev/null || echo 0) | tr -d ' ')"
[ "${DIAG_LINES}" = 5 ] || fail "the edit diagnostic wrote ${DIAG_LINES} lines for five edit events"
DIAG="$(sed 's/^ts=[0-9T:Z-]* mode=edit tool=\([A-Za-z]*\) key=[0-9a-f]\{16\} /\1 /' "${ED_STATE}/edit-diag.log" | tr '\n' '|')"
WANT='Write file_path=missing ext=- in_cwd=- counted=yes|Edit file_path=empty ext=- in_cwd=- counted=yes|Edit file_path=present ext=py in_cwd=yes counted=yes|Write file_path=present ext=md in_cwd=no counted=no|Write file_path=present ext=- in_cwd=yes counted=yes|'
[ "${DIAG}" = "${WANT}" ] || fail "the edit diagnostic lines are not the expected ones:
got  ${DIAG}
want ${WANT}"
grep -q '/hook/test/diag\|/elsewhere\|notes\|Makefile' "${ED_STATE}/edit-diag.log" && fail "the edit diagnostic recorded a path or a file name"
echo "ok  LUCIAZERO_EDIT_DIAG=1 records what each edit event carried, never the path"
