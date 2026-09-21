#!/usr/bin/env python3
"""Validate the model-neutral Astra/Luna adapter source contract.

This checker validates Luciazero-owned source fixtures only.  The preset files
are adapter fragments for a later project materializer; they are not copied to
global Codex configuration by this slice.
"""

from __future__ import annotations

import ast
import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters" / "astra-luna"
AGENTS_DIR = ADAPTER / "agents"
PRESETS_DIR = ADAPTER / "presets"
BASELINE = ROOT / "docs" / "assets" / "astra-luna-adapter-baseline.json"

ROLE_NAMES = {
    "lucia-explorer",
    "lucia-researcher",
    "lucia-worker",
    "lucia-tester",
    "lucia-reviewer",
}
READ_ONLY = {"lucia-explorer", "lucia-researcher", "lucia-reviewer"}
WRITE_ROLES = {"lucia-worker", "lucia-tester"}
MODEL_IDS = {"gpt-6-astra", "gpt-5.6-luna"}
FORBIDDEN_PRESET_KEYS = {
    "mcp",
    "hooks",
    "approval_policy",
    "sandbox_mode",
    "CODEX_HOME",
}


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"FAIL: Slice 1 adapter contract: {message}")


def parse_toml(path: Path) -> dict:
    """Parse TOML with stdlib support and a tiny 3.10 fallback.

    Luciazero supports Python 3.10, while ``tomllib`` arrived in 3.11.  The
    fallback deliberately handles only the scalar/table forms used by these
    checked-in fixtures; it is not a general TOML implementation.
    """

    try:
        import tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None
    if tomllib is not None:
        try:
            return tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - exercised by mutations
            fail(f"invalid TOML in {path.relative_to(ROOT)}: {exc}")

    result: dict = {}
    section: dict = result
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = result
            for part in line[1:-1].split("."):
                section = section.setdefault(part, {})
            continue
        match = re.match(r'^(?:"([^"]+)"|([A-Za-z0-9_-]+))\s*=\s*(.+)$', line)
        if not match:
            fail(f"unsupported TOML syntax in {path.relative_to(ROOT)}:{number}")
        quoted_key, bare_key, value = match.groups()
        key = quoted_key or bare_key
        try:
            if value == "true":
                section[key] = True
            elif value == "false":
                section[key] = False
            else:
                section[key] = ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            fail(f"unsupported TOML value in {path.relative_to(ROOT)}:{number}: {exc}")
    return result


def require_dict(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        fail(f"{label} is not a TOML table")
    return value


def require_string(table: dict, key: str, label: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"{label} must have a non-empty string {key}")
    return value


def main(root: Path = ROOT) -> int:
    adapter = root / "adapters" / "astra-luna"
    agents_dir = adapter / "agents"
    presets_dir = adapter / "presets"
    baseline_path = root / "docs" / "assets" / "astra-luna-adapter-baseline.json"
    if not adapter.is_dir() or not agents_dir.is_dir() or not presets_dir.is_dir():
        fail("adapters/astra-luna/{agents,presets} is missing")

    role_paths = sorted(agents_dir.glob("*.toml"))
    if {path.stem for path in role_paths} != ROLE_NAMES:
        fail(
            "role set drift: expected "
            + ", ".join(sorted(ROLE_NAMES))
            + "; found "
            + ", ".join(sorted(path.stem for path in role_paths))
        )
    if len(role_paths) != len(ROLE_NAMES):
        fail("role names are not unique")

    seen_names: set[str] = set()
    for path in role_paths:
        if path.is_symlink() or not path.is_file():
            fail(f"role is not a regular file: {path}")
        text = path.read_text(encoding="utf-8")
        if any(model_id in text for model_id in MODEL_IDS):
            fail(f"model choice leaked into canonical role: {path}")
        table = parse_toml(path)
        name = require_string(table, "name", str(path))
        if name != path.stem:
            fail(f"role name {name!r} does not match {path.stem!r}")
        if name in seen_names:
            fail(f"duplicate role name {name!r}")
        seen_names.add(name)
        require_string(table, "description", str(path))
        instructions = require_string(table, "developer_instructions", str(path))
        if "Report:" not in instructions and "Return:" not in instructions:
            fail(f"role report contract missing: {path}")
        sandbox = require_string(table, "sandbox_mode", str(path))
        expected = "read-only" if name in READ_ONLY else "workspace-write"
        if name not in READ_ONLY | WRITE_ROLES or sandbox != expected:
            fail(f"unexpected permission boundary for {name}: {sandbox!r}")
        if "model" in table or "model_reasoning_effort" in table:
            fail(f"model choice key leaked into canonical role: {path}")

    preset_paths = sorted(presets_dir.glob("*.toml"))
    expected_presets = {"model-neutral", "pro", "plus"}
    if {path.stem for path in preset_paths} != expected_presets:
        fail("preset set drift")
    for path in preset_paths:
        if path.is_symlink() or not path.is_file():
            fail(f"preset is not a regular file: {path}")
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for key in FORBIDDEN_PRESET_KEYS:
            if re.search(rf"\b{re.escape(key.lower())}\b", lowered):
                fail(f"forbidden project/global key {key!r} in {path}")
        table = parse_toml(path)
        if require_string(table, "preset", str(path)) != path.stem:
            fail(f"preset name does not match filename: {path}")
        if table.get("schema_version") != 1:
            fail(f"preset schema_version must be 1: {path}")
        agents = require_dict(table.get("agents"), f"{path} [agents]")
        if agents.get("enabled") is not True:
            fail(f"{path} must enable agents")
        limit = agents.get("max_concurrent_threads_per_session")
        if not isinstance(limit, int) or not 2 <= limit <= 4:
            fail(f"{path} concurrency must stay between 2 and 4")

        if path.stem == "model-neutral":
            if any(model_id in text for model_id in MODEL_IDS):
                fail("model-neutral preset contains a model ID")
            if "role_models" in table:
                fail("model-neutral preset selects named models")
            if any(
                key in table
                for key in (
                    "root_model",
                    "root_reasoning_effort",
                    "default_subagent_model",
                    "default_subagent_reasoning_effort",
                )
            ):
                fail("model-neutral preset selects a root or default model")
            continue

        for key in (
            "root_model",
            "root_reasoning_effort",
            "default_subagent_model",
            "default_subagent_reasoning_effort",
        ):
            require_string(table, key, str(path))
        routes = require_dict(table.get("role_models"), f"{path} [role_models]")
        if set(routes) != ROLE_NAMES:
            fail(f"{path} role mapping drift")
        expected_reviewer = "gpt-6-astra"
        expected_execution = "gpt-5.6-luna"
        if routes["lucia-reviewer"] != expected_reviewer:
            fail(f"{path.stem} reviewer must route to Astra")
        if any(routes[name] != expected_execution for name in ROLE_NAMES - {"lucia-reviewer"}):
            fail(f"{path.stem} execution roles must route to Luna")
        expected = {
            "pro": {
                "root_model": "gpt-6-astra",
                "root_reasoning_effort": "medium",
                "default_subagent_model": "gpt-5.6-luna",
                "default_subagent_reasoning_effort": "max",
            },
            "plus": {
                "root_model": "gpt-5.6-luna",
                "root_reasoning_effort": "max",
                "default_subagent_model": "gpt-5.6-luna",
                "default_subagent_reasoning_effort": "medium",
            },
        }[path.stem]
        for key, value in expected.items():
            if table[key] != value:
                fail(f"{path.stem} {key} drifted: expected {value!r}")

    if any(path.name == "AGENTS.md" for path in adapter.rglob("*")):
        fail("AGENTS.md must not be included in the adapter tree")

    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Slice 0 source baseline unavailable: {exc}")
    source = baseline.get("source", {})
    if source.get("repository") != "https://github.com/donvito/codex-astra-luna-orchestrator.git":
        fail("upstream repository is not recorded")
    if source.get("commit") != "9c2a98435ca9ed2b85ac6b0e942b5ded75a4d194":
        fail("upstream source commit is not recorded")

    print("ASTRA_LUNA_SLICE1_CONTRACT=PASS")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    main(args.root.resolve())
