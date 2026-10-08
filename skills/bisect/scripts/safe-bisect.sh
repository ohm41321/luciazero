#!/usr/bin/env bash
# safe-bisect.sh — the old name, kept for callers that use it. The helper
# itself is safe-bisect.cjs beside this file: Node and git only, so it runs
# the same on Windows, where there is no Bash to run this file, macOS and Linux.
if ! command -v node >/dev/null 2>&1; then
  echo "safe-bisect.sh needs Node.js 18 or newer on PATH to run safe-bisect.cjs (https://nodejs.org)" >&2
  exit 127
fi
exec node "$(dirname "$0")/safe-bisect.cjs" "$@"
