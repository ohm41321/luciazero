#!/usr/bin/env bash
# A/B eval driver: does the doctrine measurably change agent behavior?
#
# For each task under eval/tasks/, runs the agent on a fresh copy per arm:
#   arm A (doctrine) — sandbox config with this repo installed
#   arm B (bare)     — empty sandbox config
# then grades both with the task's offline grade.sh.
#
# COSTS REAL INFERENCE — API dollars or subscription quota via --use-login —
# and requires the selected provider CLI. It is deliberately
# NOT part of test.sh/CI. Results are indicative, not proof: n is small and models
# are nondeterministic — run each arm several times and compare pass RATES
# (see eval/README.md). That is what --runs and --out exist for:
#
#   eval/run.sh [--provider claude|codex] [--model MODEL]
#               [--reasoning-effort LEVEL] [--runs N] [--out results.jsonl]
#               [--with-lessons] [--use-login] [task-name ...]
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
# --provider P    claude (default) or codex
# --model M       exact Codex model ID (default gpt-5.6-terra for codex)
# --reasoning-effort E  Codex effort (default medium)
# --use-login     seed each sandbox config dir with this machine's selected
#                 CLI login state, so runs use subscription quota instead of
#                 an API key. Copies are deleted with the config dir.
# --offline       synthetic smoke mode, zero API, no agent CLI needed:
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

PROVIDER=claude
MODEL=""
REASONING_EFFORT=""
RUNS=1
OUT_FILE=""
WITH_LESSONS=0
OFFLINE=0
USE_LOGIN=0
TASKS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --provider) PROVIDER="${2:?--provider needs claude or codex}"; shift 2 ;;
    --model) MODEL="${2:?--model needs an exact model ID}"; shift 2 ;;
    --reasoning-effort) REASONING_EFFORT="${2:?--reasoning-effort needs a level}"; shift 2 ;;
    --runs) RUNS="${2:?--runs needs a number}"; shift 2 ;;
    --out)  OUT_FILE="${2:?--out needs a path}"; shift 2 ;;
    --with-lessons) WITH_LESSONS=1; shift ;;
    --use-login) USE_LOGIN=1; shift ;;
    --offline) OFFLINE=1; shift ;;
    -*) echo "unknown option: $1 (see eval/README.md)" >&2; exit 1 ;;
    *) TASKS+=("$1"); shift ;;
  esac
done

case "${PROVIDER}" in
  claude)
    if [ -n "${MODEL}" ] || [ -n "${REASONING_EFFORT}" ]; then
      echo "FAIL: --model and --reasoning-effort require --provider codex" >&2
      exit 1
    fi
    ;;
  codex)
    MODEL="${MODEL:-gpt-5.6-terra}"
    REASONING_EFFORT="${REASONING_EFFORT:-medium}"
    case "${REASONING_EFFORT}" in
      minimal|low|medium|high|xhigh) ;;
      *) echo "FAIL: unsupported Codex reasoning effort: ${REASONING_EFFORT}" >&2; exit 1 ;;
    esac
    ;;
  *) echo "FAIL: --provider must be claude or codex" >&2; exit 1 ;;
esac

# Copy the operator's login state into a sandbox config dir. The CLI keeps
# top-level state (onboarding, account) in $CLAUDE_CONFIG_DIR/.claude.json and
# — on OSes without a keychain — OAuth tokens in .credentials.json; a fresh
# mktemp dir has neither, which is why an otherwise logged-in machine reads as
# "Not logged in" inside the sandbox. Deliberately fail-soft: a partial seed
# costs nothing, because check-result.sh rejects any "Not logged in" result.
seed_claude_login() {
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

REAL_CODEX_HOME="${CODEX_HOME:-${HOME}/.codex}"
seed_codex_login() {
  if [ -f "${REAL_CODEX_HOME}/auth.json" ]; then
    cp "${REAL_CODEX_HOME}/auth.json" "$1/auth.json"
    chmod 600 "$1/auth.json"
    echo "   Codex login state seeded into sandbox config"
  else
    echo "warn: --use-login found no Codex auth at ${REAL_CODEX_HOME}/auth.json" >&2
  fi
}

if [ "${OFFLINE}" = 1 ]; then
  echo "OFFLINE SMOKE MODE: synthetic trees, zero API — this tests the"
  echo "pipeline, it does NOT measure agent behavior. Never publish it."
  echo
else
  command -v "${PROVIDER}" >/dev/null 2>&1 \
    || { echo "FAIL: the '${PROVIDER}' CLI is required (or use --offline)" >&2; exit 1; }
fi
if [ "${#TASKS[@]}" -eq 0 ]; then
  for D in "${EVAL}/tasks"/*/; do TASKS+=("$(basename "${D}")"); done
fi

if [ "${PROVIDER}" = codex ]; then
  AGENT_VERSION="$(codex --version 2>/dev/null || true)"
  echo "eval: provider=codex, model=${MODEL}, reasoning=${REASONING_EFFORT}, ${#TASKS[@]} task(s), ${RUNS} run(s)/arm"
else
  AGENT_VERSION="$(claude --version 2>/dev/null || true)"
  echo "eval: provider=claude, ${#TASKS[@]} task(s), ${RUNS} run(s)/arm, args: ${CLAUDE_ARGS}"
fi
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
        if [ "${PROVIDER}" = codex ]; then
          seed_codex_login "${CFG}"
        else
          seed_claude_login "${CFG}"
        fi
      fi
      if [ "${ARM}" != bare ]; then
        if [ "${PROVIDER}" = codex ]; then
          CODEX_HOME="${CFG}" "${ROOT}/install-codex.sh" >/dev/null
        else
          CLAUDE_CONFIG_DIR="${CFG}" "${ROOT}/install.sh" >/dev/null
        fi
      fi
      if [ "${ARM}" = lessons ]; then
        mkdir -p "${WORK}/docs"
        cp "${TDIR}/lessons.md" "${WORK}/docs/lessons.md"
      fi

      echo "== ${TASK} / ${ARM} (run ${R}/${RUNS}) =="
      RC=0
      T0="$(date +%s)"
      LOG="${WORK}/agent.log"
      ERR_LOG="${WORK}/agent.stderr"
      if [ "${OFFLINE}" = 1 ]; then
        if [ "${ARM}" != bare ]; then cp -R "${TDIR}/reference/." "${WORK}/"; fi
        printf 'offline smoke — no agent was run\n' > "${LOG}"
      elif [ "${PROVIDER}" = codex ]; then
        (cd "${WORK}" && CODEX_HOME="${CFG}" codex exec \
          --model "${MODEL}" \
          --config "model_reasoning_effort=\"${REASONING_EFFORT}\"" \
          --config 'shell_environment_policy.inherit="core"' \
          --config 'shell_environment_policy.ignore_default_excludes=false' \
          --sandbox workspace-write \
          --ephemeral \
          --ignore-user-config \
          --ignore-rules \
          --skip-git-repo-check \
          --json \
          "$(cat "${TDIR}/PROMPT.md")" >"${LOG}" 2>"${ERR_LOG}") || RC=$?
      else
        # shellcheck disable=SC2086  # CLAUDE_ARGS is intentionally word-split
        (cd "${WORK}" && CLAUDE_CONFIG_DIR="${CFG}" \
          claude -p "$(cat "${TDIR}/PROMPT.md")" ${CLAUDE_ARGS} >"${LOG}" 2>&1) || RC=$?
      fi
      T1="$(date +%s)"

      INVALID=false
      GRADE_OUT=""
      GRADE_RC=0
      CHK=""
      INVALID_REASON=""
      if [ "${RC}" -ne 0 ]; then
        # An arm where the agent never ran is not behavioral data — grading it
        # would manufacture a fake doctrine-vs-bare delta.
        INVALID=true
        INVALID_REASON="${PROVIDER} exited ${RC}"
        if [ "${PROVIDER}" = codex ] \
          && ! CHK="$("${EVAL}/check-result.sh" --provider codex "${LOG}" 2>&1)"; then
          INVALID_REASON="${INVALID_REASON}; ${CHK#INVALID: }"
        fi
        echo "== ${TASK} / ${ARM}: INVALID — ${INVALID_REASON}; log tail:"
        tail -5 "${LOG}" | sed 's/^/   /'
        if [ -s "${ERR_LOG}" ]; then tail -5 "${ERR_LOG}" | sed 's/^/   /'; fi
      elif [ "${OFFLINE}" != 1 ] \
        && ! CHK="$("${EVAL}/check-result.sh" --provider "${PROVIDER}" "${LOG}" 2>&1)"; then
        # exit 0 does not prove the agent ran: the CLI has reported subtype
        # "success" around a "Not logged in" error payload before
        INVALID=true
        INVALID_REASON="${CHK}"
        echo "== ${TASK} / ${ARM}: ${CHK}"
      else
        GRADE_OUT="$("${TDIR}/grade.sh" "${WORK}")" || GRADE_RC=$?
        printf '%s\n' "${GRADE_OUT}" | sed 's/^/   /'
        # A grader that died mid-run (no SCORE line — they run under set -e)
        # produced an infrastructure error, not behavioral data; booking it as
        # an agent failure would poison the arm's pass rate.
        if ! printf '%s\n' "${GRADE_OUT}" | grep -q '^SCORE '; then
          INVALID=true
          INVALID_REASON="grader crashed (no SCORE line, rc=${GRADE_RC})"
          echo "== ${TASK} / ${ARM}: INVALID — grader crashed (no SCORE line, rc=${GRADE_RC})"
        elif [ "${GRADE_RC}" -eq 0 ]; then
          echo "== ${TASK} / ${ARM}: PASS"
        else
          echo "== ${TASK} / ${ARM}: FAIL"
        fi
      fi
      if [ -n "${OUT_FILE}" ]; then
        GRADE_OUT="${GRADE_OUT}" INVALID_REASON="${INVALID_REASON}" python3 -c '
import json, os, sys
task, arm, run, invalid, dur, log, offline, provider, requested_model, effort, cli_version = sys.argv[1:12]
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
tokens_in = tokens_out = cached_tokens = reasoning_tokens = None
cost_usd = num_turns = None
model = (requested_model or None) if provider == "codex" else None
try:
    if provider == "codex":
        completed = []
        with open(log) as f:
            for line in f:
                event = json.loads(line)
                if isinstance(event, dict) and event.get("type") == "turn.completed":
                    completed.append(event)
        usages = [e.get("usage") or {} for e in completed]
        def usage_total(field, required=False):
            values = []
            for usage in usages:
                if field not in usage:
                    if required:
                        return None
                    values.append(0)
                    continue
                value = usage[field]
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    return None
                values.append(value)
            return sum(values) if values else None
        tokens_in = usage_total("input_tokens", required=True)
        tokens_out = usage_total("output_tokens", required=True)
        cached_tokens = usage_total("cached_input_tokens")
        reasoning_tokens = usage_total("reasoning_output_tokens")
        num_turns = len(completed) or None
    else:
        with open(log) as f:
            res = json.load(f)
        usage = res.get("usage") or {}
        tokens_in = usage.get("input_tokens")
        tokens_out = usage.get("output_tokens")
        cost_usd = res.get("total_cost_usd")
        num_turns = res.get("num_turns")
        model = ",".join(sorted(res.get("modelUsage") or {})) or None
except (OSError, ValueError):
    pass
print(json.dumps({"task": task, "arm": arm, "run": int(run),
                  "invalid": invalid == "true", "criteria": crit,
                  "score": score, "duration_s": int(dur),
                  "tokens_in": tokens_in, "tokens_out": tokens_out,
                  "cached_input_tokens": cached_tokens,
                  "reasoning_output_tokens": reasoning_tokens,
                  "cost_usd": cost_usd, "num_turns": num_turns,
                  "provider": provider, "model": model,
                  "reasoning_effort": effort or None,
                  "cli_version": cli_version or None,
                  "invalid_reason": os.environ.get("INVALID_REASON") or None,
                  "offline": offline == "1"},
                 ensure_ascii=False))' \
          "${TASK}" "${ARM}" "${R}" "${INVALID}" "$((T1 - T0))" "${LOG}" "${OFFLINE}" \
          "${PROVIDER}" "${MODEL}" "${REASONING_EFFORT}" "${AGENT_VERSION}" >> "${OUT_FILE}"
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
