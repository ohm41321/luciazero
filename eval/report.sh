#!/usr/bin/env bash
# Render a results file written by `eval/run.sh --out` as a markdown table of
# per-criterion pass RATES, doctrine vs bare — the comparison the honesty box
# in eval/README.md prescribes. Offline, deterministic: test.sh renders a
# checked-in fixture and byte-compares the output.
#
# Usage: eval/report.sh <results.jsonl>   (exit non-zero on malformed input)
set -euo pipefail

FILE="${1:?usage: report.sh <results.jsonl>}"
[ -f "${FILE}" ] || { echo "FAIL: no such file: ${FILE}" >&2; exit 1; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 - "${FILE}" "${SCRIPT_DIR}" <<'PY'
import json, sys

sys.path.insert(0, sys.argv[2])
from result_schema import validate_result_row

path = sys.argv[1]
rows = []
with open(path) as f:
    for i, line in enumerate(f, 1):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
            row = validate_result_row(raw, source=f"{path}:{i}")
            result_schema = row["result_schema"]
            provider = row["provider"]
            metadata = {
                "provider": provider,
                "model": row.get("model"),
                "requested_model": row.get("requested_model"),
                "reasoning_effort": row.get("reasoning_effort"),
                "cli_version": row.get("cli_version"),
                "campaign_id": row.get("campaign_id"),
                "campaign_started_at": row.get("campaign_started_at"),
                "repository_commit": row.get("repository_commit"),
                "seed": row.get("seed"),
                "runner_profile": row.get("runner_profile"),
                "system": row.get("system"),
                "architecture": row.get("architecture"),
            }
            aux = {field: row.get(field) for field in
                   ("task_sha256", "prompt_sha256", "pair_id", "invocation_id")}
            arm_order = row.get("arm_order")
            offline = row["offline"]
            rows.append({"task": row["task"], "arm": row["arm"],
                         "result_schema": result_schema,
                         "invalid": row["invalid"],
                         "criteria": dict(row["criteria"]),
                         "duration_s": row.get("duration_s"),
                         "tokens_out": row.get("tokens_out"),
                         "cost_usd": row.get("cost_usd"),
                         "offline": offline,
                         "repository_dirty": row["repository_dirty"],
                         **aux, "arm_order": arm_order,
                         **metadata,
                         "has_run_config": any(k in raw for k in
                                               ("provider", "model",
                                                "reasoning_effort",
                                                "cli_version", "campaign_id",
                                                "repository_commit", "seed",
                                                "runner_profile"))})
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            sys.exit(f"FAIL: {path}:{i}: malformed result line ({e})")
if not rows:
    sys.exit(f"FAIL: {path}: no result rows")

# Appending is convenient for repeated samples but dangerous across run
# configurations: aggregating two providers/models/efforts creates a number
# that describes neither. Unknown values on old or invalid rows are ignored;
# conflicting known values and synthetic/real mixtures are rejected.
def known(field):
    return {r[field] for r in rows if r[field] not in (None, "")}

if len({r["result_schema"] for r in rows}) > 1:
    sys.exit(f"FAIL: {path}: mixed result_schema values")

for field in ("provider", "model", "requested_model", "reasoning_effort",
              "cli_version", "campaign_id", "campaign_started_at",
              "repository_commit", "seed", "runner_profile", "system",
              "architecture"):
    values = known(field)
    if len(values) > 1:
        sys.exit(f"FAIL: {path}: mixed {field} values: {sorted(values, key=str)}")
if len({r["offline"] for r in rows}) > 1:
    sys.exit(f"FAIL: {path}: synthetic and real rows cannot be combined")
if len({r["repository_dirty"] for r in rows}) > 1:
    sys.exit(f"FAIL: {path}: clean and dirty rows cannot be combined")
if any(r["repository_dirty"] and not r["offline"] for r in rows):
    print(f"WARNING: {path}: dirty-checkout rows are diagnostic only", file=sys.stderr)

# Schema-v2 campaigns bind every task and prompt to one digest. This catches a
# fixture edited halfway through a campaign even when provider settings match.
for task in {r["task"] for r in rows}:
    task_rows = [r for r in rows if r["task"] == task]
    for field in ("task_sha256", "prompt_sha256"):
        values = {r[field] for r in task_rows if r[field] not in (None, "")}
        if len(values) > 1:
            sys.exit(f"FAIL: {path}: task {task} has mixed {field} values")

# A pair may be incomplete because an invocation was interrupted, but present
# arms must be unique and agree on the recorded randomized order.
for pair_id in {r["pair_id"] for r in rows if r["pair_id"] not in (None, "")}:
    pair = [r for r in rows if r["pair_id"] == pair_id]
    if len({r["arm"] for r in pair}) != len(pair):
        sys.exit(f"FAIL: {path}: duplicate arm in pair {pair_id}")
    orders = [r["arm_order"] for r in pair if r["arm_order"] is not None]
    if any(not isinstance(order, list) or
           any(not isinstance(arm, str) for arm in order) for order in orders):
        sys.exit(f"FAIL: {path}: malformed arm_order in pair {pair_id}")
    if orders and any(order != orders[0] for order in orders[1:]):
        sys.exit(f"FAIL: {path}: inconsistent arm_order in pair {pair_id}")
    if orders and any(r["arm"] not in orders[0] for r in pair):
        sys.exit(f"FAIL: {path}: arm missing from arm_order in pair {pair_id}")

invocations = [r["invocation_id"] for r in rows
               if r["invocation_id"] not in (None, "")]
if len(invocations) != len(set(invocations)):
    sys.exit(f"FAIL: {path}: duplicate invocation_id")

run_config = []
for label, field in (("provider", "provider"), ("model", "model"),
                     ("reasoning", "reasoning_effort"),
                     ("CLI", "cli_version"), ("campaign", "campaign_id"),
                     ("commit", "repository_commit"), ("seed", "seed")):
    values = known(field)
    if values:
        run_config.append(f"{label}={next(iter(values))}")

# arm columns are discovered from the data, in a fixed preferred order, so a
# --with-lessons results file grows a third column without a flag here
PREFERRED = ("doctrine", "lessons", "bare")
seen = {r["arm"] for r in rows}
ARMS = [a for a in PREFERRED if a in seen] + sorted(seen - set(PREFERRED))
DELTA_ARMS = [a for a in ARMS if a != "bare"] if "bare" in seen else []
DELTA_HDRS = ["delta"] if DELTA_ARMS == ["doctrine"] else \
             [f"{a}-bare" for a in DELTA_ARMS]

def mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None

tasks = sorted({r["task"] for r in rows})
print("# Eval report")
if any(r["has_run_config"] for r in rows) and run_config:
    print("\nRun config: " + "; ".join(run_config))
if any(r["offline"] for r in rows):
    print("\n**SYNTHETIC OFFLINE SMOKE — these rows exercise the pipeline "
          "with pre-built trees; no agent ran. Never quote them as results.**")
low_n = False
for task in tasks:
    trows = [r for r in rows if r["task"] == task]
    valid = {arm: [r for r in trows if r["arm"] == arm and not r["invalid"]]
             for arm in ARMS}
    invalid = {arm: sum(1 for r in trows if r["arm"] == arm and r["invalid"])
               for arm in ARMS}
    n = {arm: len(valid[arm]) for arm in ARMS}
    # only arms this task actually ran count toward the low-n warning — a
    # lessons column absent because the task ships no lessons.md is not
    # missing data
    present = [arm for arm in ARMS if any(r["arm"] == arm for r in trows)]
    if present and min(n[arm] for arm in present) < 5:
        low_n = True
    crits = []           # first-seen order, i.e. the grader's order
    for arm in ARMS:
        for r in valid[arm]:
            for c in r["criteria"]:
                if c not in crits:
                    crits.append(c)

    def rate(arm, pred):
        if n[arm] == 0:
            return None
        return sum(1 for r in valid[arm] if pred(r)), n[arm]

    def cell(v):
        if v is None:
            return "–"
        k, total = v
        return f"{k}/{total} ({100 * k // total}%)"

    def delta(a, b):
        if a is None or b is None:
            return "n/a"
        pp = 100 * a[0] // a[1] - 100 * b[0] // b[1]
        return f"{pp:+d}pp"

    print(f"\n## {task}\n")
    print("| criterion | " + " | ".join(ARMS + DELTA_HDRS) + " |")
    print("|---" * (1 + len(ARMS) + len(DELTA_HDRS)) + "|")
    for c in crits:
        by_arm = {a: rate(a, lambda r: r["criteria"].get(c, False)) for a in ARMS}
        cells = [cell(by_arm[a]) for a in ARMS] + \
                [delta(by_arm[a], by_arm.get("bare")) for a in DELTA_ARMS]
        print(f"| {c} | " + " | ".join(cells) + " |")
    ok = lambda r: bool(r["criteria"]) and all(r["criteria"].values())
    by_arm = {a: rate(a, ok) for a in ARMS}
    cells = [cell(by_arm[a]) for a in ARMS] + \
            [delta(by_arm[a], by_arm.get("bare")) for a in DELTA_ARMS]
    print("| **all criteria** | " + " | ".join(cells) + " |")
    inv = ", ".join(f"{arm} {invalid[arm]}" for arm in ARMS if invalid[arm])
    if inv:
        print(f"\ninvalid runs excluded: {inv}")
    # resource means, only when the results actually carry usage data — older
    # files (and runs without --output-format json) render exactly as before
    if any(r["cost_usd"] is not None or r["tokens_out"] is not None
           for arm in ARMS for r in valid[arm]):
        parts = []
        for arm in ARMS:
            if not valid[arm]:
                continue
            bits = []
            d = mean([r["duration_s"] for r in valid[arm]])
            t = mean([r["tokens_out"] for r in valid[arm]])
            c = mean([r["cost_usd"] for r in valid[arm]])
            if d is not None:
                bits.append(f"{d:.0f}s")
            if t is not None:
                bits.append(f"{t / 1000:.1f}k out-tok")
            if c is not None:
                bits.append(f"${c:.2f}")
            if bits:
                parts.append(f"{arm} " + " / ".join(bits))
        if parts:
            print("\nmeans over valid runs: " + "; ".join(parts))

print("\n---")
if low_n:
    print("**WARNING: fewer than 5 valid runs in at least one arm — treat "
          "every delta above as noise.**")
print("Honesty box: n is tiny and models are nondeterministic. Compare rates, "
      "never single runs, and do not believe a delta without >=5 runs per arm "
      "(eval/README.md).")
PY
