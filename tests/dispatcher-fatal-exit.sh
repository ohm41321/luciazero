#!/usr/bin/env bash
# tests/dispatcher-fatal-exit.sh [<checkout>] — ./test.sh must fail a run
# whose gate dies of a shell error, in every tier, under the bash running this.
#
# Bash 3.2 ends a shell on a fatal error -- an unset variable under set -u,
# `${x:?}`, a bad substitution -- with its EXIT trap's own status, and $? in
# the trap reads 0. Before the dispatcher marked its own endings, a gate that
# died that way stopped the run with exit 0 and no PASS line, and a full-only
# one, in its subshell, let the run end on PASS. `bash -n` parses all three
# forms clean, so the pre-source syntax check cannot see them.
#
# It runs over stub gates, so it needs only the dispatcher, its sanitizer and
# a POSIX userland. tests/gates/tiers.sh runs it under the suite's bash and
# LZ_BASH32; CI runs it in the pinned bash:3.2 image, where the regression
# was seen: the runner's own Bash 5 may hand the trap the error's status and
# stay red with no help from the dispatcher, so it cannot stand in for 3.2.
set -euo pipefail
ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
fail() { echo "FAIL: $*" >&2; exit 1; }

T="$(mktemp -d "${TMPDIR:-/tmp}/luciazero-fatal.XXXXXX")"
# This file has the dispatcher's hazard too: mark the one intended ending.
DONE=0
finish() {
  local RC=$?
  rm -rf "${T}"
  if [ "${RC}" -eq 0 ] && [ "${DONE}" != 1 ]; then
    echo "FAIL: dispatcher-fatal-exit.sh stopped on a shell error before it finished" >&2
    exit 1
  fi
  return "${RC}"
}
trap finish EXIT

mkdir -p "${T}/tests/gates" "${T}/scripts"
cp "${ROOT}/test.sh" "${T}/test.sh"
cp "${ROOT}/scripts/sanitize-luciazero-env.sh" "${T}/scripts/"
GATES="$(grep -o 'tests/gates/[a-z0-9-]*\.sh' "${ROOT}/test.sh" | sort -u)"
[ -n "${GATES}" ] || fail "found no gates in ${ROOT}/test.sh"
stub() { # stub <gate> [<line>]: a gate that prints its name, then runs <line>
  printf 'echo "gate %s"\n%s\n' "$1" "${2:-}" > "${T}/tests/gates/$1.sh"
}
for G in ${GATES}; do stub "$(basename "${G}" .sh)"; done
# shellcheck disable=SC2016  # the stub's own text: it expands in the child
DIE='echo "${LZ_FATAL_NEVER_SET}"'
WHO="bash ${BASH_VERSION}"

run() { # run <tier flag> [<LZ_TEST_PARALLEL>]: RC and ${T}/out of a stub run
  RC=0
  (cd "${T}" && LZ_TEST_PARALLEL="${2:-1}" "${BASH}" ./test.sh "$1") \
    >"${T}/out" 2>&1 || RC=$?
}
red() { # red <what> <gate>: the run is red, shows the error, never passes
  [ "${RC}" -ne 0 ] || fail "$1 exited 0 after gate $2 died of a shell error (${WHO})"
  grep -qF 'LZ_FATAL_NEVER_SET' "${T}/out" \
    || fail "$1 hid the shell error in gate $2 (${WHO}): $(tail -1 "${T}/out")"
  if grep -q '^PASS' "${T}/out"; then
    fail "$1 printed a PASS line after gate $2 died of a shell error (${WHO})"
  fi
  # Bash 4+ may hand the trap the error's status, which keeps the run red and
  # skips this line; on 3.x the trap sees 0, so the line must be there.
  if [ "${BASH_VERSINFO[0]}" -lt 4 ] \
    && ! grep -qF "FAIL: the run stopped in gate $2" "${T}/out"; then
    fail "$1 did not name gate $2 (${WHO}): $(tail -1 "${T}/out")"
  fi
}

# Green first: a stub run that is red for any other reason (a missing tool in
# a minimal image) would make every check below pass for nothing.
for FLAG in --discipline --fast --full; do
  run "${FLAG}"
  [ "${RC}" -eq 0 ] || fail "${FLAG} over clean stubs exited ${RC} (${WHO}): $(tail -1 "${T}/out")"
  grep -q '^PASS' "${T}/out" || fail "${FLAG} over clean stubs printed no PASS line (${WHO})"
done

# A gate sourced into the dispatcher's own shell.
stub hooks "${DIE}"
for FLAG in --discipline --fast --full; do
  run "${FLAG}"
  red "${FLAG}" hooks
done
stub hooks

# A full-only gate, in its own subshell, parallel and serial.
stub parity "${DIE}"
for PAR in 1 0; do
  run --full "${PAR}"
  red "--full (LZ_TEST_PARALLEL=${PAR})" parity
  grep -qF 'FAIL: red gates: parity' "${T}/out" \
    || fail "--full (LZ_TEST_PARALLEL=${PAR}) did not name the red gate (${WHO}): $(tail -1 "${T}/out")"
done

DONE=1
echo "ok  a gate that dies of a shell error turns every tier red, a full-only gate included (${WHO})"
