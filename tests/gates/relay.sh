# tests/gates/relay.sh — Lucia Relay draft, schema, rendering, lifecycle, fresh clone.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# 4c5c. Lucia Relay: portable draft, schema validation, human rendering,
# drift detection, secret rejection, and explicit verified consumption
RR="$(mktemp -d)"
git -C "${RR}" init -q
git -C "${RR}" config user.name test
git -C "${RR}" config user.email test@example.invalid
echo base > "${RR}/work.txt"
git -C "${RR}" add work.txt && git -C "${RR}" commit -qm base
echo pending > "${RR}/scratch.txt"
RELAY="${ROOT}/skills/lucia-relay/scripts/relay.py"
"${RELAY}" draft --root "${RR}" --recipient same-machine > "${RR}/LUCIA_RELAY.json"
python3 - "${RR}/LUCIA_RELAY.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p))
d["goal"]="# Transfer the unfinished parser change\n<img src=\"https://attacker.invalid/pixel\">"
d["state"]["done"]=["Reproduced the parser failure"]
d["state"]["in_progress"]=["Parser implementation is untouched"]
d["state"]["next_step"]={"kind":"command","value":"./verify.sh"}
d["verification"]=[{"command":"./verify.sh","exit_code":1,"decisive_line":"parser case fails","run_at":"2026-08-12T12:00:00+00:00"}]
d["knowledge"]["hypotheses"]=[{"id":"H1","claim":"encoding","status":"refuted","evidence":"ASCII fails too"}]
d["knowledge"]["read_first"]=["/Users/test/local-notes.md"]
d["knowledge"]["inline"]=[{"label":"local note","content":"Use the parser contract, not the transcript"}]
d["knowledge"]["landmines"]=["![beacon](https://attacker.invalid/pixel.png)"]
open(p,"w").write(json.dumps(d, indent=2)+"\n")
PY
"${RELAY}" validate --root "${RR}" >/dev/null || { rm -rf "${RR}"; fail "valid relay rejected"; }
"${RELAY}" render --root "${RR}" >/dev/null || { rm -rf "${RR}"; fail "relay render failed"; }
grep -q 'ASCII fails too' "${RR}/LUCIA_RELAY.md" || { rm -rf "${RR}"; fail "relay human view lost negative knowledge"; }
grep -q '\\# Transfer' "${RR}/LUCIA_RELAY.md" \
  || { rm -rf "${RR}"; fail "relay renderer did not escape injected Markdown heading"; }
! grep -q '<img' "${RR}/LUCIA_RELAY.md" \
  || { rm -rf "${RR}"; fail "relay renderer emitted injected raw HTML"; }
! grep -q '!\[beacon\](' "${RR}/LUCIA_RELAY.md" \
  || { rm -rf "${RR}"; fail "relay renderer emitted an injected remote image"; }
rm -f "${RR}/LUCIA_RELAY.md"
echo sentinel > "${RR}/outside.txt"
ln -s "${RR}/outside.txt" "${RR}/LUCIA_RELAY.md"
RC=0; "${RELAY}" render --root "${RR}" >/dev/null 2>&1 || RC=$?
if ! { [ "${RC}" -eq 1 ] && grep -qx sentinel "${RR}/outside.txt"; }; then
  rm -rf "${RR}"; fail "relay renderer followed an output symlink"
fi
rm -f "${RR}/LUCIA_RELAY.md"
rm -f "${RR}/outside.txt"
"${RELAY}" render --root "${RR}" >/dev/null || { rm -rf "${RR}"; fail "relay rerender after symlink check failed"; }
RJSON="$("${RELAY}" inspect --root "${RR}" --json)"
printf '%s' "${RJSON}" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["valid"] and not d["repository_drift"] and d["recipient"] == "same-machine" and d["warnings"] == []' \
  || { rm -rf "${RR}"; fail "fresh relay incorrectly reports drift"; }
if command -v mkfifo >/dev/null 2>&1; then
  mkfifo "${RR}/untracked.pipe"
  python3 - "${RELAY}" "${RR}" <<'PY' \
    || { rm -rf "${RR}"; fail "relay opened or lost an untracked FIFO"; }
import os
import subprocess
import sys

code = r'''
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location("relay_under_test", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
real_git = module.git
def git_with_fifo(root, *args):
    rc, output = real_git(root, *args)
    if args == ("ls-files", "--others", "--exclude-standard", "-z"):
        output += ("" if output.endswith("\0") or not output else "\0") + "untracked.pipe\0"
    return rc, output
module.git = git_with_fifo
snapshot = module.repository_snapshot(Path(sys.argv[2]))
assert "untracked.pipe" in snapshot["files"]["untracked"]
'''
subprocess.run(
    [sys.executable, "-c", code, sys.argv[1], sys.argv[2]],
    check=True,
    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    timeout=3,
)
PY
  rm -f "${RR}/untracked.pipe"
fi
echo tampered >> "${RR}/LUCIA_RELAY.md"
RC=0; RJSON="$("${RELAY}" inspect --root "${RR}" --json)" || RC=$?
if ! { [ "${RC}" -eq 1 ] && printf '%s' "${RJSON}" | python3 -c 'import json,sys; assert any("does not match" in e for e in json.load(sys.stdin)["errors"])'; }; then
  rm -rf "${RR}"; fail "relay inspect trusted a tampered human view"
fi
"${RELAY}" render --root "${RR}" >/dev/null || { rm -rf "${RR}"; fail "relay could not regenerate a tampered human view"; }
echo revised > "${RR}/scratch.txt"
RJSON="$("${RELAY}" inspect --root "${RR}" --json)"
printf '%s' "${RJSON}" | python3 -c 'import json,sys; assert json.load(sys.stdin)["repository_drift"]' \
  || { rm -rf "${RR}"; fail "relay missed changed content in an untracked file"; }
echo changed > "${RR}/work.txt"
RJSON="$("${RELAY}" inspect --root "${RR}" --json)"
printf '%s' "${RJSON}" | python3 -c 'import json,sys; assert json.load(sys.stdin)["repository_drift"]' \
  || { rm -rf "${RR}"; fail "relay missed repository drift"; }
RC=0; "${RELAY}" consume --root "${RR}" >/dev/null 2>&1 || RC=$?
if ! { [ "${RC}" -eq 2 ] && [ -f "${RR}/LUCIA_RELAY.json" ]; }; then
  rm -rf "${RR}"; fail "relay consumed without explicit re-verification"
fi
"${RELAY}" consume --root "${RR}" --verified >/dev/null \
  || { rm -rf "${RR}"; fail "verified relay consumption failed"; }
if ! { [ ! -e "${RR}/LUCIA_RELAY.json" ] && [ ! -e "${RR}/LUCIA_RELAY.md" ]; }; then
  rm -rf "${RR}"; fail "relay artifacts survived consumption"
fi
rm -rf "${RR}"
RR="$(mktemp -d)"
git -C "${RR}" init -q
echo staged > "${RR}/first.txt" && git -C "${RR}" add first.txt
"${RELAY}" draft --root "${RR}" --recipient same-machine | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["schema"] == 2 and d["route"]["recipient"] == "same-machine" and d["repository"]["head"] is None and d["repository"]["dirty"] and d["files"]["modified"] == ["first.txt"]' \
  || { rm -rf "${RR}"; fail "relay lost staged files in an unborn repository"; }
"${RELAY}" draft --root "${RR}" | python3 -c 'import json,sys; assert json.load(sys.stdin)["route"]["recipient"] == "same-machine"' \
  || { rm -rf "${RR}"; fail "relay broke legacy draft callers without --recipient"; }
rm -rf "${RR}"

# Cross-machine schema 3 must survive an actual fresh clone. The receiver
# supplies the trusted route and HEAD, reruns approved argv-safe evidence in
# its own harness, then explicitly asserts verification while consuming.
RR="$(mktemp -d)"
RREMOTE="$(mktemp -d)"
RRECEIVER="$(mktemp -d)"
RREMOTE_URL="git@relay.test.invalid:org/repo.git"
git -C "${RREMOTE}" init -q --bare
git -C "${RR}" init -q -b main
git -C "${RR}" config user.name test
git -C "${RR}" config user.email test@example.invalid
mkdir -p "${RR}/docs"
printf 'portable\n' > "${RR}/docs/notes.md"
printf 'delete after base\n' > "${RR}/docs/deleted.md"
printf '#!/bin/sh\nprintf "PASS relay verification\\n"\n' > "${RR}/verify.sh"
chmod +x "${RR}/verify.sh"
printf 'base\n' > "${RR}/work.txt"
git -C "${RR}" add work.txt docs/notes.md docs/deleted.md verify.sh
git -C "${RR}" commit -qm base
RBASE="$(git -C "${RR}" rev-parse HEAD)"
printf 'task change\n' > "${RR}/work.txt"
rm "${RR}/docs/deleted.md"
git -C "${RR}" add work.txt docs/deleted.md
git -C "${RR}" commit -qm task
RHEAD="$(git -C "${RR}" rev-parse HEAD)"
git -C "${RR}" remote add origin "${RREMOTE_URL}"
RPATH_ORIGINAL="${PATH}"
RSSH_DIR="${RREMOTE}/relay-test-bin"
mkdir -p "${RSSH_DIR}"
RSSH="${RSSH_DIR}/ssh"
# The fixture intentionally writes literal parameter expansions for its shim.
# shellcheck disable=SC2016
printf '%s\n' '#!/bin/sh' \
  'case "$*" in' \
  '  *git-receive-pack*) exec git-receive-pack "${RELAY_TEST_REMOTE}" ;;' \
  '  *git-upload-pack*) exec git-upload-pack "${RELAY_TEST_REMOTE}" ;;' \
  '  *) exit 64 ;;' \
  'esac' > "${RSSH}"
chmod +x "${RSSH}"
export PATH="${RSSH_DIR}:${PATH}" RELAY_TEST_REMOTE="${RREMOTE}"
git -C "${RR}" push -qu -u origin main
git --git-dir "${RREMOTE}" symbolic-ref HEAD refs/heads/main

"${RELAY}" draft --root "${RR}" --recipient cross-machine --base "${RBASE}" \
  > "${RR}/LUCIA_RELAY.json" \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "cross-machine draft failed after push"; }
python3 - "${RR}/LUCIA_RELAY.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p))
d["goal"]="Move parser knowledge to a fresh machine"
d["state"]["done"]=["Task commit is pushed"]
d["state"]["in_progress"]=["Receiver verification is pending"]
d["state"]["next_step"]={"kind":"command","value":"./verify.sh"}
d["verification"]=[
  {"command":"./verify.sh","exit_code":0,"decisive_line":"PASS relay verification","run_at":"2026-08-12T12:00:00+00:00"},
  {"command":"./verify.sh","exit_code":0,"decisive_line":"PASS relay verification","run_at":"2026-08-12T12:00:01+00:00"},
]
d["knowledge"]["read_first"]=["docs/notes.md — portable note"]
d["knowledge"]["inline"]=[{"label":"decision","content":"Keep the public parser contract"}]
d["knowledge"]["hypotheses"]=[{"id":"H1","claim":"encoding","status":"refuted","evidence":"ASCII passes"}]
open(p,"w").write(json.dumps(d, indent=2)+"\n")
PY
"${RELAY}" render --root "${RR}" >/dev/null \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "schema 3 relay render failed"; }
git -C "${RR}" config "url.${RREMOTE}.insteadOf" "${RREMOTE_URL}"
RC=0
"${RELAY}" envelope --root "${RR}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "trusted envelope accepted a late Git URL rewrite"; }
git -C "${RR}" config --unset-all "url.${RREMOTE}.insteadOf"
git -C "${RR}" config remote.origin.pushurl git@wrong.invalid:other/repo.git
RC=0
"${RELAY}" envelope --root "${RR}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "trusted envelope accepted a split push URL"; }
git -C "${RR}" config --unset-all remote.origin.pushurl
RENVELOPE="$("${RELAY}" envelope --root "${RR}")" \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "trusted relay envelope failed"; }
RMANIFEST="$(printf '%s' "${RENVELOPE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["trusted_manifest_sha256"])')"
python3 - "${RR}/LUCIA_RELAY.json" "${RBASE}" "${RHEAD}" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
assert d["schema"] == 3 and d["route"]["recipient"] == "cross-machine"
assert d["repository"]["base"] == sys.argv[2]
assert d["repository"]["head"] == d["repository"]["remote"]["oid"] == sys.argv[3]
assert d["repository"]["remote"]["ref"] == "refs/tags/lucia-relay-" + sys.argv[3]
assert d["repository"]["remote"]["source_ref"] == "refs/heads/main"
assert d["repository"]["remote"]["url"] == "git@relay.test.invalid:org/repo.git"
assert d["repository"]["changed_files"] == ["docs/deleted.md", "work.txt"]
PY

git clone -q "${RREMOTE_URL}" "${RRECEIVER}"
git -C "${RRECEIVER}" fetch -q origin "refs/tags/lucia-relay-${RHEAD}"
cp "${RR}/LUCIA_RELAY.json" "${RR}/LUCIA_RELAY.md" "${RRECEIVER}/"
git -C "${RRECEIVER}" checkout -q --detach "${RHEAD}"
RC=0; "${RELAY}" inspect --root "${RRECEIVER}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 2 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "cross-machine inspect trusted artifact-declared routing"; }
"${RELAY}" inspect --root "${RRECEIVER}" --expected-recipient cross-machine \
  --trusted-head "${RHEAD}" --trusted-manifest-sha256 "${RMANIFEST}" \
  --trusted-repository-url "${RREMOTE_URL}" >/dev/null \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "fresh detached receiver rejected matching relay"; }
python3 - "${RRECEIVER}/LUCIA_RELAY.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p)); d["route"]["recipient"]="same-machine"
open(p,"w").write(json.dumps(d, indent=2)+"\n")
PY
RC=0
"${RELAY}" consume --root "${RRECEIVER}" --verified >/dev/null 2>&1 || RC=$?
if [ "${RC}" -ne 2 ] || [ ! -f "${RRECEIVER}/LUCIA_RELAY.json" ]; then
  rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"
  fail "schema 3 route downgrade bypassed receiver trust"
fi
cp "${RR}/LUCIA_RELAY.json" "${RR}/LUCIA_RELAY.md" "${RRECEIVER}/"
python3 - "${RRECEIVER}/LUCIA_RELAY.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p)); d["schema"]=True; d["route"]["recipient"]="same-machine"
open(p,"w").write(json.dumps(d, indent=2)+"\n")
PY
RC=0
"${RELAY}" consume --root "${RRECEIVER}" --verified >/dev/null 2>&1 || RC=$?
if [ "${RC}" -eq 0 ] || [ ! -f "${RRECEIVER}/LUCIA_RELAY.json" ]; then
  rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"
  fail "boolean schema bypassed receiver trust"
fi
cp "${RR}/LUCIA_RELAY.json" "${RR}/LUCIA_RELAY.md" "${RRECEIVER}/"
git -C "${RRECEIVER}" config remote.origin.url git@wrong.invalid:other/repo.git
RC=0
"${RELAY}" inspect --root "${RRECEIVER}" --expected-recipient cross-machine \
  --trusted-head "${RHEAD}" --trusted-manifest-sha256 "${RMANIFEST}" \
  --trusted-repository-url "${RREMOTE_URL}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "receiver trusted an unrelated clone remote"; }
git -C "${RRECEIVER}" config remote.origin.url "${RREMOTE_URL}"
git -C "${RRECEIVER}" config remote.origin.pushurl git@wrong.invalid:other/repo.git
RC=0
"${RELAY}" inspect --root "${RRECEIVER}" --expected-recipient cross-machine \
  --trusted-head "${RHEAD}" --trusted-manifest-sha256 "${RMANIFEST}" \
  --trusted-repository-url "${RREMOTE_URL}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "receiver accepted a split push URL"; }
git -C "${RRECEIVER}" config --unset-all remote.origin.pushurl
RC=0
"${RELAY}" inspect --root "${RRECEIVER}" --expected-recipient cross-machine \
  --trusted-head "${RHEAD}" --trusted-manifest-sha256 "${RMANIFEST}" \
  --trusted-repository-url "https://wrong.invalid/repo.git" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "receiver accepted a mismatched trusted repository URL"; }
python3 - "${RRECEIVER}/LUCIA_RELAY.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p)); d["goal"]="tampered next machine goal"
open(p,"w").write(json.dumps(d, indent=2)+"\n")
PY
"${RELAY}" render --root "${RRECEIVER}" >/dev/null
RC=0
"${RELAY}" inspect --root "${RRECEIVER}" --expected-recipient cross-machine \
  --trusted-head "${RHEAD}" --trusted-manifest-sha256 "${RMANIFEST}" \
  --trusted-repository-url "${RREMOTE_URL}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "trusted digest accepted tampered relay knowledge"; }
cp "${RR}/LUCIA_RELAY.json" "${RR}/LUCIA_RELAY.md" "${RRECEIVER}/"
python3 - "${RRECEIVER}/LUCIA_RELAY_RECEIPT.json" "${RMANIFEST}" "${RHEAD}" <<'PY'
import json, sys
json.dump({
    "schema": 1,
    "kind": "luciazero-relay-receipt",
    "manifest_sha256": sys.argv[2],
    "repository_head": sys.argv[3],
    "results": [{
        "index": 1, "argv": ["./verify.sh"], "exit_code": 0,
        "decisive_line": "PASS relay verification", "matched": True,
        "run_at": "2026-08-12T12:00:00+00:00",
    }],
}, open(sys.argv[1], "w"))
PY
RC=0
"${RELAY}" consume --root "${RRECEIVER}" --expected-recipient cross-machine \
  --trusted-head "${RHEAD}" --trusted-manifest-sha256 "${RMANIFEST}" \
  --trusted-repository-url "${RREMOTE_URL}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 2 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "forged repo-local verification receipt was accepted"; }
for EVIDENCE_INDEX in 0 1; do
  EVIDENCE_OUT="$(cd "${RRECEIVER}" && ./verify.sh)" \
    || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "receiver evidence ${EVIDENCE_INDEX} failed"; }
  [ "${EVIDENCE_OUT}" = "PASS relay verification" ] \
    || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "receiver evidence ${EVIDENCE_INDEX} mismatched"; }
done
"${RELAY}" consume --root "${RRECEIVER}" --verified \
  --expected-recipient cross-machine --trusted-head "${RHEAD}" \
  --trusted-manifest-sha256 "${RMANIFEST}" \
  --trusted-repository-url "${RREMOTE_URL}" >/dev/null \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "verified receiver could not consume relay"; }
for TRANSIENT in LUCIA_RELAY.json LUCIA_RELAY.md LUCIA_RELAY_RECEIPT.json; do
  [ ! -e "${RRECEIVER}/${TRANSIENT}" ] \
    || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "${TRANSIENT} survived consumption"; }
done

# Reject stale tracking refs, incomplete knowledge/evidence, traversal, common
# secret formats, route downgrade, and legacy cross-machine payloads.
PYTHONDONTWRITEBYTECODE=1 python3 - "${RELAY}" "${RR}/LUCIA_RELAY.json" <<'PY'
import copy, importlib.util, json, sys
spec=importlib.util.spec_from_file_location("relay_under_test", sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
data=json.load(open(sys.argv[2]))
trusted_digest=module.manifest_sha256(__import__("pathlib").Path(sys.argv[2]).parent)
downgrade=copy.deepcopy(data); downgrade["route"]["recipient"]="same-machine"
result=module.inspect(
    __import__("pathlib").Path(sys.argv[2]).parent,
    downgrade,
    expected_recipient="cross-machine",
    trusted_head=data["repository"]["head"],
    trusted_manifest_sha256=trusted_digest,
    trusted_repository_url=data["repository"]["remote"]["url"],
    receiver_context=True,
)
assert any("receiver expected recipient cross-machine" in error for error in result["errors"])
for mutate in (
    lambda d: d.update(verification=[]),
    lambda d: d["knowledge"].update(read_first=[], inline=[], hypotheses=[], landmines=[]),
    lambda d: d["files"].update(modified=["../../.ssh/config"]),
    lambda d: d["knowledge"].update(inline=[{"label":"token","content":"npm_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"}]),
    lambda d: d["knowledge"].update(inline=[{"label":"dsn","content":"postgres://user:password@example.invalid/db"}]),
    lambda d: d["knowledge"].update(inline=[{"label":"jwt","content":"eyJAAAAAAAAAAAA.eyJBBBBBBBBBBBB.CCCCCCCCCCCC"}]),
):
    bad=copy.deepcopy(data); mutate(bad)
    assert module.validate(bad)[0]
legacy=copy.deepcopy(data); legacy["schema"]=2
legacy["repository"].pop("remote"); legacy["repository"].pop("base"); legacy["repository"].pop("changed_files")
assert module.validate(legacy)[0]
assert module.machine_paths({"note":"file:///Users/sender/notes.md"})
deleted=copy.deepcopy(data); deleted["knowledge"]["read_first"]=["docs/deleted.md"]
assert module.cross_machine_repository_errors(
    __import__("pathlib").Path(sys.argv[2]).parent, deleted
)
nested={}
cursor=nested
for _ in range(module.MAX_DEPTH + 2):
    cursor["x"]={}; cursor=cursor["x"]
assert module.structure_errors(nested)
assert module.sanitize_remote_url("https://example.invalid:bad/repo.git") is None
assert module.safe_command_argv("sh -c 'touch /tmp/pwned'") is None
assert module.safe_command_argv("git -c alias.pwn=!id pwn") is None
assert "valid immutable" in module.repository_path_error(
    __import__("pathlib").Path(sys.argv[2]).parent, "--batch", "docs/notes.md"
)
PY
git -C "${RR}" config "url.${RREMOTE}.insteadOf" "${RREMOTE_URL}"
RC=0
"${RELAY}" draft --root "${RR}" --recipient cross-machine --base "${RBASE}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "cross-machine draft accepted a Git URL rewrite"; }
git -C "${RR}" config --unset-all "url.${RREMOTE}.insteadOf"
git --git-dir "${RREMOTE}" update-ref -d "refs/tags/lucia-relay-${RHEAD}"
RC=0
"${RELAY}" envelope --root "${RR}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "trusted envelope accepted a deleted remote ref"; }
git --git-dir "${RREMOTE}" update-ref -d refs/heads/main
RC=0
"${RELAY}" draft --root "${RR}" --recipient cross-machine --base "${RBASE}" >/dev/null 2>&1 || RC=$?
[ "${RC}" -eq 1 ] \
  || { rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"; fail "cross-machine draft trusted a stale local remote ref"; }
rm -rf "${RR}" "${RREMOTE}" "${RRECEIVER}"
PATH="${RPATH_ORIGINAL}"
unset RELAY_TEST_REMOTE
echo "ok  lucia relay lifecycle + fresh-machine receiver verification"

# The public Relay demo drives the real producer/receiver lifecycle rather
# than printing a canned transcript.
RDEMO="$(DEMO_PAUSE=0 "${ROOT}/docs/assets/relay-demo.sh")" \
  || fail "relay demo exited red"
echo "${RDEMO}" | grep -q 'Repository drift: no' \
  || fail "relay demo never showed a matching fingerprint"
echo "${RDEMO}" | grep -q 'Repository drift: yes' \
  || fail "relay demo never detected drift"
echo "${RDEMO}" | grep -q 'consumed LUCIA_RELAY.json' \
  || fail "relay demo did not explicitly consume the verified artifact"
echo "ok  lucia relay real demo"
