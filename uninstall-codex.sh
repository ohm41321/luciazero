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
# written inside the block, under the start marker, when the install had to add
# a final newline to the user's content to make room for that marker
ADDED_NL_MARK='<!-- luciazero:added-final-newline -->'
MANAGED_DIR="${CODEX_DIR}/.luciazero-managed"

catalog() { sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "$1"; }
skill_inventory() {
  catalog "${SRC}/skills/catalog.txt"
  catalog "${SRC}/skills/aliases.txt"
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

# A symlink anywhere between the config dir and a path we are about to delete
# can redirect that delete outside the config dir, so every directory on the
# way down has to be a real one. The config dir itself may be a symlink: where
# it lives is the user's own choice.
parents_safe() {
  PS_ROOT="${CODEX_DIR%/}"
  PS_DIR="$(dirname "$1")"
  while [ "${PS_DIR}" != "${PS_ROOT}" ] && [ "${PS_DIR}" != "/" ] && [ "${PS_DIR}" != "." ]; do
    [ ! -L "${PS_DIR}" ] || return 1
    PS_NEXT="$(dirname "${PS_DIR}")"
    [ "${PS_NEXT}" != "${PS_DIR}" ] || break
    PS_DIR="${PS_NEXT}"
  done
  return 0
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

remove_managed_tree() {
  RT_DST="$1"; RT_SNAPSHOT="$2"; RT_SHIPPED="$3"; RT_LABEL="$4"; RT_ALLOW_SHIPPED="${5:-1}"
  # ancestry first, and return: refusing further down would still leave the
  # snapshot cleanup below to delete whatever the symlink points at
  if ! parents_safe "${RT_DST}" || ! parents_safe "${RT_SNAPSHOT}"; then
    echo "  !!  ${RT_LABEL} has a symlinked parent; left untouched" >&2
    return 0
  fi
  if [ ! -e "${RT_DST}" ] && [ ! -L "${RT_DST}" ]; then
    echo "  ok  ${RT_LABEL} (already absent)"
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
AGENTS_TMP=""
trap 'rm -rf "${AGENT_STAGE_ROOT}"; [ -z "${AGENTS_TMP}" ] || rm -f "${AGENTS_TMP}"' EXIT
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

if [ -f "${AGENTS_MD}" ] && grep -qxF "${START}" "${AGENTS_MD}" && ! marker_block_ok "${AGENTS_MD}"; then
  # the skills are gone by now, which is safe on its own; the file is not ours
  # to interpret, so it keeps every byte it has, backup included
  echo "  !!  AGENTS.md carries ambiguous Luciazero markers; left untouched" >&2
  echo "      expected exactly one '${START}' ... '${END}' pair, on their own lines" >&2
elif [ -f "${AGENTS_MD}" ] && grep -qxF "${START}" "${AGENTS_MD}"; then
  BACKUP="$(bakcopy -L "${AGENTS_MD}" "${AGENTS_MD}")"
  # The block goes and nothing else does, which is now the whole round trip
  # rather than a compromise. `install-codex.sh` used to write a blank
  # separator above the start marker, and removing only the block left it
  # behind, so a file the user wrote grew one blank line per cycle. Removing
  # it from here would have meant guessing whose that blank was -- the Claude
  # side may drop its separator only because `install.sh` records that it
  # added it and hashes the file it left, and there is no such record on this
  # side. The install answered it instead: it appends its block without a
  # separator and keeps the blank that spaces the doctrine inside the markers,
  # where deleting the block deletes exactly what the install added. A block
  # the user has since moved carries that blank with it, so a rearranged file
  # comes back byte for byte too. The one byte the install cannot leave alone
  # is a final newline on content that had none, because the start marker needs
  # a line of its own; it records that newline inside the block, and
  # `strip_marker_block` takes it away with the rest.
  # `${AGENTS_MD}.tmp` is a name anyone with write access to the config dir can
  # pre-create as a symlink, and both the rewrite and the rename would then
  # follow it: the awk output lands wherever it points, and the symlink itself
  # is published as AGENTS.md. mktemp picks a name nobody can predict and
  # creates it exclusively; keeping it in the same directory keeps the rename
  # on one filesystem, the way the Claude side already does it.
  AGENTS_TMP="$(mktemp "${CODEX_DIR}/.luciazero-agents-md.XXXXXX")"
  # mktemp makes its file 0600 and the rename publishes that file: copying the
  # backup, which kept the original's mode, carries the mode onto it. The
  # redirection below replaces the content and leaves the mode alone.
  cp -p "${BACKUP}" "${AGENTS_TMP}"
  strip_marker_block "${AGENTS_MD}" > "${AGENTS_TMP}"
  mv "${AGENTS_TMP}" "${AGENTS_MD}"
  AGENTS_TMP=""
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
