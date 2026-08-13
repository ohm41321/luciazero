#!/usr/bin/env bash
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
GIT_AUTHOR_DATE='2026-08-13T00:00:00+00:00' \
GIT_COMMITTER_DATE='2026-08-13T00:00:00+00:00' \
  git -C "${WORK}" commit -qm 'fixture: unfinished parser state'
