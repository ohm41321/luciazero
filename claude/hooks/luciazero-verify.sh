#!/usr/bin/env bash
# Enforcement-pack hook (Claude Code only; installed by `install.sh --with-hooks`).
# Tracks per-project whether edits have been followed by a verify run, and
# nudges ONCE at session stop when they have not — mechanizing doctrine rule 1
# ("done is proven by a command") at the exact moment it is most violated.
#
# Subcommands (wired in settings.json):
#   edit    — PostToolUse on Edit|Write|NotebookEdit : record "an edit happened"
#   bash    — PostToolUse on Bash                    : record verify runs + status
#   stop    — Stop                                   : warn once if edits are unverified
#   session — SessionStart                           : point at an existing Lucia Relay
#   doctrine— SessionStart (plugin installs only)    : emit the doctrine as context
#             (plugins cannot add a CLAUDE.md import line; this is the same
#             word-ceiling-capped text the classic install imports. Silent when
#             a classic install exists, so the doctrine never loads twice.)
#
# Optional strict gate: when LUCIAZERO_STRICT_VERIFY_CMD is set, `stop`
# actually RUNS that command and refuses the stop (exit 2) while it is red.
# Set it in your PERSONAL settings (settings.local.json env block, or your
# shell). LIMITATION: this hook cannot tell which settings scope set the
# variable — a committed .claude/settings.json env block reaches it too — so
# never commit it, and treat a repo that ships this variable as hostile.
# A blocked stop's continuation is never re-blocked (stop_hook_active),
# so this is a speed bump with evidence attached, not a wall.
#
# Requires python3 (for JSON parsing). FAILS OPEN: any internal error exits 0,
# so a broken hook can never block real work. Per-project state lives under
# $TMPDIR and never touches the repo. One exception, documented honestly: the
# stop hook appends one schema-versioned JSON line per stop outcome
# (stop-clean / nudge / strict-block) to luciazero-stats.log in the harness
# config dir — local only, capped at ~250 lines, fail-open. It records a
# privacy-preserving project hash and verify mode, never the project path or
# command. Uninstall keeps it (it is learned data).
set -u

MODE="${1:-}"

# doctrine mode needs no python3, no state, and no stdin — handled before the
# shared setup so a machine without python3 still gets the doctrine (everything
# below fails open to doing nothing there). ${HOME:-} keeps set -u fail-open
# on hosts with no HOME at all.
if [ "${MODE}" = "doctrine" ]; then
  # a classic install's CLAUDE.md import already loads this text — never twice
  [ -f "${CLAUDE_CONFIG_DIR:-${HOME:-}/.claude}/luciazero.md" ] && exit 0
  DOCTRINE="$(cd "$(dirname "$0")" 2>/dev/null && cd .. && pwd)/luciazero.md"
  [ -f "${DOCTRINE}" ] || exit 0
  cat "${DOCTRINE}" 2>/dev/null || true
  exit 0
fi

# Plugin-channel dedupe (the plugin's hooks.json invokes every mode with
# LUCIAZERO_CHANNEL=plugin): when `install.sh --with-hooks` wiring is ALSO
# present, the classic copy wins and the plugin copy stands down — otherwise
# the stop nudge double-fires and a strict verify runs twice concurrently.
if [ "${LUCIAZERO_CHANNEL:-}" = "plugin" ]; then
  CFG="${CLAUDE_CONFIG_DIR:-${HOME:-}/.claude}"
  if [ -x "${CFG}/hooks/luciazero-verify.sh" ] \
     && grep -qF "${CFG}/hooks/luciazero-verify.sh" "${CFG}/settings.json" 2>/dev/null; then
    exit 0
  fi
fi

# Hook stdin is always a pipe; when run by hand from a terminal for debugging,
# do not hang waiting for EOF that never comes.
if [ -t 0 ]; then IN=""; else IN="$(cat 2>/dev/null || true)"; fi

pyfield() { # pyfield '<python expr over dict d>' — empty string on any error
  printf '%s' "${IN}" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    v = ${1}
    print('' if v is None else v)
except Exception:
    print('')" 2>/dev/null || true
}

CWD="$(pyfield "d.get('cwd')")"
[ -n "${CWD}" ] || CWD="${PWD}"
KEY="$(printf '%s' "${CWD}" | python3 -c 'import sys,hashlib;print(hashlib.md5(sys.stdin.buffer.read()).hexdigest()[:12])' 2>/dev/null)" || exit 0
[ -n "${KEY}" ] || exit 0
STATE="${TMPDIR:-/tmp}/luciazero-verify-state/${KEY}"
mkdir -p "${STATE}" 2>/dev/null || exit 0

stat_log() { # stat_log <event> — discipline stats; fail-open, capped
  SDIR="${CLAUDE_CONFIG_DIR:-${HOME:-}/.claude}"
  SFILE="${SDIR}/luciazero-stats.log"
  VMODE=regex
  [ -n "${VERIFY_CMD:-}" ] && VMODE=exact
  [ -n "${LUCIAZERO_STRICT_VERIFY_CMD:-}" ] && VMODE=strict
  python3 - "${SFILE}" "${CWD}" "$1" "${VMODE}" <<'PY' 2>/dev/null || true
import datetime, hashlib, json, os, sys
path, cwd, event, mode = sys.argv[1:]
os.makedirs(os.path.dirname(path), exist_ok=True)
real = os.path.realpath(cwd)
row = {
    "schema": 2,
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "event": event,
    "project_id": hashlib.sha256(real.encode()).hexdigest()[:12],
    "project": os.path.basename(real) or "(root)",
    "verify_mode": mode,
}
with open(path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
with open(path, encoding="utf-8", errors="replace") as handle:
    lines = handle.readlines()
if len(lines) > 500:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.writelines(lines[-250:])
    os.replace(tmp, path)
PY
}

# What counts as a verify run. Deliberately broad; override per-shell with
# LUCIAZERO_VERIFY_REGEX (extended regex, matched against the Bash tool command).
# When LUCIAZERO_VERIFY_CMD is set (the repo's exact verify command, e.g.
# "./test.sh"), only commands that ARE it or START with it count — the broad
# regex also marks `cat test.sh` or `grep pytest README` as a verify run,
# flipping the state green without any test having run.
VERIFY_RE="${LUCIAZERO_VERIFY_REGEX:-verify|test\.sh|pytest|npm (run )?test|pnpm test|yarn test|cargo test|go test|vitest|jest|make (test|check)|tox|rake test|mix test|dotnet test|gradlew? (test|check)}"
VERIFY_CMD="${LUCIAZERO_VERIFY_CMD:-}"

case "${MODE}" in
  edit)
    # Documentation writes do not re-arm the nudge: the closeout skills
    # Closeout skills write docs AFTER the final green verify. Relay's JSON is
    # also a transient knowledge artifact, not implementation code.
    FP="$(pyfield "d.get('tool_input', {}).get('file_path')")"
    DOC_RE="${LUCIAZERO_DOC_REGEX:-\.(md|markdown|rst|txt)\$}"
    case "${FP}" in
      */LUCIA_RELAY.json|*/LUCIA_RELAY.md) : ;;
      *)
        if [ -n "${FP}" ] && printf '%s' "${FP}" | grep -qE "${DOC_RE}"; then
          :  # doc-only write; verify state unchanged
        else
          touch "${STATE}/last_edit"
          rm -f "${STATE}/nudged"    # new code edits re-arm the one-shot nudge
        fi
        ;;
    esac
    ;;
  bash)
    CMD="$(pyfield "d.get('tool_input', {}).get('command')")"
    IS_VERIFY=no
    if [ -n "${CMD}" ]; then
      if [ -n "${VERIFY_CMD}" ]; then
        # exact mode: the command must BE or START WITH the configured command
        case "${CMD}" in
          "${VERIFY_CMD}"|"${VERIFY_CMD} "*) IS_VERIFY=yes ;;
        esac
      elif printf '%s' "${CMD}" | grep -qE "${VERIFY_RE}"; then
        IS_VERIFY=yes
      fi
    fi
    if [ "${IS_VERIFY}" = yes ]; then
      # Best-effort red/green from the tool response; unknown shape -> "ran"
      STATUS="$(pyfield "(lambda r, c=None: (lambda c: 'ok' if c == 0 else ('fail' if isinstance(c, int) else ('fail' if r.get('is_error') is True else 'ran')))(r.get('exit_code', r.get('exitCode'))))(d.get('tool_response') or {})")"
      printf '%s\n' "${STATUS:-ran}" > "${STATE}/last_verify"
      # remember WHICH command produced the state — the strict gate's fast
      # path trusts a green only when this matches its own command
      printf '%s\n' "${CMD}" > "${STATE}/last_verify_cmd" 2>/dev/null || true
      rm -f "${STATE}/nudged"
    fi
    ;;
  stop)
    # Never re-block a continuation that a stop hook itself caused
    ACTIVE="$(pyfield "d.get('stop_hook_active')")"
    if [ "${ACTIVE}" = "True" ] || [ "${ACTIVE}" = "true" ]; then exit 0; fi
    # Strict gate (opt-in, see header): actually run the user's verify command
    # unless the tracked state is already green-after-last-edit. Any internal
    # error — timeout, missing command, unparseable state — degrades to the
    # ordinary fail-open nudge below, never to a block.
    STRICT_CMD="${LUCIAZERO_STRICT_VERIFY_CMD:-}"
    # Strict gate only on well-formed input: unparseable stdin means we know
    # neither cwd nor stop_hook_active — running a command on guesses would
    # break both the fail-open and the never-re-block guarantees.
    JSON_OK="$(printf '%s' "${IN}" | python3 -c 'import json,sys; json.load(sys.stdin); print("yes")' 2>/dev/null || echo no)"
    if [ -n "${STRICT_CMD}" ] && [ "${JSON_OK}" = yes ]; then
      OUT="$(python3 -c '
import os, subprocess, sys
state, cwd, cmd, timeout = sys.argv[1:5]
def m(name):
    try:
        return os.path.getmtime(os.path.join(state, name))
    except OSError:
        return None
def read(name):
    try:
        return open(os.path.join(state, name)).read().strip()
    except OSError:
        return ""
e, v = m("last_edit"), m("last_verify")
# Fast path only for a green that THIS command (or a longer invocation of
# it) produced — a broad-regex green from a mere read of the test file must
# not disarm a gate whose promise is "actually runs the command".
vcmd = read("last_verify_cmd")
if (v is not None and read("last_verify") == "ok"
        and (e is None or e <= v)
        and (vcmd == cmd or vcmd.startswith(cmd + " "))):
    print("green"); sys.exit(0)
try:
    r = subprocess.run(cmd, shell=True, cwd=cwd or None, timeout=float(timeout),
                       capture_output=True, text=True)
except Exception:
    print("error"); sys.exit(0)
if r.returncode in (126, 127):
    # command not found / not executable: an internal error, not a red verify
    print("error"); sys.exit(0)
if r.returncode == 0:
    print("ok")
else:
    tail = ((r.stdout or "") + "\n" + (r.stderr or "")).strip().splitlines()[-8:]
    print("red")
    print("\n".join(tail))
' "${STATE}" "${CWD}" "${STRICT_CMD}" "${LUCIAZERO_STRICT_TIMEOUT:-120}" 2>/dev/null || echo error)"
      case "${OUT%%$'\n'*}" in
        green) stat_log stop-clean; exit 0 ;;
        ok)
          printf 'ok\n' > "${STATE}/last_verify" 2>/dev/null || true
          printf '%s\n' "${STRICT_CMD}" > "${STATE}/last_verify_cmd" 2>/dev/null || true
          rm -f "${STATE}/nudged"
          stat_log stop-clean
          exit 0 ;;
        red)
          printf 'fail\n' > "${STATE}/last_verify" 2>/dev/null || true
          printf '%s\n' "${STRICT_CMD}" > "${STATE}/last_verify_cmd" 2>/dev/null || true
          stat_log strict-block
          echo "Strict verify gate: '${STRICT_CMD}' is RED. Fix it before finishing — or say plainly that you are handing back a red state. Failing output:" >&2
          echo "${OUT#red}" >&2
          exit 2 ;;
        *) : ;;  # error — fall through to the ordinary fail-open nudge
      esac
    fi
    # Sub-second mtime comparison via python: bash 3.2's [ -nt ] compares
    # whole seconds only, silently missing an edit made in the same second
    # as the last verify (the statusline already compares float mtimes).
    NUDGE="$(python3 -c '
import os, sys
state = sys.argv[1]
def m(name):
    try:
        return os.path.getmtime(os.path.join(state, name))
    except OSError:
        return None
e, v = m("last_edit"), m("last_verify")
print("yes" if e is not None and (v is None or e > v) else "no")' "${STATE}" 2>/dev/null || echo no)"
    if [ "${NUDGE}" = yes ] && [ ! -f "${STATE}/nudged" ]; then
      touch "${STATE}/nudged"
      stat_log nudge
      echo "Doctrine rule 1: edits were made but no verify command has run since the last edit. Run the repo's verify command and quote its decisive line — or finish anyway and say plainly that the change is unverified. (This nudge fires once.)" >&2
      exit 2
    fi
    # NUDGE=no -> genuinely clean stop; yes-but-already-nudged logs nothing
    # (that nudge was counted when it fired)
    [ "${NUDGE}" = no ] && stat_log stop-clean
    ;;
  session)
    # SessionStart emits ONE pointer, never the relay contents. A legacy
    # HANDOFF.md gets a migration warning but is not silently rewritten.
    CAP="${CWD}/LUCIA_RELAY.json"
    if [ ! -f "${CAP}" ]; then
      if [ -f "${CWD}/HANDOFF.md" ]; then
        echo "Legacy HANDOFF.md exists — read and re-verify it, then migrate the still-relevant state with /lucia-relay or delete the stale capsule."
      fi
      exit 0
    fi
    AGE="$(python3 -c 'import os,sys,time;print(int((time.time()-os.path.getmtime(sys.argv[1]))//86400))' "${CAP}" 2>/dev/null || echo '')"
    STALE="${LUCIAZERO_RELAY_STALE_DAYS:-${LUCIAZERO_HANDOFF_STALE_DAYS:-7}}"
    if [ -n "${AGE}" ] && [ "${AGE}" -ge "${STALE}" ] 2>/dev/null; then
      echo "LUCIA_RELAY.json exists but is ${AGE} days old — likely stale. Run /lucia-relay inspect, verify its claims with extra suspicion, then consume or replace it."
    else
      echo "LUCIA_RELAY.json exists (age: ${AGE:-?}d) — run /lucia-relay inspect before touching code, re-verify its evidence, then consume it."
    fi
    ;;
  *)
    ;;
esac

exit 0
