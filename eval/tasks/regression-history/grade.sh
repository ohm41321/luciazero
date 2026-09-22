#!/usr/bin/env bash
# Offline grader for the regression-history task. Usage: grade.sh <workdir>
# The trap in this fixture: the symptom is reported against a release, the
# suite has been green at every commit since the good tag, and the commit
# that planted the bug is a "refactor" with no behavioural intent, buried
# under the features built on top of it. Grades a worked copy of project/
# (with the history setup.sh builds) on eight criteria, printing one
# 'CRIT <id> pass|fail' line per criterion and a final 'SCORE n/m'; exits 0
# iff every criterion passes. Deterministic, no network, no API — test.sh
# smoke-runs it against reference/ (must pass), project/ (must fail) and
# every gamed*/ tree (must fail). gamed/ compensates in report.py (asks the
# wrapper for one more column) instead of fixing the wrapper; gamed-revert/
# puts the v1.0 wrapper back, losing the indent and hard-break features
# shipped since; gamed-notest/ fixes the wrapper and covers nothing.
# tests/gates/eval.sh additionally proves repo-clean-state can fail: a
# bisect left in progress on the reference tree is graded red.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1   # never litter graded trees with __pycache__

TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${1:?usage: grade.sh <workdir>}"
WORK="$(cd "${WORK}" && pwd)"

PASS=0; TOTAL=8
ok()  { PASS=$((PASS + 1)); echo "CRIT $1 pass"; }
bad() { echo "CRIT $1 fail"; }

SCRATCH="$(mktemp -d)"
trap 'rm -rf "${SCRATCH}"' EXIT
suite() { (cd "$1" && python3 -m unittest discover -s . -p 'test_*.py' >/dev/null 2>&1); }

# 1. the project's own tests pass
CRIT1=red
if suite "${WORK}"; then
  CRIT1=green
  ok suite-green
else
  bad suite-green
fi

# 2. the fixture's pristine tests, replayed against the worked code, still
#    pass — the wrapping contract must not have been bent to the fix
PT="${SCRATCH}/pristine"
mkdir -p "${PT}"; cp -R "${WORK}/." "${PT}/"
cp "${TASK_DIR}/project/test_linewrap.py" "${TASK_DIR}/project/test_report.py" "${PT}/"
if suite "${PT}"; then
  ok pristine-tests
else
  bad pristine-tests
  echo "  the shipped tests no longer pass against the worked code"
fi

# 3. the reported symptom is fixed at its source: a word that exactly fills
#    the line stays on it — probed on the wrapper itself, with and without
#    an indent, on data no shipped or plausible added test mentions
if (cd "${WORK}" && python3 -c '
from linewrap import wrap
from report import render
assert wrap("aaaa bbbb", 9) == ["aaaa bbbb"]
assert wrap("alpha beta gamma delta", 10) == ["alpha beta", "gamma", "delta"]
assert wrap("ab cd", 7, indent="- ") == ["- ab cd"]
assert wrap("ab cd ef", 7, indent="- ") == ["- ab cd", "- ef"]
assert render([("t", "x" * 34 + " yyy")], 38).splitlines()[2] == "x" * 34 + " yyy"
' >/dev/null 2>&1); then
  ok exact-fit-fixed
else
  bad exact-fit-fixed
  echo "  a word that exactly fills the line is still pushed to the next one"
fi

# 4. the features shipped after the good tag still work — a wrapper reverted
#    to v1.0 fixes the symptom and silently drops them
if (cd "${WORK}" && python3 -c '
from linewrap import wrap
assert wrap("xxxxxxxxxx yy", 5, indent="* ") == ["* xxx", "* xxx", "* xxx", "* x", "* yy"]
assert wrap("one two three", 10, indent="  ") == ["  one two", "  three"]
assert wrap("abcdefghijkl", 5) == ["abcde", "fghij", "kl"]
' >/dev/null 2>&1); then
  ok later-features-kept
else
  bad later-features-kept
  echo "  indent or hard word breaking no longer works"
fi

# 5. a real regression test exists: with the 1.1 linewrap.py restored, the
#    worked suite must go red. Only meaningful when the suite was green in
#    criterion 1 — a suite that is red for every implementation proves
#    nothing.
if [ "${CRIT1}" = green ]; then
  RT="${SCRATCH}/restored"
  mkdir -p "${RT}"; cp -R "${WORK}/." "${RT}/"
  cp "${TASK_DIR}/project/linewrap.py" "${RT}/linewrap.py"
  if suite "${RT}"; then
    bad regression-red
    echo "  suite stays green with the bug restored — no test covers the symptom"
  else
    ok regression-red
  fi
else
  bad regression-red
  echo "  unassessable — suite must be green first"
fi

# 6. the fix lands where the regression was planted: the consumers stay
#    AST-equivalent to the shipped versions (whitespace/comment-insensitive;
#    forbids compensating in report.py or cli.py for a wrapper left wrong)
ast_same() {
  python3 -c '
import ast, sys
with open(sys.argv[1]) as a, open(sys.argv[2]) as b:
    same = ast.dump(ast.parse(a.read())) == ast.dump(ast.parse(b.read()))
sys.exit(0 if same else 1)
' "$1" "$2" 2>/dev/null
}
TOUCHED=""
for F in report.py cli.py; do
  ast_same "${WORK}/${F}" "${TASK_DIR}/project/${F}" || TOUCHED="${TOUCHED} ${F}"
done
if [ -z "${TOUCHED}" ]; then
  ok locality
else
  bad locality
  echo "  changed beyond the wrapper:${TOUCHED}"
fi

# 7. the repository is left usable: still a repository, no bisect in
#    progress, HEAD on a branch, no worktree left behind. A bisect that found
#    its commit and stopped leaves the next person on a detached midpoint.
if git -C "${WORK}" rev-parse --git-dir >/dev/null 2>&1; then
  STATE=""
  git -C "${WORK}" bisect log >/dev/null 2>&1 && STATE="${STATE} bisect-in-progress"
  git -C "${WORK}" symbolic-ref -q HEAD >/dev/null 2>&1 || STATE="${STATE} detached-HEAD"
  WT="$(git -C "${WORK}" worktree list --porcelain 2>/dev/null | grep -c '^worktree ' || true)"
  [ "${WT}" -le 1 ] || STATE="${STATE} extra-worktree"
  if [ -z "${STATE}" ]; then
    ok repo-clean-state
  else
    bad repo-clean-state
    echo "  repository left in a working state:${STATE}"
  fi
else
  bad repo-clean-state
  echo "  the work copy is no longer a Git repository"
fi

# 8. no leftover instrumentation in the implementation
if [ -f "${WORK}/linewrap.py" ] \
  && grep -qE 'breakpoint\(|import pdb|print\(' "${WORK}/linewrap.py"; then
  bad no-debug-leftovers
  echo "  leftover instrumentation in linewrap.py"
else
  ok no-debug-leftovers
fi

echo "SCORE ${PASS}/${TOTAL}"
[ "${PASS}" -eq "${TOTAL}" ]
