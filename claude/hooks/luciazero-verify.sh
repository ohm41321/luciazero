#!/usr/bin/env bash
# Enforcement-pack hook (Claude Code only; installed by `install.sh --with-hooks`).
# Tracks per-project whether edits have been followed by a verify run, and
# nudges ONCE at session stop when they have not — mechanizing doctrine rule 1
# ("done is proven by a command") at the exact moment it is most violated.
#
# Subcommands (wired in settings.json):
#   prompt  — UserPromptSubmit: start privacy-preserving turn telemetry
#   bash-start — PreToolUse on Bash: start shell-command timing
#   edit    — PostToolUse on Edit|Write|NotebookEdit : record "an edit happened"
#   bash    — PostToolUse on Bash: record duration, verify runs, and status
#   bash-failure — PostToolUseFailure on Bash: record failed commands
#   skill   — PostToolUse on Skill: count model-invoked skills
#   skill-prompt — UserPromptExpansion: count user-invoked slash skills
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
# privacy-preserving project hash, verify mode, and aggregate latency/counts;
# never the project path, command, or skill name. Uninstall keeps it.
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
# md5 here names a state directory; it is never a security decision. Saying so
# explicitly keeps the hook alive on a FIPS-enforcing python3, where a bare
# md5() call raises and the tracker would fail open (silently doing nothing).
KEY="$(printf '%s' "${CWD}" | python3 -c 'import sys,hashlib;print(hashlib.md5(sys.stdin.buffer.read(), usedforsecurity=False).hexdigest()[:12])' 2>/dev/null)" || exit 0
[ -n "${KEY}" ] || exit 0
BASE="${TMPDIR:-/tmp}/luciazero-verify-state-$(id -u 2>/dev/null || echo unknown)"
# The base name is predictable, so validate ownership/type before touching it.
# A hostile pre-created symlink or directory makes the hook fail open.
python3 - "${BASE}" <<'PY' 2>/dev/null || exit 0
import os, stat, sys
path = sys.argv[1]
try:
    info = os.lstat(path)
except FileNotFoundError:
    os.mkdir(path, 0o700)
    info = os.lstat(path)
if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
    raise SystemExit(1)
if hasattr(os, "getuid") and info.st_uid != os.getuid():
    raise SystemExit(1)
os.chmod(path, 0o700)
PY
STATE="${BASE}/${KEY}"
mkdir -p "${STATE}" 2>/dev/null || exit 0
chmod 700 "${STATE}" 2>/dev/null || exit 0
SESSION_RAW="$(pyfield "d.get('session_id')")"
[ -n "${SESSION_RAW}" ] || SESSION_RAW="parent-${PPID}"
SESSION_KEY="$(printf '%s' "${SESSION_RAW}" | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest()[:16])' 2>/dev/null)" || exit 0
TELEMETRY="${STATE}/telemetry/${SESSION_KEY}"

tool_key() { # stable opaque key; raw tool input never leaves temporary state
  RAW="$(pyfield "d.get('tool_use_id') or d.get('tool_input', {}).get('command') or d.get('tool_input', {}).get('skill') or d.get('command_name') or d.get('prompt') or d.get('command')")"
  [ -n "${RAW}" ] || RAW=unknown
  printf '%s' "${RAW}" | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest()[:16])' 2>/dev/null
}

now_ms() {
  python3 -c 'import time; print(int(time.time() * 1000))' 2>/dev/null
}

record_strict_telemetry() { # record_strict_telemetry <start-ms>
  STRICT_END_MS="$(now_ms || true)"
  case "${1:-}:${STRICT_END_MS}" in
    *[!0-9:]*|:|*:|*::* ) return ;;
  esac
  [ "${STRICT_END_MS}" -ge "$1" ] 2>/dev/null || return
  mkdir -p "${TELEMETRY}/bash_count" "${TELEMETRY}/bash_intervals" \
    "${TELEMETRY}/verify_count" 2>/dev/null || return
  : > "${TELEMETRY}/bash_count/strict-gate" 2>/dev/null || true
  : > "${TELEMETRY}/verify_count/strict-gate" 2>/dev/null || true
  printf '%s %s\n' "$1" "${STRICT_END_MS}" \
    > "${TELEMETRY}/bash_intervals/strict-gate" 2>/dev/null || true
}

stat_log() { # stat_log <event> — discipline stats; fail-open, capped
  SDIR="${CLAUDE_CONFIG_DIR:-${HOME:-}/.claude}"
  SFILE="${SDIR}/luciazero-stats.log"
  VMODE=regex
  [ -n "${VERIFY_CMD:-}" ] && VMODE=exact
  [ -n "${LUCIAZERO_STRICT_VERIFY_CMD:-}" ] && VMODE=strict
  python3 - "${SFILE}" "${CWD}" "$1" "${VMODE}" "${TELEMETRY}" <<'PY' 2>/dev/null || true
import datetime, hashlib, json, os, sys
path, cwd, event, mode, telemetry_dir = sys.argv[1:]
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
def read_int(path):
    try:
        value = int(open(path, encoding="utf-8").read().strip())
        return value if value >= 0 else None
    except (OSError, ValueError):
        return None
def count_files(name):
    try:
        return sum(os.path.isfile(os.path.join(telemetry_dir, name, item))
                   for item in os.listdir(os.path.join(telemetry_dir, name)))
    except OSError:
        return 0
start = read_int(os.path.join(telemetry_dir, "turn_start_ms"))
if start is not None:
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
    intervals = []
    try:
        interval_dir = os.path.join(telemetry_dir, "bash_intervals")
        for item in os.listdir(interval_dir):
            try:
                a, b = map(int, open(os.path.join(interval_dir, item), encoding="utf-8").read().split())
            except (OSError, ValueError):
                continue
            if 0 <= a <= b:
                intervals.append((max(start, a), min(now, b)))
    except OSError:
        pass
    merged = []
    for a, b in sorted((a, b) for a, b in intervals if a <= b):
        if not merged or a > merged[-1][1]:
            merged.append([a, b])
        else:
            merged[-1][1] = max(merged[-1][1], b)
    bash_ms = sum(b - a for a, b in merged)
    row["telemetry"] = {
        "turn_ms": max(0, now - start),
        "bash_ms": bash_ms,
        "bash_count": count_files("bash_count"),
        "verify_count": count_files("verify_count"),
        "skill_count": count_files("skill_count"),
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
VERIFY_RE_DEFAULT='verify|test\.sh|pytest|npm (run )?test|pnpm test|yarn test|cargo test|go test|vitest|jest|make (test|check)|tox|rake test|mix test|dotnet test|gradlew? (test|check)'
VERIFY_RE="${LUCIAZERO_VERIFY_REGEX:-${VERIFY_RE_DEFAULT}}"
VERIFY_CMD="${LUCIAZERO_VERIFY_CMD:-}"

# A repository's COMMITTED .claude/settings.json can put anything in its `env`
# block, and that env reaches this hook. Two knobs are dangerous from that
# scope: LUCIAZERO_VERIFY_REGEX can be widened until every command counts as a
# verify run (enforcement dies with the statusline still green), and
# LUCIAZERO_STRICT_VERIFY_CMD is a command this hook would then RUN at stop.
# Both are refused when the shared file declares them; the personal, gitignored
# .claude/settings.local.json is never inspected and keeps working, and a
# committed LUCIAZERO_VERIFY_CMD stays honored (documented team practice).
# Refusal falls back to the safe default (built-in regex / no strict gate),
# never to a block, and any parse error leaves the configured value untouched.
# Only the modes that consume these knobs pay for the lookup — prompt, edit,
# skill, and bash-start run on the hot path and must stay cheap.
REFUSED_ENV_KEYS=""
case "${MODE}" in
  bash|bash-failure|stop|session)
    REFUSED_ENV_KEYS="$(python3 - "${CWD}/.claude/settings.json" <<'PY' 2>/dev/null || true
import json, os, stat, sys
REFUSED = ("LUCIAZERO_VERIFY_REGEX", "LUCIAZERO_STRICT_VERIFY_CMD")
LIMIT = 1_000_000  # a settings file is kilobytes; this runs on every Bash call
path = sys.argv[1]
try:
    info = os.stat(path)
except OSError:
    raise SystemExit(0)
# never read a fifo or device the repository planted here: that would hang the
# hook instead of failing open
if not stat.S_ISREG(info.st_mode):
    raise SystemExit(0)
if info.st_size > LIMIT:
    # absurd for a settings file — refuse both knobs rather than parse it
    print("\n".join(REFUSED))
    raise SystemExit(0)
try:
    with open(path, encoding="utf-8") as handle:
        env = json.loads(handle.read(LIMIT)).get("env")
except Exception:
    raise SystemExit(0)
if isinstance(env, dict):
    for key in REFUSED:
        if key in env:
            print(key)
PY
)"
    ;;
esac
project_env_declares() { printf '%s\n' "${REFUSED_ENV_KEYS}" | grep -qx "$1"; }
if [ -n "${REFUSED_ENV_KEYS}" ]; then
  if project_env_declares LUCIAZERO_VERIFY_REGEX; then
    VERIFY_RE="${VERIFY_RE_DEFAULT}"
  fi
  if project_env_declares LUCIAZERO_STRICT_VERIFY_CMD; then
    LUCIAZERO_STRICT_VERIFY_CMD=""
  fi
fi

case "${MODE}" in
  prompt)
    # Per-turn scratch data is ephemeral. Persistent rows keep aggregates only.
    rm -rf "${TELEMETRY}" 2>/dev/null || exit 0
    mkdir -p "${TELEMETRY}" 2>/dev/null || exit 0
    now_ms > "${TELEMETRY}/turn_start_ms" 2>/dev/null || true
    ;;
  bash-start)
    TK="$(tool_key)" || exit 0
    mkdir -p "${TELEMETRY}/bash_start_ms" "${TELEMETRY}/bash_count" 2>/dev/null || exit 0
    now_ms > "${TELEMETRY}/bash_start_ms/${TK}" 2>/dev/null || true
    : > "${TELEMETRY}/bash_count/${TK}" 2>/dev/null || true
    ;;
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
  bash|bash-failure)
    TK="$(tool_key)" || TK=unknown
    mkdir -p "${TELEMETRY}/bash_count" "${TELEMETRY}/bash_intervals" 2>/dev/null || true
    : > "${TELEMETRY}/bash_count/${TK}" 2>/dev/null || true
    START_MS="$(cat "${TELEMETRY}/bash_start_ms/${TK}" 2>/dev/null || true)"
    END_MS="$(now_ms || true)"
    case "${START_MS}:${END_MS}" in
      *[!0-9:]*|:|*:|*::* ) : ;;
      *)
        if [ "${END_MS}" -ge "${START_MS}" ] 2>/dev/null; then
          printf '%s %s\n' "${START_MS}" "${END_MS}" > "${TELEMETRY}/bash_intervals/${TK}" 2>/dev/null || true
        fi
        ;;
    esac
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
      mkdir -p "${TELEMETRY}/verify_count" 2>/dev/null || true
      : > "${TELEMETRY}/verify_count/${TK}" 2>/dev/null || true
      # Best-effort red/green from the tool response; failure hooks are red.
      if [ "${MODE}" = bash-failure ]; then
        STATUS=fail
      else
        STATUS="$(pyfield "(lambda r, c=None: (lambda c: 'ok' if c == 0 else ('fail' if isinstance(c, int) else ('fail' if r.get('is_error') is True else 'ran')))(r.get('exit_code', r.get('exitCode'))))(d.get('tool_response') or {})")"
      fi
      printf '%s\n' "${STATUS:-ran}" > "${STATE}/last_verify"
      # Keep only an opaque digest for strict-gate equality; raw commands may
      # contain paths or secrets and must never persist in shared state.
      printf '%s' "${CMD}" | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())' \
        > "${STATE}/last_verify_cmd_hash" 2>/dev/null || true
      rm -f "${STATE}/nudged"
    fi
    ;;
  skill|skill-prompt)
    if [ "${MODE}" = skill-prompt ]; then
      EXPANSION_TYPE="$(pyfield "d.get('expansion_type')")"
      [ "${EXPANSION_TYPE}" = slash_command ] || exit 0
    fi
    TK="$(tool_key)" || TK=unknown
    mkdir -p "${TELEMETRY}/skill_count" 2>/dev/null || true
    : > "${TELEMETRY}/skill_count/${TK}" 2>/dev/null || true
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
      STRICT_START_MS="$(now_ms || true)"
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
# Fast path only for a green whose command digest exactly matches. A
# broad-regex green from a mere read of the test file must
# not disarm a gate whose promise is "actually runs the command".
vcmd = read("last_verify_cmd_hash")
cmd_hash = __import__("hashlib").sha256(cmd.encode()).hexdigest()
if (v is not None and read("last_verify") == "ok"
        and (e is None or e <= v)
        and vcmd == cmd_hash):
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
          record_strict_telemetry "${STRICT_START_MS}"
          printf 'ok\n' > "${STATE}/last_verify" 2>/dev/null || true
          printf '%s' "${STRICT_CMD}" | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())' \
            > "${STATE}/last_verify_cmd_hash" 2>/dev/null || true
          rm -f "${STATE}/nudged"
          stat_log stop-clean
          exit 0 ;;
        red)
          record_strict_telemetry "${STRICT_START_MS}"
          printf 'fail\n' > "${STATE}/last_verify" 2>/dev/null || true
          printf '%s' "${STRICT_CMD}" | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())' \
            > "${STATE}/last_verify_cmd_hash" 2>/dev/null || true
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
    # A committed settings env block that reconfigures this hook is worth one
    # loud line: the refusal above is silent, and a repository that ships these
    # keys is either mistaken or hostile. Names the keys, never their values.
    if [ -n "${REFUSED_ENV_KEYS}" ]; then
      echo "This repository's committed .claude/settings.json sets $(printf '%s' "${REFUSED_ENV_KEYS}" | tr '\n' ' ')— Luciazero refuses those keys from project scope (they can disable verify tracking or run a command at every stop). Review that env block before trusting this repo."
    fi
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
