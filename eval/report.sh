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

python3 - "${FILE}" <<'PY'
import json, sys

path = sys.argv[1]
rows = []
with open(path) as f:
    for i, line in enumerate(f, 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if not isinstance(row.get("criteria"), dict):
                raise ValueError("criteria is not an object")
            rows.append({"task": row["task"], "arm": row["arm"],
                         "invalid": bool(row["invalid"]),
                         "criteria": dict(row["criteria"]),
                         "duration_s": row.get("duration_s"),
                         "tokens_out": row.get("tokens_out"),
                         "cost_usd": row.get("cost_usd")})
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            sys.exit(f"FAIL: {path}:{i}: malformed result line ({e})")
if not rows:
    sys.exit(f"FAIL: {path}: no result rows")

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
low_n = False
for task in tasks:
    trows = [r for r in rows if r["task"] == task]
    valid = {arm: [r for r in trows if r["arm"] == arm and not r["invalid"]]
             for arm in ARMS}
    invalid = {arm: sum(1 for r in trows if r["arm"] == arm and r["invalid"])
               for arm in ARMS}
    n = {arm: len(valid[arm]) for arm in ARMS}
    if min(n.values()) < 5:
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
