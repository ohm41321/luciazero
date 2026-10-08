#!/usr/bin/env bash
# Enforcement-pack hook (Claude Code only; installed by `install.sh --with-hooks`).
# Tracks per-project whether edits have been followed by a verify run, and
# nudges ONCE at session stop when they have not — mechanizing doctrine rule 1
# ("done is proven by a command") at the exact moment it is most violated.
#
# Subcommands (wired in settings.json):
#   prompt  — UserPromptSubmit: start privacy-preserving turn telemetry (a
#             prompt inside an open turn is a background-task notice: kept)
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
# Requires python3 (one run per event: JSON fields, hashes, the settings scan).
# FAILS OPEN: any internal error exits 0,
# so a broken hook can never block real work. Per-project state lives under
# $TMPDIR and never touches the repo. One exception, documented honestly: the
# stop hook appends one schema-versioned JSON line per stop outcome
# (stop-clean / nudge / strict-block) to luciazero-stats.log in the harness
# config dir — local only, capped at ~250 lines, fail-open. It records a
# privacy-preserving project hash, verify mode, and aggregate latency/counts —
# including how long verify commands ran and how many came back green with no
# edit since the previous green (schema 3) — never the project path, command,
# or skill name. Uninstall keeps it.
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

hook_path() { # canonical path of $1; empty when its directory does not exist
  HP_DIR="$(cd "$(dirname "$1")" 2>/dev/null && pwd -P)" || return 0
  [ -n "${HP_DIR}" ] || return 0
  printf '%s/%s' "${HP_DIR}" "$(basename "$1")"
}

# Hook stdin is always a pipe; when run by hand from a terminal for debugging,
# do not hang waiting for EOF that never comes.
if [ -t 0 ]; then IN=""; else IN="$(cat 2>/dev/null || true)"; fi

# A repository's COMMITTED .claude/settings.json can put anything in its `env`
# block, and that env reaches this hook — so NO LUCIAZERO_* knob is accepted
# from that scope. Each one is a way to disable enforcement while the
# statusline stays green: a widened LUCIAZERO_VERIFY_REGEX (or a
# LUCIAZERO_VERIFY_CMD pointing at `echo`) makes any command count as a verify
# run, LUCIAZERO_DOC_REGEX='.*' makes every edit look like documentation so
# nothing is ever unverified, and LUCIAZERO_STRICT_VERIFY_CMD is a command this
# hook would RUN at stop. CLAUDE_CONFIG_DIR is refused from that scope too: it
# moves the config directory the dedupe below trusts.
#
# PROJECT scope only. The walk covers the session directory and its ancestors —
# Claude Code merges project settings from the repository root and a session's
# cwd is often a subdirectory — but it stops at the repository root, at
# CLAUDE_PROJECT_DIR, and at $HOME, and it never reads the user's own config
# directory. Personal settings (global `~/.claude/settings.json`, gitignored
# `.claude/settings.local.json`) are the user's scope and keep working.
#
# Refusal only ever falls back to this file's own defaults, never to a block,
# and a parse error leaves the configured values untouched. Only the modes that
# consume a knob pay for the lookup.
#
# The scan runs inside the ONE python3 program this hook starts per event.
# Every field derived from stdin — cwd, the state key, session and tool keys,
# the command and its digest, the tool status, the relay age — comes out of
# this program as one value per line in a fixed order, the (possibly
# multi-line) Bash command last. A python3 start costs ~40 ms; one field per
# process spent 5–9 of them on every tool call. Any error leaves a field
# empty, and an empty state key fails the hook open below.
# The program lives in a variable, not a here-document inside $( ): bash 3.2
# (still the /bin/bash on macOS) cannot parse that combination and fails the
# whole file at load time.
PRELUDE_PY='import hashlib, json, os, stat, sys, time
ppid, mode = sys.argv[1], sys.argv[2]
LIMIT = 1000000    # a settings file is kilobytes; this runs on every tool call
MAX_DEPTH = 40     # ancestor walk is bounded, never unbounded I/O

def refused(key):
    return isinstance(key, str) and (key.startswith("LUCIAZERO_")
                                     or key == "CLAUDE_CONFIG_DIR")

def keys_in(path):
    try:
        info = os.stat(path)
    except OSError:
        return ()
    # never read a fifo or device planted here: that would hang the hook
    # instead of failing open
    if not stat.S_ISREG(info.st_mode):
        return ()
    if info.st_size > LIMIT:
        # absurd for a settings file: refuse everything rather than parse it
        return ("LUCIAZERO_*",)
    try:
        with open(path, encoding="utf-8") as handle:
            env = json.loads(handle.read(LIMIT)).get("env")
    except Exception:
        return ()
    if not isinstance(env, dict):
        return ()
    return tuple(k for k in env if refused(k))

def real(path):
    try:
        return os.path.realpath(path)
    except OSError:
        return path

def refused_keys(start):
    home = real(os.path.expanduser("~"))
    # Only the DEFAULT config directory counts as user scope. CLAUDE_CONFIG_DIR
    # is attacker-reachable: pointed at the project itself, it would mark the
    # repository settings file as user scope and skip the very file that
    # declares it, and the dedupe below would then trust a classic install
    # inside the repo.
    user_config = real(os.path.join(home, ".claude"))
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    project_dir = real(project_dir) if project_dir else None
    found, seen = [], set()
    directory = real(start or ".")
    for _ in range(MAX_DEPTH):
        claude_dir = os.path.join(directory, ".claude")
        if directory != home and real(claude_dir) != user_config:
            for key in keys_in(os.path.join(claude_dir, "settings.json")):
                if key not in seen:
                    seen.add(key)
                    found.append(key)
        if directory == home:
            break
        if os.path.exists(os.path.join(directory, ".git")):
            break  # repository root: project scope ends here
        if project_dir is not None and directory == project_dir:
            break
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    return found

json_ok = "no"
try:
    d = json.load(sys.stdin)
    json_ok = "yes"
except Exception:
    d = None

def field(*path):
    # the value at d[path...] as text; empty on any missing or mis-shaped level
    v = d
    try:
        for p in path:
            v = v.get(p)
        return "" if v is None else str(v).rstrip("\n")
    except Exception:
        return ""

def digest(v, size):
    return hashlib.sha256(v.encode("utf-8", "replace")).hexdigest()[:size]

cwd = field("cwd") or os.environ.get("PWD") or os.getcwd()
# md5 here names a state directory; it is never a security decision. Saying so
# explicitly keeps the hook alive on a FIPS-enforcing python3, where a bare
# md5() call raises and the tracker would fail open (silently doing nothing).
key = hashlib.md5(cwd.encode("utf-8", "replace"), usedforsecurity=False).hexdigest()[:12]
session = field("session_id") or "parent-" + ppid
# stable opaque tool key; raw tool input never leaves temporary state
raw = (field("tool_use_id") or field("tool_input", "command") or field("tool_input", "skill")
       or field("command_name") or field("prompt") or field("command") or "unknown")
cmd = field("tool_input", "command")
# best-effort red/green from the tool response. The Bash response of Claude
# Code carries no exit code (stdout, stderr, interrupted, isImage): PostToolUse
# only fires for a command that finished with exit 0, a non-zero exit reaches
# PostToolUseFailure (mode bash-failure) instead, so a completed, uninterrupted
# response in mode bash is a green. An explicit exit code still wins.
try:
    r = d.get("tool_response") or {}
    c = r.get("exit_code", r.get("exitCode"))
    if isinstance(c, int) and not isinstance(c, bool):
        status = "ok" if c == 0 else "fail"
    elif r.get("is_error") is True:
        status = "fail"
    elif r.get("interrupted") is True:
        status = "ran"
    else:
        status = "ok" if mode == "bash" else "ran"
except Exception:
    status = ""
refused = refused_keys(cwd) if mode in ("edit", "bash", "bash-failure", "stop", "session") else []
age = ""
if mode == "session":
    try:
        age = str(int((time.time() - os.path.getmtime(os.path.join(cwd, "LUCIA_RELAY.json"))) // 86400))
    except OSError:
        pass
tool_input = d.get("tool_input")
fp_state = ("missing" if not isinstance(tool_input, dict) or "file_path" not in tool_input
            else "empty" if tool_input["file_path"] in ("", None) else "present")
lines = [cwd, key, digest(session, 16), digest(raw, 16), str(int(time.time() * 1000)),
         " ".join(refused), field("tool_input", "file_path"), field("expansion_type"),
         field("stop_hook_active"), status, json_ok, digest(cmd, 64) if cmd else "", age,
         field("source"), field("tool_name"), fp_state]
sys.stdout.write("\n".join(v.replace("\n", " ") for v in lines) + "\n" + cmd)
'
PRE="$(printf '%s' "${IN}" | python3 -c "${PRELUDE_PY}" "${PPID}" "${MODE}" 2>/dev/null || true)"
{
  IFS= read -r CWD
  IFS= read -r KEY
  IFS= read -r SESSION_KEY
  IFS= read -r TK
  IFS= read -r NOW_MS
  IFS= read -r REFUSED_ENV_KEYS
  IFS= read -r FP
  IFS= read -r EXPANSION_TYPE
  IFS= read -r ACTIVE
  IFS= read -r STATUS
  IFS= read -r JSON_OK
  IFS= read -r CMD_HASH
  IFS= read -r RELAY_AGE
  IFS= read -r SESSION_SOURCE
  IFS= read -r TOOL_NAME
  IFS= read -r FP_STATE
  CMD="$(cat)"
} <<EOF
${PRE}
EOF
[ -n "${CWD}" ] || CWD="${PWD}"
if [ -n "${REFUSED_ENV_KEYS}" ]; then
  # `LUCIAZERO_*` is the oversized-file marker: drop every knob this hook reads
  case "${REFUSED_ENV_KEYS}" in
    *'LUCIAZERO_*'*)
      REFUSED_ENV_KEYS='LUCIAZERO_VERIFY_CMD LUCIAZERO_VERIFY_REGEX LUCIAZERO_DOC_REGEX LUCIAZERO_STRICT_VERIFY_CMD LUCIAZERO_STRICT_TIMEOUT LUCIAZERO_RELAY_STALE_DAYS LUCIAZERO_HANDOFF_STALE_DAYS LUCIAZERO_EDIT_DIAG CLAUDE_CONFIG_DIR' ;;
  esac
  # names are [A-Z_]* only, so splitting the line on spaces is exact; globbing
  # is off for the loop so a key that carries a wildcard never names a file
  set -f
  for RK in ${REFUSED_ENV_KEYS}; do
    case "${RK}" in
      LUCIAZERO_[A-Z_]*|CLAUDE_CONFIG_DIR) unset "${RK}" 2>/dev/null || true ;;
    esac
  done
  set +f
fi

# Channel dedupe: when `install.sh --with-hooks` wiring is ALSO present, the
# classic copy wins and every other copy (the plugin's) stands down — otherwise
# the stop nudge double-fires and a strict verify runs twice concurrently.
#
# Decided from this script's own path, never from LUCIAZERO_CHANNEL: an
# env-driven dedupe let a repository hand the CLASSIC hook a plugin label so it
# stood itself down. It runs after the refusal above for the same reason — a
# committed CLAUDE_CONFIG_DIR could otherwise point at a repository-controlled
# directory holding a "wired classic install", and every copy would stand down.
CFG="${CLAUDE_CONFIG_DIR:-${HOME:-}/.claude}"
CLASSIC_HOOK="$(hook_path "${CFG}/hooks/luciazero-verify.sh")"
SELF_HOOK="$(hook_path "$0")"
if [ -n "${CLASSIC_HOOK}" ] && [ "${SELF_HOOK}" != "${CLASSIC_HOOK}" ] \
   && [ -x "${CLASSIC_HOOK}" ] \
   && grep -qF "${CFG}/hooks/luciazero-verify.sh" "${CFG}/settings.json" 2>/dev/null; then
  exit 0
fi

# The state key is the prelude's md5 of cwd; empty means python3 failed.
[ -n "${KEY}" ] || exit 0
BASE="${TMPDIR:-/tmp}/luciazero-verify-state-$(id -u 2>/dev/null || echo unknown)"
# The base name is predictable, so validate ownership/type before touching it.
# A hostile pre-created symlink or directory makes the hook fail open.
if [ -e "${BASE}" ] || [ -L "${BASE}" ]; then
  [ -d "${BASE}" ] && [ ! -L "${BASE}" ] && [ -O "${BASE}" ] || exit 0
else
  (umask 077 && mkdir "${BASE}") 2>/dev/null || exit 0
fi
chmod 700 "${BASE}" 2>/dev/null || exit 0
STATE="${BASE}/${KEY}"
mkdir -p "${STATE}" 2>/dev/null || exit 0
chmod 700 "${STATE}" 2>/dev/null || exit 0
TELEMETRY="${STATE}/telemetry/${SESSION_KEY}"

# A turn is open from its first prompt until a stop lets it end. The harness
# delivers a background task's completion (a forked skill, a subagent, a
# run_in_background command) as one more UserPromptSubmit, and before this
# marker every one of those wiped the turn's counters: a turn that waited on
# a background job reported a few seconds and one Bash call. A stop that
# blocks (nudge, strict red) keeps the turn open, because the model continues
# it; every stop that lets the turn end closes it. Fail-open, like all state.
end_turn() { rm -f "${TELEMETRY}/turn_open" 2>/dev/null || true; }

now_ms() { # strict gate only; every other mode uses the prelude's NOW_MS
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
    "schema": 3,
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
def merged_ms(intervals):
    merged = []
    for a, b in sorted((a, b) for a, b in intervals if a <= b):
        if not merged or a > merged[-1][1]:
            merged.append([a, b])
        else:
            merged[-1][1] = max(merged[-1][1], b)
    return sum(b - a for a, b in merged)
start = read_int(os.path.join(telemetry_dir, "turn_start_ms"))
if start is not None:
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
    intervals, verify_intervals = [], []
    verify_dir = os.path.join(telemetry_dir, "verify_count")
    try:
        interval_dir = os.path.join(telemetry_dir, "bash_intervals")
        for item in os.listdir(interval_dir):
            try:
                a, b = map(int, open(os.path.join(interval_dir, item), encoding="utf-8").read().split())
            except (OSError, ValueError):
                continue
            if 0 <= a <= b:
                intervals.append((max(start, a), min(now, b)))
                # the interval's tool key is the verify marker's name: same
                # opaque digest, so no command is read to tell the two apart
                if os.path.isfile(os.path.join(verify_dir, item)):
                    verify_intervals.append(intervals[-1])
    except OSError:
        pass
    row["telemetry"] = {
        "turn_ms": max(0, now - start),
        "bash_ms": merged_ms(intervals),
        "bash_count": count_files("bash_count"),
        "verify_count": count_files("verify_count"),
        "skill_count": count_files("skill_count"),
        "verify_ms": merged_ms(verify_intervals),
        "redundant_green_count": count_files("redundant_green"),
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
# flipping the state green without any test having run. The default also
# knows `python -m unittest` and this repository's timing collector,
# scripts/test-timings.sh, which runs a tier -- except with --report, which
# only reads the samples kept so far; that case is carved out of the default
# below and is no concern of a regex somebody set themselves.
VERIFY_RE="${LUCIAZERO_VERIFY_REGEX:-verify|test\.sh|python[0-9.]* -m unittest|test-timings\.sh|pytest|npm (run )?test|pnpm test|yarn test|cargo test|go test|vitest|jest|make (test|check)|tox|rake test|mix test|dotnet test|gradlew? (test|check)}"
VERIFY_CMD="${LUCIAZERO_VERIFY_CMD:-}"

case "${MODE}" in
  prompt)
    # Per-turn scratch data is ephemeral. Persistent rows keep aggregates only.
    # Inside an open turn this prompt is a notification, not a new turn: the
    # counters and turn_start_ms stay exactly as they are.
    [ -f "${TELEMETRY}/turn_open" ] && exit 0
    rm -rf "${TELEMETRY}" 2>/dev/null || exit 0
    mkdir -p "${TELEMETRY}" 2>/dev/null || exit 0
    printf '%s\n' "${NOW_MS}" > "${TELEMETRY}/turn_start_ms" 2>/dev/null || true
    : > "${TELEMETRY}/turn_open" 2>/dev/null || true
    ;;
  bash-start)
    mkdir -p "${TELEMETRY}/bash_start_ms" "${TELEMETRY}/bash_count" 2>/dev/null || exit 0
    printf '%s\n' "${NOW_MS}" > "${TELEMETRY}/bash_start_ms/${TK}" 2>/dev/null || true
    : > "${TELEMETRY}/bash_count/${TK}" 2>/dev/null || true
    ;;
  edit)
    # Documentation writes do not re-arm the nudge: the closeout skills
    # Closeout skills write docs AFTER the final green verify. Relay's JSON is
    # also a transient knowledge artifact, not implementation code.
    DOC_RE="${LUCIAZERO_DOC_REGEX:-\.(md|markdown|rst|txt)\$}"
    COUNTED=yes
    case "${FP}" in
      */LUCIA_RELAY.json|*/LUCIA_RELAY.md) COUNTED=no ;;
      *)
        if [ -n "${FP}" ] && printf '%s' "${FP}" | grep -qE "${DOC_RE}"; then
          COUNTED=no  # doc-only write; verify state unchanged
        else
          touch "${STATE}/last_edit"
          rm -f "${STATE}/nudged"    # new code edits re-arm the one-shot nudge
        fi
        ;;
    esac
    # Opt-in diagnostic (LUCIAZERO_EDIT_DIAG=1): one line per edit event in
    # the state directory, next to last_edit, saying what the event carried
    # and what the hook made of it -- the tool's name, the opaque tool key,
    # whether file_path was missing, empty or present, its suffix, whether it
    # lay under cwd, and whether the edit counted. Never the path, never the
    # content. For finding out what touched last_edit when no visible edit did.
    if [ "${LUCIAZERO_EDIT_DIAG:-}" = 1 ]; then
      IN_CWD="-"; EXT="-"
      if [ -n "${FP}" ]; then
        case "${FP}" in "${CWD}"/*) IN_CWD=yes ;; *) IN_CWD=no ;; esac
        case "${FP##*/}" in *.*) EXT="${FP##*.}" ;; esac
      fi
      printf 'ts=%s mode=%s tool=%s key=%s file_path=%s ext=%s in_cwd=%s counted=%s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${MODE}" "${TOOL_NAME:--}" "${TK}" "${FP_STATE:-unknown}" \
        "${EXT}" "${IN_CWD}" "${COUNTED}" >> "${STATE}/edit-diag.log" 2>/dev/null || true
    fi
    ;;
  bash|bash-failure)
    mkdir -p "${TELEMETRY}/bash_count" "${TELEMETRY}/bash_intervals" 2>/dev/null || true
    : > "${TELEMETRY}/bash_count/${TK}" 2>/dev/null || true
    START_MS="$(cat "${TELEMETRY}/bash_start_ms/${TK}" 2>/dev/null || true)"
    END_MS="${NOW_MS}"
    case "${START_MS}:${END_MS}" in
      *[!0-9:]*|:|*:|*::* ) : ;;
      *)
        if [ "${END_MS}" -ge "${START_MS}" ] 2>/dev/null; then
          printf '%s %s\n' "${START_MS}" "${END_MS}" > "${TELEMETRY}/bash_intervals/${TK}" 2>/dev/null || true
        fi
        ;;
    esac
    IS_VERIFY=no
    if [ -n "${CMD}" ]; then
      if [ -n "${VERIFY_CMD}" ]; then
        # exact mode: the command must BE or START WITH the configured command
        case "${CMD}" in
          "${VERIFY_CMD}"|"${VERIFY_CMD} "*) IS_VERIFY=yes ;;
        esac
      elif printf '%s' "${CMD}" | grep -qE "${VERIFY_RE}"; then
        IS_VERIFY=yes
        if [ -z "${LUCIAZERO_VERIFY_REGEX:-}" ] && printf '%s' "${CMD}" | grep -qE 'test-timings\.sh +--report'; then
          IS_VERIFY=no  # the collector's report runs nothing
        fi
      fi
    fi
    if [ "${IS_VERIFY}" = yes ]; then
      mkdir -p "${TELEMETRY}/verify_count" 2>/dev/null || true
      : > "${TELEMETRY}/verify_count/${TK}" 2>/dev/null || true
      # Red/green came from the tool response in the prelude; failure hooks are red.
      [ "${MODE}" = bash-failure ] && STATUS=fail
      # A green that follows a green with no code edit between them proved
      # nothing new: count it (schema 3 `redundant_green_count`) before the
      # state below overwrites the previous result. Float mtimes for the
      # same sub-second reason as the stop nudge; one python3, verify runs only.
      if [ "${STATUS}" = ok ] && [ "$(python3 -c '
import os, sys
state = sys.argv[1]
def m(name):
    try:
        return os.path.getmtime(os.path.join(state, name))
    except OSError:
        return None
try:
    last = open(os.path.join(state, "last_verify")).read().strip()
except OSError:
    last = ""
e, v = m("last_edit"), m("last_verify")
print("yes" if last == "ok" and v is not None and (e is None or e <= v) else "no")' "${STATE}" 2>/dev/null || echo no)" = yes ]; then
        mkdir -p "${TELEMETRY}/redundant_green" 2>/dev/null || true
        : > "${TELEMETRY}/redundant_green/${TK}" 2>/dev/null || true
      fi
      printf '%s\n' "${STATUS:-ran}" > "${STATE}/last_verify"
      # Keep only an opaque digest for strict-gate equality; raw commands may
      # contain paths or secrets and must never persist in shared state.
      printf '%s\n' "${CMD_HASH}" > "${STATE}/last_verify_cmd_hash" 2>/dev/null || true
      rm -f "${STATE}/nudged"
    fi
    ;;
  skill|skill-prompt)
    if [ "${MODE}" = skill-prompt ]; then
      [ "${EXPANSION_TYPE}" = slash_command ] || exit 0
    fi
    mkdir -p "${TELEMETRY}/skill_count" 2>/dev/null || true
    : > "${TELEMETRY}/skill_count/${TK}" 2>/dev/null || true
    ;;
  stop)
    # Never re-block a continuation that a stop hook itself caused; that
    # continuation is the turn ending, so the turn closes here.
    if [ "${ACTIVE}" = "True" ] || [ "${ACTIVE}" = "true" ]; then end_turn; exit 0; fi
    # Strict gate (opt-in, see header): actually run the user's verify command
    # unless the tracked state is already green-after-last-edit. Any internal
    # error — timeout, missing command, unparseable state — degrades to the
    # ordinary fail-open nudge below, never to a block.
    STRICT_CMD="${LUCIAZERO_STRICT_VERIFY_CMD:-}"
    # Strict gate only on well-formed input: unparseable stdin means we know
    # neither cwd nor stop_hook_active — running a command on guesses would
    # break both the fail-open and the never-re-block guarantees.
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
        green) stat_log stop-clean; end_turn; exit 0 ;;
        ok)
          record_strict_telemetry "${STRICT_START_MS}"
          printf 'ok\n' > "${STATE}/last_verify" 2>/dev/null || true
          printf '%s' "${STRICT_CMD}" | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())' \
            > "${STATE}/last_verify_cmd_hash" 2>/dev/null || true
          rm -f "${STATE}/nudged"
          stat_log stop-clean
          end_turn
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
    # (that nudge was counted when it fired). Either way the turn ends here.
    [ "${NUDGE}" = no ] && stat_log stop-clean
    end_turn
    ;;
  session)
    # A marker left behind by a session that never reached its stop (crash,
    # kill, resume) would make the first real prompt look like a notification
    # and keep stale counters. Compaction is the one start that happens inside
    # a live session, possibly mid-turn, so it leaves the marker alone.
    [ "${SESSION_SOURCE}" = compact ] || end_turn
    # A committed settings env block that reconfigures this hook is worth one
    # loud line: the refusal above is silent, and a repository that ships these
    # keys is either mistaken or hostile. Names the keys, never their values.
    if [ -n "${REFUSED_ENV_KEYS}" ]; then
      echo "This repository's committed .claude/settings.json sets ${REFUSED_ENV_KEYS} — Luciazero refuses those keys from project scope (they can disable verify tracking or run a command at every stop). Review that env block before trusting this repo."
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
    AGE="${RELAY_AGE}"
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
