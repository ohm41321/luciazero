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
# target fails here instead of making the run vacuous. Every child runs
# under a temp directory of its own, empty again afterwards: the gates
# clean up on the green path and on the red one alike.
TM="$(mktemp -d)"
cp -R "${ROOT}" "${TM}/repo"
rm -rf "${TM}/repo/.git" "${TM}/repo/node_modules"
mkdir -p "${TM}/bin" "${TM}/tmp"
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
no_leftovers() { # no_leftovers <label>: the child's temp directory is empty again
  [ -z "$(ls -A "${TM}/tmp")" ] \
    || { local LEFT; LEFT="$(find "${TM}/tmp" -mindepth 1 -maxdepth 1 | sed 's#.*/##' | tr '\n' ' ')"; rm -rf "${TM}"; fail "$1 left temp directories behind: ${LEFT}"; }
}
expect_red() { # expect_red <label> <failure line the discipline tier must print>
  local RC=0 ERR
  ERR="$(cd "${TM}/repo" && env -u CI -u LZ_REQUIRE_LINT -u LZ_BASH32 -u LZ_TEST_TIMINGS \
    PATH="${TM}/bin:${PATH}" TMPDIR="${TM}/tmp" ./test.sh --discipline 2>&1 >/dev/null)" || RC=$?
  [ "${RC}" = 1 ] || { rm -rf "${TM}"; fail "$1: discipline tier exited ${RC}, want 1"; }
  printf '%s\n' "${ERR}" | grep -qF "$2" \
    || { rm -rf "${TM}"; fail "$1: discipline tier went red for another reason: $(printf '%s\n' "${ERR}" | grep '^FAIL' | head -1)"; }
  no_leftovers "$1"
}
restore() { cp "${ROOT}/$1" "${TM}/repo/$1"; }
# green first: the unmodified copy passes and leaves its temp directory empty
(cd "${TM}/repo" && env -u CI -u LZ_REQUIRE_LINT -u LZ_BASH32 -u LZ_TEST_TIMINGS \
  PATH="${TM}/bin:${PATH}" TMPDIR="${TM}/tmp" ./test.sh --discipline >/dev/null 2>&1) \
  || { rm -rf "${TM}"; fail "the unmodified copy is red in the discipline tier"; }
no_leftovers "a green discipline run"
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
echo "ok  discipline tier goes red on a hook, report or skill-prompt mutation; no temp directory outlives a run"

# (d) scripts/test-timings.sh keeps a sample per run (stdout, stderr with the
# TIMING lines, meta with tier/os/commit/exit/wall), passes the tier's exit
# code through, and its report ranks green samples by median with p95,
# skipping red ones. Proven over a stub test.sh so no tier runs twice.
TS="$(mktemp -d)"
mkdir -p "${TS}/repo/scripts"
cp "${ROOT}/scripts/test-timings.sh" "${TS}/repo/scripts/"
cat > "${TS}/repo/test.sh" <<'STUB'
#!/bin/sh
echo "ok  stub"
[ "${LZ_TEST_TIMINGS:-0}" = 1 ] && echo "TIMING gate=hooks seconds=${STUB_HOOKS:-0}" >&2
[ "$1" = --fast ] && exit "${STUB_RC:-0}"
exit 0
STUB
chmod +x "${TS}/repo/test.sh"
for N in 10 30 20; do
  STUB_HOOKS="${N}" LZ_TEST_TIMINGS_DIR="${TS}/samples" "${TS}/repo/scripts/test-timings.sh" --fast >/dev/null 2>&1 \
    || fail "test-timings.sh exited red on a green stub run"
  sleep 1  # the sample name is a whole-second stamp
done
RC=0; STUB_HOOKS=99 STUB_RC=3 LZ_TEST_TIMINGS_DIR="${TS}/samples" "${TS}/repo/scripts/test-timings.sh" --fast >/dev/null 2>&1 || RC=$?
[ "${RC}" = 3 ] || fail "test-timings.sh returned ${RC} for a tier that exited 3"
[ "$(find "${TS}/samples" -name '*-fast.meta' | wc -l | tr -d ' ')" = 4 ] || fail "test-timings.sh kept $(find "${TS}/samples" -name '*.meta' | wc -l | tr -d ' ') samples, want 4"
LAST="$(find "${TS}/samples" -name '*-fast.meta' | sort | tail -1)"  # stamps sort by time
grep -q '^exit=3$' "${LAST}" || fail "the red run's meta does not record exit=3"
grep -q '^tier=fast$' "${LAST}" || fail "the meta does not record the tier"
grep -qx 'ok  stub' "${LAST%.meta}.out" || fail "the sample kept no stdout"
REPORT="$(LZ_TEST_TIMINGS_DIR="${TS}/samples" "${ROOT}/scripts/test-timings.sh" --report)"
echo "${REPORT}" | grep -qE '^fast +hooks +3 +20 +30 +10 +30$' \
  || fail "test-timings.sh --report ranks wrong (want fast hooks n=3 median=20 p95=30 min=10 max=30): ${REPORT}"
echo "${REPORT}" | grep -q '^skipped 1 red run(s)$' || fail "the report did not skip the red run: ${REPORT}"
LZ_TEST_TIMINGS_DIR="${TS}/none" "${ROOT}/scripts/test-timings.sh" --report | grep -q '^no samples under ' \
  || fail "the report over no samples is not the one-line notice"
rm -rf "${TS}"
echo "ok  test-timings.sh keeps a sample per run and ranks gates by median and p95"

# (e) The full-only gates run at once, each in its own subshell, with agent-bus
# serial; their stdout and stderr are replayed in the original order, so both
# streams are byte-identical to the serial run (LZ_TEST_PARALLEL=0). Proven
# over stub gates that write to both streams and sleep: the parallel run
# finishes well under the sum of the sleeps, a red gate and a gate that dies
# without fail() are both named in one summary line with the run still
# exiting 1, and the buffer directory is gone afterwards either way. Each stub
# also takes a mktmp directory and records its path: every one lands under the
# run's private TMPDIR and none outlives its gate, green or red -- a subshell
# does not run the parent's EXIT trap, so the dispatcher arms one per gate.
TP="$(mktemp -d)"
mkdir -p "${TP}/repo/tests/gates" "${TP}/repo/scripts" "${TP}/tmp"
cp "${ROOT}/test.sh" "${TP}/repo/test.sh"
cp "${ROOT}/scripts/sanitize-luciazero-env.sh" "${TP}/repo/scripts/"
for G in "${DISCIPLINE_GATES[@]}" "${FAST_GATES[@]}"; do
  printf 'echo "gate %s"\n' "$(basename "${G}" .sh)" > "${TP}/repo/${G}"
done
stub() { # stub <gate>: a gate body that writes both streams and takes a mktmp directory
  # shellcheck disable=SC2016
  printf 'echo "gate %s"\necho "err %s" >&2\nmktmp STUB\necho "${STUB}" >> "%s/paths.log"\n' "$1" "$1" "${TP}"
}
for G in tiers agent-bus eval packaging install codex-install; do stub "${G}" > "${TP}/repo/tests/gates/${G}.sh"; done
for G in tiers eval install; do echo 'sleep 2' >> "${TP}/repo/tests/gates/${G}.sh"; done
par_full() { # par_full <label> [env assignments...]: run the stub full tier, keep both streams
  local LABEL="$1"; shift
  rm -f "${TP}/paths.log"
  (cd "${TP}/repo" && env -u LZ_TEST_TIMINGS TMPDIR="${TP}/tmp" "$@" ./test.sh --full \
    >"${TP}/${LABEL}.out" 2>"${TP}/${LABEL}.err")
}
gone_with_gates() { # gone_with_gates <label>: all six stubs took a directory under the private TMPDIR; none is left
  [ "$(wc -l < "${TP}/paths.log" | tr -d ' ')" = 6 ] \
    || fail "$1: $(wc -l < "${TP}/paths.log" | tr -d ' ') stub directories recorded, want 6"
  while IFS= read -r P; do
    case "${P}" in "${TP}/tmp/"*) ;; *) fail "$1: a stub's mktmp directory landed outside the private TMPDIR: ${P}" ;; esac
  done < "${TP}/paths.log"
  [ -z "$(ls -A "${TP}/tmp")" ] || fail "$1 left directories behind: $(ls "${TP}/tmp")"
}
PAR_T0="${SECONDS}"
par_full parallel || fail "stub full tier exited red when run in parallel"
PAR_WALL=$((SECONDS - PAR_T0))
gone_with_gates "a green parallel run"
par_full serial LZ_TEST_PARALLEL=0 || fail "stub full tier exited red with LZ_TEST_PARALLEL=0"
gone_with_gates "a green serial run"
cmp -s "${TP}/parallel.out" "${TP}/serial.out" || fail "parallel gates changed stdout: $(diff "${TP}/serial.out" "${TP}/parallel.out" | head -3)"
cmp -s "${TP}/parallel.err" "${TP}/serial.err" || fail "parallel gates changed stderr: $(diff "${TP}/serial.err" "${TP}/parallel.err" | head -3)"
OUT="$(sed -n 's/^gate //p' "${TP}/parallel.out" | tr '\n' ' ' | sed 's/ $//')"
[ "${OUT}" = "syntax agentd core contracts hooks relay bisect evidence astra-luna tiers agent-bus eval packaging install codex-install" ] \
  || fail "parallel full tier replayed stdout out of order: ${OUT}"
OUT="$(sed -n 's/^err //p' "${TP}/parallel.err" | tr '\n' ' ' | sed 's/ $//')"
[ "${OUT}" = "tiers agent-bus eval packaging install codex-install" ] \
  || fail "parallel full tier replayed stderr out of order: ${OUT}"
[ "${PAR_WALL}" -lt 6 ] \
  || fail "three stub gates sleeping 2 s each took ${PAR_WALL} s in parallel, want under the 6 s they add up to"
# timing lines: one per gate, still in order, still named right
par_full timed LZ_TEST_TIMINGS=1 || fail "stub full tier exited red with LZ_TEST_TIMINGS=1"
OUT="$(sed -n 's/^TIMING gate=\([a-z-]*\) seconds=[0-9]*$/\1/p' "${TP}/timed.err" | tr '\n' ' ' | sed 's/ $//')"
[ "${OUT}" = "syntax agentd core contracts hooks relay bisect evidence astra-luna tiers agent-bus eval packaging install codex-install" ] \
  || fail "parallel full tier printed the wrong timing lines: ${OUT}"
grep -qE '^TIMING gate=eval seconds=[2-9]$' "${TP}/timed.err" \
  || fail "the eval stub slept 2 s but its timing line disagrees: $(grep 'gate=eval' "${TP}/timed.err")"
# red: eval fails through fail(), install dies on a bare failing command
{ stub eval; echo 'fail "eval stub is red"'; } > "${TP}/repo/tests/gates/eval.sh"
{ stub install; printf 'false\necho "install stub ran past a failing command" >&2\n'; } > "${TP}/repo/tests/gates/install.sh"
RC=0; par_full red || RC=$?
[ "${RC}" = 1 ] || fail "parallel full tier with two red gates exited ${RC}, want 1"
grep -q '^FAIL: eval stub is red$' "${TP}/red.err" || fail "the red gate's own FAIL line was not replayed"
grep -q '^FAIL: red gates: eval install$' "${TP}/red.err" \
  || fail "the summary does not name every red gate: $(grep '^FAIL' "${TP}/red.err" | tr '\n' '|')"
grep -q 'ran past a failing command' "${TP}/red.err" && fail "set -e did not stop a gate inside its subshell"
grep -q '^gate codex-install$' "${TP}/red.out" || fail "a green gate's output was dropped because another gate was red"
grep -q '^PASS' "${TP}/red.out" && fail "a red parallel run still printed PASS"
gone_with_gates "a red parallel run"
rm -rf "${TP}"
echo "ok  full-only gates run in parallel with serial-identical output; red gates are all named; no gate's temp directory outlives it"
