#!/usr/bin/env bash
# Give the work copy the Git history the bug report is about. Usage:
# setup.sh WORKDIR. Replays history/<step>/ overlays in the order of
# history/log.tsv (step, subject, optional tag) into a scratch repository,
# one commit each with fixed identity and dates so every machine builds the
# same hashes, then checks that the replayed tree equals project/ before
# moving the .git directory into the work copy: project/ must be exactly the
# history's final state, or the fixture would lie about its own past.
# Idempotent: a copy that already has a Git directory is left alone.
set -euo pipefail

TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${1:?usage: setup.sh WORKDIR}"
if git -C "${WORK}" rev-parse --git-dir >/dev/null 2>&1; then
  exit 0
fi

BUILD="$(mktemp -d)"
trap 'rm -rf "${BUILD}"' EXIT

git -C "${BUILD}" init -q -b main
git -C "${BUILD}" config user.name "Luciazero Eval"
git -C "${BUILD}" config user.email "eval@example.invalid"
git -C "${BUILD}" config core.autocrlf false
git -C "${BUILD}" config core.filemode true
git -C "${BUILD}" config commit.gpgSign false
git -C "${BUILD}" config core.hooksPath /dev/null

N=0
while IFS=$'\t' read -r STEP SUBJECT TAG; do
  [ -n "${STEP}" ] || continue
  N=$((N + 1))
  cp -R "${TASK_DIR}/history/${STEP}/." "${BUILD}/"
  git -C "${BUILD}" add -A
  STAMP="$(printf '2026-08-%02dT09:00:00+00:00' "${N}")"
  GIT_AUTHOR_DATE="${STAMP}" GIT_COMMITTER_DATE="${STAMP}" \
    git -C "${BUILD}" commit -qm "${SUBJECT}"
  [ -z "${TAG}" ] || git -C "${BUILD}" tag "${TAG}"
done < "${TASK_DIR}/history/log.tsv"

if ! diff -r -x .git -x __pycache__ "${BUILD}" "${WORK}" >/dev/null; then
  echo "setup.sh: project/ is not the final state of history/ (run the replay and compare)" >&2
  exit 1
fi
mv "${BUILD}/.git" "${WORK}/.git"
