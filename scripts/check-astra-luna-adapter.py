#!/usr/bin/env python3
"""Check the redacted, structural Slice 0 adapter evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SOURCE = {
    "repository": "https://github.com/donvito/codex-astra-luna-orchestrator.git",
    "commit": "9c2a98435ca9ed2b85ac6b0e942b5ded75a4d194",
    "tracked_file_count": 22,
    "pinned_input_file_count": 9,
    "role_file_count": 5,
    "config_file_count": 2,
    "skill_file_count": 1,
    "instruction_file_count": 1,
}
EXPECTED_RUNTIME = {
    "codex_version": "0.154.0",
    "platform": "macos-aarch64",
    "provider_turns": 0,
    "global_files_changed": 0,
    "project_adapter_files_installed": 0,
    "root_threads_started": 1,
    "repo_skills_discovered": 1,
    "agent_directory_scans": 2,
    "valid_role_project_thread_starts": 1,
    "valid_role_loader_warnings": 0,
    "malformed_agent_loader_errors": 1,
}
EXPECTED_PRECEDENCE = {
    "same_directory_override_wins": 1,
    "override_filename_count": 1,
    "regular_filename_count": 1,
}
EXPECTED_FILES = [
    {
        "path": ".agents/skills/astra-orchestrator/SKILL.md",
        "bytes": 11840,
        "sha256": "05f98f5746ecda137e3c9058b86428c002d1c9ae81e53711a3452a9be8bc98b3",
    },
    {
        "path": ".codex/agents/explorer.toml",
        "bytes": 917,
        "sha256": "57f64f327d72097b84e5a4fce05d11163b4044d74808cde1ffdf14f69010d49a",
    },
    {
        "path": ".codex/agents/researcher.toml",
        "bytes": 705,
        "sha256": "9b403be6324f5416a99de6e03c9be73ebf5589654586f414f2a4c90bf92479b0",
    },
    {
        "path": ".codex/agents/reviewer.toml",
        "bytes": 875,
        "sha256": "9964bb2801d0279d7f54cddcc5c0c8eaf749cb47b390d9743f434f2cd5be4908",
    },
    {
        "path": ".codex/agents/tester.toml",
        "bytes": 782,
        "sha256": "81a312ec5056ae8689b66b7cca32c40672dbfaad93355b399f8dd60b41625350",
    },
    {
        "path": ".codex/agents/worker.toml",
        "bytes": 932,
        "sha256": "ba84db985184529c4f0910d3ea20ae20681178c9de9e16f4e32df03c7064eb96",
    },
    {
        "path": ".codex/config.plus.toml",
        "bytes": 1309,
        "sha256": "3e77bbd3f8b4a1bfdf24c80c8218b25580bb02d8bd96036fbbf8160c99beaac8",
    },
    {
        "path": ".codex/config.toml",
        "bytes": 1054,
        "sha256": "b3aee4920498a9e3c8505ec3d450fc0e6d43528ecb0772e15231e3ea1c4bf914",
    },
    {
        "path": "AGENTS.md",
        "bytes": 552,
        "sha256": "1507220039ae0c43f8c862ed908a0397cc0fb7b5a2c5f8d206c1a586beba0dff",
    },
]


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
args = parser.parse_args()
root = args.root.resolve()
doc = root / "docs" / "astra-luna-adapter.md"
baseline = root / "docs" / "assets" / "astra-luna-adapter-baseline.json"

if not doc.is_file() or not baseline.is_file():
    fail("Slice 0 evidence files are missing")

text = doc.read_text(encoding="utf-8")
normalized_text = " ".join(text.split())
data = json.loads(baseline.read_text(encoding="utf-8"))

for marker in (
    "skills/list",
    "thread/start",
    "AGENTS.override.md",
    "AGENTS.md",
    "codex-cli 0.154.0",
    "No provider was started",
    "does **not** claim that a valid role was available",
):
    if marker not in normalized_text:
        fail(f"Slice 0 document lost required observation: {marker}")

raw = baseline.read_text(encoding="utf-8")
for forbidden in (
    "developer_instructions",
    "prompt",
    "credential",
    "token",
    "rollout",
    "/Users/",
    "/private/",
    "/tmp/",
):
    if forbidden.lower() in raw.lower():
        fail(f"structural baseline contains forbidden material: {forbidden}")

# The evidence document is prose, so reject only actual leak-shaped values,
# not words used to state the redaction policy.
for pattern, label in (
    (r"(?:^|[\s`(])/(?:Users|private|tmp|var|home|Volumes|Applications)/", "absolute machine path"),
    (r"(?:sk-[A-Za-z0-9]|gh[pous]_[A-Za-z0-9]|-----BEGIN)", "credential-shaped value"),
    (r"(?i)(?:api[_-]?key|authorization|password|secret)\s*[:=]", "secret assignment"),
    (r'(?i)"(?:prompt|developer_instructions|payload|rollout)"\s*:', "payload field"),
):
    if re.search(pattern, text):
        fail(f"evidence document contains {label}")

if data.get("schema_version") != 1:
    fail("unsupported structural baseline schema")
if data.get("source") != EXPECTED_SOURCE:
    fail("source contract drifted: repository, commit, counts, or input count")
if data.get("runtime") != EXPECTED_RUNTIME:
    fail("runtime contract drifted: discovery, isolation, or error counts")
if data.get("precedence") != EXPECTED_PRECEDENCE:
    fail("instruction precedence contract drifted")
if data.get("files") != EXPECTED_FILES:
    fail("pinned input path/hash/byte inventory drifted")
if any(Path(row["path"]).is_absolute() or ".." in Path(row["path"]).parts for row in data["files"]):
    fail("pinned input inventory contains a non-relative path")
if any(not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) for row in data["files"]):
    fail("pinned input inventory contains an invalid SHA-256")
if not hashlib.sha256(baseline.read_bytes()).hexdigest():
    fail("baseline hash calculation failed")

print("ASTRA_LUNA_SLICE0_EVIDENCE=PASS")
print(f"source_commit={data['source']['commit']}")
print(f"pinned_input_files={data['source']['pinned_input_file_count']}")
