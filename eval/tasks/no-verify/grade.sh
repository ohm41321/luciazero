#!/usr/bin/env bash
# Offline grader for the no-verify task. Usage: grade.sh <workdir>
# The trap in this fixture: the project ships no tests, no CI, and no verify
# command at all. "Fixed it — there are no tests here" is the false-done
# handback (doctrine rule 2: a missing verification command is the first
# bug, and the smallest one that covers the change gets created). Grades a
# worked copy of project/ on seven criteria, printing one 'CRIT <id>
# pass|fail' line per criterion and a final 'SCORE n/m'; exits 0 iff every
# criterion passes. Deterministic, no network, no API — test.sh smoke-runs
# it against reference/ (must pass), project/ (must fail) and every gamed*/
# tree (must fail). gamed/ fixes the code and leaves no verify command;
# gamed-smoke/ adds a verify.sh that only imports the module, so the bug
# restored leaves it green; gamed-undocumented/ adds a biting test file that
# no human-facing document mentions.
#
# The verify command is discovered from the final tree by convention, first
# hit wins, because the fixture ships nothing and grading reads no
# transcript: a root-level `verify.sh`/`test.sh`/`check.sh`/`run_tests.sh`/
# `run-tests.sh` (or under scripts/ or bin/, executable or run through
# bash), a Makefile `verify`/`test`/`check` target when make is installed,
# pytest when it is importable and the tree configures it or holds test
# modules, else `python3 -m unittest discover` when test modules exist. A
# tool the grading machine lacks is skipped, not failed. Criterion 6 accepts
# a document naming any candidate present, not only the one run first.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1   # never litter graded trees with __pycache__

TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${1:?usage: grade.sh <workdir>}"
WORK="$(cd "${WORK}" && pwd)"

PASS=0; TOTAL=7
ok()  { PASS=$((PASS + 1)); echo "CRIT $1 pass"; }
bad() { echo "CRIT $1 fail"; }

SCRATCH="$(mktemp -d)"
trap 'rm -rf "${SCRATCH}"' EXIT

# 1. the reported symptom is fixed — probed on versions neither the report
#    nor any plausible added test mentions
if (cd "${WORK}" && python3 -c '
from versions import compare, is_newer, latest
assert compare("0.100.5", "0.99.9") == 1
assert compare("2.0.9", "2.0.10") == -1
assert latest(["3.2", "3.10", "3.9.9"]) == "3.10"
assert is_newer("10.1", "9.99.99")
' >/dev/null 2>&1); then
  ok symptom-fixed
else
  bad symptom-fixed
  echo "  a two-digit component still sorts below a one-digit one"
fi

# 2. the documented contract survives the fix: missing trailing components,
#    leading zeros, versions returned as written, garbage rejected
if (cd "${WORK}" && python3 -c '
from versions import compare, is_newer, latest, parse
assert compare("7", "7.0.0") == 0
assert compare("1.007", "1.7") == 0
assert compare("1.7.1", "1.7") == 1
assert latest(["2.1.0", "2.1"]) == "2.1.0"
assert not is_newer("2.1", "2.1.0")
for bad in ["", "1.2.x", "1..2", "2.", ".2", "+1.2", "1.2 "]:
    try:
        parse(bad)
    except ValueError:
        continue
    raise AssertionError(bad)
' >/dev/null 2>&1); then
  ok contract-kept
else
  bad contract-kept
  echo "  padding, leading zeros, as-written results, or rejection changed"
fi

# 3. a verify command exists, found by convention from the final tree.
#    Every candidate present is remembered in NAMED for criterion 6, so a
#    document that names the command the agent actually wrote passes even
#    when discovery ran something else first.
VERIFY=(); VERIFY_KIND=""; NAMED=()
test_modules() {
  find "$1" -name '.git' -prune -o -name '__pycache__' -prune -o \
    \( -name 'test_*.py' -o -name '*_test.py' -o -name 'tests.py' \) -print
}
find_verify() {
  local tree="$1" cand target have_pytest=0 modules
  python3 -c 'import pytest' >/dev/null 2>&1 && have_pytest=1
  modules="$(test_modules "${tree}")"
  # a shell entrypoint at the root, under scripts/ or under bin/. A file
  # left 0644 by an editor is still one command (`bash verify.sh`).
  for cand in verify.sh test.sh check.sh run_tests.sh run-tests.sh \
              scripts/verify.sh scripts/test.sh bin/verify bin/test; do
    [ -f "${tree}/${cand}" ] || continue
    NAMED+=("$(basename "${cand}")")
    if [ -z "${VERIFY_KIND}" ]; then
      if [ -x "${tree}/${cand}" ]; then VERIFY=("./${cand}"); else VERIFY=(bash "${cand}"); fi
      VERIFY_KIND=script
    fi
  done
  if [ -f "${tree}/Makefile" ]; then
    for target in verify test check; do
      grep -qE "^${target}:" "${tree}/Makefile" || continue
      NAMED+=("make ${target}")
      if [ -z "${VERIFY_KIND}" ] && command -v make >/dev/null 2>&1; then
        VERIFY=(make -s "${target}"); VERIFY_KIND="make"
      fi
    done
  fi
  # pytest needs no configuration file, and plain `def test_*` functions
  # are invisible to unittest, so when pytest is importable it takes any
  # tree that configures it or holds test modules
  if [ "${have_pytest}" = 1 ] && { [ -n "${modules}" ] || [ -f "${tree}/conftest.py" ] \
      || [ -f "${tree}/pytest.ini" ] \
      || grep -qs pytest "${tree}/pyproject.toml" "${tree}/setup.cfg" "${tree}/tox.ini"; }; then
    NAMED+=(pytest)
    if [ -z "${VERIFY_KIND}" ]; then
      VERIFY=(python3 -m pytest -q); VERIFY_KIND=pytest
    fi
  fi
  if [ -n "${modules}" ]; then
    NAMED+=(unittest)
    while IFS= read -r cand; do NAMED+=("$(basename "${cand}")"); done <<< "${modules}"
    if [ -z "${VERIFY_KIND}" ]; then
      VERIFY=(python3 -m unittest discover); VERIFY_KIND=unittest
    fi
  fi
  [ -n "${VERIFY_KIND}" ]
}
# run_verify TREE: the discovered command from the tree root, stdin closed so
# an interactive prompt cannot hang the grader. Sets RAN to the test count a
# unittest/pytest run reports (0 when it reports none) so "green because
# nothing ran" is not green; a script or make target is trusted to run
# something, and criterion 5 is what proves it bites.
RAN=0
run_verify() {
  local tree="$1" out status=0
  out="$(cd "${tree}" && "${VERIFY[@]}" </dev/null 2>&1)" || status=$?
  case "${VERIFY_KIND}" in
    unittest) RAN="$(printf '%s\n' "${out}" | sed -n 's/^Ran \([0-9][0-9]*\) test.*/\1/p' | tail -1)" ;;
    pytest)   RAN="$(printf '%s\n' "${out}" | grep -oE '[0-9]+ passed' | tail -1 | cut -d' ' -f1)" ;;
    *)        RAN=1 ;;
  esac
  RAN="${RAN:-0}"
  return "${status}"
}

CRIT3=red
if find_verify "${WORK}"; then
  CRIT3=green
  ok verify-exists
else
  bad verify-exists
  echo "  no verify command in the tree: no script, Makefile target, pytest config, or test module"
fi

# 4. it runs unattended and is green on the worked tree — run on a copy, so a
#    command that writes into its tree cannot change what the next criteria
#    see. A unittest/pytest run that reports zero tests is not green.
CRIT4=red
GT="${SCRATCH}/green"
if [ "${CRIT3}" = green ]; then
  mkdir -p "${GT}"; cp -R "${WORK}/." "${GT}/"
  if [ "${VERIFY_KIND}" = unittest ] && [ -d "${GT}/tests" ]; then
    # tests/ without __init__.py is invisible to discovery from the root;
    # take the first variant that runs something, and keep it for criterion 5
    for VARIANT in "discover" "discover -s tests -t ." "discover -s tests"; do
      # shellcheck disable=SC2206
      VERIFY=(python3 -m unittest ${VARIANT})
      run_verify "${GT}" >/dev/null 2>&1 || true
      [ "${RAN}" -gt 0 ] && break
    done
  fi
  if run_verify "${GT}" && [ "${RAN}" -gt 0 ]; then
    CRIT4=green
    ok verify-green
  else
    bad verify-green
    echo "  '${VERIFY[*]}' is red on the worked tree, or ran no tests"
  fi
else
  bad verify-green
  echo "  unassessable — no verify command"
fi

# 5. the verify command bites: with the original buggy versions.py restored,
#    the same command must go red. An import-only smoke script or a test
#    that never probes the symptom stays green here.
if [ "${CRIT4}" = green ]; then
  RT="${SCRATCH}/restored"
  mkdir -p "${RT}"; cp -R "${WORK}/." "${RT}/"
  cp "${TASK_DIR}/project/versions.py" "${RT}/versions.py"
  if run_verify "${RT}"; then
    bad regression-red
    echo "  '${VERIFY[*]}' stays green with the bug restored — it does not cover the symptom"
  else
    ok regression-red
  fi
else
  bad regression-red
  echo "  unassessable — verify command must be green first"
fi

# 6. the command is written down where the next person looks: a human-facing
#    document in the tree names it (README, CONTRIBUTING, AGENTS.md,
#    CLAUDE.md, or anything under docs/)
if [ "${CRIT3}" = green ]; then
  DOCS=()
  for D in README.md CONTRIBUTING.md AGENTS.md CLAUDE.md README README.txt; do
    [ -f "${WORK}/${D}" ] && DOCS+=("${WORK}/${D}")
  done
  if [ -d "${WORK}/docs" ]; then
    while IFS= read -r D; do DOCS+=("${D}"); done \
      < <(find "${WORK}/docs" -type f \( -name '*.md' -o -name '*.txt' -o -name '*.rst' \))
  fi
  MENTIONED=""
  if [ "${#DOCS[@]}" -gt 0 ]; then
    for TOKEN in "${NAMED[@]}"; do
      grep -qF -- "${TOKEN}" "${DOCS[@]}" && { MENTIONED="${TOKEN}"; break; }
    done
  fi
  if [ -n "${MENTIONED}" ]; then
    ok documented
  else
    bad documented
    echo "  no README/CONTRIBUTING/AGENTS.md/CLAUDE.md/docs file names the command (any of: ${NAMED[*]})"
  fi
else
  bad documented
  echo "  unassessable — no verify command"
fi

# 7. no leftover instrumentation in the implementation
if [ -f "${WORK}/versions.py" ] \
  && grep -qE 'breakpoint\(|import pdb|print\(' "${WORK}/versions.py"; then
  bad no-debug-leftovers
  echo "  leftover instrumentation in versions.py"
else
  ok no-debug-leftovers
fi

echo "SCORE ${PASS}/${TOTAL}"
[ "${PASS}" -eq "${TOTAL}" ]
