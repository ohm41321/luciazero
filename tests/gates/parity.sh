# tests/gates/parity.sh — the Node installers (bin/lib/installer.js, what Windows runs) against the Bash ones, scenario by scenario.
#
# Sourced by ./test.sh into its own shell, in the order it lists the gates:
# this file sees the helpers, the sandbox environment and every variable an
# earlier gate set, exactly as when the suite was one file. Not a script;
# the options below restate what ./test.sh already runs under.
# shellcheck shell=bash
set -euo pipefail

# 8. installer parity. Windows has no Bash, so `npx luciazero` runs the same
# steps from bin/lib/installer.js there. Each scenario in
# tests/installer_parity.py is played from identical fixtures through the
# four shell scripts and through the Node module, and every step must agree
# on exit status, stdout and stderr line for line, and the resulting tree:
# kind, bytes, symlink target and permission bits. POSIX hosts only, since
# one side is Bash; the Node side's Windows behaviour is checked by the
# node:test suites in the Windows CI job.
if command -v node >/dev/null 2>&1; then
  python3 "${ROOT}/tests/installer_parity.py" "${ROOT}" || fail "the Node installers differ from the Bash ones (see above)"
  # The node:test suites the Windows CI job runs: the Node installer, the
  # settings wiring, the hooks, the hooks as Codex runs them, the global
  # install and the skills' helpers, each on its own. Run here too, so a
  # change that breaks them is red before it reaches Windows; the
  # Windows-only cases skip here.
  NT_OUT="$(node --test "${ROOT}/tests/node/hooks.test.js" "${ROOT}/tests/node/wiring.test.js" \
    "${ROOT}/tests/node/installer.test.js" "${ROOT}/tests/node/global.test.js" \
    "${ROOT}/tests/node/skill-helpers.test.js" "${ROOT}/tests/node/codex-plugin.test.js" 2>&1)" \
    || { printf '%s\n' "${NT_OUT}"; fail "the node:test suites are red (see above)"; }
  echo "ok  node:test suites for the Windows installer, settings wiring, hooks, Codex plugin hooks, global install and skill helpers"
else
  echo "skip  installer parity and node:test suites (node not installed)"
fi
