#!/usr/bin/env bash
# Offline grader for the merge-conflict task. Usage: grade.sh <workdir>
# Grades a worked copy of project/ on six criteria, printing one
# 'CRIT <id> pass|fail' line per criterion and a final 'SCORE n/m'; exits 0
# iff every criterion passes. Deterministic, no network, no API — test.sh
# smoke-runs it against reference/ (must pass), project/ (must fail) and
# every gamed*/ tree (must fail). gamed/ resolves the conflict by keeping
# only the HEAD side (member discount silently dropped, signature kept so
# the shipped tests stay green) — caught by the member-kept probe.
# gamed-notests/ merges both sides correctly but adds no tests — caught by
# the tests-bite mutant swap.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1   # never litter graded trees with __pycache__

TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${1:?usage: grade.sh <workdir>}"
WORK="$(cd "${WORK}" && pwd)"

PASS=0; TOTAL=6
ok()  { PASS=$((PASS + 1)); echo "CRIT $1 pass"; }
bad() { echo "CRIT $1 fail"; }

# 1. every conflict marker is gone from the tree
if grep -rqE '^(<{7} |={7}$|>{7} )' "${WORK}"; then
  bad no-markers
  echo "  conflict markers still present in the tree"
else
  ok no-markers
fi

# 2. the project's own tests pass
CRIT2=red
if (cd "${WORK}" && python3 -m unittest discover -s . -p 'test_*.py' >/dev/null 2>&1); then
  CRIT2=green
  ok suite-green
else
  bad suite-green
fi

# 3. main's bulk discount survived — probed on data the shipped tests never
#    mention, so a hardcoded lookup fails here
if (cd "${WORK}" && python3 -c '
from pricing import total
assert total([("brick", 12, 700)]) == 7560
assert total([("nail", 9, 700)]) == 6300
' >/dev/null 2>&1); then
  ok bulk-kept
else
  bad bulk-kept
  echo "  bulk discount (qty >= 10 -> line * 90 // 100) lost or wrong"
fi

# 4. the branch's member discount survived — same unseen-data rule
if (cd "${WORK}" && python3 -c '
from pricing import total
assert total([("pen", 2, 350)], member=True) == 665
assert total([("pen", 2, 350)]) == 700
' >/dev/null 2>&1); then
  ok member-kept
else
  bad member-kept
  echo "  member discount (member=True -> subtotal * 95 // 100) lost or wrong"
fi

# 5. the agreed stacking order holds: bulk per line first, then the member
#    rate on the result
if (cd "${WORK}" && python3 -c '
from pricing import total
assert total([("brick", 10, 500), ("pen", 3, 40)], member=True) == 4389
' >/dev/null 2>&1); then
  ok stacking
else
  bad stacking
  echo "  combined bulk+member total wrong — stacking order not honored"
fi

# 6. the worked tests actually cover both features: swap in each one-sided
#    feature mutant and the suite must go red both times. Only meaningful
#    when the suite was green in criterion 2 — a suite that is red for every
#    implementation proves nothing.
if [ "${CRIT2}" = green ]; then
  BITE_OK=1
  for M in head_only member_only; do
    RT="$(mktemp -d)"
    cp -R "${WORK}/." "${RT}/"
    cp "${TASK_DIR}/mutants/${M}.py" "${RT}/pricing.py"
    if (cd "${RT}" && python3 -m unittest discover -s . -p 'test_*.py' >/dev/null 2>&1); then
      BITE_OK=0
      echo "  suite stays green with the ${M} mutant — that side is untested"
    fi
    rm -rf "${RT}"
  done
  if [ "${BITE_OK}" = 1 ]; then
    ok tests-bite
  else
    bad tests-bite
  fi
else
  bad tests-bite
  echo "  unassessable — suite must be green first"
fi

echo "SCORE ${PASS}/${TOTAL}"
[ "${PASS}" -eq "${TOTAL}" ]
