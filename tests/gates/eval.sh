# tests/gates/eval.sh — eval graders, report rendering, revert-probe, demo scaffold.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# 4d. eval graders stay honest — auto-discovered, so no task can ship without
# its proofs: PROMPT.md present, grader executable and following the output
# contract, reference/ passes, unfixed project/ fails, and any checked-in
# gamed/ cheat tree is rejected
for TDIR in "${ROOT}/eval/tasks"/*/; do
  TN="$(basename "${TDIR}")"
  [ -f "${TDIR}PROMPT.md" ] || fail "eval task ${TN}: missing PROMPT.md"
  [ -x "${TDIR}grade.sh" ] || fail "eval task ${TN}: grade.sh missing or not executable"
  if [ -f "${TDIR}setup.sh" ] && [ ! -x "${TDIR}setup.sh" ]; then
    fail "eval task ${TN}: setup.sh is not executable"
  fi
  [ -d "${TDIR}reference" ] || fail "eval task ${TN}: missing reference/"
  [ -d "${TDIR}project" ] || fail "eval task ${TN}: missing project/"
  # Mirror run.sh: project is the base tree, optional setup creates dynamic
  # local state, and reference/gamed directories are solution overlays.
  EWORK="$(mktemp -d)"
  cp -R "${TDIR}project/." "${EWORK}/"
  if [ -x "${TDIR}setup.sh" ]; then
    "${TDIR}setup.sh" "${EWORK}"
    "${TDIR}setup.sh" "${EWORK}"
  fi
  cp -R "${TDIR}reference/." "${EWORK}/"
  OUT="$("${TDIR}grade.sh" "${EWORK}" 2>&1)" \
    || { rm -rf "${EWORK}"; fail "eval grader ${TN} rejects its own reference solution: ${OUT}"; }
  rm -rf "${EWORK}"
  echo "${OUT}" | grep -q '^SCORE ' || fail "eval grader ${TN} breaks the CRIT/SCORE output contract: ${OUT}"
  EWORK="$(mktemp -d)"
  cp -R "${TDIR}project/." "${EWORK}/"
  if [ -x "${TDIR}setup.sh" ]; then
    "${TDIR}setup.sh" "${EWORK}"
    "${TDIR}setup.sh" "${EWORK}"
  fi
  if "${TDIR}grade.sh" "${EWORK}" >/dev/null 2>&1; then
    rm -rf "${EWORK}"
    fail "eval grader ${TN} passes the unfixed project (grader cannot go red)"
  fi
  rm -rf "${EWORK}"
  # every gamed*/ cheat variant must be rejected, and at least one must exist —
  # an untested "cannot be gamed" grader may not ship
  GAMED_SEEN=0
  for GD in "${TDIR}"gamed*/; do
    [ -d "${GD}" ] || continue
    GAMED_SEEN=1
    EWORK="$(mktemp -d)"
    cp -R "${TDIR}project/." "${EWORK}/"
    if [ -x "${TDIR}setup.sh" ]; then
      "${TDIR}setup.sh" "${EWORK}"
      "${TDIR}setup.sh" "${EWORK}"
    fi
    cp -R "${GD}." "${EWORK}/"
    if "${TDIR}grade.sh" "${EWORK}" >/dev/null 2>&1; then
      rm -rf "${EWORK}"
      fail "eval grader ${TN} passes its checked-in cheat tree ($(basename "${GD}")/)"
    fi
    rm -rf "${EWORK}"
  done
  [ "${GAMED_SEEN}" = 1 ] || fail "eval task ${TN}: missing gamed/ cheat tree"
  echo "ok  eval grader ${TN} red/green/anti-gamed"
done

# 4d2. report.sh renders the frozen fixtures byte-exactly and rejects garbage
RPT="$(mktemp)"
"${ROOT}/eval/report.sh" "${ROOT}/eval/testdata/sample-results.jsonl" > "${RPT}" \
  || { rm -f "${RPT}"; fail "report.sh failed on the checked-in fixture"; }
cmp -s "${RPT}" "${ROOT}/eval/testdata/sample-report.md" \
  || { rm -f "${RPT}"; fail "report.sh output drifted from eval/testdata/sample-report.md"; }
# the three-arm + usage fixture: lessons column, per-arm deltas, resource means
"${ROOT}/eval/report.sh" "${ROOT}/eval/testdata/sample-results-lessons.jsonl" > "${RPT}" \
  || { rm -f "${RPT}"; fail "report.sh failed on the lessons fixture"; }
cmp -s "${RPT}" "${ROOT}/eval/testdata/sample-report-lessons.md" \
  || { rm -f "${RPT}"; fail "report.sh output drifted from eval/testdata/sample-report-lessons.md"; }
# the skills-ablation fixture: doctrine vs noskills column, the
# doctrine-noskills delta, and the per-arm skill-use line read from the
# rows' trace evidence (a starred name is one with no evidence tied to the
# sandbox install; unknown rows carry their reason)
"${ROOT}/eval/report.sh" "${ROOT}/eval/testdata/sample-results-skills.jsonl" > "${RPT}" \
  || { rm -f "${RPT}"; fail "report.sh failed on the skills fixture"; }
cmp -s "${RPT}" "${ROOT}/eval/testdata/sample-report-skills.md" \
  || { rm -f "${RPT}"; fail "report.sh output drifted from eval/testdata/sample-report-skills.md"; }
printf 'not json\n' > "${RPT}"
if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
  rm -f "${RPT}"; fail "report.sh accepted malformed input"
fi
# criteria must be an object — a JSON array of pairs coerces via dict() into
# fake criteria and would render a confident 100% table (regression)
printf '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":["ab","cd"],"score":null,"duration_s":1}\n' > "${RPT}"
if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
  rm -f "${RPT}"; fail "report.sh accepted a non-object criteria field"
fi
# Appended rows from unlike run configurations must never become one rate.
printf '%s\n' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex","model":"model-a","reasoning_effort":"medium","cli_version":"codex 1"}' \
  '{"task":"t","arm":"bare","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex","model":"model-b","reasoning_effort":"medium","cli_version":"codex 1"}' \
  > "${RPT}"
if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
  rm -f "${RPT}"; fail "report.sh combined different models"
fi
printf '%s\n' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"claude"}' \
  '{"task":"t","arm":"bare","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex"}' \
  > "${RPT}"
if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
  rm -f "${RPT}"; fail "report.sh combined different providers"
fi
printf '%s\n' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex","model":"m","campaign_id":"a"}' \
  '{"task":"t","arm":"bare","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex","model":"m","campaign_id":"b"}' \
  > "${RPT}"
if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
  rm -f "${RPT}"; fail "report.sh combined different campaigns"
fi
printf '%s\n' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex","model":"m","task_sha256":"aaa"}' \
  '{"task":"t","arm":"bare","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex","model":"m","task_sha256":"bbb"}' \
  > "${RPT}"
if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
  rm -f "${RPT}"; fail "report.sh combined changed task fixtures"
fi
printf '%s\n' \
  '{"result_schema":2,"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"provider":"codex","model":"m"}' \
  > "${RPT}"
if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
  rm -f "${RPT}"; fail "report.sh accepted incomplete schema-v2 metadata"
fi
for BAD_ROW in \
  '{"result_schema":3,"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1}' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":"false","criteria":{"ok":true},"score":"1/1","duration_s":1}' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":"fail"},"score":"1/1","duration_s":1}' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":"fast"}'; do
  printf '%s\n' "${BAD_ROW}" > "${RPT}"
  if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
    rm -f "${RPT}"; fail "report.sh accepted a type-invalid result row"
  fi
done
# skill_use is evidence, so a malformed record must not render as a rate:
# a made-up status, a non-list names field, "observed" without a name,
# names outside "observed", string evidence (the old ad-hoc line format),
# a repeated observation, names that do not match the evidence, an
# unknown source, an arm outside the supported set
EV='{"channel":"Skill","name":"done","path":"skills/done/","source":"sandbox"}'
for BAD_ROW in \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"skill_use":{"status":"maybe","names":[],"evidence":[]}}' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"skill_use":{"status":"observed","names":"done","evidence":['"${EV}"']}}' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"skill_use":{"status":"observed","names":[],"evidence":[]}}' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"skill_use":{"status":"not observed","names":["done"],"evidence":[]}}' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"skill_use":{"status":"observed","names":["done"],"evidence":["Skill:done source=sandbox"]}}' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"skill_use":{"status":"observed","names":["done"],"evidence":['"${EV}"','"${EV}"']}}' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"skill_use":{"status":"observed","names":["ready"],"evidence":['"${EV}"']}}' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"skill_use":{"status":"observed","names":["done"],"evidence":[{"channel":"Skill","name":"done","path":"skills/done/","source":"builtin"}]}}' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"skills_installed":"yes"}' \
  '{"task":"t","arm":"doctrine-only","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1}'; do
  printf '%s\n' "${BAD_ROW}" > "${RPT}"
  if "${ROOT}/eval/report.sh" "${RPT}" >/dev/null 2>&1; then
    rm -f "${RPT}"; fail "report.sh accepted a malformed skill_use record: ${BAD_ROW}"
  fi
done
# a name is counted per run and per source: one run tied to the sandbox and
# one that was not render apart, so a built-in of the same name cannot hide
# behind a sandbox observation from another run
printf '%s\n' \
  '{"task":"t","arm":"doctrine","run":1,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"skill_use":{"status":"observed","names":["debug"],"evidence":[{"channel":"Skill","name":"debug","path":"skills/debug/","source":"sandbox"}]}}' \
  '{"task":"t","arm":"doctrine","run":2,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"skill_use":{"status":"observed","names":["debug"],"evidence":[{"channel":"Skill","name":"debug","path":"skills/debug/","source":"other"}]}}' \
  '{"task":"t","arm":"doctrine","run":3,"invalid":false,"criteria":{"ok":true},"score":"1/1","duration_s":1,"skill_use":{"status":"observed","names":["debug"],"evidence":[{"channel":"Skill","name":"debug","path":"skills/debug/","source":"unresolved"}]}}' \
  > "${RPT}"
"${ROOT}/eval/report.sh" "${RPT}" 2>/dev/null | grep -q '^skill use (trace evidence, valid runs): doctrine observed 3/3 (debug x1, debug x2\*)$' \
  || { rm -f "${RPT}"; fail "report.sh pooled sandbox and untied observations of one name: $("${ROOT}/eval/report.sh" "${RPT}" 2>&1 | grep '^skill use')"; }
rm -f "${RPT}"
echo "ok  eval report fixture + malformed input"

# 4d2b. check-result.sh: exit 0 does not prove the agent ran — the CLI has
# wrapped a "Not logged in" error in subtype "success" (2026-08-11); each
# rejection and acceptance path is proven against a fixture log
CRF="$(mktemp -d)"
CR="${ROOT}/eval/check-result.sh"
printf '{"subtype":"success","is_error":true,"terminal_reason":"api_error","result":"Not logged in · Please run /login"}' > "${CRF}/notlogged.json"
printf '{"result":"Not logged in · Please run /login"}' > "${CRF}/sneaky.json"
printf '{"subtype":"success","is_error":false,"result":"fixed the bug"}' > "${CRF}/good.json"
printf 'plain text transcript\n' > "${CRF}/text.log"
printf '%s\n' \
  '{"type":"thread.started","thread_id":"t"}' \
  '{"type":"turn.completed","usage":{"input_tokens":12,"cached_input_tokens":4,"output_tokens":3,"reasoning_output_tokens":1}}' \
  > "${CRF}/codex-good.jsonl"
printf '%s\n' \
  '{"type":"turn.started"}' \
  '{"type":"turn.failed","error":{"message":"rate limit"}}' \
  > "${CRF}/codex-failed.jsonl"
printf '{"type":"turn.started"}\n' > "${CRF}/codex-partial.jsonl"
printf '%s\n' \
  '{"type":"turn.started"}' \
  '{"type":"turn.completed","usage":{"input_tokens":null,"output_tokens":"3"}}' \
  > "${CRF}/codex-bad-usage.jsonl"
RC=0; OUT="$("${CR}" "${CRF}/notlogged.json" 2>&1)" || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result accepted a not-logged-in result"; }
echo "${OUT}" | grep -q 'Not logged in' || { rm -rf "${CRF}"; fail "check-result rejection lost the reason: ${OUT}"; }
RC=0; "${CR}" "${CRF}/sneaky.json" >/dev/null 2>&1 || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result accepted a login error without is_error"; }
"${CR}" "${CRF}/good.json" >/dev/null 2>&1 || { rm -rf "${CRF}"; fail "check-result rejected a healthy result"; }
"${CR}" "${CRF}/text.log" >/dev/null 2>&1 || { rm -rf "${CRF}"; fail "check-result rejected plain-text output"; }
"${CR}" --provider codex "${CRF}/codex-good.jsonl" >/dev/null 2>&1 \
  || { rm -rf "${CRF}"; fail "check-result rejected a completed Codex run"; }
RC=0; "${CR}" --provider codex "${CRF}/codex-failed.jsonl" >/dev/null 2>&1 || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result accepted a failed Codex turn"; }
RC=0; "${CR}" --provider codex "${CRF}/codex-partial.jsonl" >/dev/null 2>&1 || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result accepted an incomplete Codex stream"; }
RC=0; "${CR}" --provider codex "${CRF}/codex-bad-usage.jsonl" >/dev/null 2>&1 || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result accepted malformed Codex usage"; }
RC=0; "${CR}" "${CRF}/absent.json" >/dev/null 2>&1 || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result accepted a missing log"; }
# --output-format stream-json writes one event per line and the result
# object last; the same acceptance and rejection rules apply to that final
# event, and a stream that never reached it is a run that died mid-way
printf '%s\n' \
  '{"type":"system","subtype":"init","skills":["debug","done"]}' \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"done"}]}}' \
  '{"type":"result","subtype":"success","is_error":false,"result":"fixed the bug","usage":{"input_tokens":12,"output_tokens":3},"total_cost_usd":0.05,"num_turns":2}' \
  > "${CRF}/stream-good.jsonl"
printf '%s\n' \
  '{"type":"system","subtype":"init","skills":["debug"]}' \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"Not logged in · Please run /login"}]}}' \
  '{"type":"result","subtype":"success","is_error":true,"terminal_reason":"api_error","result":"Not logged in · Please run /login","num_turns":1,"total_cost_usd":0}' \
  > "${CRF}/stream-notlogged.jsonl"
printf '%s\n' \
  '{"type":"system","subtype":"init","skills":["debug"]}' \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"working"}]}}' \
  > "${CRF}/stream-noresult.jsonl"
"${CR}" "${CRF}/stream-good.jsonl" >/dev/null 2>&1 \
  || { rm -rf "${CRF}"; fail "check-result rejected a healthy stream-json log"; }
RC=0; OUT="$("${CR}" "${CRF}/stream-notlogged.jsonl" 2>&1)" || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result accepted a not-logged-in stream-json result"; }
echo "${OUT}" | grep -q 'Not logged in' || { rm -rf "${CRF}"; fail "stream-json rejection lost the reason: ${OUT}"; }
RC=0; OUT="$("${CR}" "${CRF}/stream-noresult.jsonl" 2>&1)" || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result accepted a stream-json log with no result event"; }
echo "${OUT}" | grep -q 'no result event' || { rm -rf "${CRF}"; fail "stream-json no-result rejection lost the reason: ${OUT}"; }
# a stray non-JSON line between two events (a warning on the same
# descriptor) does not turn the stream into "plain text": the result event
# after it is still read, and still refused
printf '%s\n' \
  '{"type":"system","subtype":"init","skills":["debug"]}' \
  'warning: something the CLI printed' \
  '{"type":"result","subtype":"success","is_error":true,"terminal_reason":"api_error","result":"Not logged in · Please run /login","num_turns":1}' \
  > "${CRF}/stream-noise.jsonl"
RC=0; OUT="$("${CR}" "${CRF}/stream-noise.jsonl" 2>&1)" || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${CRF}"; fail "check-result read a stream with a stray line as plain text and accepted an error result"; }
echo "${OUT}" | grep -q 'Not logged in' || { rm -rf "${CRF}"; fail "noisy stream rejection lost the reason: ${OUT}"; }
rm -rf "${CRF}"
echo "ok  check-result rejects error payloads behind exit 0"

# The non-zero Codex path must preserve the structured error in JSONL, not
# reduce a useful capacity/auth reason to only "codex exited 1". A fake CLI
# proves this without inference or credentials.
CFX="$(mktemp -d)"
mkdir -p "${CFX}/bin"
cat > "${CFX}/bin/codex" <<'FAKECODEX'
#!/bin/sh
if [ "${1:-}" = --version ]; then
  echo 'codex-cli test'
  exit 0
fi
printf '%s\n' \
  '{"type":"turn.started"}' \
  '{"type":"error","message":"Selected model is at capacity."}' \
  '{"type":"turn.failed","error":{"message":"Selected model is at capacity."}}'
exit 1
FAKECODEX
chmod +x "${CFX}/bin/codex"
PATH="${CFX}/bin:${PATH}" "${ROOT}/eval/run.sh" --discard-work --provider codex \
  --model gpt-5.6-terra --reasoning-effort medium --allow-dirty \
  --out "${CFX}/result.jsonl" false-green >/dev/null 2>&1 \
  || { rm -rf "${CFX}"; fail "run.sh rejected a recorded invalid Codex run"; }
python3 - "${CFX}/result.jsonl" <<'PY' \
  || { rm -rf "${CFX}"; fail "Codex invalid reason was not preserved"; }
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 2
assert all(row["invalid"] is True for row in rows)
assert all("Selected model is at capacity" in row["invalid_reason"] for row in rows)
PY
rm -rf "${CFX}"
echo "ok  Codex non-zero result preserves structured reason"

# A successful fake Codex run proves the actual adapter boundary: auth is
# copied into both disposable homes, only doctrine gets the pack, and every
# safety/model flag reaches the CLI. A malformed usage variant proves paid
# inference still records INVALID instead of crashing the harness.
SFX="$(mktemp -d)"
mkdir -p "${SFX}/bin" "${SFX}/real-home" "${SFX}/audit"
printf '{"fake":"auth"}\n' > "${SFX}/real-home/auth.json"
# arm_diff_is_catalog_only <doctrine.files> <noskills.files>: the two
# inventories (cksum lines) differ only by files under skills/<name>/ or
# .luciazero-managed/skills/<name>/ for a catalog name, every catalog name
# lost at least one file, and noskills added nothing.
arm_diff_is_catalog_only() {
  python3 - "$1" "$2" "${ROOT}/skills/catalog.txt" "${ROOT}/skills/aliases.txt" <<'PY'
import re, sys
full, stripped = (set(open(p).read().splitlines()) for p in sys.argv[1:3])
catalog = set()
for path in sys.argv[3:5]:
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#"):
            catalog.add(line)
added = stripped - full
if added:
    sys.exit(f"noskills holds files doctrine does not: {sorted(added)[:5]}")
lost = {}
for line in full - stripped:
    path = line.split(None, 2)[2]
    m = re.match(r"\./(\.luciazero-managed/)?skills/([^/]+)/", path)
    if not m or m.group(2) not in catalog:
        sys.exit(f"doctrine and noskills differ outside the catalog skills: {path}")
    lost.setdefault(m.group(2), 0)
    lost[m.group(2)] += 1
missing = catalog - set(lost)
if missing:
    sys.exit(f"noskills still holds every file of {sorted(missing)}")
PY
}
cat > "${SFX}/bin/codex" <<'FAKECODEXOK'
#!/bin/sh
if [ "${1:-}" = --version ]; then
  echo 'codex-cli test-success'
  exit 0
fi
ARM=bare
PACK=no
if [ -f "${CODEX_HOME}/AGENTS.md" ] && [ -d "${CODEX_HOME}/skills" ]; then
  ARM=doctrine
  PACK=yes
fi
# under Codex the reviewer agent is a skill directory too, so the catalog
# count and the reviewer are audited apart: noskills keeps the reviewer
CATALOG=$(ls -d "${CODEX_HOME}"/skills/*/SKILL.md 2>/dev/null | grep -vc '/skills/reviewer/' || true)
REVIEWER=no
[ -f "${CODEX_HOME}/skills/reviewer/SKILL.md" ] && REVIEWER=yes
if [ "${PACK}" = yes ] && [ "${CATALOG}" = 0 ]; then ARM=noskills; fi
AUTH=no
[ -s "${CODEX_HOME}/auth.json" ] && AUTH=yes
{
  printf 'auth=%s\npack=%s\nparent-key=%s\ncatalog=%s\nreviewer=%s\n' \
    "${AUTH}" "${PACK}" "${CODEX_API_KEY:+present}" "${CATALOG}" "${REVIEWER}"
  for ARG in "$@"; do printf 'arg=%s\n' "${ARG}"; done
} > "${FAKE_CODEX_AUDIT_DIR}/${ARM}.txt"
# every file the home holds, with a checksum, so two arms can be diffed
(cd "${CODEX_HOME}" && find . -type f | sort | xargs cksum) > "${FAKE_CODEX_AUDIT_DIR}/${ARM}.files"
if [ "${FAKE_CODEX_BAD_USAGE:-0}" = 1 ]; then
  printf '%s\n' \
    '{"type":"turn.started"}' \
    '{"type":"turn.completed","usage":{"input_tokens":null,"output_tokens":"bad"}}'
elif [ "${FAKE_CODEX_BAD_USAGE:-0}" = 2 ]; then
  printf '%s\n' '[]'
else
  printf '%s\n' \
    '{"type":"turn.started"}' \
    '{"type":"turn.completed","usage":{"input_tokens":12,"cached_input_tokens":4,"output_tokens":3,"reasoning_output_tokens":1}}'
fi
FAKECODEXOK
chmod +x "${SFX}/bin/codex"
CODEX_HOME="${SFX}/real-home" CODEX_API_KEY='test-key-never-log' \
  FAKE_CODEX_AUDIT_DIR="${SFX}/audit" PATH="${SFX}/bin:${PATH}" \
  "${ROOT}/eval/run.sh" --discard-work --provider codex --model gpt-5.6-terra \
  --reasoning-effort medium --use-login --allow-dirty --arms doctrine,noskills,bare \
  --out "${SFX}/ok.jsonl" false-green \
  >/dev/null 2>&1 \
  || { rm -rf "${SFX}"; fail "successful fake Codex adapter run failed"; }
for ARM in doctrine noskills bare; do
  AUDIT="${SFX}/audit/${ARM}.txt"
  [ -f "${AUDIT}" ] || { rm -rf "${SFX}"; fail "missing ${ARM} Codex audit"; }
  grep -qx 'auth=yes' "${AUDIT}" \
    || { rm -rf "${SFX}"; fail "Codex auth not copied into ${ARM} home"; }
  grep -qx 'parent-key=present' "${AUDIT}" \
    || { rm -rf "${SFX}"; fail "fake Codex parent did not receive auth key"; }
  grep -Fqx 'arg=--model' "${AUDIT}" \
    || { rm -rf "${SFX}"; fail "Codex model flag missing"; }
  grep -Fqx 'arg=gpt-5.6-terra' "${AUDIT}" \
    || { rm -rf "${SFX}"; fail "Codex model value missing"; }
  grep -Fqx 'arg=model_reasoning_effort="medium"' "${AUDIT}" \
    || { rm -rf "${SFX}"; fail "Codex reasoning config missing"; }
  grep -Fqx 'arg=shell_environment_policy.inherit="core"' "${AUDIT}" \
    || { rm -rf "${SFX}"; fail "Codex core environment policy missing"; }
  grep -Fqx 'arg=shell_environment_policy.ignore_default_excludes=false' "${AUDIT}" \
    || { rm -rf "${SFX}"; fail "Codex secret exclusion policy missing"; }
  for FLAG in --sandbox workspace-write --ephemeral --ignore-user-config \
    --ignore-rules --skip-git-repo-check --json; do
    grep -Fqx "arg=${FLAG}" "${AUDIT}" \
      || { rm -rf "${SFX}"; fail "Codex adapter missing ${FLAG}"; }
  done
done
grep -qx 'pack=yes' "${SFX}/audit/doctrine.txt" \
  || { rm -rf "${SFX}"; fail "doctrine Codex home lacks installed pack"; }
CATALOG_N="$(sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "${ROOT}/skills/catalog.txt" "${ROOT}/skills/aliases.txt" | wc -l | tr -d ' ')"
grep -qx "catalog=${CATALOG_N}" "${SFX}/audit/doctrine.txt" \
  || { rm -rf "${SFX}"; fail "doctrine Codex home: $(grep '^catalog=' "${SFX}/audit/doctrine.txt"), want catalog=${CATALOG_N}"; }
grep -qx 'pack=no' "${SFX}/audit/bare.txt" \
  || { rm -rf "${SFX}"; fail "bare Codex home inherited the pack"; }
# noskills under Codex: doctrine (AGENTS.md) and the reviewer skill stay,
# every catalog skill is gone
grep -qx 'pack=yes' "${SFX}/audit/noskills.txt" \
  || { rm -rf "${SFX}"; fail "noskills Codex home lost the doctrine"; }
grep -qx 'reviewer=yes' "${SFX}/audit/noskills.txt" \
  || { rm -rf "${SFX}"; fail "noskills Codex home lost the reviewer skill"; }
grep -qx 'catalog=0' "${SFX}/audit/noskills.txt" \
  || { rm -rf "${SFX}"; fail "noskills Codex home kept catalog skills: $(grep '^catalog=' "${SFX}/audit/noskills.txt")"; }
# the pair differs in the catalog skills and nothing else: same command
# line (model, reasoning, sandbox flags), same files with the same content
# everywhere but under skills/<catalog>/ and its managed copy
if ! diff <(grep -v '^catalog=' "${SFX}/audit/doctrine.txt") <(grep -v '^catalog=' "${SFX}/audit/noskills.txt") >/dev/null; then
  rm -rf "${SFX}"; fail "doctrine and noskills Codex invocations differ beyond the catalog count: $(diff "${SFX}/audit/doctrine.txt" "${SFX}/audit/noskills.txt" | head -5)"
fi
arm_diff_is_catalog_only "${SFX}/audit/doctrine.files" "${SFX}/audit/noskills.files" \
  || { rm -rf "${SFX}"; fail "Codex doctrine/noskills homes differ beyond the catalog skills"; }
if grep -R -q 'test-key-never-log' "${SFX}/audit" "${SFX}/ok.jsonl"; then
  rm -rf "${SFX}"; fail "Codex credential value leaked into eval artifacts"
fi
python3 - "${SFX}/ok.jsonl" <<'PY' \
  || { rm -rf "${SFX}"; fail "successful fake Codex rows wrong"; }
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 3
assert all(row["invalid"] is False for row in rows)
assert all(row["tokens_in"] == 12 and row["tokens_out"] == 3 for row in rows)
by = {row["arm"]: row for row in rows}
assert by["doctrine"]["skills_installed"] is True
assert by["noskills"]["skills_installed"] is False and by["bare"]["skills_installed"] is False
# the fake ran no command, so the Codex trace shows a completed turn and no
# skill: not observed, never unknown
assert all(row["skill_use"]["status"] == "not observed" for row in rows), rows
PY
CODEX_HOME="${SFX}/real-home" CODEX_API_KEY='test-key-never-log' \
  FAKE_CODEX_AUDIT_DIR="${SFX}/audit" FAKE_CODEX_BAD_USAGE=1 \
  PATH="${SFX}/bin:${PATH}" "${ROOT}/eval/run.sh" --discard-work --provider codex \
  --model gpt-5.6-terra --reasoning-effort medium --use-login --allow-dirty \
  --out "${SFX}/bad.jsonl" false-green >/dev/null 2>&1 \
  || { rm -rf "${SFX}"; fail "malformed Codex usage aborted run.sh"; }
python3 - "${SFX}/bad.jsonl" <<'PY' \
  || { rm -rf "${SFX}"; fail "malformed Codex usage rows wrong"; }
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 2
assert all(row["invalid"] is True for row in rows)
assert all(row["tokens_in"] is None and row["tokens_out"] is None for row in rows)
assert all("usage.input_tokens" in row["invalid_reason"] for row in rows)
PY
CODEX_HOME="${SFX}/real-home" CODEX_API_KEY='test-key-never-log' \
  FAKE_CODEX_AUDIT_DIR="${SFX}/audit" FAKE_CODEX_BAD_USAGE=2 \
  PATH="${SFX}/bin:${PATH}" "${ROOT}/eval/run.sh" --discard-work --provider codex \
  --model gpt-5.6-terra --reasoning-effort medium --use-login --allow-dirty \
  --out "${SFX}/nonobject.jsonl" false-green >/dev/null 2>&1 \
  || { rm -rf "${SFX}"; fail "non-object Codex event aborted run.sh"; }
python3 - "${SFX}/nonobject.jsonl" <<'PY' \
  || { rm -rf "${SFX}"; fail "non-object Codex event rows wrong"; }
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 2
assert all(row["invalid"] is True for row in rows)
assert all(row["tokens_in"] is None and row["tokens_out"] is None for row in rows)
assert all("not an object" in row["invalid_reason"] for row in rows)
PY
rm -rf "${SFX}"
echo "ok  Codex success path isolates auth, config, arms, and usage errors"

# 4d2c. offline smoke mode: full copy -> grade -> JSONL -> report loop with
# zero API; rows must be branded offline and the report must say SYNTHETIC
OFJ="$(mktemp -d)"
"${ROOT}/eval/run.sh" --discard-work --offline --with-lessons --seed fixture-seed \
  --campaign-id fixture-campaign --out "${OFJ}/r.jsonl" false-green >/dev/null 2>&1 \
  || { rm -rf "${OFJ}"; fail "run.sh --offline exited non-zero"; }
python3 - "${OFJ}/r.jsonl" <<'PY' || { rm -rf "${OFJ}"; fail "offline JSONL rows wrong"; }
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
assert len(rows) == 3, f"want 3 arms, got {len(rows)}"
assert {r["arm"] for r in rows} == {"doctrine", "bare", "lessons"}
assert all(r["offline"] is True for r in rows), "rows not branded offline"
assert all(r["provider"] == "claude" for r in rows), "default provider drifted"
assert all(r["invalid"] is False for r in rows), "offline rows marked invalid"
assert all(r["result_schema"] == 2 for r in rows)
assert all(r["campaign_id"] == "fixture-campaign" for r in rows)
assert len({r["pair_id"] for r in rows}) == 1
assert [r["arm"] for r in rows] == rows[0]["arm_order"]
assert all(r["seed"] == "fixture-seed" for r in rows)
assert all(len(r["task_sha256"]) == 64 and len(r["prompt_sha256"]) == 64 for r in rows)
assert all(r["repository_commit"] and r["system"] and r["architecture"] for r in rows)
assert all(r["runner_profile"].startswith("claude -p ") for r in rows)
assert len({r["invocation_id"] for r in rows}) == 3
by = {r["arm"]: r for r in rows}
assert by["doctrine"]["score"] == "6/6", by["doctrine"]["score"]
assert by["bare"]["score"] != "6/6", "bare arm must keep the planted bug"
PY
"${ROOT}/eval/run.sh" --discard-work --offline --seed relay-fixture-seed \
  --campaign-id relay-fixture-campaign --out "${OFJ}/relay.jsonl" \
  relay-transfer >/dev/null 2>&1 \
  || { rm -rf "${OFJ}"; fail "run.sh skipped or broke task setup"; }
python3 - "${OFJ}/relay.jsonl" <<'PY' \
  || { rm -rf "${OFJ}"; fail "relay offline setup/overlay rows wrong"; }
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 2
by = {row["arm"]: row for row in rows}
assert by["doctrine"]["score"] == "6/6"
assert by["bare"]["score"] == "1/6"
assert all(row["invalid"] is False and row["offline"] is True for row in rows)
PY
if "${ROOT}/eval/run.sh" --discard-work --offline --model gpt-5.6-terra false-green \
  >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh accepted Codex-only flags for Claude"
fi
if "${ROOT}/eval/run.sh" --discard-work --offline --runs 0 false-green >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh accepted zero repetitions"
fi
if "${ROOT}/eval/run.sh" --discard-work --offline --run-offset nope false-green >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh accepted a non-numeric run offset"
fi
if "${ROOT}/eval/run.sh" --discard-work --offline --resume --out "${OFJ}/missing.jsonl" \
  false-green >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh resumed without explicit campaign ID and seed"
fi
if "${ROOT}/eval/run.sh" --discard-work --offline --resume --seed resume-seed \
  --campaign-id resume-campaign --out "${OFJ}/missing.jsonl" \
  false-green >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh resumed a missing output file"
fi
: > "${OFJ}/empty.jsonl"
if "${ROOT}/eval/run.sh" --discard-work --offline --resume --seed resume-seed \
  --campaign-id resume-campaign --out "${OFJ}/empty.jsonl" \
  false-green >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh resumed an empty output file"
fi
"${ROOT}/eval/run.sh" --discard-work --offline --seed resume-seed --campaign-id resume-campaign \
  --runs 1 --out "${OFJ}/resume.jsonl" false-green >/dev/null 2>&1 \
  || { rm -rf "${OFJ}"; fail "run.sh initial resumable batch exited non-zero"; }
# Simulate an interruption after the first arm: resume must skip that exact
# invocation and fill only its missing pair mate.
python3 - "${OFJ}/resume.jsonl" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
path.write_text(path.read_text().splitlines()[0] + "\n")
PY
"${ROOT}/eval/run.sh" --discard-work --offline --resume --seed resume-seed \
  --campaign-id resume-campaign --runs 1 --out "${OFJ}/resume.jsonl" \
  false-green >/dev/null 2>&1 \
  || { rm -rf "${OFJ}"; fail "run.sh resumed batch exited non-zero"; }
python3 - "${OFJ}/resume.jsonl" <<'PY' \
  || { rm -rf "${OFJ}"; fail "run.sh resumed batch reused invocation IDs"; }
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 2
assert {row["run"] for row in rows} == {1}
assert len({row["pair_id"] for row in rows}) == 1
assert len({row["invocation_id"] for row in rows}) == 2
PY
"${ROOT}/eval/report.sh" "${OFJ}/resume.jsonl" >/dev/null \
  || { rm -rf "${OFJ}"; fail "report.sh rejected a correctly resumed campaign"; }
# Appending to a final JSON object without a newline would corrupt JSONL.
cp "${OFJ}/resume.jsonl" "${OFJ}/no-newline.jsonl"
python3 - "${OFJ}/no-newline.jsonl" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
path.write_bytes(path.read_bytes().rstrip(b"\n"))
PY
cp "${OFJ}/no-newline.jsonl" "${OFJ}/no-newline.before"
if "${ROOT}/eval/run.sh" --discard-work --offline --resume --seed resume-seed \
  --campaign-id resume-campaign --runs 1 --out "${OFJ}/no-newline.jsonl" \
  false-green >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh resumed a JSONL file without a final newline"
fi
cmp -s "${OFJ}/no-newline.before" "${OFJ}/no-newline.jsonl" \
  || { rm -rf "${OFJ}"; fail "failed resume mutated no-newline JSONL"; }
# Drift in a later task must abort before an earlier missing arm is appended.
python3 - "${OFJ}/resume.jsonl" "${OFJ}/preflight.jsonl" <<'PY'
import json, pathlib, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
first = rows[0]
later = dict(first, task="slugify", pair_id="resume-campaign/slugify/1",
             invocation_id="resume-campaign/slugify/1/" + first["arm"],
             task_sha256="0" * 64, prompt_sha256="0" * 64)
pathlib.Path(sys.argv[2]).write_text(
    "\n".join(json.dumps(row) for row in (first, later)) + "\n"
)
PY
BEFORE_LINES="$(wc -l < "${OFJ}/preflight.jsonl" | tr -d ' ')"
if "${ROOT}/eval/run.sh" --discard-work --offline --resume --seed resume-seed \
  --campaign-id resume-campaign --runs 1 --out "${OFJ}/preflight.jsonl" \
  false-green slugify >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh resumed after a later task failed preflight"
fi
[ "${BEFORE_LINES}" = "$(wc -l < "${OFJ}/preflight.jsonl" | tr -d ' ')" ] \
  || { rm -rf "${OFJ}"; fail "resume spent/appended before full task preflight"; }
# A tampered deterministic order must also fail before filling a missing mate.
python3 - "${OFJ}/resume.jsonl" "${OFJ}/order-drift.jsonl" <<'PY'
import json, pathlib, sys
row = json.loads(open(sys.argv[1]).readline())
row["arm_order"] = list(reversed(row["arm_order"]))
pathlib.Path(sys.argv[2]).write_text(json.dumps(row) + "\n")
PY
if "${ROOT}/eval/run.sh" --discard-work --offline --resume --seed resume-seed \
  --campaign-id resume-campaign --runs 1 --out "${OFJ}/order-drift.jsonl" \
  false-green >/dev/null 2>&1; then
  rm -rf "${OFJ}"; fail "run.sh resumed after deterministic arm-order drift"
fi
[ "$(wc -l < "${OFJ}/order-drift.jsonl" | tr -d ' ')" = 1 ] \
  || { rm -rf "${OFJ}"; fail "arm-order drift appended before preflight"; }
"${ROOT}/eval/report.sh" "${OFJ}/r.jsonl" | grep -q 'SYNTHETIC OFFLINE SMOKE' \
  || { rm -rf "${OFJ}"; fail "report.sh did not brand offline rows SYNTHETIC"; }
"${ROOT}/eval/report.sh" "${ROOT}/eval/testdata/sample-results-offline.jsonl" > "${OFJ}/off.md" \
  || { rm -rf "${OFJ}"; fail "report.sh failed on the offline fixture"; }
cmp -s "${OFJ}/off.md" "${ROOT}/eval/testdata/sample-report-offline.md" \
  || { rm -rf "${OFJ}"; fail "report.sh output drifted from eval/testdata/sample-report-offline.md"; }
# Codex adapter takes the same zero-quota route and records its locked model
# settings even when no Codex CLI is installed in CI.
mkdir -p "${OFJ}/codex-home"
printf '{"fake":"codex-auth"}\n' > "${OFJ}/codex-home/auth.json"
CODEX_HOME="${OFJ}/codex-home" "${ROOT}/eval/run.sh" --discard-work --offline \
  --provider codex --model gpt-5.6-terra --reasoning-effort medium \
  --use-login --out "${OFJ}/codex.jsonl" false-green >/dev/null 2>&1 \
  || { rm -rf "${OFJ}"; fail "Codex offline adapter exited non-zero"; }
python3 - "${OFJ}/codex.jsonl" <<'PY' \
  || { rm -rf "${OFJ}"; fail "Codex offline adapter rows wrong"; }
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 2
assert all(row["provider"] == "codex" for row in rows)
assert all(row["model"] == "gpt-5.6-terra" for row in rows)
assert all(row["reasoning_effort"] == "medium" for row in rows)
assert all(row["offline"] is True for row in rows)
PY
rm -rf "${OFJ}"
echo "ok  offline smoke mode end to end"

# 4d2d. --use-login plumbing: with login state under a fake HOME the sandbox
# seed line must appear once per arm; with an empty fake HOME the flag must
# warn instead of failing the run. Both offline — no CLI, no auth, no spend.
UL="$(mktemp -d)"
mkdir -p "${UL}/home/.claude"
printf '{"fake": "login-state"}\n' > "${UL}/home/.claude.json"
printf '{"fake": "credentials"}\n' > "${UL}/home/.claude/.credentials.json"
HOME="${UL}/home" "${ROOT}/eval/run.sh" --discard-work --offline --use-login --out "${UL}/r.jsonl" false-green \
  > "${UL}/out.log" 2>"${UL}/err.log" \
  || { rm -rf "${UL}"; fail "run.sh --use-login exited non-zero"; }
[ "$(grep -c 'login state seeded into sandbox config' "${UL}/out.log")" = 2 ] \
  || { rm -rf "${UL}"; fail "--use-login did not seed both arms' sandboxes"; }
# fake `security` binaries make the macOS Keychain branch deterministic on
# any OS: one that answers with a credential blob, one that always denies
mkdir -p "${UL}/bin" "${UL}/nobin" "${UL}/empty-home"
cat > "${UL}/bin/security" <<'FAKESEC'
#!/bin/sh
[ "$1" = find-generic-password ] || exit 1
printf '%s' '{}'
FAKESEC
printf '#!/bin/sh\nexit 1\n' > "${UL}/nobin/security"
chmod +x "${UL}/bin/security" "${UL}/nobin/security"
HOME="${UL}/empty-home" PATH="${UL}/bin:${PATH}" \
  "${ROOT}/eval/run.sh" --discard-work --offline --use-login false-green > "${UL}/out2.log" 2>&1 \
  || { rm -rf "${UL}"; fail "run.sh --use-login (keychain path) exited non-zero"; }
[ "$(grep -c 'keychain credentials exported into sandbox config' "${UL}/out2.log")" = 2 ] \
  || { rm -rf "${UL}"; fail "--use-login did not export keychain credentials"; }
HOME="${UL}/empty-home" PATH="${UL}/nobin:${PATH}" \
  "${ROOT}/eval/run.sh" --discard-work --offline --use-login false-green \
  > /dev/null 2>"${UL}/err2.log" \
  || { rm -rf "${UL}"; fail "run.sh --use-login with no login state exited non-zero"; }
grep -q 'warn: --use-login found no login state' "${UL}/err2.log" \
  || { rm -rf "${UL}"; fail "--use-login did not warn on missing login state"; }
rm -rf "${UL}"
echo "ok  --use-login seeds sandboxes and warns when no login state exists"

# 4d2e. run.sh's temp directories live under TMPDIR, on every path: by
# default an offline run keeps its work copy and provider logs (two
# directories per arm) and nothing else — the sandbox config is gone;
# --discard-work leaves none; a run that dies after the directories exist
# (--out pointing at a directory) keeps them by default and leaves none with
# --discard-work. The private TMPDIR is what gives the counts meaning: a bare
# mktemp ignores TMPDIR on macOS, which is why run.sh passes a template.
mktmp DW
mkdir -p "${DW}/keep" "${DW}/discard" "${DW}/red" "${DW}/red-keep"
count_in() { find "$1" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' '; }
TMPDIR="${DW}/keep" "${ROOT}/eval/run.sh" --offline false-green >/dev/null 2>&1 \
  || fail "offline run.sh (default) exited non-zero"
[ "$(count_in "${DW}/keep")" = 4 ] \
  || fail "a default offline run kept $(count_in "${DW}/keep") directories under TMPDIR, want 4 (work copy and logs per arm, no config)"
[ "$(find "${DW}/keep" -maxdepth 2 -name test_csv_export.py | wc -l | tr -d ' ')" = 2 ] \
  || fail "the kept directories are not the work copies"
TMPDIR="${DW}/discard" "${ROOT}/eval/run.sh" --offline --discard-work false-green >/dev/null 2>&1 \
  || fail "offline run.sh --discard-work exited non-zero"
[ "$(count_in "${DW}/discard")" = 0 ] \
  || fail "--discard-work left $(count_in "${DW}/discard") directories under TMPDIR"
RC=0; TMPDIR="${DW}/red-keep" "${ROOT}/eval/run.sh" --offline --out "${DW}/red-keep" false-green >/dev/null 2>&1 || RC=$?
[ "${RC}" != 0 ] || fail "--out pointing at a directory did not fail the run"
[ "$(count_in "${DW}/red-keep")" = 2 ] \
  || fail "a red run kept $(count_in "${DW}/red-keep") directories under TMPDIR, want 2 (work copy and logs; the config must not survive)"
RC=0; TMPDIR="${DW}/red" "${ROOT}/eval/run.sh" --offline --discard-work --out "${DW}/red" false-green >/dev/null 2>&1 || RC=$?
[ "${RC}" != 0 ] || fail "--out pointing at a directory did not fail the run"
[ "$(count_in "${DW}/red")" = 0 ] \
  || fail "a red --discard-work run left $(count_in "${DW}/red") directories under TMPDIR"
echo "ok  run.sh work directories live under TMPDIR: kept by default, gone with --discard-work, gone on a red run"

# 4d2f. skills ablation: an arm pair that differs in the catalog skills only.
# (i) skill_use.py reads trace evidence of skill invocation from a provider
# log and classifies it observed / not observed / unknown — a Skill tool call,
# the skill body the harness injects after it, a Read of a SKILL.md, a Bash
# command running a skill script; a log without tool events is unknown, never
# "not observed". Evidence names skills and paths only, never content.
SU="${ROOT}/eval/skill_use.py"
# the catalog as the installers and run.sh read it, never a literal list
CATALOG="$(sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "${ROOT}/skills/catalog.txt" "${ROOT}/skills/aliases.txt" | paste -sd, -)"
CATALOG_N="$(sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "${ROOT}/skills/catalog.txt" "${ROOT}/skills/aliases.txt" | wc -l | tr -d ' ')"
mktmp SUF
printf '%s\n' \
  '{"type":"system","subtype":"init","skills":["code-review","debug","done","ready","verify"]}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"done"}}]}}' \
  '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t1","content":"Launching skill: done"}]}}' \
  '{"type":"user","message":{"content":[{"type":"text","text":"Base directory for this skill: /sb/skills/done\n\n# Done\n\nsecret body text"}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t2","name":"Read","input":{"file_path":"/sb/skills/ready/SKILL.md"}}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t3","name":"Bash","input":{"command":"sh /sb/skills/done/scripts/revert-probe.sh . && echo prompt-secret"}}]}}' \
  '{"type":"result","subtype":"success","is_error":false,"result":"ok","usage":{"input_tokens":1,"output_tokens":1},"num_turns":4}' \
  > "${SUF}/observed.jsonl"
printf '%s\n' \
  '{"type":"system","subtype":"init","slash_commands":["debug"]}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"luciazero:debug","args":"x"}}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t2","name":"Skill","input":{"skill":"code-review"}}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t3","name":"Read","input":{"file_path":"/elsewhere/skills/plan/SKILL.md"}}]}}' \
  '{"type":"user","message":{"content":[{"type":"text","text":"Base directory for this skill: /builtin/skills/debug\n\n# Debug"}]}}' \
  '{"type":"result","subtype":"success","is_error":false,"result":"ok","num_turns":3}' \
  > "${SUF}/prefixed.jsonl"
printf '%s\n' \
  '{"type":"system","subtype":"init","skills":["debug"]}' \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"reading skills/done/SKILL.md would be nice"}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Bash","input":{"command":"python3 -m unittest"}}]}}' \
  '{"type":"result","subtype":"success","is_error":false,"result":"ok","num_turns":2}' \
  > "${SUF}/none.jsonl"
# the same observation twice is one: a file read twice, a skill called
# twice with its body injected twice
printf '%s\n' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"done"}}]}}' \
  '{"type":"user","message":{"content":[{"type":"text","text":"Base directory for this skill: /sb/skills/done\n\n# Done"}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t2","name":"Skill","input":{"skill":"done"}}]}}' \
  '{"type":"user","message":{"content":[{"type":"text","text":"Base directory for this skill: /sb/skills/done\n\n# Done"}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t3","name":"Skill","input":{"skill":"done"}}]}}' \
  '{"type":"user","message":{"content":[{"type":"text","text":"Base directory for this skill: /sb/skills/done\n\n# Done"}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t4","name":"Read","input":{"file_path":"/sb/skills/done/SKILL.md"}}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t5","name":"Read","input":{"file_path":"/sb/skills/done/SKILL.md"}}]}}' \
  '{"type":"result","subtype":"success","is_error":false,"result":"ok","num_turns":5}' \
  > "${SUF}/dup.jsonl"
# the path a command names is read back to its start whatever sits before
# it: a quote, a VAR= assignment, a newline; trailing shell punctuation is
# not part of it; `myskills/` is not a skill directory
# shellcheck disable=SC2016  # the literal is the command as the agent typed it, $PROBE and all
printf '%s\n' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Bash","input":{"command":"cat \"/sb/skills/done/SKILL.md\"; PROBE=/sb/skills/done/scripts/revert-probe.sh; bash $PROBE\n/sb/skills/ready/scripts/detect.sh .; ls /x/myskills/plan/"}}]}}' \
  '{"type":"result","subtype":"success","is_error":false,"result":"ok","num_turns":1}' \
  > "${SUF}/paths.jsonl"
# the sandbox reached through a symlink still resolves to the sandbox
mkdir -p "${SUF}/real/skills/done"
ln -s "${SUF}/real" "${SUF}/link"
printf '%s\n' \
  "{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"id\":\"t1\",\"name\":\"Read\",\"input\":{\"file_path\":\"${SUF}/real/skills/done/SKILL.md\"}}]}}" \
  '{"type":"result","subtype":"success","is_error":false,"result":"ok","num_turns":1}' \
  > "${SUF}/symlink.jsonl"
printf '{"subtype":"success","is_error":false,"result":"fixed the bug","num_turns":9}\n' > "${SUF}/legacy.json"
printf 'offline smoke — no agent was run\n' > "${SUF}/text.log"
: > "${SUF}/empty.jsonl"
# one Codex command is started, updated and completed: one observation
printf '%s\n' \
  '{"type":"thread.started","thread_id":"t"}' \
  '{"type":"item.started","item":{"type":"command_execution","command":"bash /sb/skills/done/scripts/revert-probe.sh ."}}' \
  '{"type":"item.updated","item":{"type":"command_execution","command":"bash /sb/skills/done/scripts/revert-probe.sh ."}}' \
  '{"type":"item.completed","item":{"type":"command_execution","command":"bash /sb/skills/done/scripts/revert-probe.sh ."}}' \
  '{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":3}}' \
  > "${SUF}/codex-observed.jsonl"
printf '{"type":"thread.started","thread_id":"t"}\n' > "${SUF}/codex-started.jsonl"
printf '%s\n' \
  '{"type":"item.completed","item":{"type":"command_execution","command":"python3 -m unittest"}}' \
  '{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":3}}' \
  > "${SUF}/codex-none.jsonl"
SU_SKILLS_DIR=/sb/skills
su_check() { # su_check <label> <provider> <log> <python assertions on `r`>
  local OUT
  OUT="$(python3 "${SU}" --provider "$2" --catalog "${CATALOG}" --skills-dir "${SU_SKILLS_DIR}" "$3" 2>&1)" \
    || fail "skill_use.py failed on $1: ${OUT}"
  python3 - "${OUT}" "$4" <<'PY' || fail "skill_use.py misread $1: ${OUT}"
import json, sys
r = json.loads(sys.argv[1])
assert set(r) == {"status", "names", "evidence", "visible", "reason"}, sorted(r)
def ev(channel, name, path, source):
    return {"channel": channel, "name": name, "path": path, "source": source}
exec(sys.argv[2])
PY
}
su_check observed claude "${SUF}/observed.jsonl" '
assert r["status"] == "observed" and r["names"] == ["done", "ready"], r
assert r["evidence"] == [ev("Skill", "done", "skills/done/", "sandbox"),
                         ev("Read", "ready", "skills/ready/SKILL.md", "sandbox"),
                         ev("Bash", "done", "skills/done/scripts/revert-probe.sh", "sandbox")], r
assert r["visible"] == ["debug", "done", "ready"], r
assert r["reason"] is None
blob = json.dumps(r)
assert "secret body text" not in blob and "prompt-secret" not in blob, blob'
su_check prefixed claude "${SUF}/prefixed.jsonl" '
assert r["status"] == "observed" and r["names"] == ["debug", "plan"], r
assert r["evidence"] == [ev("Skill", "debug", "skills/debug/", "other"),
                         ev("Read", "plan", "skills/plan/SKILL.md", "other")], r
assert r["visible"] == ["debug"], r'
su_check none claude "${SUF}/none.jsonl" '
assert r["status"] == "not observed" and r["names"] == [] and r["evidence"] == [], r
assert r["visible"] == ["debug"] and r["reason"] is None, r'
su_check dup claude "${SUF}/dup.jsonl" '
assert r["status"] == "observed" and r["names"] == ["done"], r
assert r["evidence"] == [ev("Skill", "done", "skills/done/", "sandbox"),
                         ev("Read", "done", "skills/done/SKILL.md", "sandbox")], r'
su_check paths claude "${SUF}/paths.jsonl" '
assert r["status"] == "observed" and r["names"] == ["done", "ready"], r
assert r["evidence"] == [ev("Bash", "done", "skills/done/SKILL.md", "sandbox"),
                         ev("Bash", "done", "skills/done/scripts/revert-probe.sh", "sandbox"),
                         ev("Bash", "ready", "skills/ready/scripts/detect.sh", "sandbox")], r'
SU_SKILLS_DIR="${SUF}/link/skills" su_check symlink claude "${SUF}/symlink.jsonl" '
assert r["status"] == "observed", r
assert r["evidence"] == [ev("Read", "done", "skills/done/SKILL.md", "sandbox")], r'
su_check legacy claude "${SUF}/legacy.json" '
assert r["status"] == "unknown" and r["reason"] == "result-only log (no tool events)", r
assert r["names"] == [] and r["evidence"] == [] and r["visible"] is None, r'
su_check text claude "${SUF}/text.log" '
assert r["status"] == "unknown" and r["reason"] == "no structured events in log", r'
su_check empty claude "${SUF}/empty.jsonl" '
assert r["status"] == "unknown" and r["reason"] == "no structured events in log", r'
su_check codex-observed codex "${SUF}/codex-observed.jsonl" '
assert r["status"] == "observed" and r["names"] == ["done"], r
assert r["evidence"] == [ev("command", "done", "skills/done/scripts/revert-probe.sh", "sandbox")], r
assert r["visible"] is None'
su_check codex-none codex "${SUF}/codex-none.jsonl" '
assert r["status"] == "not observed" and r["evidence"] == [], r'
su_check codex-started codex "${SUF}/codex-started.jsonl" '
assert r["status"] == "unknown" and r["reason"] == "stream has no completed turns", r'
su_check codex-empty codex "${SUF}/empty.jsonl" '
assert r["status"] == "unknown" and r["reason"] == "no structured events in log", r'
RC=0; python3 "${SU}" --provider claude --catalog "${CATALOG}" "${SUF}/absent.jsonl" >/dev/null 2>&1 || RC=$?
[ "${RC}" -ne 0 ] || fail "skill_use.py accepted a missing log"
echo "ok  skill_use.py classifies trace evidence: observed, not observed, unknown"

# (ii) --arms doctrine,noskills runs the pair that isolates the skills: both
# arms get the doctrine and the reviewer agent, neither gets hooks, only
# doctrine keeps the catalog skills. A fake claude on PATH audits its
# sandbox config, answers with a stream-json transcript (a Skill call and a
# Read of a SKILL.md when skills are present, a plain Bash call otherwise)
# and a result object, so the rows, their skill-use evidence, the parsed
# usage and the report are all proven without inference or credentials.
mktmp SKA
mkdir -p "${SKA}/bin" "${SKA}/audit"
cat > "${SKA}/bin/claude" <<'FAKECLAUDE'
#!/bin/sh
if [ "${1:-}" = --version ]; then
  echo '9.9.9 (fake)'
  exit 0
fi
CFG="${CLAUDE_CONFIG_DIR:?}"
DOCTRINE=no; [ -f "${CFG}/luciazero.md" ] && DOCTRINE=yes
REVIEWER=no; [ -f "${CFG}/agents/reviewer.md" ] && REVIEWER=yes
HOOKS=no; [ -f "${CFG}/settings.json" ] && grep -q hooks "${CFG}/settings.json" && HOOKS=yes
SKILLS=$(find "${CFG}/skills" -mindepth 2 -maxdepth 2 -name SKILL.md 2>/dev/null | wc -l | tr -d ' ')
ARM=bare
if [ "${DOCTRINE}" = yes ]; then ARM=noskills; fi
if [ "${SKILLS}" != 0 ]; then ARM=doctrine; fi
{
  printf 'doctrine=%s\nreviewer=%s\nhooks=%s\nskills=%s\n' \
    "${DOCTRINE}" "${REVIEWER}" "${HOOKS}" "${SKILLS}"
  for ARG in "$@"; do printf 'arg=%s\n' "${ARG}"; done
} > "${FAKE_CLAUDE_AUDIT_DIR}/${ARM}.txt"
# every file the sandbox holds, with a checksum, so two arms can be diffed
(cd "${CFG}" && find . -type f | sort | xargs cksum) > "${FAKE_CLAUDE_AUDIT_DIR}/${ARM}.files"
echo 'warning: a line the real CLI prints on stderr' >&2
printf '%s\n' '{"type":"system","subtype":"init","skills":["code-review","debug","verify"]}'
if [ "${SKILLS}" != 0 ]; then
  printf '%s\n' \
    '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"done"}}]}}' \
    "{\"type\":\"user\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"Base directory for this skill: ${CFG}/skills/done\\n\\n# Done\"}]}}" \
    "{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"id\":\"t2\",\"name\":\"Read\",\"input\":{\"file_path\":\"${CFG}/skills/ready/SKILL.md\"}}]}}"
else
  printf '%s\n' \
    '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Bash","input":{"command":"python3 -m unittest"}}]}}'
fi
printf '%s\n' '{"type":"result","subtype":"success","is_error":false,"result":"done","usage":{"input_tokens":12,"output_tokens":3},"total_cost_usd":0.05,"num_turns":3,"modelUsage":{"fake-model":{}}}'
FAKECLAUDE
chmod +x "${SKA}/bin/claude"
FAKE_CLAUDE_AUDIT_DIR="${SKA}/audit" PATH="${SKA}/bin:${PATH}" \
  "${ROOT}/eval/run.sh" --discard-work --arms doctrine,noskills --allow-dirty \
  --seed skills-seed --campaign-id skills-campaign \
  --out "${SKA}/r.jsonl" false-green >"${SKA}/run.out" 2>&1 \
  || fail "run.sh --arms doctrine,noskills failed with the fake claude: $(tail -5 "${SKA}/run.out")"
[ ! -e "${SKA}/audit/bare.txt" ] || fail "--arms doctrine,noskills ran a bare arm"
for ARM in doctrine noskills; do
  AUDIT="${SKA}/audit/${ARM}.txt"
  [ -f "${AUDIT}" ] || fail "missing ${ARM} claude audit (arms recorded: $(find "${SKA}/audit" -name '*.txt' | tr '\n' ' '))"
  grep -qx 'doctrine=yes' "${AUDIT}" || fail "${ARM} sandbox lacks the doctrine"
  grep -qx 'reviewer=yes' "${AUDIT}" || fail "${ARM} sandbox lacks the reviewer agent"
  grep -qx 'hooks=no' "${AUDIT}" || fail "${ARM} sandbox has hooks wired"
  grep -Fqx 'arg=--output-format' "${AUDIT}" || fail "${ARM}: no --output-format reached the CLI"
  grep -Fqx 'arg=stream-json' "${AUDIT}" || fail "${ARM}: the CLI was not asked for stream-json (tool events)"
  grep -Fqx 'arg=--verbose' "${AUDIT}" || fail "${ARM}: stream-json needs --verbose in -p mode"
done
grep -qx "skills=${CATALOG_N}" "${SKA}/audit/doctrine.txt" \
  || fail "doctrine sandbox skill count: $(grep '^skills=' "${SKA}/audit/doctrine.txt"), want ${CATALOG_N}"
grep -qx 'skills=0' "${SKA}/audit/noskills.txt" \
  || fail "noskills sandbox kept skills: $(grep '^skills=' "${SKA}/audit/noskills.txt")"
# the pair differs in the catalog skills and nothing else: the same command
# line reached the CLI (the prompt is the same file), and the sandboxes hold
# the same files with the same content everywhere but under skills/<catalog>/
# and its managed copy — doctrine text, reviewer agent, settings included
diff <(grep -v '^skills=' "${SKA}/audit/doctrine.txt") <(grep -v '^skills=' "${SKA}/audit/noskills.txt") >/dev/null \
  || fail "doctrine and noskills claude invocations differ beyond the skill count: $(diff "${SKA}/audit/doctrine.txt" "${SKA}/audit/noskills.txt" | head -5)"
arm_diff_is_catalog_only "${SKA}/audit/doctrine.files" "${SKA}/audit/noskills.files" \
  || fail "claude doctrine/noskills sandboxes differ beyond the catalog skills"
python3 - "${SKA}/r.jsonl" <<'PY' || fail "skills-ablation rows wrong"
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
assert len(rows) == 2, len(rows)
by = {r["arm"]: r for r in rows}
assert set(by) == {"doctrine", "noskills"}, set(by)
assert all(r["arm_order"] == rows[0]["arm_order"] and set(r["arm_order"]) == {"doctrine", "noskills"} for r in rows)
assert all(r["invalid"] is False and r["offline"] is False for r in rows), rows
assert all(r["tokens_in"] == 12 and r["tokens_out"] == 3 and r["cost_usd"] == 0.05
           and r["num_turns"] == 3 and r["model"] == "fake-model" for r in rows), rows
assert all(r["cli_version"] == "9.9.9 (fake)" for r in rows)
assert by["doctrine"]["skills_installed"] is True and by["noskills"]["skills_installed"] is False
d = by["doctrine"]["skill_use"]
assert d["status"] == "observed" and d["names"] == ["done", "ready"], d
assert d["evidence"] == [{"channel": "Skill", "name": "done", "path": "skills/done/", "source": "sandbox"},
                         {"channel": "Read", "name": "ready", "path": "skills/ready/SKILL.md", "source": "sandbox"}], d
assert d["visible"] == ["debug"], d
n = by["noskills"]["skill_use"]
assert n["status"] == "not observed" and n["names"] == [] and n["evidence"] == [], n
assert n["visible"] == ["debug"], n
PY
"${ROOT}/eval/report.sh" "${SKA}/r.jsonl" > "${SKA}/report.md" \
  || fail "report.sh rejected the skills-ablation rows"
grep -q '^| criterion | doctrine | noskills | doctrine-noskills |$' "${SKA}/report.md" \
  || fail "report lacks the doctrine-noskills column: $(grep '^| criterion' "${SKA}/report.md")"
grep -q '^skill use (trace evidence, valid runs): doctrine observed 1/1 (done x1, ready x1); noskills not observed 1/1$' "${SKA}/report.md" \
  || fail "report skill-use line wrong: $(grep '^skill use' "${SKA}/report.md")"
# the arm set is part of the campaign: a resume with another --arms is refused
RC=0; FAKE_CLAUDE_AUDIT_DIR="${SKA}/audit" PATH="${SKA}/bin:${PATH}" \
  "${ROOT}/eval/run.sh" --discard-work --arms doctrine,bare --allow-dirty --resume \
  --seed skills-seed --campaign-id skills-campaign \
  --out "${SKA}/r.jsonl" false-green >/dev/null 2>&1 || RC=$?
[ "${RC}" -ne 0 ] || fail "run.sh resumed a doctrine,noskills campaign with --arms doctrine,bare"
# and the same --arms resumes cleanly with nothing left to run
FAKE_CLAUDE_AUDIT_DIR="${SKA}/audit" PATH="${SKA}/bin:${PATH}" \
  "${ROOT}/eval/run.sh" --discard-work --arms noskills,doctrine --allow-dirty --resume \
  --seed skills-seed --campaign-id skills-campaign \
  --out "${SKA}/r.jsonl" false-green >"${SKA}/resume.out" 2>&1 \
  || fail "run.sh refused to resume its own --arms campaign: $(tail -3 "${SKA}/resume.out")"
[ "$(grep -c 'SKIP — already recorded' "${SKA}/resume.out")" = 2 ] \
  || fail "resume of a complete --arms campaign did not skip both invocations"
[ "$(wc -l < "${SKA}/r.jsonl" | tr -d ' ')" = 2 ] || fail "resume appended rows to a complete campaign"
# offline rows carry the same fields, with the skill-use status unknown
"${ROOT}/eval/run.sh" --discard-work --offline --arms doctrine,noskills,bare \
  --out "${SKA}/off.jsonl" false-green >/dev/null 2>&1 \
  || fail "run.sh --offline --arms doctrine,noskills,bare failed"
python3 - "${SKA}/off.jsonl" <<'PY' || fail "offline --arms rows wrong"
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
by = {r["arm"]: r for r in rows}
assert set(by) == {"doctrine", "noskills", "bare"}, set(by)
assert by["doctrine"]["skills_installed"] is True
assert by["noskills"]["skills_installed"] is False and by["bare"]["skills_installed"] is False
assert all(r["skill_use"]["status"] == "unknown"
           and r["skill_use"]["reason"] == "offline smoke — no agent was run" for r in rows), rows
assert by["noskills"]["score"] == "6/6" and by["bare"]["score"] != "6/6"
PY
for BAD_ARMS in '' 'doctrine,doctrine' 'doctrine,lessons' 'doctrine-only' 'doctrine,'; do
  if "${ROOT}/eval/run.sh" --discard-work --offline --arms "${BAD_ARMS}" false-green >/dev/null 2>&1; then
    fail "run.sh accepted --arms '${BAD_ARMS}'"
  fi
done
# a flag with no value is a red exit, not a message followed by a run:
# `${2:?...}` under an armed EXIT trap exits 0 on bash 3.2 (regression)
for FLAG in --arms --runs --out --seed; do
  if "${ROOT}/eval/run.sh" --discard-work --offline false-green "${FLAG}" >/dev/null 2>&1; then
    fail "run.sh went on after ${FLAG} with no value"
  fi
done
echo "ok  --arms doctrine,noskills isolates the catalog skills; rows carry install state and trace evidence"

# 4d3. revert-probe: a biting test passes, a vacuous test fails, non-git is
# unassessable — all in throwaway git fixtures, never the caller's tree
RP="${ROOT}/skills/done/scripts/revert-probe.sh"
RPX="$(mktemp -d)"
# fixture: committed bug + committed always-green test, fix left uncommitted
mkdir -p "${RPX}/bites/tests"
(
  cd "${RPX}/bites"
  git init -q .
  printf 'def add(a, b):\n    return a - b if a == 2 else a + b\n' > calc.py
  printf 'import calc\nassert calc.add(0, 0) == 0\nprint("ok")\n' > tests/test_calc.py
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm 'plant bug'
)
cp -R "${RPX}/bites" "${RPX}/vacuous"
cp -R "${RPX}/bites" "${RPX}/nocmd"
cp -R "${RPX}/bites" "${RPX}/bothred"
# (i) working-tree fix + a new test that bites -> probe exits 0
(
  cd "${RPX}/bites"
  printf 'def add(a, b):\n    return a + b\n' > calc.py
  printf 'import calc\nassert calc.add(0, 0) == 0\nassert calc.add(2, 2) == 4\nprint("ok")\n' > tests/test_calc.py
)
ST1="$(cd "${RPX}/bites" && git status --porcelain)"
RC=0; OUT="$(cd "${RPX}/bites" && PYTHONDONTWRITEBYTECODE=1 "${RP}" 'PYTHONPATH=. python3 tests/test_calc.py')" || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${RPX}"; fail "revert-probe rc=${RC} on a biting test: ${OUT}"; }
echo "${OUT}" | grep -q '^PASS' || { rm -rf "${RPX}"; fail "revert-probe did not print PASS: ${OUT}"; }
ST2="$(cd "${RPX}/bites" && git status --porcelain)"
[ "${ST1}" = "${ST2}" ] || { rm -rf "${RPX}"; fail "revert-probe touched the caller's working tree"; }
[ "$(cd "${RPX}/bites" && git worktree list | wc -l | tr -d ' ')" = 1 ] \
  || { rm -rf "${RPX}"; fail "revert-probe left a worktree behind"; }
# (ii) added test is vacuous (green with and without the fix) -> probe exits 1
(
  cd "${RPX}/vacuous"
  printf 'def add(a, b):\n    return a + b\n' > calc.py
  printf 'import calc\nassert calc.add(0, 0) == 0\nassert calc.add(1, 1) == 2\nprint("ok")\n' > tests/test_calc.py
)
RC=0; OUT="$(cd "${RPX}/vacuous" && PYTHONDONTWRITEBYTECODE=1 "${RP}" 'PYTHONPATH=. python3 tests/test_calc.py')" || RC=$?
[ "${RC}" = 1 ] || { rm -rf "${RPX}"; fail "revert-probe rc=${RC} on a vacuous test (want 1): ${OUT}"; }
echo "${OUT}" | grep -q 'stay green' || { rm -rf "${RPX}"; fail "vacuous-test verdict wrong: ${OUT}"; }
# (iii) not a git repo -> UNASSESSABLE, exit 2
mkdir -p "${RPX}/nogit"
RC=0; OUT="$(cd "${RPX}/nogit" && "${RP}" 'true')" || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${RPX}"; fail "revert-probe rc=${RC} outside git (want 2): ${OUT}"; }
echo "${OUT}" | grep -q '^UNASSESSABLE' || { rm -rf "${RPX}"; fail "missing UNASSESSABLE marker: ${OUT}"; }
# (iv) a non-ASCII test filename (C-quoted in git's plain output, raw with
# -z) must still be collected — regression: it was silently dropped
mkdir -p "${RPX}/uni/tests"
(
  cd "${RPX}/uni"
  git init -q .
  printf 'def add(a, b):\n    return a - b if a == 2 else a + b\n' > calc.py
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm 'plant bug'
  printf 'def add(a, b):\n    return a + b\n' > calc.py
  printf 'import calc\nassert calc.add(2, 2) == 4\nprint("ok")\n' > 'tests/test_héllo.py'
)
RC=0; OUT="$(cd "${RPX}/uni" && PYTHONDONTWRITEBYTECODE=1 "${RP}" 'PYTHONPATH=. python3 tests/test_h*.py')" || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${RPX}"; fail "revert-probe rc=${RC} on a non-ASCII test filename: ${OUT}"; }
# (v) this repository and many small projects keep assertions in root test.sh
mkdir -p "${RPX}/root-script"
(
  cd "${RPX}/root-script"
  git init -q .
  printf 'bad\n' > value
  printf '#!/bin/sh\ngrep -qx bad value\n' > test.sh
  chmod +x test.sh
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm 'plant bug'
  printf 'good\n' > value
  printf '#!/bin/sh\ngrep -qx good value\n' > test.sh
)
RC=0; OUT="$(cd "${RPX}/root-script" && "${RP}" './test.sh')" || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${RPX}"; fail "revert-probe ignored root test.sh: ${OUT}"; }
# (vi) a verify command that is not installed also fails on the old tree, for a
# reason that has nothing to do with the change -> UNASSESSABLE, never PASS
(
  cd "${RPX}/nocmd"
  printf 'def add(a, b):\n    return a + b\n' > calc.py
  printf 'import calc\nassert calc.add(2, 2) == 4\nprint("ok")\n' > tests/test_calc.py
)
RC=0; OUT="$(cd "${RPX}/nocmd" && "${RP}" 'luciazero-not-a-real-command tests/test_calc.py')" || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${RPX}"; fail "revert-probe rc=${RC} on a missing command (want 2): ${OUT}"; }
echo "${OUT}" | grep -q 'exit 127' || { rm -rf "${RPX}"; fail "missing-command verdict wrong: ${OUT}"; }
# (vii) the old tree cannot import a module the change adds — a red run that
# proves the file is new, not that the test asserts anything -> UNASSESSABLE
mkdir -p "${RPX}/newmod/tests"
(
  cd "${RPX}/newmod"
  git init -q .
  printf 'print("base")\n' > main.py
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm base
  printf 'def twice(n):\n    return n * 2\n' > helper.py
  printf 'import helper\nassert helper.twice(2) == 4\nprint("ok")\n' > tests/test_helper.py
)
RC=0; OUT="$(cd "${RPX}/newmod" && PYTHONDONTWRITEBYTECODE=1 "${RP}" 'PYTHONPATH=. python3 tests/test_helper.py')" || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${RPX}"; fail "revert-probe rc=${RC} on a parent-only import failure (want 2): ${OUT}"; }
echo "${OUT}" | grep -q 'never loaded the tests' || { rm -rf "${RPX}"; fail "import-failure verdict wrong: ${OUT}"; }
# (viii) a test that is red on the old code AND on the current code proves
# nothing about the change -> UNASSESSABLE
(
  cd "${RPX}/bothred"
  printf 'def add(a, b):\n    return a + b\n' > calc.py
  printf 'import calc\nassert calc.add(2, 2) == 5\nprint("ok")\n' > tests/test_calc.py
)
RC=0; OUT="$(cd "${RPX}/bothred" && PYTHONDONTWRITEBYTECODE=1 "${RP}" 'PYTHONPATH=. python3 tests/test_calc.py')" || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${RPX}"; fail "revert-probe rc=${RC} when current code fails too (want 2): ${OUT}"; }
echo "${OUT}" | grep -q 'also fails on the current code' \
  || { rm -rf "${RPX}"; fail "current-code control verdict wrong: ${OUT}"; }
# (ix) a whole-suite verify whose failure belongs to an unrelated broken test
# is not attributable to the changed tests -> UNASSESSABLE
mkdir -p "${RPX}/unrelated/tests"
(
  cd "${RPX}/unrelated"
  git init -q .
  printf 'def add(a, b):\n    return a - b if a == 2 else a + b\n' > calc.py
  printf 'assert False, "unrelated breakage"\n' > tests/test_broken.py
  printf '%s\n' '#!/bin/sh' "for f in tests/*.py; do PYTHONPATH=. python3 \"\$f\" || exit 1; done" > run-all.sh
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm 'plant bug and unrelated breakage'
  printf 'def add(a, b):\n    return a + b\n' > calc.py
  printf 'import calc\nassert calc.add(2, 2) == 4\nprint("ok")\n' > tests/test_calc.py
)
RC=0; OUT="$(cd "${RPX}/unrelated" && PYTHONDONTWRITEBYTECODE=1 "${RP}" 'sh run-all.sh')" || RC=$?
[ "${RC}" = 2 ] || { rm -rf "${RPX}"; fail "revert-probe rc=${RC} on an unrelated failure (want 2): ${OUT}"; }
echo "${OUT}" | grep -q 'cannot be attributed' \
  || { rm -rf "${RPX}"; fail "attribution verdict wrong: ${OUT}"; }
# (x) an untargeted suite still passes when the failure output names the
# changed test, and says so
mkdir -p "${RPX}/suite/tests"
(
  cd "${RPX}/suite"
  git init -q .
  printf 'def add(a, b):\n    return a - b if a == 2 else a + b\n' > calc.py
  printf '%s\n' '#!/bin/sh' "for f in tests/*.py; do PYTHONPATH=. python3 \"\$f\" || exit 1; done" > run-all.sh
  git add -A
  git -c user.email=t@t -c user.name=t commit -qm 'plant bug'
  printf 'def add(a, b):\n    return a + b\n' > calc.py
  printf 'import calc\nassert calc.add(2, 2) == 4\nprint("ok")\n' > tests/test_calc.py
)
RC=0; OUT="$(cd "${RPX}/suite" && PYTHONDONTWRITEBYTECODE=1 "${RP}" 'sh run-all.sh')" || RC=$?
[ "${RC}" = 0 ] || { rm -rf "${RPX}"; fail "revert-probe rc=${RC} on an untargeted but attributable suite: ${OUT}"; }
echo "${OUT}" | grep -q 'not targeted' || { rm -rf "${RPX}"; fail "missing untargeted note: ${OUT}"; }
rm -rf "${RPX}"
echo "ok  revert-probe bites/vacuous/unassessable"

# 4d4. demo.sh scaffolds the demo outside the repo; grader red on the untouched copy
DT="$(mktemp -d)"
"${ROOT}/demo.sh" "${DT}/demo" >/dev/null
[ -f "${DT}/demo/slugify.py" ] || { rm -rf "${DT}"; fail "demo target missing slugify.py"; }
[ -f "${DT}/demo/test_slugify.py" ] || { rm -rf "${DT}"; fail "demo target missing test_slugify.py"; }
[ -d "${DT}/demo/.git" ] || { rm -rf "${DT}"; fail "demo target is not a git repo"; }
# capture, then grep: grep -q on a pipe would SIGPIPE grade.sh under pipefail
RC=0
GOUT="$("${ROOT}/eval/tasks/slugify/grade.sh" "${DT}/demo" 2>&1)" || RC=$?
[ "${RC}" -ne 0 ] || { rm -rf "${DT}"; fail "grader passed the untouched demo target: ${GOUT}"; }
echo "${GOUT}" | grep -q ' fail' \
  || { rm -rf "${DT}"; fail "grader exit ${RC} but no CRIT fail line in output: ${GOUT}"; }
# a symlinked path into the repo must not slip past the in-repo refusal
ln -s "${ROOT}" "${DT}/repolink"
RC=0; "${DT}/repolink/demo.sh" "${DT}/repolink/scaffold-target" >/dev/null 2>&1 || RC=$?
if [ "${RC}" -eq 0 ] || [ -e "${ROOT}/scaffold-target" ]; then
  rm -rf "${ROOT}/scaffold-target" "${DT}"
  fail "demo.sh scaffolded through a symlink into the repo (rc=${RC})"
fi
rm -rf "${DT}"
echo "ok  demo.sh scaffold + red grader"
