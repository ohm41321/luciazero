#!/usr/bin/env bash
# Install the Luciazero doctrine + skills into ~/.claude/
# Idempotent. Backs up CLAUDE.md (and settings.json when --with-hooks)
# before editing. Writes nothing outside ~/.claude/.
#
#   ./install.sh               doctrine + skills + reviewer agent
#   ./install.sh --with-hooks  also wire the enforcement pack: verify-tracking
#                              hooks + statusline into ~/.claude/settings.json
#                              (Claude Code only; requires python3)
#   ./install.sh --status      read-only health check of an existing install;
#                              exits non-zero if a core piece is missing
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

catalog() { sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "$1"; }
skill_inventory() {
  catalog "${SRC}/skills/catalog.txt"
  catalog "${SRC}/skills/aliases.txt"
}

# newest released version in this checkout's CHANGELOG (informational)
version_of() {
  grep -m1 -oE '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' "${SRC}/CHANGELOG.md" 2>/dev/null | tr -d '#[] ' || true
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
    WIRE_MISS=""
    for SUB in prompt skill-prompt bash-start edit bash bash-failure skill stop session; do
      grep -qF "${CLAUDE_DIR}/hooks/luciazero-verify.sh ${SUB}\"" "${CLAUDE_DIR}/settings.json" 2>/dev/null \
        || WIRE_MISS="${WIRE_MISS} ${SUB}"
    done
    if [ -z "${WIRE_MISS}" ]; then
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

# 2. canonical skills plus temporary compatibility aliases
while IFS= read -r SKILL; do
  install_tree "${SRC}/skills/${SKILL}" \
    "${CLAUDE_DIR}/skills/${SKILL}" \
    "${MANAGED_DIR}/skills/${SKILL}" \
    "skills/${SKILL}"
  echo "  ok  skills/${SKILL}"
done < <(skill_inventory)

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
if [ -f "${GLOBAL_MD}" ] && grep -qF "${IMPORT_LINE}" "${GLOBAL_MD}"; then
  echo "  ok  CLAUDE.md already imports ${DOCTRINE}"
else
  if [ -f "${GLOBAL_MD}" ]; then
    BACKUP="$(bakpath "${GLOBAL_MD}")"
    cp "${GLOBAL_MD}" "${BACKUP}"
    echo "  ok  backed up CLAUDE.md -> $(basename "${BACKUP}")"
    printf '\n%s\n' "${IMPORT_LINE}" >> "${GLOBAL_MD}"
  else
    printf '%s\n' "${IMPORT_LINE}" > "${GLOBAL_MD}"
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
import json, os, sys

path, hooks_dir = sys.argv[1], sys.argv[2]
verify_cmd = os.path.join(hooks_dir, "luciazero-verify.sh")
status_cmd = os.path.join(hooks_dir, "luciazero-statusline.sh")

settings = {}
if os.path.exists(path):
    with open(path) as f:
        settings = json.load(f)

changed = False
hooks = settings.setdefault("hooks", {})

def ensure(event, matcher, command):
    global changed
    entries = hooks.setdefault(event, [])
    for e in entries:
        for h in e.get("hooks", []):
            if h.get("command") == command:
                return
    entry = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        entry["matcher"] = matcher
    entries.append(entry)
    changed = True

ensure("PostToolUse", "Edit|Write|NotebookEdit", verify_cmd + " edit")
ensure("PostToolUse", "Bash", verify_cmd + " bash")
ensure("PostToolUse", "Skill", verify_cmd + " skill")
ensure("PostToolUseFailure", "Bash", verify_cmd + " bash-failure")
ensure("PreToolUse", "Bash", verify_cmd + " bash-start")
ensure("UserPromptSubmit", None, verify_cmd + " prompt")
ensure("UserPromptExpansion", None, verify_cmd + " skill-prompt")
ensure("Stop", None, verify_cmd + " stop")
ensure("SessionStart", None, verify_cmd + " session")

sl = settings.get("statusLine")
if sl is None:
    settings["statusLine"] = {"type": "command", "command": status_cmd}
    changed = True
    print("  ok  statusline wired")
elif sl.get("command") == status_cmd:
    print("  ok  statusline already wired")
else:
    print("  !!  statusline SKIPPED — a custom statusLine exists; to use ours, set")
    print("      settings.json statusLine.command to: " + status_cmd)

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
echo "Compatibility alias for one release: /luciazero-bootstrap -> /ready."
if [ "${WITH_HOOKS}" = 1 ]; then
  echo "Enforcement pack installed: verify-tracking hooks + statusline (see settings.json)."
else
  echo "Optional: ./install.sh --with-hooks adds the verify-nudge hooks + statusline."
fi
echo "The doctrine applies from the next Claude Code session."
