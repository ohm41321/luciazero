#!/usr/bin/env bash
# Install the Luciazero doctrine + skills into OpenAI Codex CLI (~/.codex).
# Idempotent. Backs up AGENTS.md before editing. Writes nothing outside CODEX_HOME.
#
# Mapping (single source of truth stays in claude/):
#   claude/luciazero.md        -> marker block in ~/.codex/AGENTS.md
#   skills/<each>/                -> ~/.codex/skills/<each>/
#     (luciazero-bootstrap, retro, debug, done, handoff, experiment)
#   claude/agents/reviewer.md            -> ~/.codex/skills/reviewer/SKILL.md
#                                           (Codex has no subagents; ships as a skill,
#                                            Claude-only `tools:`/`model:` lines dropped)
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

# collision-proof backup path for $1 (two runs in the same second must not overwrite)
bakpath() {
  B="$1.bak.$(date +%Y%m%d%H%M%S)"
  N=1
  while [ -e "${B}" ]; do B="$1.bak.$(date +%Y%m%d%H%M%S).${N}"; N=$((N+1)); done
  printf '%s' "${B}"
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
for SKILL in luciazero-bootstrap retro debug 'done' handoff experiment; do
  rm -rf "${CODEX_DIR}/skills/${SKILL}"
  cp -r "${SRC}/skills/${SKILL}" "${CODEX_DIR}/skills/${SKILL}"
  echo "  ok  skills/${SKILL}"
done

# 3. reviewer agent as a Codex skill, minus the Claude-only tools:/model: lines
rm -rf "${CODEX_DIR}/skills/reviewer"
mkdir -p "${CODEX_DIR}/skills/reviewer"
awk 'NR==1 {front=($0=="---")} front && /^(tools|model): / {next} {print} front && NR>1 && $0=="---" {front=0}' \
  "${SRC}/claude/agents/reviewer.md" > "${CODEX_DIR}/skills/reviewer/SKILL.md"
echo "  ok  skills/reviewer"

# 4. version sidecar (informational; removed by uninstall-codex.sh)
V_NEW="$(grep -m1 -oE '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' "${SRC}/CHANGELOG.md" 2>/dev/null | tr -d '#[] ' || true)"
if [ -n "${V_NEW}" ]; then
  printf '%s\n' "${V_NEW}" > "${CODEX_DIR}/.luciazero-version"
fi

echo
echo "Done. Verify:"
echo "  grep -c 'luciazero:start' ${AGENTS_MD}   # expect 1"
echo "  ls ${CODEX_DIR}/skills/"
echo
echo "The doctrine applies from the next Codex session."
