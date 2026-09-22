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

# 4c8. the skills-ablation pair reaches the published path: a registry entry
# may name its arms (doctrine, noskills, bare — each at most once, default
# doctrine,bare), its rows are checked against that set, and a campaign that
# ran doctrine and noskills renders a skills-ablation table in both READMEs
# and the benchmark, with the skill-use count from the rows' trace evidence.
# Campaigns without the pair render exactly as before.
mktmp EVT
python3 - "${ROOT}/eval" "${EVT}" <<'PY' \
  || fail "benchmark evidence does not carry a noskills campaign through registry, rows and docs"
import copy, hashlib, json, pathlib, sys
sys.path.insert(0, sys.argv[1])
import evidence
from evidence import (benchmark_doc, campaign_arms, english_readme, load_registry,
                      load_rows, thai_readme, validate_campaign_rows)
tmp = pathlib.Path(sys.argv[2])
real = json.loads(evidence.REGISTRY.read_text(encoding="utf-8"))

def registry_with(**fields):
    data = copy.deepcopy(real)
    data["campaigns"][0].update(fields)
    path = tmp / "campaigns.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path

for bad in (["doctrine", "doctrine"], ["skills"], [], "doctrine"):
    try:
        load_registry(registry_with(arms=bad))
    except SystemExit as exc:
        assert "malformed arms" in str(exc), (bad, exc)
    else:
        raise AssertionError(f"registry accepted arms={bad!r}")
try:
    load_registry(registry_with(arms=["doctrine", "noskills"],
                                expected_invalid={"false-green/bare": 1}))
except SystemExit as exc:
    assert "expected_invalid" in str(exc), exc
else:
    raise AssertionError("registry accepted an expected_invalid cell outside the arm set")
loaded = load_registry(registry_with(arms=["doctrine", "noskills"],
                                     expected_invalid={"false-green/noskills": 1}))
assert campaign_arms(loaded[0]) == ["doctrine", "noskills"], loaded[0]
assert campaign_arms(load_registry()[0]) == ["doctrine", "bare"]

campaign = {
    "id": "syn", "date": "2026-09-22", "provider": "claude", "status": "exploratory",
    "display_model": "Claude Synthetic", "observed_model": "m", "reasoning_effort": None,
    "file": "syn.jsonl", "sha256": "0" * 64, "model_provenance": "synthetic",
    "expected_result_schema": 2, "expected_runs_per_cell": 2,
    "expected_invalid": {"false-green/noskills": 1}, "expected_model_rows": 4,
    "tasks": ["false-green"], "lessons_tasks": [], "arms": ["doctrine", "noskills"],
    "expected_task_sha256": {"false-green": {"task": "a" * 64, "prompt": "b" * 64}},
    "limitations": ["synthetic rows for the gate"],
}
base = {"result_schema": 2, "task": "false-green", "model": "m", "requested_model": "m",
        "campaign_id": "syn", "repository_dirty": False, "seed": "s",
        "repository_commit": "abc", "runner_profile": "runner", "reasoning_effort": None,
        "cli_version": "cli", "system": "system", "architecture": "arch",
        "campaign_started_at": "2026-09-22T00:00:00+00:00",
        "task_sha256": "a" * 64, "prompt_sha256": "b" * 64, "provider": "claude",
        "offline": False, "score": "1/1", "duration_s": 1}

def order(run, arms):
    return sorted(arms, key=lambda arm: hashlib.sha256(f"s\0false-green\0{run}\0{arm}".encode()).digest())

def row(arm, run, ok, use):
    return {**base, "arm": arm, "run": run, "pair_id": f"syn/false-green/{run}",
            "arm_order": order(run, ("doctrine", "noskills")),
            "invocation_id": f"syn/false-green/{run}/{arm}",
            "invalid": use == "invalid", "criteria": {} if use == "invalid" else {"fixed": ok},
            "skill_use": None if use == "invalid" else {
                "status": use, "names": ["done"] if use == "observed" else [],
                "evidence": [{"channel": "Skill", "name": "done", "path": "skills/done/",
                              "source": "sandbox"}] if use == "observed" else [],
                "visible": ["done"], "reason": None}}
rows = [row("doctrine", 1, True, "observed"), row("doctrine", 2, False, "not observed"),
        row("noskills", 1, False, "not observed"), row("noskills", 2, False, "invalid")]
validate_campaign_rows(campaign, rows, pathlib.Path("syn.jsonl"))
wrong = [{**r, "arm": "bare" if r["arm"] == "noskills" else r["arm"],
          "arm_order": order(r["run"], ("doctrine", "bare"))} for r in rows]
try:
    validate_campaign_rows(campaign, wrong, pathlib.Path("syn.jsonl"))
except SystemExit as exc:
    assert "cells differ" in str(exc), exc
else:
    raise AssertionError("a doctrine/bare file was accepted for a doctrine/noskills campaign")

campaigns = load_registry()
data = {c["id"]: load_rows(c) for c in campaigns}
before = (english_readme(campaigns, data), thai_readme(campaigns, data), benchmark_doc(campaigns, data))
assert not any("Skills ablation" in text or "ผลของ skills" in text for text in before)
campaigns.append(campaign)
data["syn"] = rows
summary = "| Claude Synthetic | 1 | 1/2 (50%) | 0/1 (0%) | +50pp | 1/2 | 1–2 | exploratory |"
en, th, bench = english_readme(campaigns, data), thai_readme(campaigns, data), benchmark_doc(campaigns, data)
assert summary in en, en
assert summary in th and "### ผลของ skills" in th, th
assert summary in bench, bench
assert "| false-green | 1/2 | 0/1 | +50pp | 1/2 |" in bench, bench
assert "Raw: [`syn.jsonl`]" in bench, bench
# the pair is not a doctrine/bare campaign: it stays out of those tables
assert "| Synthetic," not in en and "### Claude Synthetic\n" not in bench
for text, was, marker in zip((en, th, bench), before,
                             ("### GPT/Codex", "### GPT/Codex", "These samples are small")):
    head, tail = was.split(marker, 1)
    assert text.startswith(head) and text.endswith(tail), "existing tables changed"
PY
echo "ok  skills-ablation campaigns: registry arms, row checks, generated tables"
