#!/usr/bin/env bash
# revert-probe.sh — the old name, kept for callers that use it. The helper
# itself is revert-probe.cjs beside this file: Node and git only, so it runs
# the same on Windows, where there is no Bash to run this file, macOS and Linux.
if ! command -v node >/dev/null 2>&1; then
  echo "UNASSESSABLE: revert-probe.sh needs Node.js 18 or newer on PATH to run revert-probe.cjs (https://nodejs.org)"
  exit 2
fi
exec node "$(dirname "$0")/revert-probe.cjs" "$@"
