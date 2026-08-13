#!/usr/bin/env bash
set -u

WORK="${1:?usage: grade.sh WORKDIR}"
TDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELAY="$(cd "${TDIR}/../../.." && pwd)/skills/lucia-relay/scripts/relay.py"

python3 - "${WORK}" "${TDIR}/project" "${RELAY}" <<'PY'
from collections import OrderedDict
import json
from pathlib import Path
import re
import subprocess
import sys

work = Path(sys.argv[1])
project = Path(sys.argv[2])
relay = Path(sys.argv[3])
criteria = OrderedDict((name, False) for name in (
    "portable_artifacts",
    "task_state",
    "literal_next_action",
    "exact_verification",
    "negative_knowledge",
    "scope_preserved",
))

manifest_path = work / "LUCIA_RELAY.json"
human_path = work / "LUCIA_RELAY.md"
data = None
try:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
except (OSError, ValueError):
    pass

if isinstance(data, dict) and human_path.is_file():
    inspected = subprocess.run(
        [sys.executable, str(relay), "inspect", "--root", str(work), "--json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    try:
        result = json.loads(inspected.stdout)
    except ValueError:
        result = {}
    criteria["portable_artifacts"] = (
        inspected.returncode == 0
        and result.get("valid") is True
        and result.get("repository_drift") is False
        and result.get("warnings") == []
        and data.get("kind") == "luciazero-relay"
        and data.get("schema") == 2
        and data.get("route", {}).get("recipient") == "same-machine"
    )

if isinstance(data, dict):
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    done = state.get("done") if isinstance(state.get("done"), list) else []
    progress = state.get("in_progress") if isinstance(state.get("in_progress"), list) else []
    criteria["task_state"] = (
        "split_fields" in str(data.get("goal", ""))
        and "Python 3.8" in str(data.get("goal", ""))
        and any("Reproduced" in str(item) for item in done)
        and any("regression test" in str(item) for item in done)
        and any("implementation" in str(item) and "untouched" in str(item) for item in progress)
    )

    next_step = state.get("next_step") if isinstance(state.get("next_step"), dict) else {}
    next_value = str(next_step.get("value", ""))
    criteria["literal_next_action"] = (
        next_step.get("kind") == "edit"
        and "parser.py" in next_value
        and "csv.reader" in next_value
        and "./verify.sh" in next_value
    )

    verification = data.get("verification")
    expected_line = "FAIL quoted separator: expected ['alpha', 'bravo;charlie', 'delta']"
    criteria["exact_verification"] = (
        isinstance(verification, list)
        and len(verification) == 1
        and verification[0].get("command") == "./verify.sh"
        and verification[0].get("exit_code") == 1
        and verification[0].get("decisive_line") == expected_line
        and isinstance(verification[0].get("run_at"), str)
        and re.search(r"(?:Z|[+-]\d\d:\d\d)$", verification[0]["run_at"]) is not None
    )

    knowledge = data.get("knowledge") if isinstance(data.get("knowledge"), dict) else {}
    read_first = knowledge.get("read_first") if isinstance(knowledge.get("read_first"), list) else []
    hypotheses = knowledge.get("hypotheses") if isinstance(knowledge.get("hypotheses"), list) else []
    landmines = knowledge.get("landmines") if isinstance(knowledge.get("landmines"), list) else []
    criteria["negative_knowledge"] = (
        any("docs/lessons.md" in str(item) for item in read_first)
        and any(
            isinstance(item, dict)
            and item.get("id") == "H1"
            and item.get("status") == "refuted"
            and "ASCII" in str(item.get("evidence", ""))
            for item in hypotheses
        )
        and any("Python 3.8" in str(item) for item in landmines)
    )

scope_files = ("parser.py", "test_parser.py", "verify.sh", "WORK_STATE.md", "docs/lessons.md")
criteria["scope_preserved"] = all(
    (work / name).is_file()
    and not (work / name).is_symlink()
    and (work / name).read_bytes() == (project / name).read_bytes()
    for name in scope_files
)

passed = sum(criteria.values())
for name, ok in criteria.items():
    print(f"CRIT {name} {'pass' if ok else 'fail'}")
print(f"SCORE {passed}/{len(criteria)}")
raise SystemExit(0 if passed == len(criteria) else 1)
PY
