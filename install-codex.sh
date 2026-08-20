#!/usr/bin/env bash
# Install the Luciazero doctrine + skills into OpenAI Codex CLI (~/.codex).
# Idempotent. Backs up AGENTS.md before editing. Writes nothing outside CODEX_HOME.
#
# Mapping (single source of truth stays in claude/):
#   claude/luciazero.md        -> marker block in ~/.codex/AGENTS.md
#   skills/catalog.txt + aliases.txt     -> ~/.codex/skills/<each>/
#   claude/agents/catalog.txt entries     -> ~/.codex/skills/<agent>/SKILL.md
#                                           (Claude-only `tools:`/`model:` lines dropped)
#   claude/hooks/ (enforcement pack)     -> NOT installed: Codex has no hooks/statusline
set -euo pipefail

for ARG in "$@"; do
  echo "unknown option: ${ARG} (install-codex.sh takes no options)" >&2; exit 1
done

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"
AGENTS_MD="${CODEX_DIR}/AGENTS.md"
START='<!-- luciazero:start -->'
END='<!-- luciazero:end -->'
MANAGED_DIR="${CODEX_DIR}/.luciazero-managed"
BACKUP_DIR="${CODEX_DIR}/.luciazero-backups"

catalog() { sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "$1"; }
skill_inventory() {
  catalog "${SRC}/skills/catalog.txt"
  catalog "${SRC}/skills/aliases.txt"
}
version_of() {
  awk -F '"' '/^[[:space:]]*"version"[[:space:]]*:/ { print $4; exit }' \
    "${SRC}/package.json" 2>/dev/null || true
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

backup_tree() {
  BT_SRC="$1"; BT_LABEL="$2"
  BT_BASE="${BACKUP_DIR}/${BT_LABEL}"
  mkdir -p "$(dirname "${BT_BASE}")"
  BT_DST="$(bakpath "${BT_BASE}")"
  cp -RP "${BT_SRC}" "${BT_DST}"
  echo "  ok  backed up existing ${BT_LABEL} -> ${BT_DST#"${CODEX_DIR}/"}"
}

install_tree() {
  IT_SRC="$1"; IT_DST="$2"; IT_SNAPSHOT="$3"; IT_LABEL="$4"
  if [ -e "${IT_DST}" ] || [ -L "${IT_DST}" ]; then
    if ! same_tree "${IT_DST}" "${IT_SNAPSHOT}" && ! same_tree "${IT_DST}" "${IT_SRC}"; then
      backup_tree "${IT_DST}" "${IT_LABEL}"
    fi
    rm -rf "${IT_DST}"
  fi
  mkdir -p "$(dirname "${IT_DST}")" "$(dirname "${IT_SNAPSHOT}")"
  cp -R "${IT_SRC}" "${IT_DST}"
  rm -rf "${IT_SNAPSHOT}"
  cp -R "${IT_SRC}" "${IT_SNAPSHOT}"
}

# Remove a retired Luciazero skill only when its managed snapshot proves
# ownership. A customized or colliding directory is user data and must survive
# the migration with an explicit warning. Symlinked skill parents are refused
# so the deletion cannot escape the configured directory.
remove_legacy_tree() {
  LT_DST="$1"; LT_SNAPSHOT="$2"; LT_LABEL="$3"
  if [ ! -e "${LT_DST}" ] && [ ! -L "${LT_DST}" ]; then
    if [ ! -L "$(dirname "${LT_SNAPSHOT}")" ]; then
      rm -rf "${LT_SNAPSHOT}"
    fi
    return
  fi
  if [ -L "$(dirname "${LT_DST}")" ] || [ -L "$(dirname "${LT_SNAPSHOT}")" ]; then
    echo "  !!  ${LT_LABEL} has a symlinked parent; left untouched" >&2
  elif same_tree "${LT_DST}" "${LT_SNAPSHOT}"; then
    rm -rf "${LT_DST}" "${LT_SNAPSHOT}"
    echo "  ok  migrated ${LT_LABEL}"
  else
    echo "  !!  ${LT_LABEL} is customized or not Luciazero-owned; left untouched" >&2
  fi
}

echo "Installing into ${CODEX_DIR}"
mkdir -p "${CODEX_DIR}/skills"

# 1. doctrine as a marker block in global AGENTS.md (replaced in place on reinstall)
TMP="$(mktemp)"
if [ -f "${AGENTS_MD}" ]; then
  cp "${AGENTS_MD}" "$(bakpath "${AGENTS_MD}")"
  # strip the old block AND trailing blank lines, so reinstalls do not
  # accumulate one separator blank line per run
  awk -v s="${START}" -v e="${END}" '
    $0==s {inblock=1; next}
    $0==e {inblock=0; next}
    inblock {next}
    NF {for (i=0; i<blank; i++) print ""; blank=0; print; next}
    {blank++}
  ' "${AGENTS_MD}" > "${TMP}"
fi
{
  if [ -s "${TMP}" ]; then cat "${TMP}"; echo; fi
  echo "${START}"
  cat "${SRC}/claude/luciazero.md"
  echo "${END}"
} > "${AGENTS_MD}"
rm -f "${TMP}"
echo "  ok  AGENTS.md doctrine block"

# 2. skills — same SKILL.md format as Claude Code, copied as-is
while IFS= read -r SKILL; do
  install_tree "${SRC}/skills/${SKILL}" \
    "${CODEX_DIR}/skills/${SKILL}" \
    "${MANAGED_DIR}/skills/${SKILL}" \
    "skills/${SKILL}"
  echo "  ok  skills/${SKILL}"
done < <(skill_inventory)

# v2.3 migration: remove only the untouched /luciazero-bootstrap compatibility
# alias from older installs. Customized copies remain user data.
remove_legacy_tree "${CODEX_DIR}/skills/luciazero-bootstrap" \
  "${MANAGED_DIR}/skills/luciazero-bootstrap" \
  "skills/luciazero-bootstrap"

LEGACY_HANDOFF="${CODEX_DIR}/skills/handoff"
if [ -f "${LEGACY_HANDOFF}/SKILL.md" ]; then
  if cmp -s "${SRC}/migrations/handoff-v1.5.0.SKILL.md" "${LEGACY_HANDOFF}/SKILL.md"; then
    rm -rf "${LEGACY_HANDOFF}"
    echo "  ok  migrated skill handoff -> lucia-relay"
  else
    echo "  !!  skills/handoff is customized; left untouched (Luciazero now uses /lucia-relay)" >&2
  fi
fi

# 3. Claude agents as Codex skills, minus Claude-only tools:/model: lines
AGENT_STAGE_ROOT="$(mktemp -d)"
trap 'rm -rf "${AGENT_STAGE_ROOT}"' EXIT
while IFS= read -r AGENT_NAME; do
  AGENT_SOURCE="${AGENT_STAGE_ROOT}/${AGENT_NAME}"
  mkdir -p "${AGENT_SOURCE}"
  awk 'NR==1 {front=($0=="---")} front && /^(tools|model): / {next} {print} front && NR>1 && $0=="---" {front=0}' \
    "${SRC}/claude/agents/${AGENT_NAME}.md" > "${AGENT_SOURCE}/SKILL.md"
  install_tree "${AGENT_SOURCE}" "${CODEX_DIR}/skills/${AGENT_NAME}" \
    "${MANAGED_DIR}/skills/${AGENT_NAME}" "skills/${AGENT_NAME}"
  echo "  ok  skills/${AGENT_NAME}"
done < <(catalog "${SRC}/claude/agents/catalog.txt")

# 4. version sidecar (informational; removed by uninstall-codex.sh)
V_NEW="$(version_of)"
if [ -n "${V_NEW}" ]; then
  printf '%s\n' "${V_NEW}" > "${CODEX_DIR}/.luciazero-version"
fi

echo
echo "Done. Verify:"
echo "  grep -c 'luciazero:start' ${AGENTS_MD}   # expect 1"
echo "  ls ${CODEX_DIR}/skills/"
echo
echo "The doctrine applies from the next Codex session."
