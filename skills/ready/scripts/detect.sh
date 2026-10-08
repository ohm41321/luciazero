#!/usr/bin/env bash
# detect.sh — the old name, kept for callers that use it. The helper
# itself is detect.cjs beside this file: Node and git only, so it runs
# the same on Windows, where there is no Bash to run this file, macOS and Linux.
if ! command -v node >/dev/null 2>&1; then
  echo "detect.sh needs Node.js 18 or newer on PATH to run detect.cjs (https://nodejs.org)" >&2
  exit 127
fi
exec node "$(dirname "$0")/detect.cjs" "$@"
