# tests/gates/tiers.sh — the dispatcher's own contract: which gates each tier sources, in which order, and that the discipline tier goes red on a hook, report or skill-prompt mutation.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# 7. tiers. (a) Which gates each tier sources, in which order: the real
# test.sh over a directory whose gates only print their own name. This pins
# the output order of every tier and proves the discipline tier never reaches
# the agentd suite, Relay, bisect, evidence, Astra/Luna, eval, packaging or an
# install cycle — not by running them and looking, but by showing they are
# not sourced at all.
TG="$(mktemp -d)"
mkdir -p "${TG}/tests/gates" "${TG}/scripts"
cp "${ROOT}/test.sh" "${TG}/test.sh"
cp "${ROOT}/scripts/sanitize-luciazero-env.sh" "${TG}/scripts/"
for G in "${DISCIPLINE_GATES[@]}" "${FAST_GATES[@]}" "${FULL_GATES[@]}"; do
  printf 'echo "gate %s"\n' "$(basename "${G}" .sh)" > "${TG}/${G}"
done
# The child runs drop LZ_TEST_TIMINGS: an outer timed run must see its own
# gate lines only, never the stubs' (the timing checks below set it per run).
tier_gates() { # tier_gates <tier flag> -> the gate names it sourced, in order
  (cd "${TG}" && env -u LZ_TEST_TIMINGS ./test.sh "$1") | sed -n 's/^gate //p' | tr '\n' ' ' | sed 's/ $//'
}
OUT="$(tier_gates --discipline)" || fail "discipline tier over stub gates exited red"
[ "${OUT}" = "syntax core contracts hooks" ] \
  || fail "discipline tier sources the wrong gates: ${OUT}"
OUT="$(tier_gates --fast)" || fail "fast tier over stub gates exited red"
[ "${OUT}" = "syntax agentd core contracts hooks relay bisect evidence astra-luna" ] \
  || fail "fast tier sources the wrong gates: ${OUT}"
OUT="$(tier_gates --full)" || fail "full tier over stub gates exited red"
[ "${OUT}" = "syntax agentd core contracts hooks relay bisect evidence astra-luna tiers agent-bus eval packaging install codex-install" ] \
  || fail "full tier sources the wrong gates: ${OUT}"
(cd "${TG}" && env -u LZ_TEST_TIMINGS ./test.sh --discipline) | grep -q '^PASS  discipline checks green$' \
  || fail "discipline tier over stub gates printed no PASS line"
# (c) LZ_TEST_TIMINGS: unset or 0, stdout and stderr are exactly as before;
# 1, one `TIMING gate=<name> seconds=<n>` line per sourced gate on stderr, in
# order, with stdout unchanged. The hooks stub sleeps a second for that run
# so the number is seen to measure something.
(cd "${TG}" && env -u LZ_TEST_TIMINGS ./test.sh --discipline >"${TG}/out.unset" 2>"${TG}/err.unset") \
  || fail "discipline tier over stub gates exited red with LZ_TEST_TIMINGS unset"
(cd "${TG}" && LZ_TEST_TIMINGS=0 ./test.sh --discipline >"${TG}/out.0" 2>"${TG}/err.0") \
  || fail "discipline tier over stub gates exited red with LZ_TEST_TIMINGS=0"
printf 'sleep 1\necho "gate hooks"\n' > "${TG}/tests/gates/hooks.sh"
(cd "${TG}" && LZ_TEST_TIMINGS=1 ./test.sh --discipline >"${TG}/out.1" 2>"${TG}/err.1") \
  || fail "discipline tier over stub gates exited red with LZ_TEST_TIMINGS=1"
[ ! -s "${TG}/err.unset" ] || fail "stderr is not empty with LZ_TEST_TIMINGS unset: $(head -1 "${TG}/err.unset")"
[ ! -s "${TG}/err.0" ] || fail "stderr is not empty with LZ_TEST_TIMINGS=0: $(head -1 "${TG}/err.0")"
cmp -s "${TG}/out.unset" "${TG}/out.0" || fail "LZ_TEST_TIMINGS=0 changed stdout"
cmp -s "${TG}/out.unset" "${TG}/out.1" || fail "LZ_TEST_TIMINGS=1 changed stdout"
OUT="$(sed 's/ seconds=[0-9]*$//' "${TG}/err.1" | tr '\n' ' ' | sed 's/ $//')"
[ "${OUT}" = "TIMING gate=syntax TIMING gate=core TIMING gate=contracts TIMING gate=hooks" ] \
  || fail "LZ_TEST_TIMINGS=1 printed the wrong timing lines: $(tr '\n' '|' < "${TG}/err.1")"
grep -qE '^TIMING gate=hooks seconds=[1-9][0-9]*$' "${TG}/err.1" \
  || fail "the hooks stub slept a second but its timing line disagrees: $(grep hooks "${TG}/err.1")"
rm -rf "${TG}"
echo "ok  tiers source their gates in order (discipline stops at hooks); LZ_TEST_TIMINGS is opt-in"

# (b) The discipline tier bites: a copy of this checkout with one mutation in
# the hook, the discipline report or a skill prompt must exit 1 from the
# discipline tier with the failure that names it. A `shellcheck` shim keeps
# the three runs to the checks under test; lint has its own coverage above.
# Each mutation is applied by exact count, so a rewrite that misses its
# target fails here instead of making the run vacuous.
TM="$(mktemp -d)"
cp -R "${ROOT}" "${TM}/repo"
rm -rf "${TM}/repo/.git" "${TM}/repo/node_modules"
mkdir -p "${TM}/bin"
printf '#!/bin/sh\nexit 0\n' > "${TM}/bin/shellcheck"
chmod +x "${TM}/bin/shellcheck"
mutate() { # mutate <repo-relative file> <old> <new>  (exactly one occurrence)
  python3 - "${TM}/repo/$1" "$2" "$3" <<'PY'
import pathlib, sys
path, old, new = sys.argv[1:]
p = pathlib.Path(path); s = p.read_text()
assert s.count(old) == 1, f"{path}: expected exactly one match for {old!r}, found {s.count(old)}"
p.write_text(s.replace(old, new))
PY
}
expect_red() { # expect_red <label> <failure line the discipline tier must print>
  local RC=0 ERR
  ERR="$(cd "${TM}/repo" && env -u CI -u LZ_REQUIRE_LINT -u LZ_BASH32 -u LZ_TEST_TIMINGS \
    PATH="${TM}/bin:${PATH}" ./test.sh --discipline 2>&1 >/dev/null)" || RC=$?
  [ "${RC}" = 1 ] || { rm -rf "${TM}"; fail "$1: discipline tier exited ${RC}, want 1"; }
  printf '%s\n' "${ERR}" | grep -qF "$2" \
    || { rm -rf "${TM}"; fail "$1: discipline tier went red for another reason: $(printf '%s\n' "${ERR}" | grep '^FAIL' | head -1)"; }
}
restore() { cp "${ROOT}/$1" "${TM}/repo/$1"; }
# hook: a prompt inside an open turn must not reset the turn (4c5). The
# literal is the hook's own line, expansions and all.
# shellcheck disable=SC2016
mutate claude/hooks/luciazero-verify.sh \
  '    [ -f "${TELEMETRY}/turn_open" ] && exit 0
' ''
expect_red "hook mutation" "FAIL: a prompt inside an open turn reset turn_start_ms"
restore claude/hooks/luciazero-verify.sh
# report: the schema-3 aggregate must be summed, not dropped (4c5b)
mutate bin/discipline-report.js \
  'telemetry.redundant_green_count += row.telemetry.redundant_green_count;' \
  'telemetry.redundant_green_count += 0;'
expect_red "report mutation" "FAIL: discipline JSON report content wrong"
restore bin/discipline-report.js
# skill prompt: a behavioral clause /done is checked for must stay (4)
mutate skills/done/SKILL.md 'never two' 'never three'
expect_red "skill prompt mutation" "FAIL: remaining skill prompt budget or contract drift"
restore skills/done/SKILL.md
rm -rf "${TM}"
echo "ok  discipline tier goes red on a hook, report or skill-prompt mutation"
