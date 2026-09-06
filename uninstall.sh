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
MANAGED_DIR="${CLAUDE_DIR}/.luciazero-managed"

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

remove_managed_file() {
  RF_DST="$1"; RF_SNAPSHOT="$2"; RF_SHIPPED="$3"; RF_LABEL="$4"
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
if [ -f "${SETTINGS}" ] && grep -qF "${CLAUDE_DIR}/hooks/luciazero-" "${SETTINGS}"; then
  if command -v python3 >/dev/null 2>&1; then
    cp "${SETTINGS}" "$(bakpath "${SETTINGS}")"
    # exact-path matching only: never touch a user's own hook that merely
    # shares a basename with ours
    if python3 - "${SETTINGS}" "${CLAUDE_DIR}" 2>/dev/null <<'PY'
import json, os, sys

path, claude_dir = sys.argv[1], sys.argv[2]
with open(path) as f:
    settings = json.load(f)

MARKERS = (
    os.path.join(claude_dir, "hooks", "luciazero-verify.sh"),
    os.path.join(claude_dir, "hooks", "luciazero-statusline.sh"),
)
def ours(cmd):
    return any(cmd == m or cmd.startswith(m + " ") for m in MARKERS)

changed = False
hooks = settings.get("hooks") or {}
for event in list(hooks):
    kept = []
    for entry in hooks[event]:
        inner = [h for h in entry.get("hooks", []) if not ours(h.get("command", ""))]
        if inner != entry.get("hooks", []):
            changed = True
            if inner:
                entry = dict(entry)
                entry["hooks"] = inner
                kept.append(entry)
            # entry emptied by removal -> dropped
        else:
            kept.append(entry)
    if kept:
        hooks[event] = kept
    elif hooks[event] != kept:
        del hooks[event]
        changed = True

sl = settings.get("statusLine") or {}
if isinstance(sl, dict) and ours(sl.get("command", "")):
    del settings["statusLine"]
    changed = True

if changed:
    with open(path, "w") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")
PY
    then
      echo "  ok  removed hook entries from settings.json"
    else
      HOOKS_CLEAN=0
      echo "  !!  could not clean settings.json (invalid JSON?) — hook files kept so nothing dangles; remove the luciazero-* entries manually, then delete ${CLAUDE_DIR}/hooks/luciazero-*.sh" >&2
    fi
  else
    HOOKS_CLEAN=0
    echo "  !!  python3 not found — settings.json untouched; hook files kept so nothing dangles" >&2
  fi
else
  echo "  ok  no enforcement-pack entries in settings.json"
fi
if [ "${HOOKS_CLEAN}" = 1 ]; then
  for H in luciazero-verify.sh luciazero-statusline.sh; do
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
fi

if [ -f "${GLOBAL_MD}" ] && grep -qF "${IMPORT_LINE}" "${GLOBAL_MD}"; then
  BACKUP="$(bakpath "${GLOBAL_MD}")"
  cp "${GLOBAL_MD}" "${BACKUP}"
  # grep exits 1 when the import line was the only content — that is fine
  grep -vxF "${IMPORT_LINE}" "${GLOBAL_MD}" > "${GLOBAL_MD}.tmp" || [ $? -eq 1 ]
  mv "${GLOBAL_MD}.tmp" "${GLOBAL_MD}"
  [ -s "${GLOBAL_MD}" ] || rm -f "${GLOBAL_MD}"
  echo "  ok  removed import line (backup: $(basename "${BACKUP}"))"
else
  echo "  ok  no import line in CLAUDE.md"
fi

for KEEP in luciazero-stats.log luciazero-heuristics.md; do
  if [ -f "${CLAUDE_DIR}/${KEEP}" ]; then
    echo "  kept ${KEEP} (learned data) — delete manually if unwanted"
  fi
done
if [ -d "${CLAUDE_DIR}/.luciazero-backups" ]; then
  echo "  kept .luciazero-backups/ (pre-existing or customized components) — review and delete manually when no longer needed"
fi

echo
echo "Done. Other CLAUDE.md content was left untouched."
echo "The Agent Bus state directory (~/.luciazero/agent-bus) is data and was not touched."
