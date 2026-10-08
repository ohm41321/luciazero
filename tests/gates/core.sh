# tests/gates/core.sh — bash 3.2 parse, ShellCheck over every shipped script and gate file, ambient-env sanitation, detect.sh, example settings.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# 1b. The shell scripts run under whatever /bin/bash the user has -- bash 3.2
# on stock macOS, whose parser fails some constructs a modern `bash -n`
# accepts (a here-document inside a command substitution with a quoted
# expansion and a trailing redirection fails the WHOLE file at load time).
# When a real bash 3.2 is available (LZ_BASH32=/path/to/bash-3.2), parse every
# script with it. The hooks themselves are Node programs now.
if [ -n "${LZ_BASH32:-}" ] && [ -x "${LZ_BASH32}" ]; then
  for S in "${SCRIPTS[@]}"; do
    "${LZ_BASH32}" -n "${ROOT}/${S}" || fail "${S} does not parse under ${LZ_BASH32}"
  done
  echo "ok  bash 3.2 parse (${LZ_BASH32})"
else
  echo "skip bash 3.2 parse (set LZ_BASH32 to parse every script with a real bash 3.2)"
fi

# 2. shellcheck: required where it must run (CI, or LZ_REQUIRE_LINT=1), because
# a silent skip lets a local green disagree with the CI that gates the release.
if command -v shellcheck >/dev/null 2>&1; then
  (cd "${ROOT}" && shellcheck "${SCRIPTS[@]}")
  echo "ok  shellcheck"
elif [ -n "${CI:-}" ] || [ -n "${LZ_REQUIRE_LINT:-}" ]; then
  fail "shellcheck is required here (CI or LZ_REQUIRE_LINT=1) but is not installed"
else
  echo "skip shellcheck (not installed — local only; CI fails without it)"
fi

# 2b. Never pipe into `grep -q`. grep exits at the first match; under
# pipefail the writer's next write then meets a closed pipe and the match
# reads as a failure (CI, `printf: write error: Broken pipe`), or, in an `if`,
# a hit reads as none. How many lines follow the match decides it, not the
# output's size, so no site is safe by being short. Capture the output, then
# match from a here-string: `grep -q PATTERN <<<"${OUT}"`. Any stage counts,
# `|&` too; so do egrep and fgrep, a `command` or `env` prefix (with flags,
# and `env -u NAME`) and a VAR=value prefix. -q in an option group of letters
# and digits, --quiet or --silent counts anywhere before the stage ends at a
# `|`, `;`, `&` or `)` outside quotes. A command continued with `\` or a
# trailing `|` is read as one line. Comment lines may name the bad form.
PIPED_GREP="$(cd "${ROOT}" && awk '
  FNR == 1 { line = "" }
  {
    text = $0
    if (line == "") {
      if (text ~ /^[[:space:]]*#/) next
      start = FNR
    }
    more = text ~ /\\$/ || (text ~ /[|][[:space:]]*$/ && text !~ /[|][|][[:space:]]*$/)
    sub(/\\$/, "", text)
    line = line text " "
    if (more) next
    gsub(/[|][|]/, ";", line)
    if (line ~ /[|]&?[[:space:]]*((command|env)([[:space:]]+(-u[[:space:]]+[^[:space:]]+|-[^[:space:]]*))*[[:space:]]+|[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*[ef]?grep[[:space:]](([^|;&)\047"]|\047[^\047]*\047|"[^"]*")*[[:space:]])?(-[a-zA-Z0-9]*q[a-zA-Z0-9]*|--quiet|--silent)([[:space:]]|[|;&)]|$)/)
      print FILENAME ":" start ": " line
    line = ""
  }' "${SCRIPTS[@]}")"
[ -z "${PIPED_GREP}" ] \
  || fail "output piped into grep -q; capture it and match from a here-string:
${PIPED_GREP}"
echo "ok  nothing piped into grep -q"

# 2c. tests/node/*.test.js is named file by file twice -- the parity gate
# and the Windows CI job (Node 18 takes no glob) -- so a new test file named
# in neither would run nowhere, and green would say nothing about it. Only
# a `node --test` command counts (continued with `\`, read as one line);
# a comment or a message naming the file runs nothing.
NODE_TESTS="$(cd "${ROOT}" && for T in tests/node/*.test.js; do echo "${T}"; done | sort)"
[ -n "${NODE_TESTS}" ] || fail "no tests/node/*.test.js found"
for LIST in .github/workflows/ci.yml tests/gates/parity.sh; do
  NAMED="$(awk '
    { text = $0; more = text ~ /\\$/; sub(/\\$/, "", text); line = line text " " }
    !more { if (line !~ /^[[:space:]]*#/ && line ~ /node --test /) print line; line = "" }
  ' "${ROOT}/${LIST}" | grep -oE 'tests/node/[A-Za-z0-9_.-]+[.]test[.]js' | sort -u || true)"
  [ "${NAMED}" = "${NODE_TESTS}" ] \
    || fail "${LIST} does not run exactly the node tests in tests/node:
$(diff <(echo "${NODE_TESTS}") <(echo "${NAMED}") || true)"
done
echo "ok  every tests/node suite runs in parity and in the Windows CI job"

# 2a. ambient LUCIAZERO_* must not change this suite's outcome. A tiny child
# sources the same sanitation helper under every poisoned knob; the test
# entrypoint itself has no environment-controlled early exit.
CHILD_RC=0
CHILD_OUT="$(LUCIAZERO_VERIFY_CMD='never-the-fixture-command' \
  LUCIAZERO_VERIFY_REGEX='^zzz-never-matches$' \
  LUCIAZERO_STRICT_VERIFY_CMD='false' \
  LUCIAZERO_DOC_REGEX='.' \
  LUCIAZERO_CHANNEL='plugin' \
  bash -c '
    source "$1"
    LEFTOVER_LZ="$(env | sed -n '\''s/^\(LUCIAZERO_[A-Za-z0-9_]*\)=.*/\1/p'\'')"
    [ -z "${LEFTOVER_LZ}" ] || {
      echo "ambient Luciazero variables survived sanitation: ${LEFTOVER_LZ}" >&2
      exit 1
    }
  ' _ "${ROOT}/scripts/sanitize-luciazero-env.sh" 2>&1)" || CHILD_RC=$?
[ "${CHILD_RC}" = 0 ] \
  || fail "ambient LUCIAZERO_* sanitation failed: ${CHILD_OUT:-child exited ${CHILD_RC}}"
# A historical probe variable must not bypass the real entrypoint. Put a
# failing bash shim at the first syntax check so this assertion stays tiny.
FORGE_BIN="$(mktemp -d)"
# The fixture intentionally writes a literal shell parameter expansion.
# shellcheck disable=SC2016
printf '#!/bin/sh\n[ -z "${LUCIAZERO_VERIFY_CMD+x}" ] || exit 8\nexit 7\n' > "${FORGE_BIN}/bash"
chmod +x "${FORGE_BIN}/bash"
FORGE_RC=0
PATH="${FORGE_BIN}:/usr/bin:/bin" LZ_SANITATION_PROBE=1 \
  LUCIAZERO_VERIFY_CMD='must-be-removed-before-syntax-checks' \
  /bin/bash "${ROOT}/test.sh" --fast >/dev/null 2>&1 || FORGE_RC=$?
rm -rf "${FORGE_BIN}"
[ "${FORGE_RC}" = 7 ] || fail "environment variable bypassed the verification entrypoint (rc=${FORGE_RC})"
echo "ok  ambient LUCIAZERO_* sanitation"

# 2b. detect.sh runs green against this repo and finds the CI verify command
OUT="$("${ROOT}/skills/ready/scripts/detect.sh" "${ROOT}")" \
  || fail "detect.sh exited non-zero"
grep -q 'test.sh' <<<"${OUT}" || fail "detect.sh did not surface test.sh from CI config"
echo "ok  detect.sh smoke run"

# 2c. detect.sh must also match the '- run:' list form, the most common
# GitHub Actions style (this repo's own CI happens not to use it)
FX="$(mktemp -d)"
mkdir -p "${FX}/.github/workflows"
printf 'jobs:\n  t:\n    steps:\n      - run: npm run canary-cmd\n' > "${FX}/.github/workflows/ci.yml"
# capture, then grep: grep -q on a pipe would SIGPIPE detect.sh under pipefail
OUT="$("${ROOT}/skills/ready/scripts/detect.sh" "${FX}")" \
  || { rm -rf "${FX}"; fail "detect.sh exited non-zero on the fixture"; }
grep -q 'canary-cmd' <<<"${OUT}" \
  || { rm -rf "${FX}"; fail "detect.sh missed the '- run:' CI form"; }
rm -rf "${FX}"
echo "ok  detect.sh '- run:' form"

# 3. example settings must parse as JSON
python3 -m json.tool "${ROOT}/examples/project-settings.example.json" >/dev/null \
  || fail "examples/project-settings.example.json is not valid JSON"
echo "ok  example settings JSON"
