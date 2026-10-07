#!/usr/bin/env bash
# Install the Luciazero doctrine + skills into ~/.claude/
# Idempotent. Backs up CLAUDE.md (and settings.json when --with-hooks)
# before editing. Writes nothing outside ~/.claude/ unless LUCIAZERO_BIN_DIR
# names another directory for the Agent Bus launcher.
#
#   ./install.sh               doctrine + skills + reviewer agent
#   ./install.sh --with-hooks  also wire the enforcement pack: verify-tracking
#                              hooks + statusline into ~/.claude/settings.json
#                              (Claude Code 2.1.139+ only; requires Node 18+)
#   ./install.sh --status      read-only health check of an existing install;
#                              exits non-zero if a core piece is missing
#
#   LUCIAZERO_BIN_DIR=<dir>    where `luciazero-agentd` goes (default: where
#                              the last install put it, else ~/.claude/bin;
#                              a checkout only -- the daemon is not in the
#                              npm payload)
set -euo pipefail

WITH_HOOKS=0
STATUS_ONLY=0
for ARG in "$@"; do
  case "${ARG}" in
    --with-hooks) WITH_HOOKS=1 ;;
    --status) STATUS_ONLY=1 ;;
    *) echo "unknown option: ${ARG} (supported: --with-hooks, --status)" >&2; exit 1 ;;
  esac
done

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
DOCTRINE="luciazero.md"
IMPORT_LINE="@${DOCTRINE}"
MANAGED_DIR="${CLAUDE_DIR}/.luciazero-managed"
BACKUP_DIR="${CLAUDE_DIR}/.luciazero-backups"
# Agent Bus launcher (checkouts only -- ADR 0002 keeps the daemon out of the
# npm payload). Default target stays inside CLAUDE_DIR so this script keeps
# its promise to write nowhere else; LUCIAZERO_BIN_DIR points it at a PATH
# directory such as ~/.local/bin when the user wants one.
AGENTD_MARKER="luciazero-managed: agentd-launcher"
# An install told LUCIAZERO_BIN_DIR records where it put the launchers, so a
# status check, a reinstall or an uninstall not told it again still finds them.
AGENTD_BIN_FILE="${CLAUDE_DIR}/.luciazero-agentd-bin"
AGENTD_BIN_DIR="${LUCIAZERO_BIN_DIR:-}"
if [ -z "${AGENTD_BIN_DIR}" ] && [ -f "${AGENTD_BIN_FILE}" ]; then
  AGENTD_BIN_DIR="$(head -n 1 "${AGENTD_BIN_FILE}" 2>/dev/null || true)"
  case "${AGENTD_BIN_DIR}" in /*) ;; *) AGENTD_BIN_DIR="" ;; esac
fi
AGENTD_BIN_DIR="${AGENTD_BIN_DIR:-${CLAUDE_DIR}/bin}"
AGENTD_LAUNCHER="${AGENTD_BIN_DIR}/luciazero-agentd"
# One script, installed twice. `lucia claude` is the whole of the ordinary
# path and the long name is what the subcommands were documented under, so
# both are installed and both work; a copy rather than a symlink so that the
# ownership marker is in the file itself and every check below reads it the
# same way for either name.
AGENTD_NAMES="luciazero-agentd lucia"
AGENTD_HOME_FILE="${CLAUDE_DIR}/.luciazero-agentd-home"

# Ours, someone else's, or absent. A launcher we did not write is never
# replaced: it is on PATH under a name we chose, and it may be a symlink the
# user made to a checkout of their own.
launcher_kind() {
  if [ -L "$1" ]; then
    if grep -qF "${AGENTD_MARKER}" "$1" 2>/dev/null; then echo symlink; else echo foreign; fi
  elif [ -e "$1" ]; then
    if [ -f "$1" ] && grep -qF "${AGENTD_MARKER}" "$1" 2>/dev/null; then echo ours; else echo foreign; fi
  else
    echo absent
  fi
}

on_path() {
  case ":${PATH}:" in
    *":$1:"*) return 0 ;;
    *) return 1 ;;
  esac
}

catalog() { sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "$1"; }
skill_inventory() {
  catalog "${SRC}/skills/catalog.txt"
  catalog "${SRC}/skills/aliases.txt"
}

# Package metadata is present in git checkouts and npm payloads alike.
version_of() {
  awk -F '"' '/^[[:space:]]*"version"[[:space:]]*:/ { print $4; exit }' \
    "${SRC}/package.json" 2>/dev/null || true
}
# A plugin install of Luciazero beside this classic one loads every skill and
# the reviewer agent twice in each session, as `/x` and `/luciazero:x` (the
# hook and the doctrine dedupe themselves; skills and agents cannot). Only the
# harness's own registry is consulted, read-only; when it is absent or says
# nothing, nothing is printed.
plugin_double_install_note() {
  REGISTRY="${CLAUDE_DIR}/plugins/installed_plugins.json"
  [ -f "${REGISTRY}" ] && grep -q '"luciazero@' "${REGISTRY}" 2>/dev/null || return 0
  echo "  !!    Luciazero is also installed as a Claude Code plugin: every skill and the"
  echo "        reviewer agent load twice per session. Keep one channel — /plugin uninstall"
  echo "        luciazero@luciazero for the plugin, or ./uninstall.sh for this copy."
}

# Node 18+ runs the hooks, the status line and the settings wiring.
node_ok() {
  command -v node >/dev/null 2>&1 \
    && node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 18 ? 0 : 1)' 2>/dev/null
}

# The hooks are wired in exec form (`args`), which Claude Code reads from
# 2.1.139 on; an older one runs `node` with no script. A note, never a stop:
# the version cannot always be asked, and the install itself is still right.
claude_version_note() { # claude_version_note <indent>
  CV="$(claude --version 2>/dev/null | head -n 1 | sed -n 's/^\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p')" || CV=""
  if [ -z "${CV}" ]; then
    echo "$1--    Claude Code version unknown — the hooks need 2.1.139 or newer"
  elif printf '%s\n%s\n' 2.1.139 "${CV}" | sort -t. -k1,1n -k2,2n -k3,3n -C; then
    echo "$1ok    Claude Code ${CV} (the hooks need 2.1.139 or newer)"
  else
    echo "$1!!    Claude Code ${CV} is older than 2.1.139 — it cannot run the hooks' exec-form entries; update Claude Code"
  fi
}

if [ "${STATUS_ONLY}" = 1 ]; then
  echo "Status of ${CLAUDE_DIR} (read-only)"
  STATUS_RC=0
  check() { # check <file-test-flag: -f|-x> <path> <label...>
    T="$1"; P="$2"; shift 2
    OK=0
    case "${T}" in
      -x) if [ -x "${P}" ]; then OK=1; fi ;;
      *)  if [ -f "${P}" ]; then OK=1; fi ;;
    esac
    if [ "${OK}" = 1 ]; then echo "  ok    $*"; else echo "  MISS  $*"; STATUS_RC=1; fi
  }
  check -f "${CLAUDE_DIR}/${DOCTRINE}" "doctrine ${DOCTRINE}"
  while IFS= read -r SKILL; do
    check -f "${CLAUDE_DIR}/skills/${SKILL}/SKILL.md" "skill ${SKILL}"
  done < <(skill_inventory)
  check -x "${CLAUDE_DIR}/skills/ready/scripts/detect.cjs" "detect.cjs executable"
  check -x "${CLAUDE_DIR}/skills/done/scripts/revert-probe.cjs" "revert-probe.cjs executable"
  check -x "${CLAUDE_DIR}/skills/bisect/scripts/safe-bisect.cjs" "safe-bisect.cjs executable"
  check -x "${CLAUDE_DIR}/skills/ready/scripts/detect.sh" "detect.sh executable"
  check -x "${CLAUDE_DIR}/skills/done/scripts/revert-probe.sh" "revert-probe.sh executable"
  check -x "${CLAUDE_DIR}/skills/bisect/scripts/safe-bisect.sh" "safe-bisect.sh executable"
  check -x "${CLAUDE_DIR}/skills/lucia-relay/scripts/relay.py" "relay.py executable"
  while IFS= read -r AGENT_NAME; do
    check -f "${CLAUDE_DIR}/agents/${AGENT_NAME}.md" "agent ${AGENT_NAME}"
  done < <(catalog "${SRC}/claude/agents/catalog.txt")
  if [ -f "${SRC}/agentd/luciazero_agentd/__init__.py" ]; then
    AGENTD_ANY=0
    for AGENTD_NAME in ${AGENTD_NAMES}; do
      case "$(launcher_kind "${AGENTD_BIN_DIR}/${AGENTD_NAME}")" in
        ours|symlink)
          echo "  ok    agent bus launcher ${AGENTD_BIN_DIR}/${AGENTD_NAME}"
          AGENTD_ANY=1 ;;
        foreign)
          echo "  MISS  ${AGENTD_BIN_DIR}/${AGENTD_NAME} is not the Luciazero launcher (left untouched)"; STATUS_RC=1 ;;
        *)
          echo "  --    ${AGENTD_NAME} not installed (optional; ./install.sh installs it)" ;;
      esac
    done
    if [ "${AGENTD_ANY}" = 1 ]; then
      on_path "${AGENTD_BIN_DIR}" \
        || echo "        (not on PATH: export PATH=\"${AGENTD_BIN_DIR}:\$PATH\")"
      if [ -f "${AGENTD_HOME_FILE}" ] && [ -d "$(cat "${AGENTD_HOME_FILE}")/luciazero_agentd" ]; then
        echo "  ok    agentd package recorded at $(cat "${AGENTD_HOME_FILE}")"
      else
        echo "  MISS  ${AGENTD_HOME_FILE} does not point at an agentd package — re-run ./install.sh"; STATUS_RC=1
      fi
    fi
  fi
  GLOBAL_MD="${CLAUDE_DIR}/CLAUDE.md"
  N="$(grep -cxF "${IMPORT_LINE}" "${GLOBAL_MD}" 2>/dev/null || true)"
  if [ "${N:-0}" = 1 ]; then
    echo "  ok    CLAUDE.md imports the doctrine"
  else
    echo "  MISS  CLAUDE.md import line (${IMPORT_LINE} exactly once; found ${N:-0})"; STATUS_RC=1
  fi
  plugin_double_install_note
  V_SRC="$(version_of)"
  V_INST="$(cat "${CLAUDE_DIR}/.luciazero-version" 2>/dev/null || true)"
  if [ -z "${V_INST}" ]; then
    echo "  --    installed version unknown (no sidecar — installed by an older version)"
  elif [ "${V_INST}" = "${V_SRC}" ]; then
    echo "  ok    version ${V_INST} (matches this checkout)"
  else
    echo "  !!    installed ${V_INST}, checkout ${V_SRC:-?} — re-run ./install.sh to update"
  fi
  if [ -f "${CLAUDE_DIR}/hooks/luciazero-verify.cjs" ]; then
    # stale hooks are the silent failure mode of `git pull && ./install.sh`
    # without --with-hooks: sidecar updates, hook files do not
    for HFILE in luciazero-verify.cjs luciazero-statusline.cjs; do
      if cmp -s "${CLAUDE_DIR}/hooks/${HFILE}" "${SRC}/claude/hooks/${HFILE}"; then
        echo "  ok    hooks/${HFILE} matches this checkout"
      else
        echo "  MISS  hooks/${HFILE} differs from this checkout (stale or customized) — re-run ./install.sh --with-hooks"; STATUS_RC=1
      fi
    done
    # Whether a subcommand is wired is asked of the parsed settings, by the
    # same module that wires them, never of the bytes.
    WIRE_MISS=""
    WIRE_UNCHECKED=""
    if node_ok; then
      # a reader that crashed printed nothing, and nothing is what a fully
      # wired settings.json prints too -- so its exit status decides
      WIRE_MISS="$(node "${SRC}/bin/lib/settings-wiring.js" status \
        "${CLAUDE_DIR}/settings.json" "${CLAUDE_DIR}/hooks")" || WIRE_UNCHECKED=reader
    else
      WIRE_UNCHECKED=node
    fi
    # Two different unknowns, and neither is "wired": no Node to ask with,
    # and a reader that could not answer. Both are reported as what they are,
    # because a status that says "ok" here is the one nobody re-checks.
    if [ "${WIRE_UNCHECKED}" = node ]; then
      echo "  MISS  hook wiring not checked — Node 18+ not found"; STATUS_RC=1
    elif [ "${WIRE_UNCHECKED}" = reader ]; then
      echo "  MISS  hook wiring not checked — settings.json could not be read"; STATUS_RC=1
    elif [ -z "${WIRE_MISS}" ]; then
      echo "  ok    hooks wired in settings.json (prompt/skill-prompt/bash-start/edit/bash/bash-failure/skill/stop/session)"
    else
      echo "  MISS  settings.json missing hook entries:${WIRE_MISS} (re-run ./install.sh --with-hooks)"; STATUS_RC=1
    fi
    if node_ok; then
      echo "  ok    node >= 18 available (the hooks need it)"
    elif command -v node >/dev/null 2>&1; then
      echo "  MISS  node is older than 18 — the hooks fail (doing nothing)"; STATUS_RC=1
    else
      # a missing node breaks the hooks SILENTLY — surface it here
      echo "  MISS  node not found — the installed hooks cannot run (doing nothing)"; STATUS_RC=1
    fi
    claude_version_note "  "
  elif [ -f "${CLAUDE_DIR}/hooks/luciazero-verify.sh" ]; then
    # the Bash hooks before the move to Node: still running where python3 is,
    # but not what this checkout installs
    echo "  MISS  enforcement pack is the older Bash version (needs python3) — re-run ./install.sh --with-hooks to move it to Node"; STATUS_RC=1
  elif [ -f "${CLAUDE_DIR}/settings.json" ] \
    && grep -qF "${CLAUDE_DIR}/hooks/luciazero-" "${CLAUDE_DIR}/settings.json"; then
    # worse than not installed: Claude Code keeps executing references to
    # files that are gone — exactly what uninstall.sh works to prevent
    echo "  MISS  settings.json references hook files that do not exist (dangling — re-run ./install.sh --with-hooks or ./uninstall.sh)"; STATUS_RC=1
  else
    echo "  --    enforcement pack not installed (optional: ./install.sh --with-hooks)"
  fi
  exit "${STATUS_RC}"
fi

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
# helper made and then entered, and only once what it entered passes
# `bc_enter`; from then on a swap of the name cannot redirect the writes.
# Paths and link targets are kept byte for byte, a trailing newline included.
# $1 is `-L` to back up what a symlink points at, as `cp` does, or `-P` to
# back up the symlink itself, as `cp -P` does.
#
# bc_raw <var> <command...>: the command's output, whole, into <var>. `$( )`
# deletes every trailing newline, and a file name or link target may end in
# one, so only the one newline the command itself ends with is taken off.
bc_raw() {
  BC_OUT="$(shift; "$@" && printf x)" || return 1
  BC_OUT="${BC_OUT%x}"
  printf -v "$1" '%s' "${BC_OUT%$'\n'}"
}

# The physical path of directory $1, for bc_raw.
bc_physical() {
  CDPATH='' cd -P -- "$1" && pwd -P
}

bc_symlink() {
  case "$1" in
    ln) ln -sT -- "$2" "$3" ;;
    perl) perl -e 'symlink($ARGV[0], $ARGV[1]) or exit 1' -- "$2" "$3" ;;
    node) node -e 'try { require("fs").symlinkSync(process.argv[1], process.argv[2]) } catch (e) { process.exit(1) }' -- "$2" "$3" ;;
    *) return 1 ;;
  esac
}

# Enter $1, an absolute physical path to a directory bakcopy made, and succeed
# only when what was entered is a directory owned by this user, empty, and at
# that physical path, reached without a symlink. Empty is a listing that
# succeeded and printed nothing at all, so an entry named only by newlines
# counts. Not an inode identity check: it shuts out other users' directories
# and planted symlinks, not this user's own processes, and it holds only
# while other users cannot rename entries in the directory above.
bc_enter() {
  cd "$1" 2>/dev/null && [ -O . ] && bc_raw BC_LS ls -A . && [ -z "${BC_LS}" ] \
    && [ "$(pwd -P; printf x)" = "$1"$'\n'x ]
}

bakcopy() {
  BC_SRC="$2"; BC_BASE="$3"; BC_Q=""; BC_RC=0
  BC_STAMP="$(date +%Y%m%d%H%M%S)"
  if [ "$1" = -P ] && [ -L "${BC_SRC}" ]; then
    BC_KIND="link"
  elif [ -d "${BC_SRC}" ]; then
    BC_KIND="tree"
  else
    BC_KIND="file"
  fi
  case "${BC_SRC}" in /*) ;; *) BC_SRC="${PWD}/${BC_SRC}" ;; esac
  if ! { bc_raw BC_DIR dirname "${BC_BASE}" && bc_raw BC_DIR bc_physical "${BC_DIR}"; }; then
    echo "FAIL: could not back up ${BC_SRC}" >&2; return 1
  fi
  if [ "${BC_KIND}" = link ]; then
    # `readlink -n`, whole: macOS adds no newline after a target that already
    # ends in one, so taking one off would cut the target.
    BC_TO="$(readlink -n "${BC_SRC}" && printf x)" \
      || { echo "FAIL: could not back up ${BC_SRC}" >&2; return 1; }
    BC_TO="${BC_TO%x}"
    BC_SL=""
    BC_P="$(mktemp -d)" || { echo "FAIL: could not back up ${BC_SRC}" >&2; return 1; }
    for BC_T in ln perl node; do
      command -v "${BC_T}" >/dev/null 2>&1 || continue
      rm -rf "${BC_P}/t"
      if ! { mkdir "${BC_P}/t" "${BC_P}/t/d" && : > "${BC_P}/t/d/c" && printf k > "${BC_P}/t/r" \
        && ln -s d "${BC_P}/t/s" && ln -s nowhere "${BC_P}/t/g"; }; then
        break
      fi
      if bc_symlink "${BC_T}" x "${BC_P}/t/n" 2>/dev/null \
        && [ "$(readlink "${BC_P}/t/n")" = x ] \
        && ! bc_symlink "${BC_T}" x "${BC_P}/t/d" 2>/dev/null \
        && ! bc_symlink "${BC_T}" x "${BC_P}/t/s" 2>/dev/null \
        && ! bc_symlink "${BC_T}" x "${BC_P}/t/g" 2>/dev/null \
        && ! bc_symlink "${BC_T}" x "${BC_P}/t/r" 2>/dev/null \
        && [ "$(ls -A "${BC_P}/t/d")" = c ] && [ ! -e "${BC_P}/t/nowhere" ] \
        && [ ! -L "${BC_P}/t/nowhere" ] && [ ! -L "${BC_P}/t/r" ] \
        && [ "$(cat "${BC_P}/t/r")" = k ]; then
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
  # The private directory goes only when it passes the same owner and path
  # check as before it was written; anything else at its name stays.
  if [ -n "${BC_Q}" ]; then
    if ( cd "${BC_Q}" 2>/dev/null && [ -O . ] && [ "$(pwd -P; printf x)" = "${BC_Q}"$'\n'x ] \
      && rm -f f ); then
      rmdir "${BC_Q}" 2>/dev/null || :
    fi
  fi
  [ "${BC_RC}" = 0 ] || { echo "FAIL: could not back up ${BC_SRC}" >&2; return 1; }
}

# A catalog entry such as "plan" can already belong to the user or another
# plugin. Keep an exact snapshot of what Luciazero installed, so reinstalls can
# distinguish our copy from user data. Collisions/customizations are copied to
# a hidden backup tree before replacement; hidden directories are not loaded as
# skills by either harness.
same_tree() {
  [ -d "$1" ] && [ ! -L "$1" ] && [ -d "$2" ] && [ ! -L "$2" ] \
    && diff -qr "$1" "$2" >/dev/null 2>&1
}

backup_tree() {
  BT_SRC="$1"; BT_LABEL="$2"
  BT_BASE="${BACKUP_DIR}/${BT_LABEL}"
  mkdir -p "$(dirname "${BT_BASE}")"
  BT_DST="$(bakcopy -P "${BT_SRC}" "${BT_BASE}")"
  echo "  ok  backed up existing ${BT_LABEL} -> ${BT_DST#"${CLAUDE_DIR}/"}"
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

install_file() {
  IF_SRC="$1"; IF_DST="$2"; IF_SNAPSHOT="$3"; IF_LABEL="$4"
  if [ -e "${IF_DST}" ] || [ -L "${IF_DST}" ]; then
    IF_OURS=0
    if [ -f "${IF_DST}" ] && [ ! -L "${IF_DST}" ]; then
      if { [ -f "${IF_SNAPSHOT}" ] && cmp -s "${IF_DST}" "${IF_SNAPSHOT}"; } \
        || cmp -s "${IF_DST}" "${IF_SRC}"; then
        IF_OURS=1
      fi
    fi
    if [ "${IF_OURS}" = 0 ]; then
      IF_BASE="${BACKUP_DIR}/${IF_LABEL}"
      mkdir -p "$(dirname "${IF_BASE}")"
      IF_BACKUP="$(bakcopy -P "${IF_DST}" "${IF_BASE}")"
      echo "  ok  backed up existing ${IF_LABEL} -> ${IF_BACKUP#"${CLAUDE_DIR}/"}"
    fi
    rm -f "${IF_DST}"
  fi
  mkdir -p "$(dirname "${IF_DST}")" "$(dirname "${IF_SNAPSHOT}")"
  cp "${IF_SRC}" "${IF_DST}"
  rm -f "${IF_SNAPSHOT}"
  cp "${IF_SRC}" "${IF_SNAPSHOT}"
}

echo "Installing into ${CLAUDE_DIR}"
mkdir -p "${CLAUDE_DIR}/skills"

# 1. doctrine
install_file "${SRC}/claude/${DOCTRINE}" "${CLAUDE_DIR}/${DOCTRINE}" \
  "${MANAGED_DIR}/${DOCTRINE}" "${DOCTRINE}"
echo "  ok  ${DOCTRINE}"

# 2. canonical skills
while IFS= read -r SKILL; do
  install_tree "${SRC}/skills/${SKILL}" \
    "${CLAUDE_DIR}/skills/${SKILL}" \
    "${MANAGED_DIR}/skills/${SKILL}" \
    "skills/${SKILL}"
  echo "  ok  skills/${SKILL}"
done < <(skill_inventory)

# v2.3 migration: remove only the untouched /luciazero-bootstrap compatibility
# alias from older installs. Customized copies remain user data.
remove_legacy_tree "${CLAUDE_DIR}/skills/luciazero-bootstrap" \
  "${MANAGED_DIR}/skills/luciazero-bootstrap" \
  "skills/luciazero-bootstrap"

# v1.5 migration: remove only an untouched Luciazero /handoff. A customized
# skill is user data and stays in place with an explicit warning.
LEGACY_HANDOFF="${CLAUDE_DIR}/skills/handoff"
if [ -f "${LEGACY_HANDOFF}/SKILL.md" ]; then
  if cmp -s "${SRC}/migrations/handoff-v1.5.0.SKILL.md" "${LEGACY_HANDOFF}/SKILL.md"; then
    rm -rf "${LEGACY_HANDOFF}"
    echo "  ok  migrated skill handoff -> lucia-relay"
  else
    echo "  !!  skills/handoff is customized; left untouched (Luciazero now uses /lucia-relay)" >&2
  fi
fi

# 3. agents (same ownership/snapshot rule as skills)
mkdir -p "${CLAUDE_DIR}/agents"
while IFS= read -r AGENT_NAME; do
  AGENT="${CLAUDE_DIR}/agents/${AGENT_NAME}.md"
  install_file "${SRC}/claude/agents/${AGENT_NAME}.md" "${AGENT}" \
    "${MANAGED_DIR}/agents/${AGENT_NAME}.md" "agents/${AGENT_NAME}.md"
  echo "  ok  agents/${AGENT_NAME}.md"
done < <(catalog "${SRC}/claude/agents/catalog.txt")

# 3b. Agent Bus launcher, so the daemon has a public command instead of
# `cd agentd && python3 -m luciazero_agentd`. Only from a checkout: the npm
# payload ships this shim but not the package it runs.
if [ -f "${SRC}/agentd/luciazero_agentd/__init__.py" ] && [ -f "${SRC}/bin/luciazero-agentd" ]; then
  # `ours` for the pair: one foreign name must not stop the other being
  # installed, and must not stop the package pointer both of them read.
  AGENTD_KIND=absent
  for AGENTD_NAME in ${AGENTD_NAMES}; do
    AGENTD_TARGET="${AGENTD_BIN_DIR}/${AGENTD_NAME}"
    AGENTD_ONE="$(launcher_kind "${AGENTD_TARGET}")"
    case "${AGENTD_ONE}" in
      foreign)
        echo "  !!  ${AGENTD_TARGET} exists and is not the Luciazero launcher; left untouched" >&2
        echo "      install it elsewhere with: LUCIAZERO_BIN_DIR=<dir> ./install.sh" >&2 ;;
      symlink)
        echo "  ok  bin/${AGENTD_NAME} (symlink to a Luciazero launcher; left as is)"
        AGENTD_KIND=ours ;;
      *)
        mkdir -p "${AGENTD_BIN_DIR}"
        if [ "${AGENTD_ONE}" = ours ] && cmp -s "${SRC}/bin/luciazero-agentd" "${AGENTD_TARGET}"; then
          echo "  ok  bin/${AGENTD_NAME} (unchanged)"
        else
          cp "${SRC}/bin/luciazero-agentd" "${AGENTD_TARGET}"
          echo "  ok  bin/${AGENTD_NAME} -> ${AGENTD_TARGET}"
        fi
        chmod +x "${AGENTD_TARGET}"
        AGENTD_KIND=ours ;;
    esac
  done
  if [ "${AGENTD_KIND}" != absent ]; then
    # The installed copy is no longer next to the package, so it is told
    # where the package went. Nothing here depends on the caller's cwd.
    printf '%s\n' "${SRC}/agentd" > "${AGENTD_HOME_FILE}"
    if [ "${AGENTD_BIN_DIR}" = "${CLAUDE_DIR}/bin" ]; then
      rm -f "${AGENTD_BIN_FILE}"
    else
      printf '%s\n' "$(CDPATH='' cd -- "${AGENTD_BIN_DIR}" && pwd -P)" > "${AGENTD_BIN_FILE}"
    fi
    on_path "${AGENTD_BIN_DIR}" \
      || echo "      add to PATH:  export PATH=\"${AGENTD_BIN_DIR}:\$PATH\""
  fi
fi

# 4. version sidecar — lets --status and future installs tell what is installed
V_NEW="$(version_of)"
V_OLD="$(cat "${CLAUDE_DIR}/.luciazero-version" 2>/dev/null || true)"
if [ -n "${V_NEW}" ]; then
  if [ -n "${V_OLD}" ] && [ "${V_OLD}" != "${V_NEW}" ]; then
    echo "  ok  updating ${V_OLD} -> ${V_NEW}"
  fi
  printf '%s\n' "${V_NEW}" > "${CLAUDE_DIR}/.luciazero-version"
fi

# 5. import line in global CLAUDE.md
GLOBAL_MD="${CLAUDE_DIR}/CLAUDE.md"
IMPORT_PROVENANCE="${CLAUDE_DIR}/.luciazero-import"

# Empty when neither hasher is present, which makes the record unusable and
# sends the uninstaller down its conservative path. That is the right failure.
sha_of() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 < "$1" | cut -d' ' -f1
  elif command -v sha256sum >/dev/null 2>&1; then sha256sum < "$1" | cut -d' ' -f1
  else echo ""; fi
}

# Anything already at this path belongs to whoever put it there until it
# proves otherwise, and "it is a regular file" proves nothing -- a plain file
# somebody keeps notes in would pass that and be overwritten here and deleted
# by the uninstaller. Ownership is the marker in the first line, the same rule
# the launcher lives under. A symlink, a directory, or a regular file without
# the marker: the installer writes nothing and says so, and the uninstaller,
# finding no record of its own, stays conservative.
IMPORT_MARKER="luciazero-managed: import-provenance"
provenance_is_ours() {
  [ -f "${IMPORT_PROVENANCE}" ] && [ ! -L "${IMPORT_PROVENANCE}" ] \
    && [ "$(head -n 1 "${IMPORT_PROVENANCE}" 2>/dev/null)" = "${IMPORT_MARKER}" ]
}
write_provenance() {
  if [ -e "${IMPORT_PROVENANCE}" ] || [ -L "${IMPORT_PROVENANCE}" ]; then
    if ! provenance_is_ours; then
      echo "  !!  ${IMPORT_PROVENANCE} exists and is not ours; left untouched" >&2
      echo "      uninstall will remove the import line and nothing else" >&2
      return 0
    fi
  fi
  # mktemp creates the file itself, exclusively and under a name nobody can
  # guess, so there is no window in which a symlink planted at a predictable
  # path could take the write. The rename is what publishes it.
  IMPORT_TMP="$(mktemp "${CLAUDE_DIR}/.luciazero-import.XXXXXX")" || return 0
  if printf '%s\n%s\n' "${IMPORT_MARKER}" "$1" > "${IMPORT_TMP}"; then
    mv -f "${IMPORT_TMP}" "${IMPORT_PROVENANCE}" || rm -f "${IMPORT_TMP}"
  else
    rm -f "${IMPORT_TMP}"
  fi
}
if [ -f "${GLOBAL_MD}" ] && grep -qF "${IMPORT_LINE}" "${GLOBAL_MD}"; then
  echo "  ok  CLAUDE.md already imports ${DOCTRINE}"
else
  if [ -f "${GLOBAL_MD}" ]; then
    BACKUP="$(bakcopy -L "${GLOBAL_MD}" "${GLOBAL_MD}")"
    echo "  ok  backed up CLAUDE.md -> $(basename "${BACKUP}")"
    printf '\n%s\n' "${IMPORT_LINE}" >> "${GLOBAL_MD}"
    # Provenance for the uninstaller, and the only reason it may remove the
    # blank line above the import line. A CLAUDE.md can arrive at that same
    # shape without this branch running -- somebody writes the import line
    # themselves, blank line and all, and the check above then leaves the file
    # alone -- and in that case the blank is theirs. The hash is what makes the
    # record about THIS file rather than about this installer's habits: edit
    # the file afterwards, move the import line, add a blank of your own, and
    # the hash stops matching and the uninstaller keeps its hands off.
    write_provenance "appended $(sha_of "${GLOBAL_MD}")"
  else
    printf '%s\n' "${IMPORT_LINE}" > "${GLOBAL_MD}"
    write_provenance "created $(sha_of "${GLOBAL_MD}")"
  fi
  echo "  ok  CLAUDE.md imports ${DOCTRINE}"
fi

# wire_settings <check|write>: wire the pack's hooks and status line into
# ${SETTINGS}, additively and idempotently, migrating the Bash-era entries of
# an older install in place. `check` decides everything and writes nothing;
# `write` replaces the file whole. bin/lib/settings-wiring.js holds the rules,
# shared with uninstall.sh and the Windows installer.
wire_settings() {
  node "${SRC}/bin/lib/settings-wiring.js" wire "$1" "${SETTINGS}" "${CLAUDE_DIR}/hooks"
}

# legacy_shipped <file>: the file is a Bash-era hook exactly as this project
# shipped it (claude/hooks/legacy-hooks.sha256), so nobody's edits are in it.
legacy_shipped() {
  LS_SUM="$(sha_of "$1")"
  [ -n "${LS_SUM}" ] && grep -qx "${LS_SUM}" "${SRC}/claude/hooks/legacy-hooks.sha256"
}

# 6. enforcement pack (opt-in): hooks + statusline wired into settings.json
if [ "${WITH_HOOKS}" = 1 ]; then
  command -v node >/dev/null 2>&1 || { echo "FAIL: --with-hooks requires Node 18+ (node not found)" >&2; exit 1; }
  node_ok || { echo "FAIL: --with-hooks requires Node 18+ (found $(node --version 2>/dev/null))" >&2; exit 1; }
  SETTINGS="${CLAUDE_DIR}/settings.json"
  # Whether settings.json can be wired is decided before anything of the pack
  # is copied: a file that is not JSON, not the shape hooks live in, or not
  # writable stops the install here, with no hook file in place and
  # settings.json untouched (roadmap R14).
  WIRE_PENDING="$(wire_settings check)" \
    || { echo "FAIL: settings.json cannot be wired (see above) — hook files not copied, settings.json untouched" >&2; exit 1; }
  mkdir -p "${CLAUDE_DIR}/hooks"
  for H in luciazero-verify.cjs luciazero-statusline.cjs; do
    DST="${CLAUDE_DIR}/hooks/${H}"
    if [ -f "${DST}" ] && ! cmp -s "${SRC}/claude/hooks/${H}" "${DST}"; then
      bakcopy -L "${DST}" "${DST}" >/dev/null
      echo "  ok  backed up existing hooks/${H}"
    fi
    cp "${SRC}/claude/hooks/${H}" "${DST}"
    chmod +x "${DST}"
  done
  # backed up only when the wiring is about to change it
  if [ -f "${SETTINGS}" ] && [ "${WIRE_PENDING}" = changes ]; then
    bakcopy -L "${SETTINGS}" "${SETTINGS}" >/dev/null
  fi
  wire_settings write \
    || { echo "FAIL: could not update settings.json (see above) — hook files copied but not wired" >&2; exit 1; }
  # The Bash hooks of an older install are unwired now. One still named in
  # settings.json (a custom status line built on it) stays; one exactly as
  # shipped goes; one somebody edited goes only after a backup.
  for H in luciazero-verify.sh luciazero-statusline.sh; do
    F="${CLAUDE_DIR}/hooks/${H}"
    [ -f "${F}" ] || continue
    if [ -f "${SETTINGS}" ] && grep -qF "${H}" "${SETTINGS}"; then
      echo "  !!  hooks/${H} kept — settings.json still names it"
    elif legacy_shipped "${F}"; then
      rm -f "${F}"
      echo "  ok  retired hooks/${H} (the Bash hooks before Node)"
    else
      B="$(bakcopy -L "${F}" "${F}")"
      rm -f "${F}"
      echo "  ok  retired edited hooks/${H} (backup: $(basename "${B}"))"
    fi
  done
  claude_version_note "  "
fi

echo
echo "Done. Verify:"
echo "  ./install.sh --status"
echo
SKILL_SUMMARY="$(catalog "${SRC}/skills/catalog.txt" | awk 'BEGIN{s=""} {s=s (s ? ", " : "") "/" $0} END{print s}')"
AGENT_SUMMARY="$(catalog "${SRC}/claude/agents/catalog.txt" | awk 'BEGIN{s=""} {s=s (s ? ", " : "") $0} END{print s}')"
echo "Skills: ${SKILL_SUMMARY}. Agents: ${AGENT_SUMMARY}."
if [ -f "${SRC}/agentd/luciazero_agentd/__init__.py" ] && [ -x "${AGENTD_BIN_DIR}/lucia" ] \
  && [ "$(launcher_kind "${AGENTD_BIN_DIR}/lucia")" != foreign ]; then
  echo "Agent Bus: lucia claude in one window, lucia codex in another (${AGENTD_BIN_DIR}/lucia)."
  echo "           the long name luciazero-agentd answers to every subcommand as before."
elif [ -f "${SRC}/agentd/luciazero_agentd/__init__.py" ] && [ -x "${AGENTD_LAUNCHER}" ] \
  && [ "$(launcher_kind "${AGENTD_LAUNCHER}")" != foreign ]; then
  echo "Agent Bus: luciazero-agentd next | watch | chat | run (${AGENTD_LAUNCHER})."
fi
if [ "${WITH_HOOKS}" = 1 ]; then
  echo "Enforcement pack installed: verify-tracking hooks + statusline (see settings.json)."
else
  echo "Optional: ./install.sh --with-hooks adds the verify-nudge hooks + statusline."
fi
plugin_double_install_note
echo "The doctrine applies from the next Claude Code session."
