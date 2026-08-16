#!/usr/bin/env bash
# Remove the Luciazero doctrine + skills from OpenAI Codex CLI (~/.codex).
set -euo pipefail

for ARG in "$@"; do
  echo "unknown option: ${ARG} (uninstall-codex.sh takes no options)" >&2; exit 1
done

CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_MD="${CODEX_DIR}/AGENTS.md"
START='<!-- luciazero:start -->'
END='<!-- luciazero:end -->'
MANAGED_DIR="${CODEX_DIR}/.luciazero-managed"

catalog() { sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "$1"; }
skill_inventory() {
  catalog "${SRC}/skills/catalog.txt"
  catalog "${SRC}/skills/aliases.txt"
}

# collision-proof backup path for $1 (two runs in the same second must not overwrite)
bakpath() {
  B="$1.bak.$(date +%Y%m%d%H%M%S)"
  N=1
  while [ -e "${B}" ]; do B="$1.bak.$(date +%Y%m%d%H%M%S).${N}"; N=$((N+1)); done
  printf '%s' "${B}"
}

same_tree() {
  [ -d "$1" ] && [ ! -L "$1" ] && [ -d "$2" ] && [ ! -L "$2" ] \
    && diff -qr "$1" "$2" >/dev/null 2>&1
}

tree_parents_safe() {
  [ ! -L "$(dirname "$1")" ] && [ ! -L "$(dirname "$2")" ]
}

remove_managed_tree() {
  RT_DST="$1"; RT_SNAPSHOT="$2"; RT_SHIPPED="$3"; RT_LABEL="$4"; RT_ALLOW_SHIPPED="${5:-1}"
  if [ ! -e "${RT_DST}" ] && [ ! -L "${RT_DST}" ]; then
    echo "  ok  ${RT_LABEL} (already absent)"
  elif ! tree_parents_safe "${RT_DST}" "${RT_SNAPSHOT}"; then
    echo "  !!  ${RT_LABEL} has a symlinked parent; left untouched" >&2
  elif same_tree "${RT_DST}" "${RT_SNAPSHOT}" \
    || { [ "${RT_ALLOW_SHIPPED}" = 1 ] && [ ! -e "${RT_SNAPSHOT}" ] && same_tree "${RT_DST}" "${RT_SHIPPED}"; }; then
    rm -rf "${RT_DST}"
    echo "  ok  ${RT_LABEL}"
  else
    echo "  !!  ${RT_LABEL} is not the exact Luciazero-managed copy; left untouched" >&2
  fi
  rm -rf "${RT_SNAPSHOT}"
}

echo "Removing from ${CODEX_DIR}"

rm -f "${CODEX_DIR}/.luciazero-version"
while IFS= read -r SKILL; do
  remove_managed_tree "${CODEX_DIR}/skills/${SKILL}" \
    "${MANAGED_DIR}/skills/${SKILL}" "${SRC}/skills/${SKILL}" "skills/${SKILL}"
done < <(skill_inventory)

# v2.3 migration: also remove an untouched alias left by older installs.
remove_managed_tree "${CODEX_DIR}/skills/luciazero-bootstrap" \
  "${MANAGED_DIR}/skills/luciazero-bootstrap" \
  "${SRC}/migrations/luciazero-bootstrap-v2.2.0" \
  "skills/luciazero-bootstrap (retired alias)" 0

AGENT_STAGE_ROOT="$(mktemp -d)"
trap 'rm -rf "${AGENT_STAGE_ROOT}"' EXIT
while IFS= read -r AGENT_NAME; do
  AGENT_SOURCE="${AGENT_STAGE_ROOT}/${AGENT_NAME}"
  mkdir -p "${AGENT_SOURCE}"
  awk 'NR==1 {front=($0=="---")} front && /^(tools|model): / {next} {print} front && NR>1 && $0=="---" {front=0}' \
    "${SRC}/claude/agents/${AGENT_NAME}.md" > "${AGENT_SOURCE}/SKILL.md"
  remove_managed_tree "${CODEX_DIR}/skills/${AGENT_NAME}" \
    "${MANAGED_DIR}/skills/${AGENT_NAME}" "${AGENT_SOURCE}" "skills/${AGENT_NAME}"
done < <(catalog "${SRC}/claude/agents/catalog.txt")

rmdir "${MANAGED_DIR}/skills" "${MANAGED_DIR}" 2>/dev/null || true

LEGACY_HANDOFF="${CODEX_DIR}/skills/handoff"
if [ -f "${LEGACY_HANDOFF}/SKILL.md" ]; then
  if cmp -s "${SRC}/migrations/handoff-v1.5.0.SKILL.md" "${LEGACY_HANDOFF}/SKILL.md"; then
    rm -rf "${LEGACY_HANDOFF}"
    echo "  ok  legacy skills/handoff"
  else
    echo "  !!  customized legacy skills/handoff left untouched" >&2
  fi
fi

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
if [ -d "${CODEX_DIR}/.luciazero-backups" ]; then
  echo "  kept .luciazero-backups/ (pre-existing or customized components) — review and delete manually when no longer needed"
fi

echo
echo "Done. Other AGENTS.md content was left untouched."
