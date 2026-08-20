#!/usr/bin/env bash
# Build the exact directory published to npm without changing the checkout.
# npm treats every root README variant as mandatory and currently chooses
# README.th.md before README.md, so the publish stage keeps only README.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$#" -ne 1 ]; then
  echo "usage: scripts/stage-npm-package.sh EMPTY_DIRECTORY" >&2
  exit 64
fi

DEST="$1"
mkdir -p "${DEST}"
DEST="$(cd "${DEST}" && pwd -P)"
if [ "${DEST}" = / ] || [ "${DEST}" = "${ROOT}" ]; then
  echo "refusing unsafe npm staging directory: ${DEST}" >&2
  exit 64
fi
if [ -n "$(find "${DEST}" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
  echo "npm staging directory must be empty: ${DEST}" >&2
  exit 64
fi

PACK_JSON="$(npm pack "${ROOT}" --json --pack-destination "${DEST}")"
ARCHIVE="$(printf '%s' "${PACK_JSON}" | node -e '
let input = "";
process.stdin.on("data", chunk => input += chunk);
process.stdin.on("end", () => {
  const rows = JSON.parse(input);
  if (!Array.isArray(rows) || rows.length !== 1 || !rows[0].filename) process.exit(1);
  process.stdout.write(rows[0].filename);
});
')"
case "${ARCHIVE}" in
  ""|*/*|.*) echo "npm pack returned an unsafe archive name" >&2; exit 1 ;;
esac

tar -xzf "${DEST}/${ARCHIVE}" -C "${DEST}"
rm "${DEST}/${ARCHIVE}"
[ -f "${DEST}/package/README.md" ] || { echo "staged package lost README.md" >&2; exit 1; }
[ -f "${DEST}/package/README.th.md" ] || { echo "source package lost README.th.md" >&2; exit 1; }
rm "${DEST}/package/README.th.md"

printf '%s\n' "${DEST}/package"
