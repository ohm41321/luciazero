# tests/gates/astra-luna.sh — Astra/Luna adapter slices 0-3 contracts and mutation guards.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

python3 "${ROOT}/scripts/check-astra-luna-adapter.py" >/dev/null \
  || fail "Astra/Luna Slice 0 evidence contract"
echo "ok  Astra/Luna Slice 0 evidence contract"

# Mutation checks keep the exact Slice 0 contract from becoming a vacuous
# schema check: a changed isolation count and a document path leak must bite.
ADAPTER_GUARD_TMP="$(mktemp -d)"
mkdir -p "${ADAPTER_GUARD_TMP}/docs/assets"
cp "${ROOT}/docs/astra-luna-adapter.md" "${ADAPTER_GUARD_TMP}/docs/astra-luna-adapter.md"
cp "${ROOT}/docs/assets/astra-luna-adapter-baseline.json" \
  "${ADAPTER_GUARD_TMP}/docs/assets/astra-luna-adapter-baseline.json"
python3 - "${ADAPTER_GUARD_TMP}" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
path = root / "docs/assets/astra-luna-adapter-baseline.json"
data = json.loads(path.read_text())
data["runtime"]["global_files_changed"] = 1
path.write_text(json.dumps(data, indent=2) + "\n")
PY
ADAPTER_RC=0
python3 "${ROOT}/scripts/check-astra-luna-adapter.py" --root "${ADAPTER_GUARD_TMP}" >/dev/null 2>&1 \
  || ADAPTER_RC=$?
[ "${ADAPTER_RC}" -ne 0 ] \
  || { rm -rf "${ADAPTER_GUARD_TMP}"; fail "Slice 0 guard missed a runtime mutation"; }
cp "${ROOT}/docs/assets/astra-luna-adapter-baseline.json" \
  "${ADAPTER_GUARD_TMP}/docs/assets/astra-luna-adapter-baseline.json"
printf '%s\n' 'leak /Users/not-a-real-home/file' >> "${ADAPTER_GUARD_TMP}/docs/astra-luna-adapter.md"
ADAPTER_RC=0
python3 "${ROOT}/scripts/check-astra-luna-adapter.py" --root "${ADAPTER_GUARD_TMP}" >/dev/null 2>&1 \
  || ADAPTER_RC=$?
rm -rf "${ADAPTER_GUARD_TMP}"
[ "${ADAPTER_RC}" -ne 0 ] || fail "Slice 0 guard missed a document path leak"
echo "ok  Astra/Luna Slice 0 mutation guards"

python3 "${ROOT}/scripts/check-astra-luna-adapter-slice1.py" >/dev/null \
  || fail "Astra/Luna Slice 1 adapter contract"
echo "ok  Astra/Luna Slice 1 adapter contract"

# Mutation checks keep the Slice 1 contract tied to role boundaries, preset
# safety, and the explicit exclusion of upstream instruction files.
SLICE1_GUARD_TMP="$(mktemp -d)"
mkdir -p "${SLICE1_GUARD_TMP}/adapters" "${SLICE1_GUARD_TMP}/docs/assets"
cp -R "${ROOT}/adapters/astra-luna" "${SLICE1_GUARD_TMP}/adapters/astra-luna"
cp "${ROOT}/docs/assets/astra-luna-adapter-baseline.json" \
  "${SLICE1_GUARD_TMP}/docs/assets/astra-luna-adapter-baseline.json"
python3 - "${SLICE1_GUARD_TMP}" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
path = root / "adapters/astra-luna/agents/lucia-explorer.toml"
text = path.read_text()
path.write_text(text.replace('sandbox_mode = "read-only"', 'sandbox_mode = "workspace-write"', 1))
PY
SLICE1_RC=0
python3 "${ROOT}/scripts/check-astra-luna-adapter-slice1.py" \
  --root "${SLICE1_GUARD_TMP}" >/dev/null 2>&1 || SLICE1_RC=$?
[ "${SLICE1_RC}" -ne 0 ] \
  || { rm -rf "${SLICE1_GUARD_TMP}"; fail "Slice 1 guard missed a role permission mutation"; }
cp -R "${ROOT}/adapters/astra-luna/." "${SLICE1_GUARD_TMP}/adapters/astra-luna/"
printf '%s\n' 'approval_policy = "on-request"' \
  >>"${SLICE1_GUARD_TMP}/adapters/astra-luna/presets/pro.toml"
SLICE1_RC=0
python3 "${ROOT}/scripts/check-astra-luna-adapter-slice1.py" \
  --root "${SLICE1_GUARD_TMP}" >/dev/null 2>&1 || SLICE1_RC=$?
[ "${SLICE1_RC}" -ne 0 ] \
  || { rm -rf "${SLICE1_GUARD_TMP}"; fail "Slice 1 guard missed a preset safety mutation"; }
cp -R "${ROOT}/adapters/astra-luna/." "${SLICE1_GUARD_TMP}/adapters/astra-luna/"
python3 - "${SLICE1_GUARD_TMP}" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
path = root / "adapters/astra-luna/presets/pro.toml"
text = path.read_text()
path.write_text(text.replace('root_model = "gpt-6-astra"', 'root_model = "gpt-5.6-luna"', 1))
PY
SLICE1_RC=0
python3 "${ROOT}/scripts/check-astra-luna-adapter-slice1.py" \
  --root "${SLICE1_GUARD_TMP}" >/dev/null 2>&1 || SLICE1_RC=$?
[ "${SLICE1_RC}" -ne 0 ] \
  || { rm -rf "${SLICE1_GUARD_TMP}"; fail "Slice 1 guard missed a preset routing mutation"; }
cp -R "${ROOT}/adapters/astra-luna/." "${SLICE1_GUARD_TMP}/adapters/astra-luna/"
printf '%s\n' '# upstream instructions must stay out' \
  >"${SLICE1_GUARD_TMP}/adapters/astra-luna/AGENTS.md"
SLICE1_RC=0
python3 "${ROOT}/scripts/check-astra-luna-adapter-slice1.py" \
  --root "${SLICE1_GUARD_TMP}" >/dev/null 2>&1 || SLICE1_RC=$?
rm -rf "${SLICE1_GUARD_TMP}"
[ "${SLICE1_RC}" -ne 0 ] || fail "Slice 1 guard missed an AGENTS.md mutation"
echo "ok  Astra/Luna Slice 1 mutation guards"

python3 "${ROOT}/scripts/check-astra-luna-slice2.py" >/dev/null \
  || fail "Astra/Luna Slice 2 orchestration skill contract"
echo "ok  Astra/Luna Slice 2 orchestration skill contract"

# Mutation checks keep the Slice 2 skill contract tied to its delegation gate,
# root verification, role namespace, and global-catalog isolation.
SLICE2_GUARD_TMP="$(mktemp -d)"
mkdir -p "${SLICE2_GUARD_TMP}/adapters/astra-luna/skills/lucia-orchestrator" \
  "${SLICE2_GUARD_TMP}/docs/assets" "${SLICE2_GUARD_TMP}/claude" "${SLICE2_GUARD_TMP}/skills"
cp "${ROOT}/adapters/astra-luna/skills/lucia-orchestrator/SKILL.md" \
  "${SLICE2_GUARD_TMP}/adapters/astra-luna/skills/lucia-orchestrator/SKILL.md"
cp "${ROOT}/docs/assets/astra-luna-slice2-behavior.json" \
  "${SLICE2_GUARD_TMP}/docs/assets/astra-luna-slice2-behavior.json"
cp "${ROOT}/claude/luciazero.md" "${SLICE2_GUARD_TMP}/claude/luciazero.md"
cp "${ROOT}/skills/catalog.txt" "${SLICE2_GUARD_TMP}/skills/catalog.txt"
python3 - "${SLICE2_GUARD_TMP}" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
path = root / "adapters/astra-luna/skills/lucia-orchestrator/SKILL.md"
text = path.read_text()
path.write_text(text.replace("independently bounded work", "file count alone requires spawn", 1))
PY
SLICE2_RC=0
python3 "${ROOT}/scripts/check-astra-luna-slice2.py" \
  --root "${SLICE2_GUARD_TMP}" >/dev/null 2>&1 || SLICE2_RC=$?
[ "${SLICE2_RC}" -ne 0 ] \
  || { rm -rf "${SLICE2_GUARD_TMP}"; fail "Slice 2 guard missed the delegation conjunction"; }
cp "${ROOT}/adapters/astra-luna/skills/lucia-orchestrator/SKILL.md" \
  "${SLICE2_GUARD_TMP}/adapters/astra-luna/skills/lucia-orchestrator/SKILL.md"
python3 - "${SLICE2_GUARD_TMP}" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
path = root / "adapters/astra-luna/skills/lucia-orchestrator/SKILL.md"
text = path.read_text()
path.write_text(text.replace("root performs final repository verification", "root reports the subagent result", 1))
PY
SLICE2_RC=0
python3 "${ROOT}/scripts/check-astra-luna-slice2.py" \
  --root "${SLICE2_GUARD_TMP}" >/dev/null 2>&1 || SLICE2_RC=$?
[ "${SLICE2_RC}" -ne 0 ] \
  || { rm -rf "${SLICE2_GUARD_TMP}"; fail "Slice 2 guard missed root verification drift"; }
cp "${ROOT}/adapters/astra-luna/skills/lucia-orchestrator/SKILL.md" \
  "${SLICE2_GUARD_TMP}/adapters/astra-luna/skills/lucia-orchestrator/SKILL.md"
cp "${ROOT}/docs/assets/astra-luna-slice2-behavior.json" \
  "${SLICE2_GUARD_TMP}/docs/assets/astra-luna-slice2-behavior.json"
python3 - "${SLICE2_GUARD_TMP}" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
path = root / "docs/assets/astra-luna-slice2-behavior.json"
data = json.loads(path.read_text())
for fixture in data["fixtures"]:
    if fixture["id"] == "authorized-parallel":
        fixture["runtime_authority"] = False
        fixture["expected"] = "root-only"
path.write_text(json.dumps(data) + "\n")
PY
SLICE2_RC=0
python3 "${ROOT}/scripts/check-astra-luna-slice2.py" \
  --root "${SLICE2_GUARD_TMP}" >/dev/null 2>&1 || SLICE2_RC=$?
[ "${SLICE2_RC}" -ne 0 ] \
  || { rm -rf "${SLICE2_GUARD_TMP}"; fail "Slice 2 guard missed authorized-parallel input drift"; }
cp "${ROOT}/docs/assets/astra-luna-slice2-behavior.json" \
  "${SLICE2_GUARD_TMP}/docs/assets/astra-luna-slice2-behavior.json"
python3 - "${SLICE2_GUARD_TMP}" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
path = root / "docs/assets/astra-luna-slice2-behavior.json"
data = json.loads(path.read_text())
for fixture in data["fixtures"]:
    if fixture["id"] == "worker-scope-expansion":
        fixture["worker_scope_expansion"] = False
        fixture["expected"] = "root-only"
path.write_text(json.dumps(data) + "\n")
PY
SLICE2_RC=0
python3 "${ROOT}/scripts/check-astra-luna-slice2.py" \
  --root "${SLICE2_GUARD_TMP}" >/dev/null 2>&1 || SLICE2_RC=$?
[ "${SLICE2_RC}" -ne 0 ] \
  || { rm -rf "${SLICE2_GUARD_TMP}"; fail "Slice 2 guard missed worker-scope input drift"; }

# Restore the canonical fixture before each independent mutation.  In
# particular, the catalog mutation below must start from a clean baseline;
# otherwise a still-mutated behavior fixture could make the guard fail for the
# wrong reason and let removal of the catalog check go unnoticed.
cp "${ROOT}/docs/assets/astra-luna-slice2-behavior.json" \
  "${SLICE2_GUARD_TMP}/docs/assets/astra-luna-slice2-behavior.json"
python3 - "${SLICE2_GUARD_TMP}" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
path = root / "docs/assets/astra-luna-slice2-behavior.json"
data = json.loads(path.read_text())
for fixture in data["fixtures"]:
    if fixture["id"] == "authorized-parallel":
        fixture["runtime_authority"] = 1
        fixture["expected"] = "root-only"
path.write_text(json.dumps(data) + "\n")
PY
SLICE2_RC=0
python3 "${ROOT}/scripts/check-astra-luna-slice2.py" \
  --root "${SLICE2_GUARD_TMP}" >/dev/null 2>&1 || SLICE2_RC=$?
[ "${SLICE2_RC}" -ne 0 ] \
  || { rm -rf "${SLICE2_GUARD_TMP}"; fail "Slice 2 guard missed boolean type drift"; }

cp "${ROOT}/docs/assets/astra-luna-slice2-behavior.json" \
  "${SLICE2_GUARD_TMP}/docs/assets/astra-luna-slice2-behavior.json"
python3 - "${SLICE2_GUARD_TMP}" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
path = root / "docs/assets/astra-luna-slice2-behavior.json"
data = json.loads(path.read_text())
for fixture in data["fixtures"]:
    if fixture["id"] == "spawn-unavailable":
        fixture["required_report"] = "delegation skipped"
path.write_text(json.dumps(data) + "\n")
PY
SLICE2_RC=0
python3 "${ROOT}/scripts/check-astra-luna-slice2.py" \
  --root "${SLICE2_GUARD_TMP}" >/dev/null 2>&1 || SLICE2_RC=$?
[ "${SLICE2_RC}" -ne 0 ] \
  || { rm -rf "${SLICE2_GUARD_TMP}"; fail "Slice 2 guard missed required_report drift"; }

cp "${ROOT}/adapters/astra-luna/skills/lucia-orchestrator/SKILL.md" \
  "${SLICE2_GUARD_TMP}/adapters/astra-luna/skills/lucia-orchestrator/SKILL.md"
cp "${ROOT}/docs/assets/astra-luna-slice2-behavior.json" \
  "${SLICE2_GUARD_TMP}/docs/assets/astra-luna-slice2-behavior.json"
SLICE2_RC=0
python3 "${ROOT}/scripts/check-astra-luna-slice2.py" \
  --root "${SLICE2_GUARD_TMP}" >/dev/null 2>&1 || SLICE2_RC=$?
[ "${SLICE2_RC}" -eq 0 ] \
  || { rm -rf "${SLICE2_GUARD_TMP}"; fail "Slice 2 mutation baseline is not clean"; }
printf '%s\n' 'lucia-orchestrator' >>"${SLICE2_GUARD_TMP}/skills/catalog.txt"
SLICE2_RC=0
python3 "${ROOT}/scripts/check-astra-luna-slice2.py" \
  --root "${SLICE2_GUARD_TMP}" >/dev/null 2>&1 || SLICE2_RC=$?
rm -rf "${SLICE2_GUARD_TMP}"
[ "${SLICE2_RC}" -ne 0 ] || fail "Slice 2 guard missed global catalog leakage"
echo "ok  Astra/Luna Slice 2 mutation guards"

python3 "${ROOT}/scripts/test_astra_luna_canary_budget.py" >/dev/null \
  || fail "Astra/Luna Slice 3 canary budget enforcement"
echo "ok  Astra/Luna Slice 3 canary budget enforcement (offline)"
