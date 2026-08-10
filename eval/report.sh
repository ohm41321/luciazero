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
                         "criteria": dict(row["criteria"])})
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            sys.exit(f"FAIL: {path}:{i}: malformed result line ({e})")
if not rows:
    sys.exit(f"FAIL: {path}: no result rows")

ARMS = ("doctrine", "bare")
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
    for r in valid["doctrine"] + valid["bare"]:
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
    print("| criterion | doctrine | bare | delta |")
    print("|---|---|---|---|")
    for c in crits:
        d = rate("doctrine", lambda r: r["criteria"].get(c, False))
        b = rate("bare", lambda r: r["criteria"].get(c, False))
        print(f"| {c} | {cell(d)} | {cell(b)} | {delta(d, b)} |")
    ok = lambda r: bool(r["criteria"]) and all(r["criteria"].values())
    d, b = rate("doctrine", ok), rate("bare", ok)
    print(f"| **all criteria** | {cell(d)} | {cell(b)} | {delta(d, b)} |")
    inv = ", ".join(f"{arm} {invalid[arm]}" for arm in ARMS if invalid[arm])
    if inv:
        print(f"\ninvalid runs excluded: {inv}")

print("\n---")
if low_n:
    print("**WARNING: fewer than 5 valid runs in at least one arm — treat "
          "every delta above as noise.**")
print("Honesty box: n is tiny and models are nondeterministic. Compare rates, "
      "never single runs, and do not believe a delta without >=5 runs per arm "
      "(eval/README.md).")
PY
