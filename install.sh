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
  for SKILL in luciazero-bootstrap retro debug 'done' handoff experiment; do
    check -f "${CLAUDE_DIR}/skills/${SKILL}/SKILL.md" "skill ${SKILL}"
  done
  check -x "${CLAUDE_DIR}/skills/luciazero-bootstrap/scripts/detect.sh" "detect.sh executable"
  check -x "${CLAUDE_DIR}/skills/done/scripts/revert-probe.sh" "revert-probe.sh executable"
  check -f "${CLAUDE_DIR}/agents/reviewer.md" "reviewer agent"
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
    for SUB in edit bash stop session; do
      grep -qF "${CLAUDE_DIR}/hooks/luciazero-verify.sh ${SUB}" "${CLAUDE_DIR}/settings.json" 2>/dev/null \
        || WIRE_MISS="${WIRE_MISS} ${SUB}"
    done
    if [ -z "${WIRE_MISS}" ]; then
      echo "  ok    hooks wired in settings.json (edit/bash/stop/session)"
    else
      echo "  MISS  settings.json missing hook entries:${WIRE_MISS} (re-run ./install.sh --with-hooks)"; STATUS_RC=1
    fi
    if command -v python3 >/dev/null 2>&1; then
      echo "  ok    python3 available (the hooks need it)"
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

echo "Installing into ${CLAUDE_DIR}"
mkdir -p "${CLAUDE_DIR}/skills"

# 1. doctrine
cp "${SRC}/claude/${DOCTRINE}" "${CLAUDE_DIR}/${DOCTRINE}"
echo "  ok  ${DOCTRINE}"

# 2. skills
for SKILL in luciazero-bootstrap retro debug 'done' handoff experiment; do
  rm -rf "${CLAUDE_DIR}/skills/${SKILL}"
  cp -r "${SRC}/skills/${SKILL}" "${CLAUDE_DIR}/skills/${SKILL}"
  echo "  ok  skills/${SKILL}"
done

# 3. reviewer agent (back up a pre-existing customized copy before overwriting)
mkdir -p "${CLAUDE_DIR}/agents"
AGENT="${CLAUDE_DIR}/agents/reviewer.md"
if [ -f "${AGENT}" ] && ! cmp -s "${SRC}/claude/agents/reviewer.md" "${AGENT}"; then
  cp "${AGENT}" "$(bakpath "${AGENT}")"
  echo "  ok  backed up existing agents/reviewer.md"
fi
cp "${SRC}/claude/agents/reviewer.md" "${AGENT}"
echo "  ok  agents/reviewer.md"

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
echo "Skills: /luciazero-bootstrap, /debug, /done, /handoff, /experiment, /retro. Reviewer agent: 'reviewer'."
if [ "${WITH_HOOKS}" = 1 ]; then
  echo "Enforcement pack installed: verify-tracking hooks + statusline (see settings.json)."
else
  echo "Optional: ./install.sh --with-hooks adds the verify-nudge hooks + statusline."
fi
echo "The doctrine applies from the next Claude Code session."
