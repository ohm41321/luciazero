# tests/gates/core.sh — shell syntax, bash 3.2 parse, ShellCheck, the agentd suite, ambient-env sanitation, detect.sh, example settings.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# 1. shell syntax
for S in "${SCRIPTS[@]}"; do bash -n "${ROOT}/${S}"; done
echo "ok  shell syntax"

PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  "${ROOT}/scripts/agent_bus_spike.py" || fail "agent bus M0 Python syntax"
echo "ok  agent bus M0 Python syntax"
agent_bus_store

# 1b. The hooks run under whatever /bin/bash the user has — bash 3.2 on stock
# macOS. Verified against a real 3.2: a here-document inside a command
# substitution whose command also carries a quoted expansion and a trailing
# redirection breaks its parser, and it fails the WHOLE file at load time with
# an error pointing at some unrelated later line. A modern `bash -n` accepts
# it, so the hooks simply must not contain the construct at all.
for S in claude/hooks/luciazero-verify.sh claude/hooks/luciazero-statusline.sh; do
  if grep -qE '\$\([^)]*<<' "${ROOT}/${S}"; then
    fail "${S} has a here-document inside \$( ) — bash 3.2 fails to parse the file"
  fi
done
# and when a real bash 3.2 is available (LZ_BASH32=/path/to/bash-3.2), parse
# every script with it instead of trusting the textual rule
if [ -n "${LZ_BASH32:-}" ] && [ -x "${LZ_BASH32}" ]; then
  for S in "${SCRIPTS[@]}"; do
    "${LZ_BASH32}" -n "${ROOT}/${S}" || fail "${S} does not parse under ${LZ_BASH32}"
  done
  echo "ok  bash 3.2 parse (${LZ_BASH32})"
else
  echo "ok  hooks free of here-documents inside \$( ) (bash 3.2; set LZ_BASH32 to parse for real)"
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
echo "${OUT}" | grep -q 'test.sh' || fail "detect.sh did not surface test.sh from CI config"
echo "ok  detect.sh smoke run"

# 2c. detect.sh must also match the '- run:' list form, the most common
# GitHub Actions style (this repo's own CI happens not to use it)
FX="$(mktemp -d)"
mkdir -p "${FX}/.github/workflows"
printf 'jobs:\n  t:\n    steps:\n      - run: npm run canary-cmd\n' > "${FX}/.github/workflows/ci.yml"
# capture, then grep: grep -q on a pipe would SIGPIPE detect.sh under pipefail
OUT="$("${ROOT}/skills/ready/scripts/detect.sh" "${FX}")" \
  || { rm -rf "${FX}"; fail "detect.sh exited non-zero on the fixture"; }
echo "${OUT}" | grep -q 'canary-cmd' \
  || { rm -rf "${FX}"; fail "detect.sh missed the '- run:' CI form"; }
rm -rf "${FX}"
echo "ok  detect.sh '- run:' form"

# 3. example settings must parse as JSON
python3 -m json.tool "${ROOT}/examples/project-settings.example.json" >/dev/null \
  || fail "examples/project-settings.example.json is not valid JSON"
echo "ok  example settings JSON"
