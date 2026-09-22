#!/usr/bin/env bash
# Make the work copy a Git repository with the fixture as its one commit, so
# an agent's "is this even a repo?" check has an answer. Idempotent: a copy
# that already has a Git directory is left alone.
set -euo pipefail

WORK="${1:?usage: setup.sh WORKDIR}"
if git -C "${WORK}" rev-parse --git-dir >/dev/null 2>&1; then
  exit 0
fi

git -C "${WORK}" init -q -b main
git -C "${WORK}" config user.name "Luciazero Eval"
git -C "${WORK}" config user.email "eval@example.invalid"
git -C "${WORK}" config core.autocrlf false
git -C "${WORK}" config core.filemode true
git -C "${WORK}" config commit.gpgSign false
git -C "${WORK}" config core.hooksPath /dev/null
git -C "${WORK}" add .
GIT_AUTHOR_DATE='2026-09-01T00:00:00+00:00' \
GIT_COMMITTER_DATE='2026-09-01T00:00:00+00:00' \
  git -C "${WORK}" commit -qm 'fixture: update checker'
