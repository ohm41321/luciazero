#!/usr/bin/env bash
# Two-minute demo: scaffold the planted-bug slugify project into a scratch
# directory, then YOU fix it in your own Claude Code session and grade the
# result objectively. This script never runs claude itself and writes nothing
# inside this repo.
#
# Usage: ./demo.sh [target-dir]   (default: a fresh temp directory)
set -euo pipefail

# -P: compare PHYSICAL paths — a symlink into the repo must not slip past
# the in-repo refusal below
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
TASK="${ROOT}/eval/tasks/slugify"

say() { printf '%s\n' "$*"; }
hr()  { printf '\n== %s ==\n' "$*"; }

TARGET="${1:-$(mktemp -d)}"
mkdir -p "${TARGET}"
TARGET="$(cd "${TARGET}" && pwd -P)"
case "${TARGET}/" in
  "${ROOT}/"*)
    rmdir -p "${TARGET}" 2>/dev/null || true   # drop empty dirs the mkdir above just made
    say "demo.sh: refusing to scaffold inside this repo — pick a directory elsewhere" >&2
    exit 1 ;;
esac

cp -R "${TASK}/project/." "${TARGET}/"

if command -v git >/dev/null 2>&1; then
  (cd "${TARGET}" \
     && git init -q \
     && git add -A \
     && git -c user.email=demo@example.invalid -c user.name='Luciazero Demo' \
          commit -qm 'planted bug: slugify strips non-ASCII') \
    || say "note: git setup failed — continuing without a repo (the demo still works)"
else
  say "note: git not found — continuing without a repo (the demo still works)"
fi

say "Scaffolded the planted-bug project into:"
say "  ${TARGET}"

hr "1. the bug report — this is your prompt"
sed 's/^/  /' "${TASK}/PROMPT.md"

hr "2. run it in YOUR Claude Code session"
say "  cd ${TARGET} && claude"
say "  ...then paste the bug report above as the prompt."

hr "3. afterwards: the objective verdict"
say "  ${TASK}/grade.sh ${TARGET}"
say ""
say "  Its later criteria (regression test red on the reverted fix, no weakened checks,"
say "  original contract enforced) are the doctrine's fingerprint: a bare agent often fixes the bug yet fails them."

hr "honest note"
say "  The run uses your own API credits, and a strong model may pass everything"
say "  without the doctrine. The interesting comparison is running it once before"
say "  and once after ./install.sh."
