# tests/gates/evidence.sh — learning layer wiring, benchmark digests and generated docs.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# 4c6. learning layer stays wired through the skills that read/write it
grep -q 'docs/lessons.md' "${ROOT}/skills/debug/SKILL.md" || fail "debug skill lost the lesson-ledger lookup"
grep -q 'luciazero-heuristics.md' "${ROOT}/skills/debug/SKILL.md" || fail "debug skill lost the heuristics lookup"
grep -q 'docs/lessons.md' "${ROOT}/skills/retro/SKILL.md" || fail "retro skill lost the lesson-ledger routing"
grep -q 'luciazero-heuristics.md' "${ROOT}/skills/retro/SKILL.md" || fail "retro skill lost the heuristics routing"
grep -q 'luciazero discipline' "${ROOT}/skills/retro/SKILL.md" || fail "retro skill lost the discipline-report integration"
echo "ok  learning-layer skill wiring"

# 4c7. published benchmark tables are generated from immutable, digest-checked
# raw campaigns. A stale table or edited JSONL must turn CI red.
python3 "${ROOT}/eval/evidence.py" --check >/dev/null \
  || fail "benchmark evidence digest or generated documentation drift"
python3 - "${ROOT}/eval" <<'PY' \
  || fail "benchmark evidence accepted duplicate schema-v2 invocations"
import hashlib, pathlib, sys
sys.path.insert(0, sys.argv[1])
from evidence import validate_campaign_rows

campaign = {
    "expected_result_schema": 2, "expected_runs_per_cell": 2,
    "expected_invalid": {}, "expected_model_rows": 4,
    "id": "c", "tasks": ["t"], "lessons_tasks": [], "observed_model": "m",
    "expected_task_sha256": {"t": {"task": "a" * 64, "prompt": "b" * 64}},
}
base = {"result_schema": 2, "task": "t", "invalid": False,
        "model": "m", "requested_model": "m", "criteria": {"ok": True},
        "campaign_id": "c", "repository_dirty": False, "seed": "s",
        "repository_commit": "abc", "runner_profile": "runner",
        "reasoning_effort": "medium", "cli_version": "cli",
        "system": "system", "architecture": "arch",
        "campaign_started_at": "2026-08-12T00:00:00+00:00",
        "task_sha256": "a" * 64, "prompt_sha256": "b" * 64}
rows = [
    {**base, "arm": "doctrine", "run": 1, "pair_id": "c/t/1",
     "arm_order": ["doctrine", "bare"], "invocation_id": "c/t/1/doctrine"},
    {**base, "arm": "doctrine", "run": 1, "pair_id": "c/t/1",
     "arm_order": ["doctrine", "bare"], "invocation_id": "c/t/1/doctrine"},
    {**base, "arm": "bare", "run": 1, "pair_id": "c/t/1",
     "arm_order": ["doctrine", "bare"], "invocation_id": "c/t/1/bare"},
    {**base, "arm": "bare", "run": 2, "pair_id": "c/t/2",
     "arm_order": ["bare", "doctrine"], "invocation_id": "c/t/2/bare"},
]
try:
    validate_campaign_rows(campaign, rows, pathlib.Path("synthetic.jsonl"))
except SystemExit as exc:
    assert "duplicate" in str(exc)
else:
    raise AssertionError("duplicate invocation IDs were accepted")

def expected_order(run):
    return sorted(("doctrine", "bare"), key=lambda arm: hashlib.sha256(
        f"s\0t\0{run}\0{arm}".encode()).digest())

valid = [
    {**base, "arm": arm, "run": run, "pair_id": f"c/t/{run}",
     "arm_order": expected_order(run),
     "invocation_id": f"c/t/{run}/{arm}"}
    for run in (1, 2) for arm in ("doctrine", "bare")
]
valid[0]["repository_dirty"] = True
try:
    validate_campaign_rows(campaign, valid, pathlib.Path("synthetic.jsonl"))
except SystemExit as exc:
    assert "dirty-checkout" in str(exc)
else:
    raise AssertionError("dirty evidence rows were accepted")
valid[0]["repository_dirty"] = False
for row in valid:
    if row["run"] == 1:
        row["arm_order"] = list(reversed(expected_order(1)))
try:
    validate_campaign_rows(campaign, valid, pathlib.Path("synthetic.jsonl"))
except SystemExit as exc:
    assert "does not match seed" in str(exc)
else:
    raise AssertionError("tampered deterministic arm order was accepted")
PY
echo "ok  benchmark evidence digests + generated docs"
