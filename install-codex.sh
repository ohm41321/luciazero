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
# written inside the block, under the start marker, when the install had to add
# a final newline to the user's content to make room for that marker
ADDED_NL_MARK='<!-- luciazero:added-final-newline -->'
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

# Copy $2 to a free backup name beside $3, <base>.bak.<timestamp>[.n], and
# print that name. Two runs in the same second must not overwrite each other,
# and nothing planted at a name -- before it is chosen or after -- may be
# followed, written into or replaced (roadmap R24). So a name is never tested
# and then written. It is taken by one call that fails when anything at all is
# there, a dangling symlink included, and that neither follows nor enters what
# it finds: `mkdir` for a directory, `link` (link(2)) for a file, and for a
# symlink a tool shown, on a scratch directory first, to make the link at
# exactly the name it is given. Plain `ln` puts the link inside a directory it
# finds, and `ln -f` replaces what is inside, so it is never trusted with an
# unchecked name. Everything else is written relative to a directory this
# helper made and then entered, after checking it is still that directory:
# once entered, a swap of the name cannot redirect the writes.
# $1 is `-L` to back up what a symlink points at, as `cp` does, or `-P` to
# back up the symlink itself, as `cp -P` does.
bc_symlink() {
  case "$1" in
    ln) ln -sT -- "$2" "$3" ;;
    perl) perl -e 'symlink($ARGV[0], $ARGV[1]) or exit 1' -- "$2" "$3" ;;
    node) node -e 'try { require("fs").symlinkSync(process.argv[1], process.argv[2]) } catch (e) { process.exit(1) }' -- "$2" "$3" ;;
    *) return 1 ;;
  esac
}

# Enter $1, an absolute physical path to a directory bakcopy made, and succeed
# only when what was entered is still that directory: owned by this user,
# empty, and reached without following a symlink.
bc_enter() {
  cd "$1" 2>/dev/null && [ -O . ] && [ -z "$(ls -A .)" ] && [ "$(pwd -P)" = "$1" ]
}

bakcopy() {
  BC_SRC="$2"; BC_BASE="$3"; BC_Q=""; BC_RC=0
  BC_STAMP="$(date +%Y%m%d%H%M%S)"
  if [ "$1" = -P ] && [ -L "${BC_SRC}" ]; then
    BC_KIND=link
  elif [ -d "${BC_SRC}" ]; then
    BC_KIND=tree
  else
    BC_KIND=file
  fi
  case "${BC_SRC}" in /*) ;; *) BC_SRC="$(pwd)/${BC_SRC}" ;; esac
  BC_DIR="$(CDPATH='' cd -P "$(dirname "${BC_BASE}")" && pwd -P)" \
    || { echo "FAIL: could not back up ${BC_SRC}" >&2; return 1; }
  if [ "${BC_KIND}" = link ]; then
    BC_TO="$(readlink "${BC_SRC}")" \
      || { echo "FAIL: could not back up ${BC_SRC}" >&2; return 1; }
    BC_SL=""
    BC_P="$(mktemp -d)" || { echo "FAIL: could not back up ${BC_SRC}" >&2; return 1; }
    for BC_T in ln perl node; do
      command -v "${BC_T}" >/dev/null 2>&1 || continue
      rm -rf "${BC_P}/t"
      mkdir "${BC_P}/t" "${BC_P}/t/d" && : > "${BC_P}/t/d/c" \
        && ln -s d "${BC_P}/t/s" && ln -s nowhere "${BC_P}/t/g" || break
      if bc_symlink "${BC_T}" x "${BC_P}/t/n" 2>/dev/null \
        && [ "$(readlink "${BC_P}/t/n")" = x ] \
        && ! bc_symlink "${BC_T}" x "${BC_P}/t/d" 2>/dev/null \
        && ! bc_symlink "${BC_T}" x "${BC_P}/t/s" 2>/dev/null \
        && ! bc_symlink "${BC_T}" x "${BC_P}/t/g" 2>/dev/null \
        && [ "$(ls -A "${BC_P}/t/d")" = c ] && [ ! -e "${BC_P}/t/nowhere" ] \
        && [ ! -L "${BC_P}/t/nowhere" ]; then
        BC_SL="${BC_T}"; break
      fi
    done
    rm -rf "${BC_P}"
    if [ -z "${BC_SL}" ]; then
      echo "FAIL: could not back up the symlink ${BC_SRC}, so it was left as it is: no tool here makes a symlink at exactly a given name (needs GNU ln -T, perl or node)" >&2
      return 1
    fi
  elif [ "${BC_KIND}" = file ]; then
    BC_Q="$(mktemp -d "${BC_DIR}/.luciazero-bak.XXXXXX")" \
      || { echo "FAIL: could not back up ${BC_SRC}" >&2; return 1; }
  fi
  (
    if [ "${BC_KIND}" = file ]; then
      bc_enter "${BC_Q}" && cp -p "${BC_SRC}" f || exit 1
    fi
    BC_DST="${BC_BASE}.bak.${BC_STAMP}"; BC_N=0
    while :; do
      BC_AT="${BC_DIR}/${BC_DST##*/}"
      case "${BC_KIND}" in
        tree) mkdir "${BC_AT}" 2>/dev/null && break ;;
        link) bc_symlink "${BC_SL}" "${BC_TO}" "${BC_AT}" 2>/dev/null && break ;;
        file) link f "${BC_AT}" 2>/dev/null && break ;;
      esac
      # Taken is the only reason to try the next name; anything else would
      # loop over a failure that every name shares.
      if { [ ! -e "${BC_AT}" ] && [ ! -L "${BC_AT}" ]; } || [ "${BC_N}" -ge 100 ]; then
        echo "FAIL: could not reserve a backup name for ${BC_SRC} (needs mkdir, or the link utility and hard links)" >&2
        exit 1
      fi
      BC_N=$((BC_N+1)); BC_DST="${BC_BASE}.bak.${BC_STAMP}.${BC_N}"
    done
    case "${BC_KIND}" in
      tree) bc_enter "${BC_AT}" && cp -RP "${BC_SRC}/." . || exit 1 ;;
      file) rm -f f ;;
    esac
    printf '%s' "${BC_DST}"
  ) || BC_RC=1
  if [ -n "${BC_Q}" ]; then
    ( cd "${BC_Q}" 2>/dev/null && [ -O . ] && [ "$(pwd -P)" = "${BC_Q}" ] && rm -f f ) || :
    rmdir "${BC_Q}" 2>/dev/null || :
  fi
  [ "${BC_RC}" = 0 ] || { echo "FAIL: could not back up ${BC_SRC}" >&2; return 1; }
}

same_tree() {
  [ -d "$1" ] && [ ! -L "$1" ] && [ -d "$2" ] && [ ! -L "$2" ] \
    && diff -qr "$1" "$2" >/dev/null 2>&1
}

backup_tree() {
  BT_SRC="$1"; BT_LABEL="$2"
  BT_BASE="${BACKUP_DIR}/${BT_LABEL}"
  mkdir -p "$(dirname "${BT_BASE}")"
  BT_DST="$(bakcopy -P "${BT_SRC}" "${BT_BASE}")"
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

# Does $1 end in a newline? A last line without one is content like any other,
# and `awk` cannot pass it through: print terminates every record it writes, so
# a rewrite that goes through awk hands such a file back one byte longer.
ends_with_newline() {
  [ -s "$1" ] && [ -z "$(tail -c 1 "$1")" ]
}

# Write $1 with its marker block removed and every other byte kept, including a
# last line that carries no newline.
#
# The newline directly above the start marker is removed with the block when
# the block says the installer put it there. The install has to: a start marker
# only counts on a line of its own, so a file whose last line was unterminated
# needs one before the block can be appended. That newline is the installer's,
# not the user's, and nothing in the finished file distinguishes it from a
# newline the user typed -- so the installer records it, on the line under the
# start marker, where the markers are its provenance exactly as they are the
# blank line's. The record is honoured only while the block is still the last
# thing in the file, which is where the install put it; a user who has moved
# the block since has moved that newline into the middle of their own text,
# where it is no longer provably ours and stays.
strip_marker_block() {
  if ends_with_newline "$1"; then SMB_SRC_NL=1; else SMB_SRC_NL=0; fi
  awk -v s="${START}" -v e="${END}" -v mark="${ADDED_NL_MARK}" -v srcnl="${SMB_SRC_NL}" '
    $0==s {inblock=1; head=1; blockend=NR; next}
    $0==e {inblock=0; blockend=NR; next}
    inblock {if (head && $0==mark) added=1; head=0; blockend=NR; next}
    {n++; keep[n]=$0; lastkept=NR}
    END {
      chop = (added && n > 0 && blockend == NR)
      for (i = 1; i <= n; i++) {
        printf "%s", keep[i]
        if (i < n) printf "\n"
      }
      if (n > 0 && !chop && !(lastkept == NR && srcnl == 0)) printf "\n"
    }
  ' "$1"
}

# Exactly one well-formed marker pair, or none at all. Anything else — a start
# with no end, a second pair, a pair nested inside another — has no defined
# meaning, and the awk rewrites below would answer it by dropping whatever
# follows the opening marker. AGENTS.md is the user's file; an ambiguous one is
# left exactly as it is, down to the byte, rather than repaired by guesswork.
# Markers count only on a line of their own, which is what the rewrites match.
marker_block_ok() {
  MB_FILE="$1"
  [ -f "${MB_FILE}" ] || return 0
  MB_S="$(grep -cxF "${START}" "${MB_FILE}" || true)"
  MB_E="$(grep -cxF "${END}" "${MB_FILE}" || true)"
  [ "${MB_S}" = 0 ] && [ "${MB_E}" = 0 ] && return 0
  if [ "${MB_S}" = 1 ] && [ "${MB_E}" = 1 ]; then
    MB_SL="$(grep -nxF "${START}" "${MB_FILE}" | cut -d: -f1)"
    MB_EL="$(grep -nxF "${END}" "${MB_FILE}" | cut -d: -f1)"
    [ "${MB_SL}" -lt "${MB_EL}" ] && return 0
  fi
  return 1
}

if ! marker_block_ok "${AGENTS_MD}"; then
  echo "AGENTS.md carries ambiguous Luciazero markers; nothing was installed" >&2
  echo "  expected exactly one '${START}' ... '${END}' pair, on their own lines" >&2
  echo "  fix ${AGENTS_MD} and run this again" >&2
  exit 1
fi

echo "Installing into ${CODEX_DIR}"
mkdir -p "${CODEX_DIR}/skills"

# 1. doctrine as a marker block in global AGENTS.md (replaced in place on reinstall)
#
# This rewrite and the uninstaller's are exact inverses: it strips the marker
# block and nothing else, and appends the block back with no separator of its
# own. That is the whole of what makes a full cycle return AGENTS.md to its
# original bytes.
#
# It used to write a blank separator above the start marker, and then trim
# trailing blank lines here so that separator would not accumulate one line
# per reinstall. The trim could not tell a blank line this installer had added
# from one the user wrote, so it spent theirs to pay for ours: a file ending in
# no blank line came back from a cycle one line longer, and one ending in
# several came back shorter. The blank line that keeps the doctrine readable
# now lives INSIDE the block, under the start marker, where the markers are its
# provenance and the uninstaller takes it away without having to guess. The
# newline this installer has to add to an unterminated last line is recorded in
# the same place, for the same reason.
TMP="$(mktemp)"
if [ -f "${AGENTS_MD}" ]; then
  bakcopy -L "${AGENTS_MD}" "${AGENTS_MD}" >/dev/null
  strip_marker_block "${AGENTS_MD}" > "${TMP}"
fi
# A start marker counts only on a line of its own, so content whose last line
# has no newline needs one before the block can follow it. That newline is the
# only byte of the user's file this installer changes, and it is recorded under
# the start marker so the uninstall takes it back with the block.
if [ -s "${TMP}" ] && ! ends_with_newline "${TMP}"; then ADDED_NL=1; else ADDED_NL=0; fi
{
  if [ -s "${TMP}" ]; then cat "${TMP}"; fi
  if [ "${ADDED_NL}" = 1 ]; then printf '\n'; fi
  echo "${START}"
  if [ "${ADDED_NL}" = 1 ]; then echo "${ADDED_NL_MARK}"; fi
  echo
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
