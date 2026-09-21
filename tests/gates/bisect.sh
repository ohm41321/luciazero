# tests/gates/bisect.sh — safe-bisect worktree isolation and first-bad-commit.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# 4c5d. Safe bisect: identifies the first bad commit while preserving the
# caller branch/worktree and distinguishes a missing verify command
BR="$(mktemp -d)"
git -C "${BR}" init -q
git -C "${BR}" config user.name test
git -C "${BR}" config user.email test@example.invalid
cat > "${BR}/verify.sh" <<'SH'
#!/usr/bin/env bash
[ ! -e .criterion-state ] || exit 9
touch .criterion-state
[ ! -e skip.flag ] || exit 125
grep -qx good value.txt
SH
cat > "${BR}/verify-noskip.sh" <<'SH'
#!/usr/bin/env bash
grep -qx good value.txt
SH
chmod +x "${BR}/verify.sh" "${BR}/verify-noskip.sh"
echo good > "${BR}/value.txt"
git -C "${BR}" add . && git -C "${BR}" commit -qm good
BGOOD="$(git -C "${BR}" rev-parse HEAD)"
echo neutral > "${BR}/note.txt" && git -C "${BR}" add note.txt && git -C "${BR}" commit -qm neutral
echo skip > "${BR}/skip.flag" && git -C "${BR}" add skip.flag && git -C "${BR}" commit -qm untestable
rm -f "${BR}/skip.flag"
echo bad > "${BR}/value.txt" && git -C "${BR}" add -u && git -C "${BR}" commit -qm regression
BFIRST="$(git -C "${BR}" rev-parse HEAD)"
echo later >> "${BR}/note.txt" && git -C "${BR}" commit -qam later
BBAD="$(git -C "${BR}" rev-parse HEAD)"
BHEAD="${BBAD}"
BOUT="$(cd "${BR}" && "${ROOT}/skills/bisect/scripts/safe-bisect.sh" --good "${BGOOD}" --bad "${BBAD}" -- ./verify-noskip.sh)" \
  || { rm -rf "${BR}"; fail "safe bisect exited red"; }
echo "${BOUT}" | grep -q "FIRST_BAD ${BFIRST}" || { rm -rf "${BR}"; fail "safe bisect found wrong commit: ${BOUT}"; }
if ! { [ "$(git -C "${BR}" rev-parse HEAD)" = "${BHEAD}" ] && [ "$(git -C "${BR}" status --porcelain)" = "" ]; }; then
  rm -rf "${BR}"; fail "safe bisect mutated caller worktree"
fi
[ "$(git -C "${BR}" worktree list --porcelain | grep -c '^worktree ')" -eq 1 ] \
  || { rm -rf "${BR}"; fail "safe bisect leaked a temporary worktree"; }
RC=0; BERR="$(cd "${BR}" && "${ROOT}/skills/bisect/scripts/safe-bisect.sh" --good "${BGOOD}" --bad "${BBAD}" -- ./verify.sh 2>&1)" || RC=$?
if ! { [ "${RC}" -eq 2 ] && echo "${BERR}" | grep -q 'could not identify a unique first bad commit'; }; then
  rm -rf "${BR}"; fail "safe bisect did not preserve ambiguous exit-125 semantics (rc=${RC}): ${BERR}"
fi
RC=0; BERR="$(cd "${BR}" && "${ROOT}/skills/bisect/scripts/safe-bisect.sh" --good "${BGOOD}" --bad "${BBAD}" -- ./missing-verify 2>&1)" || RC=$?
if ! { [ "${RC}" -eq 66 ] && echo "${BERR}" | grep -q 'could not be evaluated'; }; then
  rm -rf "${BR}"; fail "safe bisect treated missing command as a bad revision (rc=${RC}): ${BERR}"
fi
rm -rf "${BR}"
echo "ok  safe regression bisect"
