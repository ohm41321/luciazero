#!/usr/bin/env bash
# Drives the shipped enforcement-pack hooks through the loop the README
# describes — edit, blocked stop, red verify, fix, green verify — in a
# sandbox, printing the hooks' REAL output. This is the script the README
# GIF records (docs/assets/demo.tape + vhs), so the GIF can never drift
# from what the scripts actually print. Touches nothing outside its own
# mktemp dirs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOOK="${ROOT}/claude/hooks/luciazero-verify.sh"
SL="${ROOT}/claude/hooks/luciazero-statusline.sh"
PAUSE="${DEMO_PAUSE:-1.2}"

TMPDIR="$(mktemp -d)"; export TMPDIR
CLAUDE_CONFIG_DIR="$(mktemp -d)"; export CLAUDE_CONFIG_DIR
PROJ="$(mktemp -d)"
trap 'rm -rf "${TMPDIR}" "${CLAUDE_CONFIG_DIR}" "${PROJ}"' EXIT

DIM=$'\033[2m'; BOLD=$'\033[1m'; OFF=$'\033[0m'

narrate() { printf '\n%s%s%s\n' "${DIM}" "$*" "${OFF}"; sleep "${PAUSE}"; }
statusline() {
  printf '{"model":{"display_name":"Opus"},"workspace":{"current_dir":"%s"}}' "${PROJ}" \
    | "${SL}" | sed "s/^/  ${BOLD}statusline →${OFF} /"
  sleep "${PAUSE}"
}
edit() {
  printf '{"cwd":"%s","tool_input":{"file_path":"%s/calc.py"}}' "${PROJ}" "${PROJ}" \
    | "${HOOK}" edit
}
verify() {  # $1 = exit code the verify command returned
  printf '{"cwd":"%s","tool_input":{"command":"./test.sh"},"tool_response":{"exit_code":%s}}' \
    "${PROJ}" "$1" | "${HOOK}" bash
}

narrate "# the agent edits calc.py"
edit
statusline
sleep 1   # statusline compares whole-second mtimes

narrate "# ...and tries to end the session without verifying:"
MSG="$(printf '{"cwd":"%s"}' "${PROJ}" | "${HOOK}" stop 2>&1)" || true   # nudge exits 2 by design
printf '%s\n' "${MSG}" | sed 's/^/  /'
sleep "${PAUSE}"

narrate "# so it runs the verify command — red"
verify 1
statusline
sleep 1

narrate "# fixes calc.py, runs it again — green"
edit
verify 0
statusline

narrate "# done is proven by a command, not claimed."
