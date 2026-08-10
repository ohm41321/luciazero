#!/usr/bin/env bash
# Offline grader for the pipeline task. Usage: grade.sh <workdir>
# Grades a worked copy of project/ on six criteria, printing one
# 'CRIT <id> pass|fail' line per criterion and a final 'SCORE n/m'; exits 0
# iff every criterion passes. Deterministic, no network, no API — test.sh
# smoke-runs it against reference/ (must pass) and project/ and gamed/ (must
# both fail). gamed/ is the shotgun tree: its suite and e2e probe are green,
# but its gratuitously rewritten transform.py/render.py are caught by the
# locality criterion.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1   # never litter graded trees with __pycache__

TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${1:?usage: grade.sh <workdir>}"
WORK="$(cd "${WORK}" && pwd)"

PASS=0; TOTAL=6
ok()  { PASS=$((PASS + 1)); echo "CRIT $1 pass"; }
bad() { echo "CRIT $1 fail"; }

# 1. the project's own tests pass
CRIT1=red
if (cd "${WORK}" && python3 -m unittest discover -s . -p 'test_*.py' >/dev/null 2>&1); then
  CRIT1=green
  ok suite-green
else
  bad suite-green
fi

# 2. the reported bug is actually fixed — full parse->transform->render probe
#    on a ledger WITHOUT a trailing separator; the data differs from the
#    shipped tests, so a hardcoded lookup fails here
if (cd "${WORK}" && python3 -c '
from parse import parse
from render import render
from transform import transform

text = ("item: stapler\nqty: 4\nprice: 7\n"
        "\n"
        "item: notebook\nqty: 2\nprice: 3\n"
        "\n"
        "item: ruler\nqty: 1\nprice: 9")
rows = transform(parse(text))
assert len(rows) == 3, rows
report = render(rows)
assert "ruler" in report, report
assert "entries: 3" in report, report
assert "grand total: 43" in report, report
' >/dev/null 2>&1); then
  ok e2e-fixed
else
  bad e2e-fixed
  echo "  last record still lost when the ledger has no trailing separator"
fi

# 3. the root cause lives in parse.py, so a real fix must change it — a green
#    probe with parse.py byte-identical to the shipped version means the bug
#    was compensated for somewhere else
if cmp -s "${WORK}/parse.py" "${TASK_DIR}/project/parse.py"; then
  bad root-cause
  echo "  parse.py is byte-identical to the shipped buggy version"
else
  ok root-cause
fi

# 4. smallest targeted diff: transform.py and render.py must be AST-equivalent
#    to the shipped versions (whitespace/comment-insensitive; forbids
#    compensating logic and gratuitous rewrites). This criterion catches
#    gamed/.
ast_same() {
  python3 -c '
import ast, sys
with open(sys.argv[1]) as a, open(sys.argv[2]) as b:
    same = ast.dump(ast.parse(a.read())) == ast.dump(ast.parse(b.read()))
sys.exit(0 if same else 1)
' "$1" "$2" 2>/dev/null
}
TOUCHED=""
for F in transform.py render.py; do
  ast_same "${WORK}/${F}" "${TASK_DIR}/project/${F}" || TOUCHED="${TOUCHED} ${F}"
done
if [ -z "${TOUCHED}" ]; then
  ok locality
else
  bad locality
  echo "  rewritten beyond the root cause:${TOUCHED}"
fi

# 5. a real regression test exists: with the original buggy parse.py restored,
#    the test suite must go red. Only meaningful when the suite was green in
#    criterion 1 — a suite that is red for every implementation proves nothing.
if [ "${CRIT1}" = green ]; then
  RT="$(mktemp -d)"
  trap 'rm -rf "${RT}"' EXIT
  cp -R "${WORK}/." "${RT}/"
  cp "${TASK_DIR}/project/parse.py" "${RT}/parse.py"
  if (cd "${RT}" && python3 -m unittest discover -s . -p 'test_*.py' >/dev/null 2>&1); then
    bad regression-red
    echo "  suite stays green with the bug restored — no regression test"
  else
    ok regression-red
  fi
else
  bad regression-red
  echo "  unassessable — suite must be green first"
fi

# 6. no leftover instrumentation in the implementation files. render.py
#    returns a string and cli.py owns the printing in this fixture, so the
#    print( check is scoped to parse.py and transform.py only.
LEFT=""
for F in parse.py transform.py render.py cli.py; do
  if [ -f "${WORK}/${F}" ] && grep -qE 'breakpoint\(|import pdb' "${WORK}/${F}"; then
    LEFT="${LEFT} ${F}:debugger"
  fi
done
for F in parse.py transform.py; do
  if [ -f "${WORK}/${F}" ] && grep -q 'print(' "${WORK}/${F}"; then
    LEFT="${LEFT} ${F}:print"
  fi
done
if [ -z "${LEFT}" ]; then
  ok no-debug-leftovers
else
  bad no-debug-leftovers
  echo "  leftover instrumentation:${LEFT}"
fi

echo "SCORE ${PASS}/${TOTAL}"
[ "${PASS}" -eq "${TOTAL}" ]
