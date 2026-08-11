#!/usr/bin/env bash
# A/B eval driver: does the doctrine measurably change agent behavior?
#
# For each task under eval/tasks/, runs the agent on a fresh copy per arm:
#   arm A (doctrine) — sandbox config with this repo installed
#   arm B (bare)     — empty sandbox config
# then grades both with the task's offline grade.sh.
#
# COSTS REAL INFERENCE — API dollars via ANTHROPIC_API_KEY, or subscription
# quota via --use-login — and requires the `claude` CLI. It is deliberately
# NOT part of test.sh/CI. Results are indicative, not proof: n is small and models
# are nondeterministic — run each arm several times and compare pass RATES
# (see eval/README.md). That is what --runs and --out exist for:
#
#   eval/run.sh [--runs N] [--out results.jsonl] [--with-lessons] [--use-login] [task-name ...]
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
# --use-login     seed each sandbox config dir with this machine's Claude
#                 login state (~/.claude.json, and .credentials.json when the
#                 OS stores tokens on disk instead of a keychain) so runs bill
#                 the operator's existing subscription quota instead of
#                 needing ANTHROPIC_API_KEY. The copies live only inside the
#                 per-run mktemp config dir and are deleted with it; nothing
#                 leaves the machine. Fail-soft: if the seed is not enough to
#                 authenticate, check-result.sh marks the arm INVALID — no
#                 quota is spent on an arm that never ran.
# --offline       synthetic smoke mode, zero API, no claude CLI needed:
#                 doctrine-style arms get the task's reference/ tree, bare
#                 keeps the planted bug. Exercises copy -> grade -> JSONL ->
#                 report end to end. NOT agent behavior: rows are marked
#                 "offline": true and report.sh brands the output SYNTHETIC.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVAL="${ROOT}/eval"

# --output-format json makes the CLI print one result object (usage, cost,
# turn count) to claude.log; the usage parse below fails open to nulls if an
# EVAL_CLAUDE_ARGS override drops it.
CLAUDE_ARGS=${EVAL_CLAUDE_ARGS:-"--permission-mode bypassPermissions --max-turns 40 --output-format json"}

RUNS=1
OUT_FILE=""
WITH_LESSONS=0
OFFLINE=0
USE_LOGIN=0
TASKS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --runs) RUNS="${2:?--runs needs a number}"; shift 2 ;;
    --out)  OUT_FILE="${2:?--out needs a path}"; shift 2 ;;
    --with-lessons) WITH_LESSONS=1; shift ;;
    --use-login) USE_LOGIN=1; shift ;;
    --offline) OFFLINE=1; shift ;;
    -*) echo "unknown option: $1 (supported: --runs N, --out FILE, --with-lessons, --use-login, --offline)" >&2; exit 1 ;;
    *) TASKS+=("$1"); shift ;;
  esac
done

# Copy the operator's login state into a sandbox config dir. The CLI keeps
# top-level state (onboarding, account) in $CLAUDE_CONFIG_DIR/.claude.json and
# — on OSes without a keychain — OAuth tokens in .credentials.json; a fresh
# mktemp dir has neither, which is why an otherwise logged-in machine reads as
# "Not logged in" inside the sandbox. Deliberately fail-soft: a partial seed
# costs nothing, because check-result.sh rejects any "Not logged in" result.
seed_login() {
  SEEDED=0
  if [ -f "${HOME}/.claude.json" ]; then
    cp "${HOME}/.claude.json" "$1/.claude.json"
    SEEDED=1
  fi
  if [ -f "${HOME}/.claude/.credentials.json" ]; then
    cp "${HOME}/.claude/.credentials.json" "$1/.credentials.json"
    chmod 600 "$1/.credentials.json"
    SEEDED=1
  fi
  # macOS keeps OAuth tokens in the Keychain, not on disk — export them into
  # the sandbox as .credentials.json. A denied or missing Keychain item just
  # skips this (fail-soft, see above).
  if [ ! -f "$1/.credentials.json" ] && command -v security >/dev/null 2>&1; then
    if CRED="$(security find-generic-password -s 'Claude Code-credentials' -w 2>/dev/null)" \
      && [ -n "${CRED}" ]; then
      printf '%s\n' "${CRED}" > "$1/.credentials.json"
      chmod 600 "$1/.credentials.json"
      SEEDED=1
      echo "   keychain credentials exported into sandbox config"
    fi
  fi
  if [ "${SEEDED}" = 1 ]; then
    echo "   login state seeded into sandbox config"
  else
    echo "warn: --use-login found no login state under ${HOME} (expected ~/.claude.json)" >&2
  fi
}

if [ "${OFFLINE}" = 1 ]; then
  echo "OFFLINE SMOKE MODE: synthetic trees, zero API — this tests the"
  echo "pipeline, it does NOT measure agent behavior. Never publish it."
  echo
else
  command -v claude >/dev/null 2>&1 || { echo "FAIL: the 'claude' CLI is required (or use --offline)" >&2; exit 1; }
fi
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

      if [ "${USE_LOGIN}" = 1 ]; then
        seed_login "${CFG}"
      fi
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
      if [ "${OFFLINE}" = 1 ]; then
        if [ "${ARM}" != bare ]; then cp -R "${TDIR}/reference/." "${WORK}/"; fi
        printf 'offline smoke — no agent was run\n' > "${WORK}/claude.log"
      else
        # shellcheck disable=SC2086  # CLAUDE_ARGS is intentionally word-split
        (cd "${WORK}" && CLAUDE_CONFIG_DIR="${CFG}" \
          claude -p "$(cat "${TDIR}/PROMPT.md")" ${CLAUDE_ARGS} >"${WORK}/claude.log" 2>&1) || RC=$?
      fi
      T1="$(date +%s)"

      INVALID=false
      GRADE_OUT=""
      GRADE_RC=0
      CHK=""
      if [ "${RC}" -ne 0 ]; then
        # An arm where the agent never ran is not behavioral data — grading it
        # would manufacture a fake doctrine-vs-bare delta.
        INVALID=true
        echo "== ${TASK} / ${ARM}: INVALID — claude exited ${RC}; log tail:"
        tail -5 "${WORK}/claude.log" | sed 's/^/   /'
      elif [ "${OFFLINE}" != 1 ] \
        && ! CHK="$("${EVAL}/check-result.sh" "${WORK}/claude.log" 2>&1)"; then
        # exit 0 does not prove the agent ran: the CLI has reported subtype
        # "success" around a "Not logged in" error payload before
        INVALID=true
        echo "== ${TASK} / ${ARM}: ${CHK}"
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
task, arm, run, invalid, dur, log, offline = sys.argv[1:8]
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
                  "cost_usd": cost_usd, "num_turns": num_turns,
                  "offline": offline == "1"},
                 ensure_ascii=False))' \
          "${TASK}" "${ARM}" "${R}" "${INVALID}" "$((T1 - T0))" "${WORK}/claude.log" "${OFFLINE}" >> "${OUT_FILE}"
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
