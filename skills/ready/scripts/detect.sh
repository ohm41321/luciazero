#!/usr/bin/env bash
# Read-only evidence scan for ready Phase 1.
# Prints what exists in a repo — docs, manifests, script/target names, CI run
# lines, test dirs, workspace markers. It surfaces candidates only; it never
# picks the verify command. Judgment stays with the agent.
#
# Usage: detect.sh [repo-root]   (default: current directory)
# Exits 0 unless the target directory does not exist; absence of a section
# means nothing was found.
set -euo pipefail

cd "${1:-.}" 2>/dev/null || { printf 'detect.sh: no such directory: %s\n' "${1:-.}" >&2; exit 1; }

say() { printf '%s\n' "$*"; }
hr()  { printf '\n== %s ==\n' "$*"; }

hr "repo: $(pwd)"
if git rev-parse --git-dir >/dev/null 2>&1; then
  say "git repo: yes (toplevel: $(git rev-parse --show-toplevel))"
  if [ -z "$(git ls-files . | head -1)" ]; then
    say "  WARNING: no tracked files under this dir — it may just sit inside an unrelated repo; revert/stash will not protect it"
  fi
else
  say "git repo: NO — no safe revert, stash, or bisect until 'git init' (ask first)"
fi

hr "docs"
for F in README README.md README.rst CONTRIBUTING.md AGENTS.md CLAUDE.md docs; do
  if [ -e "$F" ]; then say "exists: $F"; fi
done

hr "manifests"
for F in package.json pyproject.toml setup.py tox.ini noxfile.py Makefile \
         justfile Justfile Cargo.toml go.mod build.gradle build.gradle.kts \
         pom.xml composer.json Gemfile mix.exs CMakeLists.txt Package.swift; do
  if [ -f "$F" ]; then say "exists: $F"; fi
done

if [ -f package.json ]; then
  hr "package.json scripts"
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json,sys
d = json.load(open("package.json"))
for k, v in d.get("scripts", {}).items():
    print(f"  {k}: {v}")' 2>/dev/null || say "  (unparseable package.json)"
  else
    sed -n '/"scripts"[[:space:]]*:/,/}/p' package.json
  fi
fi

if [ -f Makefile ]; then
  hr "Makefile targets"
  grep -E '^[A-Za-z0-9_.-]+:' Makefile | cut -d: -f1 | sed 's/^/  /' | head -30 || true
fi

for J in justfile Justfile; do
  if [ -f "$J" ]; then
    hr "$J recipes"
    grep -E '^[A-Za-z0-9_-]+.*:' "$J" | sed 's/^/  /' | head -30 || true
  fi
done

hr "ci — whatever CI runs is the honest verify command; read these files yourself"
for C in .github/workflows/*.yml .github/workflows/*.yaml .gitlab-ci.yml .circleci/config.yml; do
  if [ -f "$C" ]; then
    say "file: $C"
    grep -nE '^[[:space:]]*(-[[:space:]]+)?(run|script)[[:space:]]*:' "$C" | sed 's/^/  /' | head -30 || true
  fi
done

hr "test dirs / files (top two levels)"
find . -maxdepth 2 \( -name .git -o -name node_modules -o -name .venv -o -name vendor \) -prune -o \
  \( -type d \( -name tests -o -name test -o -name spec -o -name __tests__ \) -print \) 2>/dev/null | sed 's/^/  /' | head -10 || true
find . -maxdepth 2 \( -name .git -o -name node_modules -o -name .venv -o -name vendor \) -prune -o \
  \( -type f \( -name '*_test.*' -o -name 'test_*.*' -o -name '*.test.*' -o -name '*.spec.*' \) -print \) 2>/dev/null | sed 's/^/  /' | head -10 || true

hr "workspace / monorepo markers"
for F in pnpm-workspace.yaml turbo.json nx.json lerna.json go.work; do
  if [ -f "$F" ]; then say "exists: $F"; fi
done
if [ -f package.json ] && grep -q '"workspaces"' package.json; then say "package.json declares workspaces"; fi
if [ -f Cargo.toml ] && grep -q '^\[workspace\]' Cargo.toml; then say "Cargo.toml declares [workspace]"; fi

exit 0
