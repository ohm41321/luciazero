#!/usr/bin/env bash
# revert-probe.sh — the mechanical form of the done-skill question "would the
# new tests fail if the change were reverted?" (doctrine: red before green).
# Checks <base-ref> out into a throwaway worktree, copies ONLY the test files
# changed since <base-ref> from the working tree on top of it, and runs the
# verify command there. The result is INVERTED: old code failing the new
# tests is the PASS.
#
# Usage: revert-probe.sh "<verify-cmd>" [base-ref]    (base-ref default: HEAD)
# Run it BEFORE committing — the fix and its new tests sit in the working
# tree while HEAD is still the old code. For an already-committed fix, pass
# the pre-fix ref (e.g. HEAD~1) as base-ref.
#
# Exit: 0 tests bite · 1 tests stay green on old code, or no changed test
# files · 2 UNASSESSABLE (not a git repo, no commits, invalid base).
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

# test-file patterns mirror luciazero-bootstrap's detect.sh: tests-style dirs
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

# scratch space first — the changed-file list is stored NUL-delimited in a
# file, because git C-quotes non-ASCII/backslash names in its plain output
# (-z emits them raw) and bash variables cannot hold NUL bytes
TMP="$(mktemp -d)"
WT="${TMP}/worktree"
trap 'git worktree remove --force "${WT}" >/dev/null 2>&1 || true
      rm -rf "${TMP}"
      git worktree prune >/dev/null 2>&1 || true' EXIT

# changed vs base (tracked) plus untracked — the two sets are disjoint —
# filtered to test files that still exist (a deleted test cannot bite)
TEST_LIST="${TMP}/tests"
: > "${TEST_LIST}"
COUNT=0
while IFS= read -r -d '' F; do
  [ -f "${F}" ] || continue
  if is_test_file "${F}"; then
    printf '%s\0' "${F}" >> "${TEST_LIST}"
    COUNT=$((COUNT + 1))
  fi
done < <({ git diff --name-only -z "${BASE}" --; git ls-files --others --exclude-standard -z; } 2>/dev/null)

if [ "${COUNT}" -eq 0 ]; then
  echo "FAIL: no test files changed since ${BASE} — the change ships without a test that bites"
  exit 1
fi

# old code in a throwaway worktree; cleanup runs on every exit path
git worktree add --detach "${WT}" "${BASE}" >/dev/null 2>&1 \
  || unassessable "git worktree add failed for ${BASE}"

# overlay ONLY the changed test files from the working tree
while IFS= read -r -d '' F; do
  mkdir -p "${WT}/$(dirname "${F}")"
  cp "${F}" "${WT}/${F}"
done < "${TEST_LIST}"

RC=0
OUT="$(cd "${WT}" && sh -c "${VERIFY}" 2>&1)" || RC=$?

if [ "${RC}" -ne 0 ]; then
  LAST=""
  while IFS= read -r LINE; do
    case "${LINE}" in *[![:space:]]*) LAST="${LINE}" ;; esac
  done <<EOF
${OUT}
EOF
  echo "PASS: regression tests bite — old code fails the new tests"
  echo "  evidence (exit ${RC}): ${LAST:-<no output>}"
  exit 0
fi
echo "FAIL: the changed tests stay green against the old code — they do not cover the change"
exit 1
