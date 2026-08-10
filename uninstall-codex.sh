#!/usr/bin/env bash
# Remove the Luciazero doctrine + skills from OpenAI Codex CLI (~/.codex).
set -euo pipefail

for ARG in "$@"; do
  echo "unknown option: ${ARG} (uninstall-codex.sh takes no options)" >&2; exit 1
done

CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"
AGENTS_MD="${CODEX_DIR}/AGENTS.md"
START='<!-- luciazero:start -->'
END='<!-- luciazero:end -->'

# collision-proof backup path for $1 (two runs in the same second must not overwrite)
bakpath() {
  B="$1.bak.$(date +%Y%m%d%H%M%S)"
  N=1
  while [ -e "${B}" ]; do B="$1.bak.$(date +%Y%m%d%H%M%S).${N}"; N=$((N+1)); done
  printf '%s' "${B}"
}

echo "Removing from ${CODEX_DIR}"

rm -f "${CODEX_DIR}/.luciazero-version"
for SKILL in luciazero-bootstrap retro debug 'done' handoff experiment reviewer; do
  rm -rf "${CODEX_DIR}/skills/${SKILL}"
  echo "  ok  skills/${SKILL}"
done

if [ -f "${AGENTS_MD}" ] && grep -qF "${START}" "${AGENTS_MD}"; then
  BACKUP="$(bakpath "${AGENTS_MD}")"
  cp "${AGENTS_MD}" "${BACKUP}"
  awk -v s="${START}" -v e="${END}" '
    $0==s {inblock=1; next}
    $0==e {inblock=0; next}
    !inblock {print}
  ' "${AGENTS_MD}" > "${AGENTS_MD}.tmp"
  mv "${AGENTS_MD}.tmp" "${AGENTS_MD}"
  [ -s "${AGENTS_MD}" ] || rm -f "${AGENTS_MD}"
  echo "  ok  removed doctrine block (backup: $(basename "${BACKUP}"))"
else
  echo "  ok  no doctrine block in AGENTS.md"
fi

if [ -f "${CODEX_DIR}/luciazero-heuristics.md" ]; then
  echo "  kept luciazero-heuristics.md (learned data) — delete manually if unwanted"
fi

echo
echo "Done. Other AGENTS.md content was left untouched."
