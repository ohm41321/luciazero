#!/usr/bin/env bash
# Install the Luciazero doctrine + skills into ~/.claude/
# Idempotent. Backs up CLAUDE.md (and settings.json when --with-hooks)
# before editing. Writes nothing outside ~/.claude/ unless LUCIAZERO_BIN_DIR
# names another directory for the Agent Bus launcher.
#
#   ./install.sh               doctrine + skills + reviewer agent
#   ./install.sh --with-hooks  also wire the enforcement pack: verify-tracking
#                              hooks + statusline into ~/.claude/settings.json
#                              (Claude Code only; requires python3)
#   ./install.sh --status      read-only health check of an existing install;
#                              exits non-zero if a core piece is missing
#
#   LUCIAZERO_BIN_DIR=<dir>    where `luciazero-agentd` goes (default
#                              ~/.claude/bin; a checkout only -- the daemon
#                              is not in the npm payload)
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
AGENTD_BIN_DIR="${LUCIAZERO_BIN_DIR:-${CLAUDE_DIR}/bin}"
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
  V_SRC="$(version_of)"
  V_INST="$(cat "${CLAUDE_DIR}/.luciazero-version" 2>/dev/null || true)"
  if [ -z "${V_INST}" ]; then
    echo "  --    installed version unknown (no sidecar — installed by an older version)"
  elif [ "${V_INST}" = "${V_SRC}" ]; then
    echo "  ok    version ${V_INST} (matches this checkout)"
  else
    echo "  !!    installed ${V_INST}, checkout ${V_SRC:-?} — re-run ./install.sh to update"
  fi
  if [ -f "${CLAUDE_DIR}/hooks/luciazero-verify.sh" ]; then
    check -x "${CLAUDE_DIR}/hooks/luciazero-verify.sh" "hook luciazero-verify.sh executable"
    check -x "${CLAUDE_DIR}/hooks/luciazero-statusline.sh" "hook luciazero-statusline.sh executable"
    # stale hooks are the silent failure mode of `git pull && ./install.sh`
    # without --with-hooks: sidecar updates, hook files do not
    for HFILE in luciazero-verify.sh luciazero-statusline.sh; do
      if cmp -s "${CLAUDE_DIR}/hooks/${HFILE}" "${SRC}/claude/hooks/${HFILE}"; then
        echo "  ok    hooks/${HFILE} matches this checkout"
      else
        echo "  MISS  hooks/${HFILE} differs from this checkout (stale or customized) — re-run ./install.sh --with-hooks"; STATUS_RC=1
      fi
    done
    # The stored command is a shell string whose path may be quoted, so
    # whether a subcommand is wired is asked of the parsed command rather
    # than of the bytes: a `grep` for the bare path stops seeing a
    # correctly quoted entry the moment the path needs quoting.
    WIRE_MISS=""
    WIRE_UNCHECKED=""
    if command -v python3 >/dev/null 2>&1; then
      # a reader that crashed printed nothing, and nothing is what a fully
      # wired settings.json prints too -- so its exit status decides
      WIRE_MISS="$(python3 - "${CLAUDE_DIR}/settings.json" "${CLAUDE_DIR}/hooks/luciazero-verify.sh" <<'WIREPY'
import json, shlex, sys

path, verify = sys.argv[1], sys.argv[2]
try:
    with open(path) as f:
        settings = json.load(f)
except (OSError, ValueError):
    settings = {}

def sub_of(cmd):
    """Which subcommand of ours this entry runs, or None if it is not ours."""
    if not isinstance(cmd, str):
        return None
    if cmd == verify:
        return ""
    if cmd.startswith(verify + " "):
        return cmd[len(verify) + 1:].strip()
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return None
    if parts and parts[0] == verify:
        return " ".join(parts[1:])
    return None

hooks = settings.get("hooks") if isinstance(settings, dict) else None
wired = set()
for entries in (hooks or {}).values() if isinstance(hooks, dict) else ():
    for entry in entries if isinstance(entries, list) else ():
        inner = entry.get("hooks") if isinstance(entry, dict) else None
        for hook in inner if isinstance(inner, list) else ():
            if not isinstance(hook, dict):
                continue
            sub = sub_of(hook.get("command", ""))
            if sub is not None:
                wired.add(sub)

want = "prompt skill-prompt bash-start edit bash bash-failure skill stop session".split()
sys.stdout.write("".join(" " + s for s in want if s not in wired))
WIREPY
)" || WIRE_UNCHECKED=reader
    else
      WIRE_UNCHECKED=python3
    fi
    # Two different unknowns, and neither is "wired": no python3 to ask with,
    # and a reader that could not answer. Both are reported as what they are,
    # because a status that says "ok" here is the one nobody re-checks.
    if [ "${WIRE_UNCHECKED}" = python3 ]; then
      echo "  MISS  hook wiring not checked — python3 not found"; STATUS_RC=1
    elif [ "${WIRE_UNCHECKED}" = reader ]; then
      echo "  MISS  hook wiring not checked — settings.json could not be read"; STATUS_RC=1
    elif [ -z "${WIRE_MISS}" ]; then
      echo "  ok    hooks wired in settings.json (prompt/skill-prompt/bash-start/edit/bash/bash-failure/skill/stop/session)"
    else
      echo "  MISS  settings.json missing hook entries:${WIRE_MISS} (re-run ./install.sh --with-hooks)"; STATUS_RC=1
    fi
    if command -v python3 >/dev/null 2>&1 \
      && python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      echo "  ok    python3 >= 3.9 available (the hooks need it)"
    elif command -v python3 >/dev/null 2>&1; then
      echo "  MISS  python3 is older than 3.9 — the hooks fail open (doing nothing)"; STATUS_RC=1
    else
      # fail-open means a missing python3 breaks the hooks SILENTLY — surface it here
      echo "  MISS  python3 not found — the installed hooks are failing open (doing nothing)"; STATUS_RC=1
    fi
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

# collision-proof backup path for $1 (two runs in the same second must not overwrite)
bakpath() {
  B="$1.bak.$(date +%Y%m%d%H%M%S)"
  N=1
  while [ -e "${B}" ]; do B="$1.bak.$(date +%Y%m%d%H%M%S).${N}"; N=$((N+1)); done
  printf '%s' "${B}"
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
  BT_DST="$(bakpath "${BT_BASE}")"
  cp -RP "${BT_SRC}" "${BT_DST}"
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
      IF_BACKUP="$(bakpath "${IF_BASE}")"
      cp -P "${IF_DST}" "${IF_BACKUP}"
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
    BACKUP="$(bakpath "${GLOBAL_MD}")"
    cp "${GLOBAL_MD}" "${BACKUP}"
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

# 6. enforcement pack (opt-in): hooks + statusline wired into settings.json
if [ "${WITH_HOOKS}" = 1 ]; then
  command -v python3 >/dev/null 2>&1 || { echo "FAIL: --with-hooks requires python3" >&2; exit 1; }
  # 3.9 is where hashlib gained usedforsecurity=, which the hooks pass so their
  # md5 state key does not raise under FIPS and silently disable tracking
  python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null \
    || { echo "FAIL: --with-hooks requires a working python3 >= 3.9" >&2; exit 1; }
  mkdir -p "${CLAUDE_DIR}/hooks"
  for H in luciazero-verify.sh luciazero-statusline.sh; do
    DST="${CLAUDE_DIR}/hooks/${H}"
    if [ -f "${DST}" ] && ! cmp -s "${SRC}/claude/hooks/${H}" "${DST}"; then
      cp "${DST}" "$(bakpath "${DST}")"
      echo "  ok  backed up existing hooks/${H}"
    fi
    cp "${SRC}/claude/hooks/${H}" "${DST}"
    chmod +x "${DST}"
  done
  SETTINGS="${CLAUDE_DIR}/settings.json"
  if [ -f "${SETTINGS}" ]; then
    cp "${SETTINGS}" "$(bakpath "${SETTINGS}")"
  fi
  python3 - "${SETTINGS}" "${CLAUDE_DIR}/hooks" <<'PY' || { echo "FAIL: could not update settings.json (invalid JSON?) — hook files copied but not wired" >&2; exit 1; }
import json, os, shlex, sys

path, hooks_dir = sys.argv[1], sys.argv[2]
verify_cmd = os.path.join(hooks_dir, "luciazero-verify.sh")
status_cmd = os.path.join(hooks_dir, "luciazero-statusline.sh")
MARKERS = (verify_cmd, status_cmd)

# A hook command is a shell string, not an argv. A hooks directory whose name
# contains a space ends the command at that byte -- the stored command runs a
# prefix of the path and the shell answers 127 -- and a quote or a `$` in it
# would be worse than a broken hook. `shlex.quote` leaves a path that needs
# nothing exactly as it was, so an install that already worked keeps every
# byte and only the ones that were broken change.
def command(script, sub=""):
    return shlex.quote(script) + (" " + sub if sub else "")

# Ours in either spelling: what `command` writes now, and the bare path older
# versions wrote -- including a bare path with a space in it, which shlex
# cannot parse back because it was never a valid command in the first place.
def parse(cmd):
    for m in MARKERS:
        if cmd == m:
            return (m, "")
        if cmd.startswith(m + " "):
            return (m, cmd[len(m) + 1:].strip())
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return None
    if parts and parts[0] in MARKERS:
        return (parts[0], " ".join(parts[1:]))
    return None

settings = {}
if os.path.exists(path):
    with open(path) as f:
        settings = json.load(f)

changed = False
hooks = settings.setdefault("hooks", {})

def ensure(event, matcher, sub):
    global changed
    want = command(verify_cmd, sub)
    entries = hooks.setdefault(event, [])
    for e in entries:
        for h in e.get("hooks", []):
            if parse(h.get("command", "")) == (verify_cmd, sub):
                if h.get("command") != want:
                    h["command"] = want  # an older install's unquoted entry
                    changed = True
                return
    entry = {"hooks": [{"type": "command", "command": want}]}
    if matcher is not None:
        entry["matcher"] = matcher
    entries.append(entry)
    changed = True

ensure("PostToolUse", "Edit|Write|NotebookEdit", "edit")
ensure("PostToolUse", "Bash", "bash")
ensure("PostToolUse", "Skill", "skill")
ensure("PostToolUseFailure", "Bash", "bash-failure")
ensure("PreToolUse", "Bash", "bash-start")
ensure("UserPromptSubmit", None, "prompt")
ensure("UserPromptExpansion", None, "skill-prompt")
ensure("Stop", None, "stop")
ensure("SessionStart", None, "session")

sl = settings.get("statusLine")
want_sl = command(status_cmd)
if sl is None:
    settings["statusLine"] = {"type": "command", "command": want_sl}
    changed = True
    print("  ok  statusline wired")
elif isinstance(sl, dict) and parse(sl.get("command", "")) == (status_cmd, ""):
    if sl.get("command") != want_sl:
        sl["command"] = want_sl
        changed = True
        print("  ok  statusline rewritten so its path survives the shell")
    else:
        print("  ok  statusline already wired")
else:
    print("  !!  statusline SKIPPED — a custom statusLine exists; to use ours, set")
    print("      settings.json statusLine.command to: " + want_sl)

if changed:
    with open(path, "w") as f:
        # ensure_ascii=False: an escaped non-ASCII config path (é) would
        # never match --status's byte-level greps for the hook commands
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("  ok  hooks wired into settings.json")
else:
    print("  ok  hooks already wired")
PY
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
echo "The doctrine applies from the next Claude Code session."
