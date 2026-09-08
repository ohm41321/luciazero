#!/usr/bin/env bash
# revert-probe.sh — the mechanical form of the done-skill question "would the
# new tests fail if the change were reverted?" (doctrine: red before green).
# Checks <base-ref> out into a throwaway worktree, copies ONLY the test files
# changed since <base-ref> from the working tree on top of it, and runs the
# verify command there. The result is INVERTED: old code failing the new
# tests is the PASS.
#
# A red old-code run is not proof by itself. Plenty of things fail only on the
# old tree without saying anything about the change: a module the change adds,
# a command that is not installed there, a denied execution, an unrelated
# broken test. So a red run has to survive three more checks before it counts:
#   * its fingerprint must be a test verdict, not infrastructure — a shell that
#     could not run or execute the command (exit 127/126) and a run that failed
#     to load the tests at all (import/collection errors) are refused;
#   * it must be attributable to the changed tests — either the verify command
#     targets one of them, or the failure output names one;
#   * the same command must PASS against the current state (the base plus every
#     changed file), so a command that is red everywhere cannot be read as a
#     regression.
# What it still cannot see: a flake that only reproduces on the old tree; a
# command the change itself adds when a wrapper swallows the shell's exit 127;
# and, in the other direction, a suite whose own output quotes a loader error is
# read as one (this repository's revert-probe fixtures do exactly that, so
# probing a change to this script needs the manual comparison instead).
#
# Usage: revert-probe.sh "<verify-cmd>" [base-ref]    (base-ref default: HEAD)
# Run it BEFORE committing — the fix and its new tests sit in the working
# tree while HEAD is still the old code. For an already-committed fix, pass
# the pre-fix ref (e.g. HEAD~1) as base-ref. Prefer a verify command aimed at
# the tests the change adds; a whole-suite command works but attributes the
# failure only through the output.
#
# Exit: 0 tests bite · 1 tests stay green on old code, or no changed test
# files · 2 UNASSESSABLE (not a git repo, no commits, invalid base, an
# infrastructure failure, a failure that cannot be attributed to the changed
# tests, or a verify command that does not pass on the current code).
# Pure bash + git; never touches the caller's working tree.
set -euo pipefail

VERIFY="${1:?usage: revert-probe.sh \"<verify-cmd>\" [base-ref]}"
BASE="${2:-HEAD}"

unassessable() { echo "UNASSESSABLE: $*"; exit 2; }

git rev-parse --git-dir >/dev/null 2>&1 || unassessable "not a git repo"
git rev-parse --verify HEAD >/dev/null 2>&1 || unassessable "no commits yet"
git rev-parse --verify --quiet "${BASE}^{commit}" >/dev/null 2>&1 \
  || unassessable "invalid base ref: ${BASE}"
TOP="$(git rev-parse --show-toplevel 2>/dev/null)" || unassessable "no working tree (bare repo?)"
cd "${TOP}"

# test-file patterns mirror ready's detect.sh: tests-style dirs
# plus the common root `test.sh` entrypoint and test_*.*, *_test.*, *.test.*,
# *.spec.* file names
is_test_file() {
  case "/$1" in
    */tests/*|*/test/*|*/spec/*|*/__tests__/*) return 0 ;;
  esac
  case "${1##*/}" in
    test.sh|test_*.*|*_test.*|*.test.*|*.spec.*) return 0 ;;
  esac
  return 1
}

# scratch space first — the changed-file lists are stored NUL-delimited in
# files, because git C-quotes non-ASCII/backslash names in its plain output
# (-z emits them raw) and bash variables cannot hold NUL bytes
TMP="$(mktemp -d)"
WT="${TMP}/old"
WT_NEW="${TMP}/new"
trap 'git worktree remove --force "${WT}" >/dev/null 2>&1 || true
      git worktree remove --force "${WT_NEW}" >/dev/null 2>&1 || true
      rm -rf "${TMP}"
      git worktree prune >/dev/null 2>&1 || true' EXIT

# changed vs base (tracked) plus untracked — the two sets are disjoint.
# TEST_LIST drives the old-code overlay; CHANGED_LIST and GONE_LIST rebuild the
# current state for the control run (a deleted test cannot bite, but a deleted
# source file is part of the change).
TEST_LIST="${TMP}/tests"
CHANGED_LIST="${TMP}/changed"
GONE_LIST="${TMP}/gone"
: > "${TEST_LIST}"; : > "${CHANGED_LIST}"; : > "${GONE_LIST}"
COUNT=0
while IFS= read -r -d '' F; do
  if [ ! -f "${F}" ]; then
    printf '%s\0' "${F}" >> "${GONE_LIST}"
    continue
  fi
  printf '%s\0' "${F}" >> "${CHANGED_LIST}"
  if is_test_file "${F}"; then
    printf '%s\0' "${F}" >> "${TEST_LIST}"
    COUNT=$((COUNT + 1))
  fi
done < <({ git diff --name-only -z "${BASE}" --; git ls-files --others --exclude-standard -z; } 2>/dev/null)

if [ "${COUNT}" -eq 0 ]; then
  echo "FAIL: no test files changed since ${BASE} — the change ships without a test that bites"
  exit 1
fi

# copy the files named in $2 out of the working tree into the worktree $1
overlay() {
  local target="$1" list="$2" f
  while IFS= read -r -d '' f; do
    mkdir -p "${target}/$(dirname "${f}")"
    cp "${f}" "${target}/${f}"
  done < "${list}"
}

# shortest decisive line: the last line that is not blank
last_line() {
  local line last=""
  while IFS= read -r line; do
    case "${line}" in *[![:space:]]*) last="${line}" ;; esac
  done <<EOF
$1
EOF
  printf '%s' "${last:-<no output>}"
}

RC=0
OUT=""
run_verify() {
  RC=0
  OUT="$(cd "$1" && sh -c "${VERIFY}" 2>&1)" || RC=$?
}

# a run that never loaded the tests judged nothing. Only loader failures are
# matched here: an environment that cannot run the command at all shows up as
# exit 127/126, or fails the current-code control run below as well. Matching
# shell-level phrases too would flag any suite whose own output quotes them.
load_marker() {
  printf '%s\n' "$1" | grep -m1 -E \
    'ModuleNotFoundError|ImportError|error while loading shared libraries|[Cc]annot find module|MODULE_NOT_FOUND|ERROR collecting|errors? during collection|INTERNALERROR'
}

# does $1 name one of the changed test files, by path or by basename?
names_changed_test() {
  local f
  while IFS= read -r -d '' f; do
    case "$1" in *"${f}"*) return 0 ;; esac
    case "$1" in *"${f##*/}"*) return 0 ;; esac
  done < "${TEST_LIST}"
  return 1
}

# old code in a throwaway worktree; cleanup runs on every exit path
git worktree add --detach "${WT}" "${BASE}" >/dev/null 2>&1 \
  || unassessable "git worktree add failed for ${BASE}"

# overlay ONLY the changed test files from the working tree
overlay "${WT}" "${TEST_LIST}"

run_verify "${WT}"
RC_OLD="${RC}"
OUT_OLD="${OUT}"

if [ "${RC_OLD}" -eq 0 ]; then
  echo "FAIL: the changed tests stay green against the old code — they do not cover the change"
  exit 1
fi

# --- the red run has to earn the word "regression" -------------------------
if [ "${RC_OLD}" -eq 127 ]; then
  unassessable "the verify command could not be run on ${BASE} (exit 127): $(last_line "${OUT_OLD}")"
fi
if [ "${RC_OLD}" -eq 126 ]; then
  unassessable "the verify command was not executable on ${BASE} (exit 126): $(last_line "${OUT_OLD}")"
fi
if MARK="$(load_marker "${OUT_OLD}")"; then
  unassessable "the old-code run never loaded the tests: ${MARK}
  that is an import failure on ${BASE}, not a regression — the change may
  simply add code the tests import. Point the verify command at a test that
  fails on its assertion instead."
fi

NOTE=""
if ! names_changed_test "${VERIFY}"; then
  names_changed_test "${OUT_OLD}" \
    || unassessable "the verify command does not target any changed test file and
  its failure output does not name one, so the failure cannot be attributed to
  the changed tests. Re-run with a command that targets them."
  NOTE="note: the verify command is not targeted at the changed tests; attribution comes from the failure output"
fi

# control: the same command must pass on the current state (base + every
# changed file), or the failure says nothing about the change
git worktree add --detach "${WT_NEW}" "${BASE}" >/dev/null 2>&1 \
  || unassessable "git worktree add failed for ${BASE}"
overlay "${WT_NEW}" "${CHANGED_LIST}"
while IFS= read -r -d '' F; do
  rm -f "${WT_NEW}/${F}"
done < "${GONE_LIST}"

run_verify "${WT_NEW}"
if [ "${RC}" -ne 0 ]; then
  unassessable "the same command also fails on the current code (exit ${RC}): $(last_line "${OUT}")
  the old-code failure cannot be attributed to reverting the change. Make the
  verify command pass on the current tree first."
fi

echo "PASS: regression tests bite — old code fails the new tests, the same command passes on the current code"
echo "  evidence (exit ${RC_OLD} on ${BASE}): $(last_line "${OUT_OLD}")"
[ -n "${NOTE}" ] && echo "  ${NOTE}"
exit 0
