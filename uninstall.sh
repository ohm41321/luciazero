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

remove_managed_tree() {
  RT_DST="$1"; RT_SNAPSHOT="$2"; RT_SHIPPED="$3"; RT_LABEL="$4"
  if [ ! -e "${RT_DST}" ] && [ ! -L "${RT_DST}" ]; then
    echo "  ok  ${RT_LABEL} (already absent)"
  elif same_tree "${RT_DST}" "${RT_SNAPSHOT}" \
    || { [ ! -e "${RT_SNAPSHOT}" ] && same_tree "${RT_DST}" "${RT_SHIPPED}"; }; then
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

while IFS= read -r AGENT_NAME; do
  remove_managed_file "${CLAUDE_DIR}/agents/${AGENT_NAME}.md" \
    "${MANAGED_DIR}/agents/${AGENT_NAME}.md" \
    "${SRC}/claude/agents/${AGENT_NAME}.md" "agents/${AGENT_NAME}.md"
done < <(catalog "${SRC}/claude/agents/catalog.txt")

rmdir "${MANAGED_DIR}/skills" "${MANAGED_DIR}/agents" "${MANAGED_DIR}" 2>/dev/null || true

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
