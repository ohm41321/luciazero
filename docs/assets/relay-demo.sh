#!/usr/bin/env bash
# Demonstrates the shipped Lucia Relay producer/receiver lifecycle in a
# throwaway Git repository. The README GIF records this real script, so the
# visual cannot drift into a product mockup.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RELAY="${ROOT}/skills/lucia-relay/scripts/relay.py"
PAUSE="${DEMO_PAUSE:-1.1}"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

DIM=$'\033[2m'; BOLD=$'\033[1m'; OFF=$'\033[0m'
narrate() { printf '\n%s%s%s\n' "${DIM}" "$*" "${OFF}"; sleep "${PAUSE}"; }

git -C "${WORK}" init -q -b main
git -C "${WORK}" config user.name "Relay Demo"
git -C "${WORK}" config user.email "demo@example.invalid"
git -C "${WORK}" config commit.gpgSign false
git -C "${WORK}" config core.hooksPath /dev/null
mkdir -p "${WORK}/docs"
printf '%s\n' \
  'def split_fields(record):' \
  '    return record.split(";")' > "${WORK}/parser.py"
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'echo "FAIL quoted separator"' \
  'exit 1' > "${WORK}/verify.sh"
chmod +x "${WORK}/verify.sh"
printf '%s\n' \
  '## Quoted delimiters' \
  'Use a real CSV parser; raw splitting loses quote boundaries.' > "${WORK}/docs/lessons.md"
git -C "${WORK}" add .
git -C "${WORK}" commit -qm 'fixture: unfinished parser'

narrate '# Session A verifies the unfinished state — still red'
(cd "${WORK}" && ./verify.sh) || true

"${RELAY}" draft --root "${WORK}" --recipient same-machine > "${WORK}/LUCIA_RELAY.json"
python3 - "${WORK}/LUCIA_RELAY.json" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
data["source"] = {"harness": "session-a", "agent": "agent-a", "session": "demo"}
data["goal"] = "Preserve quoted semicolons in split_fields"
data["state"]["done"] = ["Reproduced the quoted-separator failure"]
data["state"]["in_progress"] = ["Parser implementation is untouched"]
data["state"]["next_step"] = {
    "kind": "edit",
    "value": "Edit parser.py, then run ./verify.sh",
}
data["verification"] = [{
    "command": "./verify.sh",
    "exit_code": 1,
    "decisive_line": "FAIL quoted separator",
    "run_at": "2026-08-13T00:00:00+00:00",
}]
data["knowledge"]["read_first"] = ["docs/lessons.md"]
data["knowledge"]["hypotheses"] = [{
    "id": "H1",
    "claim": "Input encoding corrupts the separator",
    "status": "refuted",
    "evidence": "ASCII input fails too",
}]
data["knowledge"]["landmines"] = ["Keep Python 3.8 compatibility"]
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=2)
    handle.write("\n")
PY
"${RELAY}" render --root "${WORK}" >/dev/null
printf '  %sSession A →%s JSON + generated Markdown + Git fingerprint\n' "${BOLD}" "${OFF}"
sleep "${PAUSE}"

narrate '# Session B validates before trusting the transfer'
"${RELAY}" inspect --root "${WORK}"
python3 - "${WORK}/LUCIA_RELAY.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
hypothesis = data["knowledge"]["hypotheses"][0]
print(f"Refuted: {hypothesis['id']} — {hypothesis['evidence']}")
PY
sleep "${PAUSE}"

narrate '# If the tree changes in transit, the receiver sees drift'
printf '\n# changed after relay\n' >> "${WORK}/parser.py"
"${RELAY}" inspect --root "${WORK}"
git -C "${WORK}" restore parser.py
sleep "${PAUSE}"

narrate '# Receiver re-runs evidence, then explicitly consumes it'
(cd "${WORK}" && ./verify.sh) || true
"${RELAY}" consume --root "${WORK}" --verified \
  | sed 's#^.*/#  consumed #'

narrate '# Knowledge moved; stale relay files did not remain.'
