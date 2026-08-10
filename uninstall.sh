#!/usr/bin/env bash
# Remove the Luciazero doctrine + bootstrap skill from ~/.claude/
set -euo pipefail

for ARG in "$@"; do
  echo "unknown option: ${ARG} (uninstall.sh takes no options)" >&2; exit 1
done

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
DOCTRINE="luciazero.md"
IMPORT_LINE="@${DOCTRINE}"
GLOBAL_MD="${CLAUDE_DIR}/CLAUDE.md"

# collision-proof backup path for $1 (two runs in the same second must not overwrite)
bakpath() {
  B="$1.bak.$(date +%Y%m%d%H%M%S)"
  N=1
  while [ -e "${B}" ]; do B="$1.bak.$(date +%Y%m%d%H%M%S).${N}"; N=$((N+1)); done
  printf '%s' "${B}"
}

echo "Removing from ${CLAUDE_DIR}"

rm -f "${CLAUDE_DIR}/${DOCTRINE}"
rm -f "${CLAUDE_DIR}/.luciazero-version"
echo "  ok  ${DOCTRINE}"

for SKILL in luciazero-bootstrap retro debug 'done' handoff experiment; do
  rm -rf "${CLAUDE_DIR}/skills/${SKILL}"
  echo "  ok  skills/${SKILL}"
done

rm -f "${CLAUDE_DIR}/agents/reviewer.md"
echo "  ok  agents/reviewer.md"

# enforcement pack, if it was installed with --with-hooks.
# Order matters: clean settings.json FIRST and delete the hook files only if
# that succeeded — otherwise Claude Code would keep executing references to
# files we just deleted.
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

echo
echo "Done. Other CLAUDE.md content was left untouched."
