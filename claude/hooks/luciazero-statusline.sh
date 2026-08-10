#!/usr/bin/env bash
# Enforcement-pack statusline (Claude Code only; installed by `install.sh
# --with-hooks`). Shows: model | git branch | verify status from the state
# that luciazero-verify.sh maintains — so the doctrine's ground truth is visible
# at a glance instead of remembered.
#
#   ✅ verify 3m     last verify-ish command succeeded, 3 minutes ago
#   ❌ verify RED    last verify-ish command failed
#   ✳ verify ran     a verify ran but its result was unreadable
#   ✎ unverified     edits happened after the last verify run
#   — no verify yet  nothing tracked this session
#
# Requires python3. Fails open to a minimal line.
set -u

IN="$(cat 2>/dev/null || true)"

LINE="$(printf '%s' "${IN}" | python3 -c '
import json, os, sys, time, hashlib

try:
    d = json.load(sys.stdin)
except Exception:
    d = {}

model = ((d.get("model") or {}).get("display_name")) or "claude"
cwd = ((d.get("workspace") or {}).get("current_dir")) or d.get("cwd") or os.getcwd()

key = hashlib.md5(cwd.encode()).hexdigest()[:12]
state = os.path.join(os.environ.get("TMPDIR", "/tmp"), "luciazero-verify-state", key)

def mtime(name):
    try:
        return os.path.getmtime(os.path.join(state, name))
    except OSError:
        return None

def age(ts):
    s = int(time.time() - ts)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h"

ve, ed = mtime("last_verify"), mtime("last_edit")
if ve is None and ed is None:
    verify = "— no verify yet"
elif ve is None or (ed is not None and ed > ve):
    verify = "✎ unverified"
else:
    try:
        status = open(os.path.join(state, "last_verify")).read().strip()
    except OSError:
        status = "ran"
    if status == "ok":
        verify = f"✅ verify {age(ve)}"
    elif status == "fail":
        verify = f"❌ verify RED {age(ve)}"
    else:
        verify = f"✳ verify ran {age(ve)}"

print(model + "\t" + cwd + "\t" + verify)' 2>/dev/null)" || LINE=""

if [ -z "${LINE}" ]; then
  echo "claude"
  exit 0
fi

MODEL="${LINE%%$'\t'*}"
REST="${LINE#*$'\t'}"
DIR="${REST%%$'\t'*}"
VERIFY="${REST#*$'\t'}"

BRANCH="$(git -C "${DIR}" branch --show-current 2>/dev/null || true)"
if [ -n "${BRANCH}" ]; then
  printf '%s | %s | %s\n' "${MODEL}" "${BRANCH}" "${VERIFY}"
else
  printf '%s | %s\n' "${MODEL}" "${VERIFY}"
fi
exit 0
