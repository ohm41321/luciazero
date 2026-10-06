# tests/gates/syntax.sh — bash -n over every shipped script and gate file.
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
# the hooks, the status line and the installers' shared modules are Node
for S in "${ROOT}"/claude/hooks/*.cjs "${ROOT}"/bin/*.js "${ROOT}"/bin/lib/*.js; do
  node --check "${S}" || fail "${S#"${ROOT}"/} does not parse"
done
echo "ok  Node syntax"
