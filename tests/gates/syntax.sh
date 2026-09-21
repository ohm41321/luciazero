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
