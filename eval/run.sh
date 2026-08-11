#!/usr/bin/env bash
# A/B eval driver: does the doctrine measurably change agent behavior?
#
# For each task under eval/tasks/, runs the agent on a fresh copy per arm:
#   arm A (doctrine) — sandbox config with this repo installed
#   arm B (bare)     — empty sandbox config
# then grades both with the task's offline grade.sh.
#
# COSTS REAL API MONEY and requires the `claude` CLI. It is deliberately NOT
# part of test.sh/CI. Results are indicative, not proof: n is small and models
# are nondeterministic — run each arm several times and compare pass RATES
# (see eval/README.md). That is what --runs and --out exist for:
#
#   eval/run.sh [--runs N] [--out results.jsonl] [--with-lessons] [task-name ...]
#
# --runs N        repeat every (task, arm) N times (default 1)
# --out F         append one JSON line per (task, arm, run) to F — criteria
#                 parsed from the grader's CRIT lines, plus token/cost usage
#                 parsed from the CLI's JSON output (null when unavailable);
#                 render with eval/report.sh F
# --with-lessons  add a third arm (lessons) to every task that ships a
#                 lessons.md: same doctrine install, plus the task's ledger
#                 pre-seeded as docs/lessons.md in the work copy — measures
#                 whether the learning layer lifts pass rates over doctrine
#                 alone. Tasks without a lessons.md keep two arms.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVAL="${ROOT}/eval"
command -v claude >/dev/null 2>&1 || { echo "FAIL: the 'claude' CLI is required" >&2; exit 1; }

# --output-format json makes the CLI print one result object (usage, cost,
# turn count) to claude.log; the usage parse below fails open to nulls if an
# EVAL_CLAUDE_ARGS override drops it.
CLAUDE_ARGS=${EVAL_CLAUDE_ARGS:-"--permission-mode bypassPermissions --max-turns 40 --output-format json"}

RUNS=1
OUT_FILE=""
WITH_LESSONS=0
TASKS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --runs) RUNS="${2:?--runs needs a number}"; shift 2 ;;
    --out)  OUT_FILE="${2:?--out needs a path}"; shift 2 ;;
    --with-lessons) WITH_LESSONS=1; shift ;;
    -*) echo "unknown option: $1 (supported: --runs N, --out FILE, --with-lessons)" >&2; exit 1 ;;
    *) TASKS+=("$1"); shift ;;
  esac
done
if [ "${#TASKS[@]}" -eq 0 ]; then
  for D in "${EVAL}/tasks"/*/; do TASKS+=("$(basename "${D}")"); done
fi

echo "eval: ${#TASKS[@]} task(s), ${RUNS} run(s)/arm, args: ${CLAUDE_ARGS}"
echo

for TASK in "${TASKS[@]}"; do
  TDIR="${EVAL}/tasks/${TASK}"
  [ -f "${TDIR}/PROMPT.md" ] || { echo "skip ${TASK}: no PROMPT.md"; continue; }

  ARMS=(doctrine bare)
  if [ "${WITH_LESSONS}" = 1 ]; then
    if [ -f "${TDIR}/lessons.md" ]; then
      ARMS=(doctrine bare lessons)
    else
      echo "note ${TASK}: no lessons.md — lessons arm skipped"
    fi
  fi

  R=1
  while [ "${R}" -le "${RUNS}" ]; do
    for ARM in "${ARMS[@]}"; do
      CFG="$(mktemp -d)"
      WORK="$(mktemp -d)"
      cp -R "${TDIR}/project/." "${WORK}/"

      if [ "${ARM}" != bare ]; then
        CLAUDE_CONFIG_DIR="${CFG}" "${ROOT}/install.sh" >/dev/null
      fi
      if [ "${ARM}" = lessons ]; then
        mkdir -p "${WORK}/docs"
        cp "${TDIR}/lessons.md" "${WORK}/docs/lessons.md"
      fi

      echo "== ${TASK} / ${ARM} (run ${R}/${RUNS}) =="
      RC=0
      T0="$(date +%s)"
      # shellcheck disable=SC2086  # CLAUDE_ARGS is intentionally word-split
      (cd "${WORK}" && CLAUDE_CONFIG_DIR="${CFG}" \
        claude -p "$(cat "${TDIR}/PROMPT.md")" ${CLAUDE_ARGS} >"${WORK}/claude.log" 2>&1) || RC=$?
      T1="$(date +%s)"

      INVALID=false
      GRADE_OUT=""
      GRADE_RC=0
      if [ "${RC}" -ne 0 ]; then
        # An arm where the agent never ran is not behavioral data — grading it
        # would manufacture a fake doctrine-vs-bare delta.
        INVALID=true
        echo "== ${TASK} / ${ARM}: INVALID — claude exited ${RC}; log tail:"
        tail -5 "${WORK}/claude.log" | sed 's/^/   /'
      else
        GRADE_OUT="$("${TDIR}/grade.sh" "${WORK}")" || GRADE_RC=$?
        printf '%s\n' "${GRADE_OUT}" | sed 's/^/   /'
        # A grader that died mid-run (no SCORE line — they run under set -e)
        # produced an infrastructure error, not behavioral data; booking it as
        # an agent failure would poison the arm's pass rate.
        if ! printf '%s\n' "${GRADE_OUT}" | grep -q '^SCORE '; then
          INVALID=true
          echo "== ${TASK} / ${ARM}: INVALID — grader crashed (no SCORE line, rc=${GRADE_RC})"
        elif [ "${GRADE_RC}" -eq 0 ]; then
          echo "== ${TASK} / ${ARM}: PASS"
        else
          echo "== ${TASK} / ${ARM}: FAIL"
        fi
      fi
      if [ -n "${OUT_FILE}" ]; then
        GRADE_OUT="${GRADE_OUT}" python3 -c '
import json, os, sys
task, arm, run, invalid, dur, log = sys.argv[1:7]
crit = {}
score = None
for line in os.environ.get("GRADE_OUT", "").splitlines():
    p = line.split()
    if len(p) == 3 and p[0] == "CRIT":
        crit[p[1]] = (p[2] == "pass")
    elif len(p) == 2 and p[0] == "SCORE":
        score = p[1]
# usage/cost from the CLI result object — fail open to nulls on any shape
# surprise (text output, truncated log, override without --output-format json)
tokens_in = tokens_out = cost_usd = num_turns = None
try:
    with open(log) as f:
        res = json.load(f)
    usage = res.get("usage") or {}
    tokens_in = usage.get("input_tokens")
    tokens_out = usage.get("output_tokens")
    cost_usd = res.get("total_cost_usd")
    num_turns = res.get("num_turns")
except (OSError, ValueError):
    pass
print(json.dumps({"task": task, "arm": arm, "run": int(run),
                  "invalid": invalid == "true", "criteria": crit,
                  "score": score, "duration_s": int(dur),
                  "tokens_in": tokens_in, "tokens_out": tokens_out,
                  "cost_usd": cost_usd, "num_turns": num_turns},
                 ensure_ascii=False))' \
          "${TASK}" "${ARM}" "${R}" "${INVALID}" "$((T1 - T0))" "${WORK}/claude.log" >> "${OUT_FILE}"
      fi
      echo "   workdir kept for inspection: ${WORK}"
      rm -rf "${CFG}"
      echo
    done
    R=$((R + 1))
  done
done

if [ -n "${OUT_FILE}" ]; then
  echo "results appended to ${OUT_FILE} — render with: eval/report.sh ${OUT_FILE}"
fi
