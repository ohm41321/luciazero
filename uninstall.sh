#!/usr/bin/env bash
# Remove the Luciazero doctrine + skills from ~/.claude/
set -euo pipefail

for ARG in "$@"; do
  echo "unknown option: ${ARG} (uninstall.sh takes no options)" >&2; exit 1
done

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCTRINE="luciazero.md"
IMPORT_LINE="@${DOCTRINE}"
GLOBAL_MD="${CLAUDE_DIR}/CLAUDE.md"
IMPORT_PROVENANCE="${CLAUDE_DIR}/.luciazero-import"

sha_of() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 < "$1" | cut -d' ' -f1
  elif command -v sha256sum >/dev/null 2>&1; then sha256sum < "$1" | cut -d' ' -f1
  else echo ""; fi
}

# Read only a plain file of our own, proved by the marker install.sh writes as
# its first line. Following a symlink, or trusting any regular file that
# happens to sit at this path, would let somebody else's content decide
# whether a blank line in the user's CLAUDE.md gets deleted.
IMPORT_MARKER="luciazero-managed: import-provenance"
provenance_is_ours() {
  [ -f "${IMPORT_PROVENANCE}" ] && [ ! -L "${IMPORT_PROVENANCE}" ] \
    && [ "$(head -n 1 "${IMPORT_PROVENANCE}" 2>/dev/null)" = "${IMPORT_MARKER}" ]
}
read_provenance() {
  provenance_is_ours || return 0
  sed -n '2p' "${IMPORT_PROVENANCE}" 2>/dev/null || true
}
MANAGED_DIR="${CLAUDE_DIR}/.luciazero-managed"

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
  PS_ROOT="${CLAUDE_DIR%/}"
  PS_DIR="$(dirname "$1")"
  while [ "${PS_DIR}" != "${PS_ROOT}" ] && [ "${PS_DIR}" != "/" ] && [ "${PS_DIR}" != "." ]; do
    [ ! -L "${PS_DIR}" ] || return 1
    PS_NEXT="$(dirname "${PS_DIR}")"
    [ "${PS_NEXT}" != "${PS_DIR}" ] || break
    PS_DIR="${PS_NEXT}"
  done
  return 0
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

remove_managed_file() {
  RF_DST="$1"; RF_SNAPSHOT="$2"; RF_SHIPPED="$3"; RF_LABEL="$4"
  if ! parents_safe "${RF_DST}" || ! parents_safe "${RF_SNAPSHOT}"; then
    echo "  !!  ${RF_LABEL} has a symlinked parent; left untouched" >&2
    return 0
  fi
  if [ ! -e "${RF_DST}" ] && [ ! -L "${RF_DST}" ]; then
    echo "  ok  ${RF_LABEL} (already absent)"
  elif [ -f "${RF_DST}" ] && [ ! -L "${RF_DST}" ] \
    && { { [ -f "${RF_SNAPSHOT}" ] && cmp -s "${RF_DST}" "${RF_SNAPSHOT}"; } \
      || { [ ! -e "${RF_SNAPSHOT}" ] && cmp -s "${RF_DST}" "${RF_SHIPPED}"; }; }; then
    rm -f "${RF_DST}"
    echo "  ok  ${RF_LABEL}"
  else
    echo "  !!  ${RF_LABEL} is not the exact Luciazero-managed copy; left untouched" >&2
  fi
  rm -f "${RF_SNAPSHOT}"
}

echo "Removing from ${CLAUDE_DIR}"

remove_managed_file "${CLAUDE_DIR}/${DOCTRINE}" \
  "${MANAGED_DIR}/${DOCTRINE}" "${SRC}/claude/${DOCTRINE}" "${DOCTRINE}"
rm -f "${CLAUDE_DIR}/.luciazero-version"

while IFS= read -r SKILL; do
  remove_managed_tree "${CLAUDE_DIR}/skills/${SKILL}" \
    "${MANAGED_DIR}/skills/${SKILL}" "${SRC}/skills/${SKILL}" "skills/${SKILL}"
done < <(skill_inventory)

# v2.3 migration: also remove an untouched alias left by older installs.
remove_managed_tree "${CLAUDE_DIR}/skills/luciazero-bootstrap" \
  "${MANAGED_DIR}/skills/luciazero-bootstrap" \
  "${SRC}/migrations/luciazero-bootstrap-v2.2.0" \
  "skills/luciazero-bootstrap (retired alias)" 0

while IFS= read -r AGENT_NAME; do
  remove_managed_file "${CLAUDE_DIR}/agents/${AGENT_NAME}.md" \
    "${MANAGED_DIR}/agents/${AGENT_NAME}.md" \
    "${SRC}/claude/agents/${AGENT_NAME}.md" "agents/${AGENT_NAME}.md"
done < <(catalog "${SRC}/claude/agents/catalog.txt")

rmdir "${MANAGED_DIR}/skills" "${MANAGED_DIR}/agents" "${MANAGED_DIR}" 2>/dev/null || true

# Agent Bus launcher. Only a regular file carrying the ownership marker is
# ours to delete: a symlink is something the user made, and anything without
# the marker is another program that happens to share the name.
AGENTD_MARKER="luciazero-managed: agentd-launcher"
AGENTD_SERVICE_MARKER="luciazero-managed: agentd-service"
AGENTD_BIN_DIR="${LUCIAZERO_BIN_DIR:-${CLAUDE_DIR}/bin}"
AGENTD_LAUNCHER="${AGENTD_BIN_DIR}/luciazero-agentd"
# Both names install.sh writes. The long one is kept in its own variable
# because the service is stopped through it before either is removed.
AGENTD_NAMES="luciazero-agentd lucia"

# The background service outlives this script unless it is stopped first.
# Removing the launcher while a LaunchAgent or a systemd unit still points at
# it leaves either a daemon serving after an uninstall or a service manager
# restarting a file that is gone, so the service is dealt with first and the
# launcher stays put if it could not be.
AGENTD_KEEP=0
AGENTD_SERVICE_ROOT="${LUCIAZERO_SERVICE_ROOT:-$HOME}"
for AGENTD_SVC in "${AGENTD_SERVICE_ROOT}/Library/LaunchAgents/com.luciazero.agentd.plist" \
  "${AGENTD_SERVICE_ROOT}/.config/systemd/user/luciazero-agentd.service"; do
  [ -f "${AGENTD_SVC}" ] || continue
  grep -qF "${AGENTD_SERVICE_MARKER}" "${AGENTD_SVC}" 2>/dev/null || continue
  AGENTD_RUN=""
  if [ -f "${AGENTD_LAUNCHER}" ] && grep -qF "${AGENTD_MARKER}" "${AGENTD_LAUNCHER}" 2>/dev/null; then
    AGENTD_RUN="${AGENTD_LAUNCHER}"
  fi
  if [ -n "${AGENTD_RUN}" ] && "${AGENTD_RUN}" service uninstall >/dev/null 2>&1; then
    echo "  ok  agent bus service stopped and removed"
  elif [ -d "${SRC}/agentd/luciazero_agentd" ] && command -v python3 >/dev/null 2>&1 \
    && PYTHONPATH="${SRC}/agentd" python3 -m luciazero_agentd service uninstall >/dev/null 2>&1; then
    echo "  ok  agent bus service stopped and removed"
  else
    echo "  !!  the Agent Bus service is still installed (${AGENTD_SVC})" >&2
    echo "      stop it first:  luciazero-agentd service uninstall" >&2
    echo "      the launcher is left in place so the service does not restart a missing file" >&2
    AGENTD_KEEP=1
  fi
done

if [ "${AGENTD_KEEP}" = 0 ]; then
  for AGENTD_NAME in ${AGENTD_NAMES}; do
    AGENTD_TARGET="${AGENTD_BIN_DIR}/${AGENTD_NAME}"
    if [ -L "${AGENTD_TARGET}" ]; then
      echo "  !!  ${AGENTD_TARGET} is a symlink you made; left untouched" >&2
    elif [ -f "${AGENTD_TARGET}" ]; then
      if grep -qF "${AGENTD_MARKER}" "${AGENTD_TARGET}" 2>/dev/null; then
        rm -f "${AGENTD_TARGET}"
        echo "  ok  bin/${AGENTD_NAME}"
      else
        echo "  !!  ${AGENTD_TARGET} is not the Luciazero launcher; left untouched" >&2
      fi
    elif [ -e "${AGENTD_TARGET}" ]; then
      echo "  !!  ${AGENTD_TARGET} is not a regular file; left untouched" >&2
    fi
  done
  # Only once both are gone, and only if it is empty.
  rmdir "${AGENTD_BIN_DIR}" 2>/dev/null || true
  rm -f "${CLAUDE_DIR}/.luciazero-agentd-home"
fi

LEGACY_HANDOFF="${CLAUDE_DIR}/skills/handoff"
if [ -f "${LEGACY_HANDOFF}/SKILL.md" ]; then
  if cmp -s "${SRC}/migrations/handoff-v1.5.0.SKILL.md" "${LEGACY_HANDOFF}/SKILL.md"; then
    rm -rf "${LEGACY_HANDOFF}"
    echo "  ok  legacy skills/handoff"
  else
    echo "  !!  customized legacy skills/handoff left untouched" >&2
  fi
fi

# enforcement pack, if it was installed with --with-hooks.
# Order matters: clean settings.json FIRST and delete the hook files only if
# that succeeded — otherwise Claude Code would keep executing references to
# files we just deleted.
SETTINGS="${CLAUDE_DIR}/settings.json"
HOOKS_CLEAN=1
# No `grep` gate. A hook path can be stored quoted (the Bash-era installer
# shell-quoted it), as an exec-form argument, or base64 inside the status
# line's command, so the bare path is not always a substring of what is
# there, and a grep that answered "nothing of ours" would let the hook files
# be deleted under entries still pointing at them. Only the parser knows what
# is ours, so the parser is asked whenever there is a file to ask about --
# bin/lib/settings-wiring.js, the module that wrote them. It reports three
# separate outcomes and never writes a backup it did not need:
#   0  nothing of ours -- settings.json untouched
#   10 ours found and removed -- backup written first (O_EXCL, never through
#      a planted name)
#   *  read, parse or write failed -- settings.json is left exactly as it was
if [ -f "${SETTINGS}" ]; then
  if command -v node >/dev/null 2>&1 \
    && node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 18 ? 0 : 1)' 2>/dev/null; then
    HOOKS_RC=0
    # exact-path matching only: never touch a user's own hook that merely
    # shares a basename with ours
    node "${SRC}/bin/lib/settings-wiring.js" clean "${SETTINGS}" "${CLAUDE_DIR}" || HOOKS_RC=$?
    case "${HOOKS_RC}" in
      0)
        echo "  ok  no enforcement-pack entries in settings.json"
        ;;
      10)
        echo "  ok  removed hook entries from settings.json"
        ;;
      *)
        HOOKS_CLEAN=0
        echo "  !!  could not clean settings.json (invalid JSON?) — hook files kept so nothing dangles; remove the luciazero-* entries manually, then delete ${CLAUDE_DIR}/hooks/luciazero-*" >&2
        ;;
    esac
  else
    HOOKS_CLEAN=0
    echo "  !!  Node 18+ not found — settings.json untouched; hook files kept so nothing dangles" >&2
  fi
else
  echo "  ok  no settings.json to clean"
fi
if [ "${HOOKS_CLEAN}" = 1 ]; then
  for H in luciazero-verify.cjs luciazero-statusline.cjs; do
    F="${CLAUDE_DIR}/hooks/${H}"
    if [ -f "${F}" ]; then
      if cmp -s "${F}" "${SRC}/claude/hooks/${H}" 2>/dev/null; then
        rm -f "${F}"
        echo "  ok  hooks/${H}"
      else
        echo "  !!  hooks/${H} differs from the shipped version (customized or newer?) — left in place" >&2
      fi
    fi
  done
  # The Bash hooks of an install made before the move to Node: removed when
  # they are exactly as some release shipped them, kept when edited.
  for H in luciazero-verify.sh luciazero-statusline.sh; do
    F="${CLAUDE_DIR}/hooks/${H}"
    if [ -f "${F}" ]; then
      SUM="$(sha_of "${F}")"
      if [ -n "${SUM}" ] && grep -qx "${SUM}" "${SRC}/claude/hooks/legacy-hooks.sha256" 2>/dev/null; then
        rm -f "${F}"
        echo "  ok  hooks/${H}"
      else
        echo "  !!  hooks/${H} differs from every shipped version (customized?) — left in place" >&2
      fi
    fi
  done
fi

if [ -f "${GLOBAL_MD}" ] && grep -qF "${IMPORT_LINE}" "${GLOBAL_MD}"; then
  BACKUP="$(bakcopy -L "${GLOBAL_MD}" "${GLOBAL_MD}")"
  # `install.sh` appends the import line to an existing CLAUDE.md as
  # `printf '\n%s\n'` — a blank separator and then the line — so removing only
  # the line leaves the separator behind and every install-and-uninstall cycle
  # grows a file the user wrote. Removing it is only safe where this
  # installer is provably the one that put it there: the same file shape
  # arises when somebody writes the import line themselves, and `install.sh`
  # then leaves the file untouched, which makes the blank theirs. So the
  # separator goes only on the record `install.sh` left behind, and the record
  # carries the hash of the file as the installer left it, so it says something
  # about THIS file and not merely about what the installer usually does. Move
  # the import line, add a blank line, change a word: the hash stops matching
  # and the separator stays. Any other value -- including none, which is every
  # install older than this one, and every install that found a foreign
  # `.luciazero-import` and refused to write -- takes the conservative path of
  # removing the line and nothing else.
  # BACKUP is the snapshot everything below reads: the hash is taken from it
  # and the rewrite is computed from it, so the decision and the transform
  # cannot see two different files. The live file is compared against that
  # snapshot again before the result is published; anything that changed it in
  # between wins, and this leaves it alone. A rename cannot be made atomic
  # against an editor that is mid-write, so this narrows the window rather
  # than closing it.
  PROV="$(read_provenance)"
  MD_TMP="$(mktemp "${CLAUDE_DIR}/.luciazero-claude-md.XXXXXX")"
  # mktemp makes its file 0600 and the rename below publishes that file, so
  # without this a 0640 CLAUDE.md came back 0600. Copying the backup -- which
  # kept the original's mode -- onto the temporary file carries the mode over;
  # the redirection that follows replaces the content and leaves it.
  cp -p "${BACKUP}" "${MD_TMP}"
  if [ "${PROV%% *}" = appended ] && [ -n "${PROV#appended }" ] \
     && [ "${PROV#appended }" = "$(sha_of "${BACKUP}")" ]; then
    awk -v want="${IMPORT_LINE}" '
      $0 == want { pending = 0; next }
      pending    { print ""; pending = 0 }
      $0 == ""   { pending = 1; next }
                 { print }
      END        { if (pending) print "" }
    ' "${BACKUP}" > "${MD_TMP}"
  else
    # grep exits 1 when the import line was the only content — that is fine
    grep -vxF "${IMPORT_LINE}" "${BACKUP}" > "${MD_TMP}" || [ $? -eq 1 ]
  fi
  if cmp -s "${BACKUP}" "${GLOBAL_MD}"; then
    mv "${MD_TMP}" "${GLOBAL_MD}"
    [ -s "${GLOBAL_MD}" ] || rm -f "${GLOBAL_MD}"
    IMPORT_REWRITTEN=1
  else
    rm -f "${MD_TMP}"
    IMPORT_REWRITTEN=0
    echo "  !!  CLAUDE.md changed while this was running; left exactly as it is now (backup: $(basename "${BACKUP}"))" >&2
  fi
  # A backup whose entire content is the line this installer wrote, on a
  # CLAUDE.md that held nothing else, protects nothing: the machine had no
  # CLAUDE.md before the install, and leaving the backup means it does not
  # come back to that. Only this invocation's own BACKUP path is considered --
  # never a glob, and never an older backup, whose identical content would
  # still be somebody's decision to keep. One byte of anyone else's text and
  # the file stays.
  if [ "${IMPORT_REWRITTEN}" = 1 ]; then
    if printf '%s\n' "${IMPORT_LINE}" | cmp -s - "${BACKUP}"; then
      rm -f "${BACKUP}"
      echo "  ok  removed import line (its backup held only that line; removed)"
    else
      echo "  ok  removed import line (backup: $(basename "${BACKUP}"))"
    fi
  fi
else
  echo "  ok  no import line in CLAUDE.md"
fi
# Ours to remove only if it is ours, by the same marker install.sh wrote.
# Anything else at this path -- a symlink, a directory, a regular file with
# somebody's notes in it -- is left exactly where it is.
if provenance_is_ours; then
  rm -f "${IMPORT_PROVENANCE}"
fi

for KEEP in luciazero-stats.log luciazero-heuristics.md; do
  if [ -f "${CLAUDE_DIR}/${KEEP}" ]; then
    echo "  kept ${KEEP} (learned data) — delete manually if unwanted"
  fi
done
if [ -d "${CLAUDE_DIR}/.luciazero-backups" ]; then
  echo "  kept .luciazero-backups/ (pre-existing or customized components) — review and delete manually when no longer needed"
fi

# Directories this installer is the reason for, leaf to root, by name and
# never by glob. rmdir refuses a directory that still holds anything, so one
# file of the user's own keeps its directory and everything above it.
rmdir "${CLAUDE_DIR}/skills" "${CLAUDE_DIR}/agents" 2>/dev/null || true
rmdir "${CLAUDE_DIR}" 2>/dev/null || true

echo
echo "Done. Other CLAUDE.md content was left untouched."
echo "The Agent Bus state directory (~/.luciazero/agent-bus) is data and was not touched."
