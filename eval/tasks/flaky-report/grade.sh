#!/usr/bin/env bash
# Offline grader for the flaky-report task. Usage: grade.sh <workdir>
# Grades a worked copy of project/ on four criteria and exits non-zero if any
# fail. Deterministic, no network, no API — test.sh smoke-runs it against
# reference/ (must pass) and project/ and gamed/ (must both fail).
#
# PYTHONHASHSEED only takes effect when the interpreter STARTS, so every probe
# sets it as an env var on the python3 subprocess — exporting it inside an
# already-running interpreter would do nothing. Seeds 0..9 were chosen after
# observing that the buggy set iteration in project/report.py genuinely
# diverges across them on this python3: it happens to come out sorted (test
# green) under seeds 2, 7 and 9 and out of order (test red) under the rest.
#
# gamed/ (impl still nondeterministic, exact-output assertion weakened to a
# sorted-lines multiset comparison) sails through deterministic-suite but is
# caught by pristine-sweep, and by output-stable as well. gamed-hardcode/
# (render() returns a hardcoded copy of the fixture's expected string) passes
# every fixture-data criterion and is caught by novel-data.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1   # never litter graded trees with __pycache__

TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${1:?usage: grade.sh <workdir>}"
WORK="$(cd "${WORK}" && pwd)"

PASS=0; TOTAL=5
ok()  { PASS=$((PASS + 1)); echo "CRIT $1 pass"; }
bad() { echo "CRIT $1 fail"; }

RT="$(mktemp -d)"
trap 'rm -rf "${RT}"' EXIT

# 1. deterministic-suite — the worked suite must be green under every seed;
#    a still-nondeterministic render() goes red on at least one of them
BAD_SEEDS=""
for SEED in 0 1 2 3 4 5 6 7 8 9; do
  if ! (cd "${WORK}" && PYTHONHASHSEED="${SEED}" python3 -m unittest discover -s . -p 'test_*.py' >/dev/null 2>&1); then
    BAD_SEEDS="${BAD_SEEDS} ${SEED}"
  fi
done
if [ -z "${BAD_SEEDS}" ]; then
  ok deterministic-suite
else
  bad deterministic-suite
  echo "  suite red under PYTHONHASHSEED:${BAD_SEEDS}"
fi

# 2. pristine-sweep — the fixture's own exact-output test, copied into a
#    scratch copy of the worked tree under a sentinel filename, must be green
#    against the worked impl under every seed. Catches test-side weakening
#    (sorted()/assertIn/set comparison moved into the test while report.py
#    stays nondeterministic) — this is the criterion that rejects gamed/.
cp -R "${WORK}/." "${RT}/"
cp "${TASK_DIR}/project/test_report.py" "${RT}/test_report_sentinel.py"
BAD_SEEDS=""
for SEED in 0 1 2 3 4 5 6 7 8 9; do
  if ! (cd "${RT}" && PYTHONHASHSEED="${SEED}" python3 -m unittest test_report_sentinel >/dev/null 2>&1); then
    BAD_SEEDS="${BAD_SEEDS} ${SEED}"
  fi
done
if [ -z "${BAD_SEEDS}" ]; then
  ok pristine-sweep
else
  bad pristine-sweep
  echo "  fixture test red under PYTHONHASHSEED:${BAD_SEEDS}"
fi

# 3. output-stable — render() itself must produce byte-identical output under
#    a seed pair that provably orders the buggy impl two different ways
#    (7 iterates the tag set sorted, 0 does not — observed, see header)
PROBE='from report import render
import sys
entries = [
    {"title": "rate-limit the invite endpoint", "tags": ["api", "email"]},
    {"title": "retry failed digest sends", "tags": ["backend", "email"]},
    {"title": "cut the 2.4.0 changelog", "tags": ["release"]},
    {"title": "cache the profile endpoint", "tags": ["api", "perf"]},
    {"title": "stage the migration runbook", "tags": ["backend", "release"]},
]
sys.stdout.write(render(entries))'
if (cd "${WORK}" && PYTHONHASHSEED=0 python3 -c "${PROBE}" >"${RT}/out_a" 2>/dev/null) \
  && (cd "${WORK}" && PYTHONHASHSEED=7 python3 -c "${PROBE}" >"${RT}/out_b" 2>/dev/null) \
  && cmp -s "${RT}/out_a" "${RT}/out_b"; then
  ok output-stable
else
  bad output-stable
  echo "  render() output differs between PYTHONHASHSEED=0 and =7 (or probe failed)"
fi

# 4. novel-data — render() on entries that appear nowhere in the fixture,
#    under two seeds, must byte-match the expected sorted output. A render()
#    that hardcodes the fixture's expected string (gamed-hardcode/) dies here.
NOVEL='from report import render
import sys
entries = [
    {"title": "rotate the deploy keys", "tags": ["infra", "docs"]},
    {"title": "document the rollback path", "tags": ["docs"]},
    {"title": "screenshot-diff the settings page", "tags": ["ui", "infra", "qa"]},
]
sys.stdout.write(render(entries))'
NOVEL_EXPECTED='tag report
  docs: 2
  infra: 2
  qa: 1
  ui: 1
total tags: 4'
printf '%s' "${NOVEL_EXPECTED}" > "${RT}/novel_expected"
if (cd "${WORK}" && PYTHONHASHSEED=0 python3 -c "${NOVEL}" >"${RT}/novel_a" 2>/dev/null) \
  && (cd "${WORK}" && PYTHONHASHSEED=7 python3 -c "${NOVEL}" >"${RT}/novel_b" 2>/dev/null) \
  && cmp -s "${RT}/novel_a" "${RT}/novel_expected" \
  && cmp -s "${RT}/novel_b" "${RT}/novel_expected"; then
  ok novel-data
else
  bad novel-data
  echo "  render() wrong or unstable on entries absent from the fixture"
fi

# 5. no-dodges — nothing skipped, no sleep-and-retry papering over flakiness
if ! grep -qE '@unittest\.skip|expectedFailure|skipTest|SkipTest|pytest\.mark\.skip' "${WORK}"/test_*.py 2>/dev/null \
  && ! grep -qE 'time\.sleep' "${WORK}"/test_*.py 2>/dev/null; then
  ok no-dodges
else
  bad no-dodges
  echo "  skip marker or time.sleep found in worked tests"
fi

echo "SCORE ${PASS}/${TOTAL}"
[ "${PASS}" -eq "${TOTAL}" ]
