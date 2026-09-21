#!/usr/bin/env python3
"""Check the project-scoped Luciazero orchestration-skill contract."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_REL = Path("adapters/astra-luna/skills/lucia-orchestrator/SKILL.md")
FIXTURE_REL = Path("docs/assets/astra-luna-slice2-behavior.json")
ROLE_NAMES = {
    "lucia-explorer",
    "lucia-researcher",
    "lucia-worker",
    "lucia-tester",
    "lucia-reviewer",
}
MODEL_ID_RE = re.compile(r"\bgpt-[0-9][^\s`)]*\b|\b(?:astra|luna)\b", re.I)
EXPECTED_FIXTURES = {
    "trivial-root-only": {
        "id": "trivial-root-only",
        "independently_bounded": True,
        "measurable_benefit": False,
        "runtime_authority": True,
        "expected": "root-only",
    },
    "authorized-parallel": {
        "id": "authorized-parallel",
        "independently_bounded": True,
        "measurable_benefit": True,
        "runtime_authority": True,
        "expected": "delegate",
    },
    "spawn-unavailable": {
        "id": "spawn-unavailable",
        "independently_bounded": True,
        "measurable_benefit": True,
        "runtime_authority": False,
        "expected": "root-only",
        "required_report": "no delegation occurred",
    },
    "worker-scope-expansion": {
        "id": "worker-scope-expansion",
        "worker_scope_expansion": True,
        "expected": "stop-and-report",
    },
    "failed-tester-verification": {
        "id": "failed-tester-verification",
        "tester_verification": "failed",
        "expected": "block-completion",
    },
    "material-reviewer-finding": {
        "id": "material-reviewer-finding",
        "reviewer_finding": "major",
        "expected": "surface-and-resolve",
    },
}


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"FAIL: Slice 2 adapter contract: {message}")


def normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def require(text: str, phrase: str, label: str) -> None:
    if normalized(phrase) not in normalized(text):
        fail(f"{label} is missing required phrase {phrase!r}")


def parse_frontmatter(text: str) -> str:
    match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.S)
    if not match:
        fail("SKILL.md is missing frontmatter")
    block = match.group(1)
    if re.findall(r"(?m)^name:\s*lucia-orchestrator\s*$", block) != [
        "name: lucia-orchestrator"
    ]:
        fail("frontmatter name is not lucia-orchestrator")
    descriptions = re.findall(r"(?m)^description:\s*(.+)$", block)
    if len(descriptions) != 1 or not descriptions[0].strip():
        fail("frontmatter needs one description")
    return block


def decision(fixture: dict) -> str:
    if fixture.get("worker_scope_expansion"):
        return "stop-and-report"
    if fixture.get("tester_verification") == "failed":
        return "block-completion"
    if fixture.get("reviewer_finding") == "major":
        return "surface-and-resolve"
    if all(
        fixture.get(key) is True
        for key in ("independently_bounded", "measurable_benefit", "runtime_authority")
    ):
        return "delegate"
    return "root-only"


def check_fixtures(root: Path, text: str) -> None:
    fixture_path = root / FIXTURE_REL
    try:
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"behavior fixture unavailable or invalid: {exc}")
    if data.get("schema_version") != 1 or not isinstance(data.get("fixtures"), list):
        fail("behavior fixture schema drift")
    fixtures = data["fixtures"]
    expected_ids = set(EXPECTED_FIXTURES)
    if {fixture.get("id") for fixture in fixtures} != expected_ids:
        fail("behavior fixture set drift")
    if len(fixtures) != len(expected_ids):
        fail("behavior fixture IDs are not unique")
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            fail("behavior fixture is not an object")
        fixture_id = fixture.get("id")
        expected = EXPECTED_FIXTURES[fixture_id]
        if set(fixture) != set(expected):
            fail(f"behavior fixture {fixture_id} fields drifted")
        for key, wanted in expected.items():
            actual = fixture[key]
            if type(actual) is not type(wanted) or actual != wanted:
                fail(
                    f"behavior fixture {fixture_id} field {key} drifted: "
                    f"expected {wanted!r} ({type(wanted).__name__})"
                )
        if decision(fixture) != fixture.get("expected"):
            fail(f"behavior fixture {fixture_id} has an inconsistent expected outcome")
    require(text, "no delegation occurred", "spawn-unavailable behavior")
    require(text, "stop and report", "worker-scope-expansion behavior")
    require(text, "failed verification blocks completion", "failed-tester behavior")
    require(text, "material reviewer findings", "reviewer-finding behavior")
    require(text, "surface", "reviewer-finding behavior")
    require(text, "resolve", "reviewer-finding behavior")


def main(root: Path = ROOT) -> int:
    skill_path = root / SKILL_REL
    if not skill_path.is_file():
        fail(f"missing {SKILL_REL}")
    text = skill_path.read_text(encoding="utf-8")
    parse_frontmatter(text)
    if MODEL_ID_RE.search(text):
        fail("model/provider choice leaked into the model-neutral skill")
    if "luciazero:start" in text or "luciazero:end" in text:
        fail("Luciazero doctrine block was copied into the adapter skill")
    doctrine_path = root / "claude/luciazero.md"
    doctrine = normalized(doctrine_path.read_text(encoding="utf-8"))
    for candidate in re.split(r"(?<=[.!?])\s+", doctrine):
        words = candidate.split()
        if len(words) >= 12 and candidate in normalized(text):
            fail("a long Luciazero doctrine sentence was duplicated")

    role_tokens = set(re.findall(r"\blucia-[a-z][a-z-]*\b", text)) - {"lucia-orchestrator"}
    if role_tokens != ROLE_NAMES:
        fail(f"role request set drift: {sorted(role_tokens)}")
    require(text, "only selectable roles", "role boundary")
    require(text, "`/ready`", "ready reference")
    require(text, "`/debug`", "debug reference")
    require(text, "`/done`", "done reference")
    require(text, "`/retro`", "retro reference")
    require(text, "independently bounded work", "delegation conjunction")
    require(text, "measurable benefit", "delegation conjunction")
    require(text, "runtime and user authority to spawn", "delegation conjunction")
    require(text, "all three", "delegation conjunction")
    require(text, "file count alone", "root-only boundary")
    require(text, "root-only", "root-only boundary")
    require(text, "failed, cancelled, or incomplete", "failure visibility")
    require(text, "material reviewer findings", "review visibility")
    require(text, "worker never expands ownership", "worker boundary")
    require(text, "root performs final repository verification", "root verification")
    require(text, "runtime start evidence", "spawn honesty")
    require(text, "never claims a role started", "spawn honesty")
    require(text, "project configuration", "configuration isolation")
    require(text, "model routing", "configuration isolation")
    require(text, "skills/catalog.txt", "catalog isolation")
    if "lucia-orchestrator" in (root / "skills/catalog.txt").read_text(encoding="utf-8"):
        fail("lucia-orchestrator leaked into the global skill catalog")
    check_fixtures(root, text)
    print("ASTRA_LUNA_SLICE2_CONTRACT=PASS")
    # This is static contract/fixture validation only; runtime role selection
    # and provider behavior are intentionally deferred to Slice 3.
    print("ASTRA_LUNA_SLICE2_BEHAVIOR=PASS")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    main(args.root.resolve())
