#!/usr/bin/env bash
# Run a test tier with per-gate timing and keep the sample, or rank the
# samples kept so far. Samples come from real work runs — run this instead of
# ./test.sh while collecting — so no benchmark time is spent on purpose.
#
#   scripts/test-timings.sh [--discipline|--fast|--full]   run, keep the sample
#   scripts/test-timings.sh --report                       median / p95 per gate
#
# A sample is three files under LZ_TEST_TIMINGS_DIR (default
# .test-timings/ in the checkout, git-ignored): <stamp>-<tier>.out, .err
# (the TIMING lines live here) and .meta (tier, os, commit, exit, wall). The
# tier's exit code is passed through. The report reads only green samples,
# names the commits they came from (warning when a tier's samples span more
# than one: a baseline is one revision's) and says how many red it skipped.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="${LZ_TEST_TIMINGS_DIR:-${ROOT}/.test-timings}"

case "${1:-}" in
  ""|--full) TIER=full ;;
  --fast) TIER=fast ;;
  --discipline) TIER=discipline ;;
  --report) TIER=report ;;
  *) echo "usage: scripts/test-timings.sh [--discipline|--fast|--full|--report]" >&2; exit 64 ;;
esac

if [ "${TIER}" = report ]; then
  python3 - "${DIR}" <<'PY'
import math, os, re, statistics, sys
from collections import defaultdict
d = sys.argv[1]
if not os.path.isdir(d):
    print(f"no samples under {d}"); sys.exit(0)
samples = defaultdict(list)   # (tier, gate) -> [seconds]
runs, skipped, walls, oses = defaultdict(int), 0, defaultdict(list), defaultdict(set)
commits = defaultdict(lambda: defaultdict(int))   # tier -> commit -> runs
for name in sorted(os.listdir(d)):
    if not name.endswith(".meta"):
        continue
    meta = dict(line.split("=", 1) for line in open(os.path.join(d, name)).read().splitlines() if "=" in line)
    if meta.get("exit") != "0":
        skipped += 1; continue
    tier = meta.get("tier", "?")
    runs[tier] += 1
    oses[tier].add(meta.get("os", "?"))
    commits[tier][meta.get("commit", "?")] += 1
    if meta.get("wall", "").isdigit():
        walls[tier].append(int(meta["wall"]))
    err = os.path.join(d, name[:-5] + ".err")
    for line in open(err).read().splitlines() if os.path.isfile(err) else []:
        m = re.match(r"^TIMING gate=([a-z-]+) seconds=(\d+)$", line)
        if m:
            samples[(tier, m.group(1))].append(int(m.group(2)))
def p95(xs):
    xs = sorted(xs); return xs[max(0, math.ceil(0.95 * len(xs)) - 1)]
print(f"{'tier':<11}{'gate':<15}{'n':>3} {'median':>7} {'p95':>5} {'min':>5} {'max':>5}")
for (tier, gate), xs in sorted(samples.items(), key=lambda kv: (kv[0][0], -statistics.median(kv[1]), kv[0][1])):
    print(f"{tier:<11}{gate:<15}{len(xs):>3} {statistics.median(xs):>7g} {p95(xs):>5} {min(xs):>5} {max(xs):>5}")
for tier in sorted(runs):
    w = walls[tier]
    wall = f", wall median {statistics.median(w):g}s p95 {p95(w)}s" if w else ""
    print(f"{tier}: {runs[tier]} green run(s) on {', '.join(sorted(oses[tier]))}{wall}")
    seen = commits[tier]
    print(f"{tier}: commits " + ", ".join(f"{c} x{n}" for c, n in sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))))
    if len(seen) > 1:
        # the samples are history, not one revision's baseline
        print(f"warning: {tier} samples span {len(seen)} revisions -- split them before reading a baseline; "
              "one sha+dirty can still be different trees")
if skipped:
    print(f"skipped {skipped} red run(s)")
PY
  exit 0
fi

mkdir -p "${DIR}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASE="${DIR}/${STAMP}-${TIER}"
COMMIT="$(git -C "${ROOT}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [ -n "$(git -C "${ROOT}" status --porcelain 2>/dev/null)" ]; then COMMIT="${COMMIT}+dirty"; fi
RC=0
SECONDS=0
# stdout streams through tee; stderr (FAIL and TIMING lines) goes to the
# file and is shown once the run ends — no process substitution, so this
# holds on bash 3.2 and the exit code is the tier's own (pipefail).
LZ_TEST_TIMINGS=1 "${ROOT}/test.sh" "--${TIER}" 2> "${BASE}.err" | tee "${BASE}.out" || RC=$?
WALL="${SECONDS}"
cat "${BASE}.err" >&2
printf 'tier=%s\nos=%s\ncommit=%s\nexit=%s\nwall=%s\nstamp=%s\n' \
  "${TIER}" "$(uname -s) $(uname -m)" "${COMMIT}" "${RC}" "${WALL}" "${STAMP}" > "${BASE}.meta"
echo "sample kept: ${BASE}.{out,err,meta} (exit ${RC}, ${WALL}s)" >&2
exit "${RC}"
