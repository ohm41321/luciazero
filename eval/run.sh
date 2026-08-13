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
#               [--seed SEED] [--campaign-id ID] [--run-offset N]
#               [--resume] [--with-lessons] [--use-login] [--allow-dirty]
#               [task-name ...]
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
# --seed S        deterministically randomize arm order within each task/run;
#                 defaults to a new 64-bit seed printed and stored in every row
# --campaign-id I stable identifier for this invocation batch; defaults to a
#                 timestamp + repository commit + seed identifier
# --run-offset N  number the first repetition N+1 (default 0); use only to
#                 extend a fully completed batch, never to skip interrupted gaps
# --resume        validate a non-empty existing --out campaign and skip IDs
#                 already present; requires explicit --campaign-id and --seed
# --allow-dirty   permit a real run from a dirty checkout; recorded in every
#                 row, but unsuitable for published evidence
# --use-login     seed each sandbox config dir with this machine's selected
#                 CLI login state, so runs use subscription quota instead of
#                 an API key. Copies are deleted with the config dir.
# --offline       synthetic smoke mode, zero API, no agent CLI needed:
#                 after optional task setup, doctrine-style arms get the
#                 task's reference/ overlay; bare keeps the planted bug.
#                 Exercises copy -> grade -> JSONL -> report end to end.
#                 NOT agent behavior: rows are marked
#                 "offline": true and report.sh brands the output SYNTHETIC.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVAL="${ROOT}/eval"

# --output-format json makes the CLI print one result object (usage, cost,
# turn count) to the provider log; the usage parse below fails open to nulls if an
# EVAL_CLAUDE_ARGS override drops it.
CLAUDE_ARGS=${EVAL_CLAUDE_ARGS:-"--permission-mode bypassPermissions --max-turns 40 --output-format json"}

PROVIDER=claude
MODEL=""
REASONING_EFFORT=""
RUNS=1
RUN_OFFSET=0
OUT_FILE=""
WITH_LESSONS=0
OFFLINE=0
USE_LOGIN=0
RUN_SEED=""
RUN_SEED_EXPLICIT=0
CAMPAIGN_ID=""
CAMPAIGN_ID_EXPLICIT=0
ALLOW_DIRTY=0
RESUME=0
TASKS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --provider) PROVIDER="${2:?--provider needs claude or codex}"; shift 2 ;;
    --model) MODEL="${2:?--model needs an exact model ID}"; shift 2 ;;
    --reasoning-effort) REASONING_EFFORT="${2:?--reasoning-effort needs a level}"; shift 2 ;;
    --runs) RUNS="${2:?--runs needs a number}"; shift 2 ;;
    --run-offset) RUN_OFFSET="${2:?--run-offset needs a number}"; shift 2 ;;
    --out)  OUT_FILE="${2:?--out needs a path}"; shift 2 ;;
    --seed) RUN_SEED="${2:?--seed needs a value}"; RUN_SEED_EXPLICIT=1; shift 2 ;;
    --campaign-id) CAMPAIGN_ID="${2:?--campaign-id needs a value}"; CAMPAIGN_ID_EXPLICIT=1; shift 2 ;;
    --resume) RESUME=1; shift ;;
    --allow-dirty) ALLOW_DIRTY=1; shift ;;
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

case "${RUNS}" in
  ''|*[!0-9]*) echo "FAIL: --runs must be a positive integer" >&2; exit 1 ;;
esac
[ "${RUNS}" -gt 0 ] || { echo "FAIL: --runs must be a positive integer" >&2; exit 1; }
case "${RUN_OFFSET}" in
  ''|*[!0-9]*) echo "FAIL: --run-offset must be a non-negative integer" >&2; exit 1 ;;
esac
RUNS=$((10#${RUNS}))
RUN_OFFSET=$((10#${RUN_OFFSET}))
LAST_RUN=$((RUN_OFFSET + RUNS))
if [ "${RESUME}" = 1 ]; then
  [ -n "${OUT_FILE}" ] || { echo "FAIL: --resume requires --out" >&2; exit 1; }
  if [ "${RUN_SEED_EXPLICIT}" != 1 ] || [ "${CAMPAIGN_ID_EXPLICIT}" != 1 ]; then
    echo "FAIL: --resume requires explicit --campaign-id and --seed" >&2
    exit 1
  fi
  [ -s "${OUT_FILE}" ] || {
    echo "FAIL: --resume requires an existing non-empty --out file" >&2
    exit 1
  }
fi

RUN_SEED="${RUN_SEED:-$(python3 -c 'import secrets; print(secrets.randbits(64))')}"
STARTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
REPOSITORY_COMMIT="$(git -C "${ROOT}" rev-parse HEAD 2>/dev/null || printf unknown)"
if [ -n "$(git -C "${ROOT}" status --porcelain 2>/dev/null || true)" ]; then
  REPOSITORY_DIRTY=true
  DIRTY_LABEL="-dirty"
else
  REPOSITORY_DIRTY=false
  DIRTY_LABEL=""
fi
SYSTEM_NAME="$(uname -s 2>/dev/null || printf unknown)"
SYSTEM_ARCH="$(uname -m 2>/dev/null || printf unknown)"
if [ -z "${CAMPAIGN_ID}" ]; then
  CAMPAIGN_ID="$(date -u '+%Y%m%dT%H%M%SZ')-${REPOSITORY_COMMIT:0:12}-${RUN_SEED:0:12}"
fi
if [ "${OFFLINE}" != 1 ] && [ "${REPOSITORY_DIRTY}" = true ] \
  && [ "${ALLOW_DIRTY}" != 1 ]; then
  echo "FAIL: real eval requires a clean checkout for reproducibility" >&2
  echo "      commit/stash changes, or pass --allow-dirty for a non-publishable run" >&2
  exit 1
fi
if [ "${OFFLINE}" != 1 ] && [ "${REPOSITORY_COMMIT}" = unknown ] \
  && [ "${ALLOW_DIRTY}" != 1 ]; then
  echo "FAIL: real eval requires a Git commit for reproducibility" >&2
  echo "      run from a Git checkout, or pass --allow-dirty for a non-publishable run" >&2
  exit 1
fi

tree_hash() {
  python3 - "$1" <<'PY'
import hashlib, pathlib, sys
root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
for path in sorted(p for p in root.rglob("*") if p.is_file()):
    relative = path.relative_to(root)
    if "__pycache__" in relative.parts or path.suffix == ".pyc":
        continue
    digest.update(str(relative).encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.read_bytes())
    digest.update(b"\0")
print(digest.hexdigest())
PY
}

ordered_arms() {
  python3 - "${RUN_SEED}" "$1" "$2" "${@:3}" <<'PY'
import hashlib, sys
seed, task, run, *arms = sys.argv[1:]
for arm in sorted(arms, key=lambda value: hashlib.sha256(
        f"{seed}\0{task}\0{run}\0{value}".encode()).digest()):
    print(arm)
PY
}

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
  RUNNER_PROFILE="codex exec --model ${MODEL} --config model_reasoning_effort=${REASONING_EFFORT} --config shell_environment_policy.inherit=core --config shell_environment_policy.ignore_default_excludes=false --sandbox workspace-write --ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check --json"
  echo "eval: provider=codex, model=${MODEL}, reasoning=${REASONING_EFFORT}, ${#TASKS[@]} task(s), ${RUNS} run(s)/arm"
else
  AGENT_VERSION="$(claude --version 2>/dev/null || true)"
  RUNNER_PROFILE="claude -p ${CLAUDE_ARGS}"
  echo "eval: provider=claude, ${#TASKS[@]} task(s), ${RUNS} run(s)/arm, args: ${CLAUDE_ARGS}"
fi
echo "campaign=${CAMPAIGN_ID}, seed=${RUN_SEED}, commit=${REPOSITORY_COMMIT}${DIRTY_LABEL}"
echo

RECORDED_INVOCATIONS=()
if [ "${RESUME}" = 1 ]; then
  RESUME_INDEX="$(python3 - "${OUT_FILE}" "${EVAL}" "${CAMPAIGN_ID}" \
    "${RUN_SEED}" "${PROVIDER}" "${MODEL}" "${REASONING_EFFORT}" \
    "${AGENT_VERSION}" "${REPOSITORY_COMMIT}" "${REPOSITORY_DIRTY}" \
    "${OFFLINE}" "${SYSTEM_NAME}" "${SYSTEM_ARCH}" "${RUNNER_PROFILE}" <<'PY'
import json, pathlib, sys
sys.path.insert(0, sys.argv[2])
from result_schema import validate_result_row

(path, _, campaign_id, seed, provider, requested_model, effort, cli_version,
 repository_commit, repository_dirty, offline, system, architecture,
 runner_profile) = sys.argv[1:15]
expected = {
    "campaign_id": campaign_id, "seed": seed, "provider": provider,
    "requested_model": requested_model or None,
    "reasoning_effort": effort or None,
    "repository_commit": repository_commit,
    "repository_dirty": repository_dirty == "true",
    "offline": offline == "1", "system": system,
    "architecture": architecture, "runner_profile": runner_profile,
}
rows = []
payload = pathlib.Path(path).read_bytes()
if payload and not payload.endswith(b"\n"):
    raise SystemExit("FAIL: --resume output must end with a newline")
with open(path, encoding="utf-8") as stream:
    for line_number, line in enumerate(stream, 1):
        if not line.strip():
            continue
        try:
            row = validate_result_row(json.loads(line), source=f"{path}:{line_number}")
        except (json.JSONDecodeError, ValueError) as exc:
            raise SystemExit(f"FAIL: cannot resume malformed output ({exc})")
        if row["result_schema"] != 2:
            raise SystemExit("FAIL: --resume requires schema-v2 output")
        mismatched = [field for field, value in expected.items() if row.get(field) != value]
        if not expected["offline"] and row.get("cli_version") != cli_version:
            mismatched.append("cli_version")
        if mismatched:
            raise SystemExit(
                "FAIL: --resume configuration differs in " + ", ".join(sorted(set(mismatched)))
            )
        rows.append(row)
if not rows:
    raise SystemExit("FAIL: --resume output contains no result rows")
starts = {row["campaign_started_at"] for row in rows}
if len(starts) != 1:
    raise SystemExit("FAIL: --resume output has mixed campaign_started_at values")
ids = [row["invocation_id"] for row in rows]
if len(ids) != len(set(ids)):
    raise SystemExit("FAIL: --resume output already has duplicate invocation IDs")
print(next(iter(starts)))
for invocation_id in ids:
    print(invocation_id)
PY
)" || exit $?
  RESUME_LINE=0
  while IFS= read -r RESUME_VALUE; do
    if [ "${RESUME_LINE}" = 0 ]; then
      STARTED_AT="${RESUME_VALUE}"
    else
      RECORDED_INVOCATIONS+=("${RESUME_VALUE}")
    fi
    RESUME_LINE=$((RESUME_LINE + 1))
  done <<< "${RESUME_INDEX}"
  echo "resume: ${#RECORDED_INVOCATIONS[@]} completed invocation(s) found"
fi

invocation_recorded() {
  local WANTED="$1"
  local RECORDED
  for RECORDED in "${RECORDED_INVOCATIONS[@]}"; do
    [ "${RECORDED}" = "${WANTED}" ] && return 0
  done
  return 1
}

# Validate every requested fixture before any provider invocation. This avoids
# spending part of a resumed batch before discovering that a later task drifted.
if [ "${RESUME}" = 1 ]; then
  python3 - "${OUT_FILE}" "${EVAL}" "${WITH_LESSONS}" "${TASKS[@]}" <<'PY'
import hashlib, json, pathlib, sys

path, eval_dir, with_lessons, *tasks = sys.argv[1:]
eval_root = pathlib.Path(eval_dir)

def tree_hash(root):
    digest = hashlib.sha256()
    for item in sorted(path for path in root.rglob("*") if path.is_file()):
        relative = item.relative_to(root)
        if "__pycache__" in relative.parts or item.suffix == ".pyc":
            continue
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()

rows = [json.loads(line) for line in pathlib.Path(path).read_text().splitlines()
        if line.strip()]
for task in tasks:
    task_dir = eval_root / "tasks" / task
    prompt = task_dir / "PROMPT.md"
    if not prompt.is_file():
        continue
    expected_arms = {"doctrine", "bare"}
    if with_lessons == "1" and (task_dir / "lessons.md").is_file():
        expected_arms.add("lessons")
    expected_task = tree_hash(task_dir)
    expected_prompt = hashlib.sha256(prompt.read_bytes()).hexdigest()
    for row in rows:
        if row.get("task") != task:
            continue
        if (row.get("task_sha256") != expected_task
                or row.get("prompt_sha256") != expected_prompt):
            raise SystemExit(f"FAIL: --resume task/prompt changed for {task}")
        expected_order = sorted(expected_arms, key=lambda arm: hashlib.sha256(
            f"{row['seed']}\0{task}\0{row['run']}\0{arm}".encode()
        ).digest())
        if row.get("arm_order") != expected_order:
            raise SystemExit(f"FAIL: --resume arm order changed for {task}")
PY
fi

for TASK in "${TASKS[@]}"; do
  TDIR="${EVAL}/tasks/${TASK}"
  [ -f "${TDIR}/PROMPT.md" ] || { echo "skip ${TASK}: no PROMPT.md"; continue; }
  TASK_SHA256="$(tree_hash "${TDIR}")"
  PROMPT_SHA256="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "${TDIR}/PROMPT.md")"

  ARMS=(doctrine bare)
  if [ "${WITH_LESSONS}" = 1 ]; then
    if [ -f "${TDIR}/lessons.md" ]; then
      ARMS=(doctrine bare lessons)
    else
      echo "note ${TASK}: no lessons.md — lessons arm skipped"
    fi
  fi
  R=$((RUN_OFFSET + 1))
  while [ "${R}" -le "${LAST_RUN}" ]; do
    ORDERED_ARMS=()
    while IFS= read -r ORDERED_ARM; do
      ORDERED_ARMS+=("${ORDERED_ARM}")
    done < <(ordered_arms "${TASK}" "${R}" "${ARMS[@]}")
    ARM_ORDER="$(IFS=,; printf '%s' "${ORDERED_ARMS[*]}")"
    PAIR_ID="${CAMPAIGN_ID}/${TASK}/${R}"
    for ARM in "${ORDERED_ARMS[@]}"; do
      INVOCATION_ID="${PAIR_ID}/${ARM}"
      if [ "${RESUME}" = 1 ] && invocation_recorded "${INVOCATION_ID}"; then
        echo "== ${TASK} / ${ARM} (run ${R}): SKIP — already recorded =="
        continue
      fi
      CFG="$(mktemp -d)"
      WORK="$(mktemp -d)"
      TRACE="$(mktemp -d)"
      cp -R "${TDIR}/project/." "${WORK}/"

      # A task may need deterministic local state that cannot be stored in the
      # fixture tree itself (for example, a Git repository). Run setup before
      # inference and before the offline reference overlay so every arm starts
      # from the same state. Setup must be offline and idempotent.
      if [ -x "${TDIR}/setup.sh" ]; then
        "${TDIR}/setup.sh" "${WORK}"
      fi

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

      echo "== ${TASK} / ${ARM} (run ${R}; batch $((R - RUN_OFFSET))/${RUNS}) =="
      RC=0
      T0="$(date +%s)"
      # Provider transcripts are evidence about the invocation, not task
      # files. Keeping them outside WORK prevents them from contaminating Git
      # status, repository fingerprints, or final-tree grading.
      LOG="${TRACE}/agent.log"
      ERR_LOG="${TRACE}/agent.stderr"
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
import datetime, json, math, os, sys
(task, arm, run, invalid, dur, log, offline, provider, requested_model,
 effort, cli_version, campaign_id, pair_id, arm_order, seed, started_at,
 repository_commit, repository_dirty, task_sha256, prompt_sha256,
 system_name, system_arch, runner_profile) = sys.argv[1:24]
crit = {}
score = None
for line in os.environ.get("GRADE_OUT", "").splitlines():
    p = line.split()
    if len(p) == 3 and p[0] == "CRIT":
        crit[p[1]] = (p[2] == "pass")
    elif len(p) == 2 and p[0] == "SCORE":
        score = p[1]
# Infrastructure-invalid rows are excluded, not partial behavioral failures.
# Drop any CRIT lines printed before a grader/provider crash so the row remains
# valid schema-v2 data and cannot leak partial results into later tooling.
if invalid == "true":
    crit = {}
    score = None
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
def nonnegative_int_or_none(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
def nonnegative_number_or_none(value):
    return value if (isinstance(value, (int, float)) and not isinstance(value, bool)
                     and value >= 0 and (not isinstance(value, float)
                                         or math.isfinite(value))) else None
tokens_in = nonnegative_int_or_none(tokens_in)
tokens_out = nonnegative_int_or_none(tokens_out)
cached_tokens = nonnegative_int_or_none(cached_tokens)
reasoning_tokens = nonnegative_int_or_none(reasoning_tokens)
num_turns = nonnegative_int_or_none(num_turns)
cost_usd = nonnegative_number_or_none(cost_usd)
print(json.dumps({"result_schema": 2,
                  "campaign_id": campaign_id, "pair_id": pair_id,
                  "invocation_id": pair_id + "/" + arm,
                  "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "campaign_started_at": started_at,
                  "seed": seed, "arm_order": arm_order.split(","),
                  "repository_commit": repository_commit,
                  "repository_dirty": repository_dirty == "true",
                  "task_sha256": task_sha256, "prompt_sha256": prompt_sha256,
                  "system": system_name, "architecture": system_arch,
                  "runner_profile": runner_profile,
                  "task": task, "arm": arm, "run": int(run),
                  "invalid": invalid == "true", "criteria": crit,
                  "score": score, "duration_s": int(dur),
                  "tokens_in": tokens_in, "tokens_out": tokens_out,
                  "cached_input_tokens": cached_tokens,
                  "reasoning_output_tokens": reasoning_tokens,
                  "cost_usd": cost_usd, "num_turns": num_turns,
                  "provider": provider, "model": model,
                  "requested_model": requested_model or None,
                  "reasoning_effort": effort or None,
                  "cli_version": cli_version or None,
                  "invalid_reason": os.environ.get("INVALID_REASON") or None,
                  "offline": offline == "1"},
                 ensure_ascii=False))' \
          "${TASK}" "${ARM}" "${R}" "${INVALID}" "$((T1 - T0))" "${LOG}" "${OFFLINE}" \
          "${PROVIDER}" "${MODEL}" "${REASONING_EFFORT}" "${AGENT_VERSION}" \
          "${CAMPAIGN_ID}" "${PAIR_ID}" "${ARM_ORDER}" "${RUN_SEED}" "${STARTED_AT}" \
          "${REPOSITORY_COMMIT}" "${REPOSITORY_DIRTY}" "${TASK_SHA256}" "${PROMPT_SHA256}" \
          "${SYSTEM_NAME}" "${SYSTEM_ARCH}" "${RUNNER_PROFILE}" >> "${OUT_FILE}"
      fi
      echo "   workdir kept for inspection: ${WORK}"
      echo "   provider logs kept separately: ${TRACE}"
      rm -rf "${CFG}"
      echo
    done
    R=$((R + 1))
  done
done

if [ -n "${OUT_FILE}" ]; then
  echo "results appended to ${OUT_FILE} — render with: eval/report.sh ${OUT_FILE}"
fi
