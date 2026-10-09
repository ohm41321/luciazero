#!/usr/bin/env node
// Enforcement-pack hook (Claude Code only; installed by `install.sh --with-hooks`
// or `luciazero --with-hooks`, or loaded by the plugin).
// Tracks per-project whether edits have been followed by a verify run, and
// nudges each session ONCE at stop when its own edits have not — mechanizing
// doctrine rule 1 ("done is proven by a command") at the exact moment it is
// most violated. Any session's verify run covers every session's edits.
//
// One Node program on every platform, wired in exec form
// (`"command": "node", "args": [<this file>, <subcommand>]`), so no shell sits
// between Claude Code and the hook: the same entry runs on macOS, Linux and
// native Windows, where a shell-form command would go through Git Bash or
// PowerShell depending on what is installed. The `.cjs` extension keeps it
// CommonJS wherever it is copied: a config directory inside a project whose
// package.json says "type": "module" would make a `.js` file an ES module.
//
// Subcommands (wired in settings.json):
//   prompt  — UserPromptSubmit: start privacy-preserving turn telemetry (a
//             prompt inside an open turn is a background-task notice: kept)
//   bash-start — PreToolUse on Bash: start shell-command timing
//   edit    — PostToolUse on Edit|Write|NotebookEdit : record "an edit happened"
//   bash    — PostToolUse on Bash: record duration, verify runs, and status
//   bash-failure — PostToolUseFailure on Bash: record failed commands
//   skill   — PostToolUse on Skill: count model-invoked skills
//   skill-prompt — UserPromptExpansion: count user-invoked slash skills
//   stop    — Stop                                   : warn once if edits are unverified
//   session — SessionStart                           : point at an existing Lucia Relay
//   doctrine— SessionStart (plugin installs only)    : emit the doctrine as context
//             (plugins cannot add a CLAUDE.md import line; this is the same
//             word-ceiling-capped text the classic install imports. Silent when
//             a classic install exists, so the doctrine never loads twice.)
//
// Optional strict gate: when LUCIAZERO_STRICT_VERIFY_CMD is set, `stop`
// actually RUNS that command (through the platform shell: /bin/sh, or cmd.exe
// on Windows, in the session's project directory whichever subdirectory the
// session moved to) and refuses the stop (exit 2) while it is red. Set it in your
// PERSONAL settings (settings.local.json env block, or your shell).
// LIMITATION: this hook cannot tell which settings scope set the variable — a
// committed .claude/settings.json env block reaches it too — so never commit
// it, and treat a repo that ships this variable as hostile. A blocked stop's
// continuation is never re-blocked (stop_hook_active), so this is a speed bump
// with evidence attached, not a wall.
//
// FAILS OPEN: any internal error exits 0, so a broken hook can never block real
// work. Per-project state lives under the temporary directory and never
// touches the repo. One exception, documented honestly: the stop hook appends
// one schema-versioned JSON line per stop outcome (stop-clean / nudge /
// strict-block) to luciazero-stats.log in the harness config dir — local only,
// capped at ~250 lines, fail-open. It records a privacy-preserving project
// hash, verify mode, and aggregate latency/counts — including how long verify
// commands ran and how many came back green with no edit since the previous
// green (schema 3) — never the project path, command, or skill name.
// Uninstall keeps it.
"use strict";

const childProcess = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const tty = require("tty");

const WINDOWS = process.platform === "win32";
const LIMIT = 1000000; // a settings file is kilobytes; this runs on every tool call
const MAX_DEPTH = 40; // ancestor walk is bounded, never unbounded I/O
const ALL_KNOBS = ["LUCIAZERO_VERIFY_CMD", "LUCIAZERO_VERIFY_REGEX", "LUCIAZERO_DOC_REGEX",
  "LUCIAZERO_STRICT_VERIFY_CMD", "LUCIAZERO_STRICT_TIMEOUT", "LUCIAZERO_RELAY_STALE_DAYS",
  "LUCIAZERO_HANDOFF_STALE_DAYS", "LUCIAZERO_EDIT_DIAG", "CLAUDE_CONFIG_DIR"];
// What counts as a verify run. Deliberately broad; override per-shell with
// LUCIAZERO_VERIFY_REGEX (extended regex, matched against each line of the
// Bash tool command). When LUCIAZERO_VERIFY_CMD is set (the repo's exact verify
// command, e.g. "./test.sh"), only commands that ARE it or START with it count
// — the broad regex also marks `cat test.sh` or `grep pytest README` as a
// verify run, flipping the state green without any test having run. The
// default also knows `python -m unittest` and this repository's timing
// collector, scripts/test-timings.sh, which runs a tier -- except with
// --report, which only reads the samples kept so far; that case is carved out
// of the default below and is no concern of a regex somebody set themselves.
const DEFAULT_VERIFY_RE = "verify|test\\.sh|python[0-9.]* -m unittest|test-timings\\.sh|pytest|npm (run )?test|pnpm test|yarn test|cargo test|go test|vitest|jest|make (test|check)|tox|rake test|mix test|dotnet test|gradlew? (test|check)";
// .txt is not on it: requirements.txt, CMakeLists.txt and constraints.txt
// are build inputs, and a nudge after editing notes.txt costs less than none
// after editing requirements.txt.
const DEFAULT_DOC_RE = "\\.(md|markdown|rst)$";
const NUDGE_TEXT = "Doctrine rule 1: edits were made but no verify command has run since the last edit. Run the repo's verify command and quote its decisive line — or finish anyway and say plainly that the change is unverified. (This nudge fires once.)";

function home() {
  // os.homedir() reads HOME on POSIX and USERPROFILE on Windows, which is
  // where Claude Code keeps ~/.claude on each.
  try {
    return os.homedir();
  } catch {
    return "";
  }
}

function configDir() {
  return process.env.CLAUDE_CONFIG_DIR || path.join(home(), ".claude");
}

// Whether Codex's classic install (install-codex.sh) already puts the
// doctrine in its global AGENTS.md: its marker block's opening line.
function codexDoctrineInstalled() {
  const file = path.join(process.env.CODEX_HOME || path.join(home(), ".codex"), "AGENTS.md");
  if (!isFile(file)) return false;
  try {
    return fs.readFileSync(file, "utf8").split(/\r?\n/).includes("<!-- luciazero:start -->");
  } catch {
    return false;
  }
}

function isFile(file) {
  try {
    return fs.statSync(file).isFile();
  } catch {
    return false;
  }
}

function sha256(text, size) {
  return crypto.createHash("sha256").update(String(text), "utf8").digest("hex").slice(0, size);
}

// The state directory is named by md5 of the project directory; md5 here is
// never a security decision. A FIPS-enforcing Node refuses md5, and then the
// name falls back to sha256 rather than the tracker failing open.
function stateKey(cwd) {
  try {
    return crypto.createHash("md5").update(cwd, "utf8").digest("hex").slice(0, 12);
  } catch {
    return sha256(cwd, 12);
  }
}

// The project a hook event belongs to, which names its state: the session's
// CLAUDE_PROJECT_DIR when the event's cwd lies inside it, spelled as the cwd
// spells it, else the cwd. A `cd` into a subdirectory persists between tool
// calls, and must not move the session to state that holds none of its edits.
function projectOf(cwd, project = process.env.CLAUDE_PROJECT_DIR || "") {
  if (!project || !cwd || !path.isAbsolute(project) || !path.isAbsolute(cwd)) return cwd;
  const rel = path.relative(project, cwd);
  if (rel === "") return cwd;
  if (rel === ".." || rel.startsWith(".." + path.sep) || path.isAbsolute(rel)) return cwd;
  const own = cwd.slice(0, cwd.length - rel.length).replace(/[\\/]+$/, "");
  return own && path.relative(own, project) === "" ? own : path.resolve(project);
}

// Where the per-user state lives. POSIX keeps the shell's spelling,
// ${TMPDIR:-/tmp}, suffixed with the uid; Windows has no uid, but its
// temporary directory is already per user, and the user name keeps two
// accounts apart if it is ever shared.
function stateBase() {
  if (WINDOWS) {
    let user = "user";
    try {
      user = os.userInfo().username.replace(/[^A-Za-z0-9._-]/g, "_") || "user";
    } catch {}
    return path.join(os.tmpdir(), "luciazero-verify-state-" + user);
  }
  const uid = typeof process.getuid === "function" ? process.getuid() : "unknown";
  return path.join(process.env.TMPDIR || "/tmp", "luciazero-verify-state-" + uid);
}

// The base name is predictable, so ownership and type are checked before it
// is used: a hostile pre-created symlink, junction or foreign directory makes
// the caller fail open. POSIX also requires it private; Windows reports no
// meaningful mode bits, and its temporary directory is per user already.
function trustedBase(base) {
  let info;
  try {
    info = fs.lstatSync(base);
  } catch {
    return false;
  }
  if (info.isSymbolicLink() || !info.isDirectory()) return false;
  if (!WINDOWS) {
    if (typeof process.getuid === "function" && info.uid !== process.getuid()) return false;
    if (info.mode & 0o077) return false;
  }
  return true;
}

function mtime(file) {
  try {
    return fs.statSync(file).mtimeMs;
  } catch {
    return null;
  }
}

// A verify run vouches for the code as it was when it started: an edit made
// while it ran (another session, a background agent) has to stay after it.
function stampAt(file, ms) {
  try {
    fs.utimesSync(file, new Date(ms), new Date(ms));
  } catch {}
}

// Overlapping verify runs finish in any order, and the one that started
// last tested the newest code. A run that started before the recorded one
// is not written over it: moving last_verify back to the earlier start
// would un-cover an edit the later run covered, and its red would replace
// a green for newer code. Returns whether the run was recorded.
//
// The recorded mtime is a start only when last_verify_start, written beside
// it, says so. The released copy and a run with no recorded start stamp the
// finish, and when one start is unknown the order of the runs is too, so
// the guard stands aside and the run that finishes later wins, as it always
// did. That can let a red for older code replace a released copy's green
// for newer code: an extra nudge, never a false green. A start in the
// future is a clock that stepped back, not a run.
function recordVerify(state, status, startMs, command) {
  const file = path.join(state, "last_verify");
  const startFile = path.join(state, "last_verify_start");
  const recorded = mtime(file);
  const recordedStart = recorded === null ? null : Math.round(recorded);
  if (startMs !== null && recordedStart !== null && startMs < recordedStart
      && recordedStart <= Date.now() && readTrimmed(startFile) === String(recordedStart)) return false;
  write(file, status + "\n");
  if (startMs !== null) {
    stampAt(file, startMs);
    write(startFile, startMs + "\n");
  } else {
    removeFile(startFile);
  }
  // Keep only an opaque digest for strict-gate equality; raw commands may
  // contain paths or secrets and must never persist in shared state.
  write(path.join(state, "last_verify_cmd_hash"), sha256(command, 64) + "\n");
  return true;
}

function readTrimmed(file) {
  try {
    return fs.readFileSync(file, "utf8").trim();
  } catch {
    return "";
  }
}

// `touch`: the kernel stamps the time, at its own precision. An edit made in
// the same millisecond as the last verify must still read as after it.
function touch(file) {
  try {
    fs.writeFileSync(file, "");
  } catch {}
}

function write(file, text) {
  try {
    fs.writeFileSync(file, text);
  } catch {}
}

function mkdirs(...dirs) {
  try {
    for (const dir of dirs) fs.mkdirSync(dir, { recursive: true });
    return true;
  } catch {
    return false;
  }
}

function removeFile(file) {
  try {
    fs.rmSync(file, { force: true });
  } catch {}
}

// The stop nudge is kept per session in two directories under the project's
// state: edited/<key> is touched by each counted edit, nudged-sessions/<key>
// when that session is nudged. An older copy keeps one plain `nudged` file
// for the whole project and reads only last_edit; this copy still touches
// last_edit and removes `nudged` where that copy did, so a session still
// running it keeps working.

// The last edit a stop would nudge this session for: its own newest one, or
// one only an older copy recorded (last_edit, before edited/ existed), which
// is every session's, as it was for that copy.
function lastEditOf(state, key) {
  const edited = path.join(state, "edited");
  const times = [mtime(path.join(edited, key)),
    fs.existsSync(edited) ? mtime(path.join(state, "legacy_edit")) : mtime(path.join(state, "last_edit"))]
    .filter((t) => t !== null);
  return times.length ? Math.max(...times) : null;
}

// A verify run settles the sessions whose edits it covers: their markers go,
// and a later edit re-arms each one anyway. A session that edited after the
// run started keeps its marker, so it is not nudged twice for one edit.
function settleNudged(state) {
  removeOlderMarker(state);
  const verified = mtime(path.join(state, "last_verify"));
  const dir = path.join(state, "nudged-sessions");
  let keys;
  try {
    keys = fs.readdirSync(dir);
  } catch {
    return;
  }
  for (const key of keys) {
    const last = lastEditOf(state, key);
    if (verified !== null && (last === null || last <= verified)) removeFile(path.join(dir, key));
  }
}

// An older copy's one-shot marker. A directory there was left by an
// unreleased build that kept the per-session markers under that name.
function removeOlderMarker(state) {
  try {
    fs.rmSync(path.join(state, "nudged"), { recursive: true, force: true });
  } catch {}
}

// LUCIAZERO_VERIFY_REGEX and LUCIAZERO_DOC_REGEX are POSIX extended regular
// expressions, as `grep -E` read them. The common ERE is already JavaScript;
// the bracket classes are not, and are translated so `[[:digit:]]` keeps its
// meaning. A pattern that does not compile matches nothing, as a `grep -E`
// that errors matched nothing.
const CLASSES = { alnum: "A-Za-z0-9", alpha: "A-Za-z", blank: " \\t", digit: "0-9",
  lower: "a-z", punct: "!-\\/:-@\\[-`{-~", space: " \\t\\n\\r\\f\\v", upper: "A-Z",
  xdigit: "0-9A-Fa-f" };

function ere(source) {
  try {
    return new RegExp(source.replace(/\[:([a-z]+):\]/g, (all, name) => CLASSES[name] || all));
  } catch {
    return null;
  }
}

// grep matches line by line: a multi-line command counts when any line does.
function anyLine(text, source) {
  const re = ere(source);
  return re !== null && text.split("\n").some((line) => re.test(line));
}

// A repository's COMMITTED .claude/settings.json can put anything in its `env`
// block, and that env reaches this hook — so NO LUCIAZERO_* knob is accepted
// from that scope. Each one is a way to disable enforcement while the
// statusline stays green: a widened LUCIAZERO_VERIFY_REGEX (or a
// LUCIAZERO_VERIFY_CMD pointing at `echo`) makes any command count as a verify
// run, LUCIAZERO_DOC_REGEX='.*' makes every edit look like documentation so
// nothing is ever unverified, and LUCIAZERO_STRICT_VERIFY_CMD is a command this
// hook would RUN at stop. CLAUDE_CONFIG_DIR is refused from that scope too: it
// moves the config directory the dedupe below trusts.
//
// PROJECT scope only. The walk covers the session directory and its ancestors —
// Claude Code merges project settings from the repository root and a session's
// cwd is often a subdirectory — but it stops at the repository root (a nested
// repository inside CLAUDE_PROJECT_DIR does not end it), at CLAUDE_PROJECT_DIR,
// and at the home directory, and it never reads the user's
// own config directory. Personal settings (global `~/.claude/settings.json`,
// gitignored `.claude/settings.local.json`) are the user's scope and keep
// working.
//
// Refusal only ever falls back to this file's own defaults, never to a block,
// and a parse error leaves the configured values untouched. Every mode pays for
// the lookup: each one reads CLAUDE_CONFIG_DIR before it does anything else.
function refusedKey(key) {
  return key.startsWith("LUCIAZERO_") || key === "CLAUDE_CONFIG_DIR";
}

function keysIn(file) {
  let info;
  try {
    info = fs.statSync(file);
  } catch {
    return [];
  }
  // never read a fifo or device planted here: that would hang the hook
  // instead of failing open
  if (!info.isFile()) return [];
  // absurd for a settings file: refuse everything rather than parse it
  if (info.size > LIMIT) return ["LUCIAZERO_*"];
  let env;
  try {
    env = JSON.parse(fs.readFileSync(file, "utf8")).env;
  } catch {
    return [];
  }
  if (!env || typeof env !== "object" || Array.isArray(env)) return [];
  // Windows reads environment names regardless of case: a lowercase name
  // sets the same variable
  return Object.keys(env).map((key) => (WINDOWS ? key.toUpperCase() : key)).filter(refusedKey);
}

function real(file) {
  try {
    return fs.realpathSync(file);
  } catch {
    return path.resolve(file);
  }
}

function samePath(a, b) {
  return WINDOWS ? a.toLowerCase() === b.toLowerCase() : a === b;
}

function refusedKeys(start) {
  const homeDir = real(home() || path.sep);
  // Only the DEFAULT config directory counts as user scope. CLAUDE_CONFIG_DIR
  // is attacker-reachable: pointed at the project itself, it would mark the
  // repository settings file as user scope and skip the very file that
  // declares it, and the dedupe below would then trust a classic install
  // inside the repo.
  const userConfig = real(path.join(homeDir, ".claude"));
  const projectDir = process.env.CLAUDE_PROJECT_DIR ? real(process.env.CLAUDE_PROJECT_DIR) : null;
  const found = [];
  let directory = real(start || ".");
  // Inside the session's project the walk goes on up to it: a submodule or
  // nested checkout below the project root does not end the project's scope.
  const rel = projectDir === null ? ".." : path.relative(projectDir, directory);
  const inProject = rel === "" || !(rel === ".." || rel.startsWith(".." + path.sep) || path.isAbsolute(rel));
  for (let depth = 0; depth < MAX_DEPTH; depth++) {
    const claudeDir = path.join(directory, ".claude");
    if (!samePath(directory, homeDir) && !samePath(real(claudeDir), userConfig)) {
      for (const key of keysIn(path.join(claudeDir, "settings.json"))) {
        if (!found.includes(key)) found.push(key);
      }
    }
    if (samePath(directory, homeDir)) break;
    // repository root: project scope ends here
    if (!inProject && fs.existsSync(path.join(directory, ".git"))) break;
    if (projectDir !== null && samePath(directory, projectDir)) break;
    const parent = path.dirname(directory);
    if (parent === directory) break;
    directory = parent;
  }
  return found;
}

// The value at input[path...] as text; empty on any missing or mis-shaped
// level. Text, as the field's own string or as Python's str() spelled the
// scalars the earlier hook compared against.
function field(input, ...keys) {
  let value = input;
  for (const key of keys) {
    if (value === null || typeof value !== "object" || Array.isArray(value)) return "";
    value = value[key];
  }
  if (value === undefined || value === null) return "";
  if (value === true) return "True";
  if (value === false) return "False";
  if (typeof value === "object") return "";
  return String(value).replace(/\n+$/, "");
}

function readStdin() {
  // Hook stdin is always a pipe; when run by hand from a terminal for
  // debugging, do not hang waiting for EOF that never comes. `tty.isatty`,
  // never `process.stdin`: opening that stream makes the pipe non-blocking,
  // and a read before the writer has written then fails with EAGAIN, which
  // dropped the event as if it were empty. The pipe can also arrive
  // non-blocking from whoever made it, so EAGAIN is waited out here; Windows
  // reports the end of a pipe as EOF.
  if (tty.isatty(0)) return "";
  const chunks = [];
  const buffer = Buffer.alloc(65536);
  const pause = new Int32Array(new SharedArrayBuffer(4));
  for (;;) {
    let n;
    try {
      n = fs.readSync(0, buffer, 0, buffer.length, null);
    } catch (error) {
      if (error.code === "EAGAIN") {
        Atomics.wait(pause, 0, 0, 10);
        continue;
      }
      if (error.code === "EOF") break;
      return "";
    }
    if (n === 0) break;
    chunks.push(Buffer.from(buffer.subarray(0, n)));
  }
  return Buffer.concat(chunks).toString("utf8");
}

// The classic install's hook path as a canonical path; empty when its
// directory does not exist. The file itself is not resolved, so a copy reached
// through a symlinked file is a different copy, as it always was.
function hookPath(file) {
  try {
    return path.join(fs.realpathSync(path.dirname(file)), path.basename(file));
  } catch {
    return "";
  }
}

// Channel dedupe: when the classic `--with-hooks` wiring is ALSO present, the
// classic copy wins and every other copy (the plugin's) stands down — otherwise
// the stop nudge double-fires and a strict verify runs twice concurrently.
//
// Decided from this program's own path, never from LUCIAZERO_CHANNEL: an
// env-driven dedupe let a repository hand the CLASSIC hook a plugin label so it
// stood itself down. It runs after the refusal for the same reason — a
// committed CLAUDE_CONFIG_DIR could otherwise point at a repository-controlled
// directory holding a "wired classic install", and every copy would stand down.
// A classic install made before the hooks moved to Node is wired to
// luciazero-verify.sh; it still counts, so this copy never doubles it.
function classicWired(self) {
  const cfg = configDir();
  let settings = null;
  for (const name of ["luciazero-verify.cjs", "luciazero-verify.sh"]) {
    const classic = hookPath(path.join(cfg, "hooks", name));
    if (!classic || samePath(classic, self) || !isFile(classic)) continue;
    // the Bash hook only ran when executable; a copy that cannot run is no copy
    if (name.endsWith(".sh")) {
      try {
        fs.accessSync(classic, fs.constants.X_OK);
      } catch {
        continue;
      }
    }
    // read only a regular file: a fifo here would hang every hook call
    if (settings === null) {
      const file = path.join(cfg, "settings.json");
      if (!isFile(file)) return false;
      try {
        settings = fs.readFileSync(file, "utf8");
      } catch {
        return false;
      }
    }
    // The installer writes the config directory as it was given, unnormalized
    // (a TMPDIR ending in "/" leaves a "//" in it), so the raw spelling is
    // the one to find; the normalized and forward-slash ones cover Windows.
    const spelled = path.join(cfg, "hooks", name);
    const spellings = new Set([cfg + "/hooks/" + name, spelled, spelled.replace(/\\/g, "/")]);
    for (const s of [...spellings]) spellings.add(JSON.stringify(s).slice(1, -1));
    if ([...spellings].some((s) => settings.includes(s))) return true;
  }
  return false;
}

// Discipline stats: one row per stop outcome, fail-open, capped.
function statLog(event, ctx) {
  try {
    const file = path.join(configDir(), "luciazero-stats.log");
    let mode = "regex";
    if (process.env.LUCIAZERO_VERIFY_CMD) mode = "exact";
    if (process.env.LUCIAZERO_STRICT_VERIFY_CMD) mode = "strict";
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const realCwd = real(ctx.cwd);
    const row = {
      schema: 3,
      timestamp: new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00"),
      event,
      project_id: sha256(realCwd, 12),
      project: path.basename(realCwd) || "(root)",
      verify_mode: mode,
    };
    const telemetry = ctx.telemetry;
    const readInt = (name) => {
      const text = readTrimmed(path.join(telemetry, name));
      return /^\d+$/.test(text) ? Number(text) : null;
    };
    const countFiles = (name) => {
      try {
        return fs.readdirSync(path.join(telemetry, name))
          .filter((item) => isFile(path.join(telemetry, name, item))).length;
      } catch {
        return 0;
      }
    };
    const mergedMs = (intervals) => {
      const merged = [];
      for (const [a, b] of intervals.filter(([a, b]) => a <= b).sort((x, y) => x[0] - y[0] || x[1] - y[1])) {
        if (!merged.length || a > merged[merged.length - 1][1]) merged.push([a, b]);
        else merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], b);
      }
      return merged.reduce((sum, [a, b]) => sum + b - a, 0);
    };
    const start = readInt("turn_start_ms");
    if (start !== null) {
      const now = Date.now();
      const intervals = [];
      const verifyIntervals = [];
      const intervalDir = path.join(telemetry, "bash_intervals");
      let items = [];
      try {
        items = fs.readdirSync(intervalDir);
      } catch {}
      for (const item of items) {
        const parts = readTrimmed(path.join(intervalDir, item)).split(/\s+/);
        if (parts.length !== 2 || !parts.every((p) => /^\d+$/.test(p))) continue;
        const [a, b] = parts.map(Number);
        if (a <= b) {
          intervals.push([Math.max(start, a), Math.min(now, b)]);
          // the interval's tool key is the verify marker's name: same opaque
          // digest, so no command is read to tell the two apart
          if (isFile(path.join(telemetry, "verify_count", item))) verifyIntervals.push(intervals[intervals.length - 1]);
        }
      }
      row.telemetry = {
        turn_ms: Math.max(0, now - start),
        bash_ms: mergedMs(intervals),
        bash_count: countFiles("bash_count"),
        verify_count: countFiles("verify_count"),
        skill_count: countFiles("skill_count"),
        verify_ms: mergedMs(verifyIntervals),
        redundant_green_count: countFiles("redundant_green"),
      };
    }
    // ASCII only, as the log has always been written: a project name outside
    // ASCII is escaped, never written raw.
    const line = JSON.stringify(row).replace(/[\u007f-￿]/g,
      (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
    fs.appendFileSync(file, line + "\n", "utf8");
    const lines = fs.readFileSync(file, "utf8").split(/(?<=\n)/);
    if (lines.length > 500) {
      // A fresh name beside the log, never a predictable one: a symlink
      // planted at a fixed name would otherwise receive the rotated lines and
      // then replace the log (roadmap R21). `wx` refuses any name already
      // taken, a dangling symlink included.
      const tmp = path.join(path.dirname(file), ".luciazero-stats." + crypto.randomBytes(6).toString("hex"));
      let fd = null;
      try {
        fd = fs.openSync(tmp, "wx", 0o600);
        fs.writeFileSync(fd, lines.slice(-250).join(""));
        fs.closeSync(fd);
        fd = null;
        fs.renameSync(tmp, file);
      } catch (error) {
        if (fd !== null) {
          try {
            fs.closeSync(fd);
          } catch {}
        }
        removeFile(tmp);
        throw error;
      }
    }
  } catch {}
}

// cmd.exe's own commands, which no file lookup finds.
const CMD_BUILTINS = new Set(("assoc break call cd chdir cls color copy date del dir dpath echo endlocal "
  + "erase exit for ftype goto if keys md mkdir mklink move path pause popd prompt pushd rd rem ren rename "
  + "rmdir set setlocal shift start time title type ver verify vol").split(" "));

// Whether cmd.exe certainly failed to find the program `command` starts.
// `cmd /c` exits 1 for that, as a failing test does, and names the cause only
// in the display language, so this asks the file system instead: true only
// for one command, or an && chain that stops at its first, whose first word
// is no builtin and no file in the working directory or a PATH entry, as is
// or with a PATHEXT extension. Anything it cannot read stays the command's
// own verdict.
function cmdMissing(command, cwd) {
  const text = command.replace(/^[\s@]+/, "");
  // cmd.exe skips a leading delimiter and takes a leading redirection apart
  // from the command, which this does not follow
  if (/^[;,=<>]/.test(text)) return false;
  let word;
  let rest;
  if (text[0] === '"') {
    const end = text.indexOf('"', 1);
    if (end < 0) return false;
    word = text.slice(1, end);
    rest = text.slice(end + 1);
  } else {
    word = text.match(/^[^\s&|<>()";,=]*/)[0];
    rest = text.slice(word.length);
    // unquoted, cmd.exe reads a / as the start of a switch
    if (word.includes("/")) return false;
  }
  if (!word || /[%!^*?]/.test(word)) return false;
  // the word has to end where cmd.exe certainly ends it: a quote, delimiter
  // or redirection right after it (`"C:\Program Files"\x`, `npm,test`,
  // `2>nul npm test`) makes a different command of it there
  if (rest && !/^[\s&|]/.test(rest)) return false;
  const lead = word.match(/^[A-Za-z]+/);
  if (lead && CMD_BUILTINS.has(lead[0].toLowerCase())) return false;
  // `D:` changes the drive and a word that starts with `:` is a label: no
  // program either way
  if (/^:|^[A-Za-z]:$/.test(word)) return false;
  // after `&`, `||` or `|` a later command decides the exit status
  let quoted = false;
  for (let i = 0; i < rest.length; i += 1) {
    const c = rest[i];
    if (c === '"') quoted = !quoted;
    else if (quoted) continue;
    else if (c === "^") i += 1;
    else if (c === "|" || c === "(" || c === ")") return false;
    else if (c === "&" && rest[i - 1] !== ">" && rest[i - 1] !== "<") {
      if (rest[i + 1] !== "&") return false;
      i += 1;
    }
  }
  const base = cwd || process.cwd();
  const names = [word, ...(process.env.PATHEXT || ".COM;.EXE;.BAT;.CMD").split(";").filter(Boolean)
    .map((ext) => word + ext)];
  // anything there but a directory, or anything that cannot be checked,
  // counts as found
  const found = (file) => {
    try {
      return !fs.lstatSync(file).isDirectory();
    } catch (error) {
      return !error || (error.code !== "ENOENT" && error.code !== "ENOTDIR");
    }
  };
  const dirs = /[\\/:]/.test(word) ? [base]
    : [base, ...(process.env.PATH || "").split(";").map((dir) => dir.replace(/^"(.*)"$/, "$1")).filter(Boolean)];
  return !dirs.some((dir) => names.some((name) => found(path.resolve(base, dir, name))));
}

// The strict gate: the user's verify command, run through the platform shell.
// "error" for anything that is not the command's own verdict — a timeout, a
// shell that could not find the command — so the stop degrades to the
// fail-open nudge instead of fabricating a red.
function runStrict(state, cwd, command, timeout) {
  const lastEdit = mtime(path.join(state, "last_edit"));
  const lastVerify = mtime(path.join(state, "last_verify"));
  // Fast path only for a green whose command digest exactly matches. A
  // broad-regex green from a mere read of the test file must not disarm a
  // gate whose promise is "actually runs the command".
  if (lastVerify !== null && readTrimmed(path.join(state, "last_verify")) === "ok"
      && (lastEdit === null || lastEdit <= lastVerify)
      && readTrimmed(path.join(state, "last_verify_cmd_hash")) === sha256(command, 64)) {
    return { verdict: "green" };
  }
  const seconds = Number(timeout);
  if (!(seconds > 0)) return { verdict: "error" };
  // asked before the run as well as after it: a runner that deletes itself
  // as it fails was there to run, and its red stands
  const missingBefore = WINDOWS && cmdMissing(command, cwd);
  // On POSIX the shell leads a process group of its own, so a timeout stops
  // everything it started, not the shell alone.
  const result = childProcess.spawnSync(command, {
    shell: true, cwd: cwd || undefined, timeout: seconds * 1000, encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024, windowsHide: true, detached: !WINDOWS,
  });
  if (result.error) {
    if (!WINDOWS && result.pid > 0) {
      try {
        process.kill(-result.pid, "SIGKILL");
      } catch {}
    }
    return { verdict: "error" };
  }
  // command not found / not executable: an internal error, not a red verify.
  // 126 and 127 are the POSIX shell's; 9009 is the ERRORLEVEL cmd.exe sets
  // for a command it cannot find, which a batch file can pass on. `cmd /c`
  // given a missing command directly exits 1, which cmdMissing tells apart.
  if ([126, 127].includes(result.status) || (WINDOWS && result.status === 9009)
      || (result.status === 1 && missingBefore && cmdMissing(command, cwd))) return { verdict: "error" };
  if (result.status === 0) return { verdict: "ok" };
  const tail = ((result.stdout || "") + "\n" + (result.stderr || "")).trim().split(/\r?\n/).slice(-8);
  return { verdict: "red", tail: tail.join("\n") };
}

// Drop every knob the project's committed settings set (see refusedKeys);
// the names refused.
function dropRefused(cwd) {
  let refused = refusedKeys(cwd);
  // `LUCIAZERO_*` is the oversized-file marker: drop every knob this hook reads
  if (refused.includes("LUCIAZERO_*")) refused = ALL_KNOBS.slice();
  for (const name of refused) {
    if (/^LUCIAZERO_[A-Z_]+$/.test(name) || name === "CLAUDE_CONFIG_DIR") delete process.env[name];
  }
  return refused;
}

function main(argv) {
  const mode = argv[0] || "";
  // The plugin's Codex wiring (.codex-plugin/hooks.json) names its host; a
  // repository cannot change that argument, as it could an environment
  // variable. Codex never reads Claude Code's config directory, so nothing
  // there may stand this copy down.
  const codex = argv[1] === "codex";

  // doctrine mode needs no state and no stdin — handled before the shared
  // setup. It reads the config directory, so a committed one is refused first.
  if (mode === "doctrine") {
    dropRefused(process.env.CLAUDE_PROJECT_DIR || process.env.PWD || process.cwd());
    // a classic install already loads this text — never twice: Claude Code's
    // through its CLAUDE.md import, Codex's through its AGENTS.md block
    if (codex ? codexDoctrineInstalled() : isFile(path.join(configDir(), "luciazero.md"))) return 0;
    try {
      process.stdout.write(fs.readFileSync(path.join(__dirname, "..", "luciazero.md")));
    } catch {}
    return 0;
  }

  let input;
  try {
    input = JSON.parse(readStdin());
  } catch {
    return 0; // nothing known about the event: do nothing, block nothing
  }
  if (input === null || typeof input !== "object" || Array.isArray(input)) return 0;

  const cwd = field(input, "cwd") || process.env.PWD || process.cwd();
  const project = projectOf(cwd);
  const key = stateKey(project);
  const sessionKey = sha256(field(input, "session_id") || "parent-" + process.ppid, 16);
  // Who the stop nudge is for. An event without a session_id cannot be told
  // apart from another one, so all of those share one key, which is the
  // per-project nudge this hook had before it tracked sessions.
  const editorKey = field(input, "session_id") ? sessionKey : "no-session";
  // stable opaque tool key; raw tool input never leaves temporary state
  const toolKey = sha256(field(input, "tool_use_id") || field(input, "tool_input", "command")
    || field(input, "tool_input", "skill") || field(input, "command_name") || field(input, "prompt")
    || field(input, "command") || "unknown", 16);
  const nowMs = Date.now();
  const command = field(input, "tool_input", "command");
  const filePath = field(input, "tool_input", "file_path").replace(/\n/g, " ");
  const toolInput = input.tool_input;
  const filePathState = (toolInput === null || typeof toolInput !== "object" || Array.isArray(toolInput)
    || !("file_path" in toolInput)) ? "missing"
    : (toolInput.file_path === "" || toolInput.file_path === null) ? "empty" : "present";
  // best-effort red/green from the tool response. The Bash response of Claude
  // Code carries no exit code (stdout, stderr, interrupted, isImage):
  // PostToolUse only fires for a command that finished with exit 0, a non-zero
  // exit reaches PostToolUseFailure (mode bash-failure) instead, so a
  // completed, uninterrupted response in mode bash is a green. An explicit exit
  // code still wins. Codex has no failure event: its PostToolUse fires for
  // every finished command, and its response is only the output, a string, so
  // there a command ran and nothing says whether it passed.
  let status;
  const response = input.tool_response && typeof input.tool_response === "object" ? input.tool_response : {};
  const code = "exit_code" in response ? response.exit_code : response.exitCode;
  if (Number.isInteger(code)) status = code === 0 ? "ok" : "fail";
  else if (response.is_error === true) status = "fail";
  else if (response.interrupted === true) status = "ran";
  else status = mode === "bash" && !codex ? "ok" : "ran";

  // every mode reads the config directory (classicWired below)
  const refused = dropRefused(cwd);

  // Codex's classic install wires no hooks, so under Codex this copy is the only one.
  if (!codex && classicWired(hookPath(process.argv[1] || __filename))) return 0;

  const base = stateBase();
  if (fs.existsSync(base) || (() => {
    try {
      fs.lstatSync(base);
      return true;
    } catch {
      return false;
    }
  })()) {
    if (!trustedBase(base)) return 0;
  } else {
    try {
      fs.mkdirSync(base, { mode: 0o700 });
    } catch {
      return 0;
    }
  }
  try {
    fs.chmodSync(base, 0o700);
  } catch {
    return 0;
  }
  const state = path.join(base, key);
  if (!mkdirs(state)) return 0;
  try {
    fs.chmodSync(state, 0o700);
  } catch {
    return 0;
  }
  const telemetry = path.join(state, "telemetry", sessionKey);
  const ctx = { cwd, telemetry };

  // A turn is open from its first prompt until a stop lets it end. The harness
  // delivers a background task's completion (a forked skill, a subagent, a
  // run_in_background command) as one more UserPromptSubmit, and before this
  // marker every one of those wiped the turn's counters. A stop that blocks
  // (nudge, strict red) keeps the turn open, because the model continues it;
  // every stop that lets the turn end closes it. Fail-open, like all state.
  const endTurn = () => removeFile(path.join(telemetry, "turn_open"));

  const recordStrictTelemetry = (startMs) => {
    const endMs = Date.now();
    if (!(endMs >= startMs)) return;
    if (!mkdirs(path.join(telemetry, "bash_count"), path.join(telemetry, "bash_intervals"),
      path.join(telemetry, "verify_count"))) return;
    touch(path.join(telemetry, "bash_count", "strict-gate"));
    touch(path.join(telemetry, "verify_count", "strict-gate"));
    write(path.join(telemetry, "bash_intervals", "strict-gate"), startMs + " " + endMs + "\n");
  };

  switch (mode) {
    case "prompt": {
      // Per-turn scratch data is ephemeral. Persistent rows keep aggregates
      // only. Inside an open turn this prompt is a notification, not a new
      // turn: the counters and turn_start_ms stay exactly as they are.
      if (isFile(path.join(telemetry, "turn_open"))) return 0;
      try {
        fs.rmSync(telemetry, { recursive: true, force: true });
      } catch {
        return 0;
      }
      if (!mkdirs(telemetry)) return 0;
      write(path.join(telemetry, "turn_start_ms"), nowMs + "\n");
      touch(path.join(telemetry, "turn_open"));
      return 0;
    }
    case "bash-start": {
      if (!mkdirs(path.join(telemetry, "bash_start_ms"), path.join(telemetry, "bash_count"))) return 0;
      write(path.join(telemetry, "bash_start_ms", toolKey), nowMs + "\n");
      touch(path.join(telemetry, "bash_count", toolKey));
      return 0;
    }
    case "edit": {
      // Documentation writes do not re-arm the nudge: closeout skills write
      // docs AFTER the final green verify. Relay's JSON is also a transient
      // knowledge artifact, not implementation code.
      const docRe = process.env.LUCIAZERO_DOC_REGEX || DEFAULT_DOC_RE;
      const separators = WINDOWS ? /[\\/]/ : /\//;
      const base = filePath.split(separators).pop();
      const relay = filePath !== base && (base === "LUCIA_RELAY.json" || base === "LUCIA_RELAY.md");
      let counted = "yes";
      if (relay) counted = "no";
      else if (filePath && anyLine(filePath, docRe)) counted = "no"; // doc-only write; verify state unchanged
      else {
        // The first edit this copy records keeps the time of the last one an
        // older copy recorded, which no session's edited/ entry carries.
        const edited = path.join(state, "edited");
        const before = fs.existsSync(edited) ? null : mtime(path.join(state, "last_edit"));
        touch(path.join(state, "last_edit"));
        if (mkdirs(edited)) {
          if (before !== null) {
            try {
              fs.writeFileSync(path.join(state, "legacy_edit"), "", { flag: "wx" });
              stampAt(path.join(state, "legacy_edit"), before);
            } catch {}
          }
          touch(path.join(edited, editorKey));
        }
        // a new code edit re-arms this session's nudge, and an older copy's
        removeFile(path.join(state, "nudged-sessions", editorKey));
        removeOlderMarker(state);
      }
      // Opt-in diagnostic (LUCIAZERO_EDIT_DIAG=1): one line per edit event in
      // the state directory, next to last_edit, saying what the event carried
      // and what the hook made of it -- the tool's name, the opaque tool key,
      // whether file_path was missing, empty or present, its suffix, whether it
      // lay under cwd, and whether the edit counted. Never the path, never the
      // content. For finding out what touched last_edit when no visible edit did.
      if (process.env.LUCIAZERO_EDIT_DIAG === "1") {
        let inCwd = "-";
        let ext = "-";
        if (filePath) {
          const under = (dir) => [dir + "/", ...(WINDOWS ? [dir + "\\"] : [])]
            .some((prefix) => (WINDOWS ? filePath.toLowerCase().startsWith(prefix.toLowerCase()) : filePath.startsWith(prefix)));
          inCwd = under(cwd) ? "yes" : "no";
          if (base.includes(".")) ext = base.slice(base.lastIndexOf(".") + 1);
        }
        const ts = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
        try {
          fs.appendFileSync(path.join(state, "edit-diag.log"),
            `ts=${ts} mode=${mode} tool=${field(input, "tool_name") || "-"} key=${toolKey} file_path=${filePathState} ext=${ext} in_cwd=${inCwd} counted=${counted}\n`);
        } catch {}
      }
      return 0;
    }
    case "bash":
    case "bash-failure": {
      mkdirs(path.join(telemetry, "bash_count"), path.join(telemetry, "bash_intervals"));
      touch(path.join(telemetry, "bash_count", toolKey));
      const startMs = readTrimmed(path.join(telemetry, "bash_start_ms", toolKey));
      if (/^\d+$/.test(startMs) && nowMs >= Number(startMs)) {
        write(path.join(telemetry, "bash_intervals", toolKey), startMs + " " + nowMs + "\n");
      }
      const verifyCmd = process.env.LUCIAZERO_VERIFY_CMD || "";
      const verifyRe = process.env.LUCIAZERO_VERIFY_REGEX || DEFAULT_VERIFY_RE;
      let isVerify = false;
      if (command) {
        if (verifyCmd) {
          // exact mode: the command must BE or START WITH the configured command
          isVerify = command === verifyCmd || command.startsWith(verifyCmd + " ");
        } else if (anyLine(command, verifyRe)) {
          isVerify = true;
          // the collector's report runs nothing
          if (!process.env.LUCIAZERO_VERIFY_REGEX && anyLine(command, "test-timings\\.sh +--report")) isVerify = false;
        }
      }
      // A command started in the background has no result yet: its
      // PostToolUse marks the launch, and a later failure comes back as a
      // notice, never as a failed tool call. It counts, and records nothing.
      const background = toolInput !== null && typeof toolInput === "object" && toolInput.run_in_background === true;
      if (isVerify && background) {
        mkdirs(path.join(telemetry, "verify_count"));
        touch(path.join(telemetry, "verify_count", toolKey));
      } else if (isVerify) {
        mkdirs(path.join(telemetry, "verify_count"));
        touch(path.join(telemetry, "verify_count", toolKey));
        // Red/green came from the tool response; failure hooks are red.
        if (mode === "bash-failure") status = "fail";
        // A green that follows a green with no code edit between them proved
        // nothing new: count it (schema 3 `redundant_green_count`) before the
        // state below overwrites the previous result.
        if (status === "ok") {
          const lastEdit = mtime(path.join(state, "last_edit"));
          const lastVerify = mtime(path.join(state, "last_verify"));
          if (readTrimmed(path.join(state, "last_verify")) === "ok" && lastVerify !== null
              && (lastEdit === null || lastEdit <= lastVerify)) {
            mkdirs(path.join(telemetry, "redundant_green"));
            touch(path.join(telemetry, "redundant_green", toolKey));
          }
        }
        const started = /^\d+$/.test(startMs) && nowMs >= Number(startMs) ? Number(startMs) : null;
        if (recordVerify(state, status || "ran", started, command)) settleNudged(state);
      }
      return 0;
    }
    case "skill":
    case "skill-prompt": {
      if (mode === "skill-prompt" && field(input, "expansion_type") !== "slash_command") return 0;
      mkdirs(path.join(telemetry, "skill_count"));
      touch(path.join(telemetry, "skill_count", toolKey));
      return 0;
    }
    case "stop": {
      // Never re-block a continuation that a stop hook itself caused; that
      // continuation is the turn ending, so the turn closes here.
      const active = field(input, "stop_hook_active");
      if (active === "True" || active === "true") {
        endTurn();
        return 0;
      }
      // Strict gate (opt-in, see header): actually run the user's verify
      // command unless the tracked state is already green-after-last-edit. Any
      // internal error — timeout, missing command, unparseable state — degrades
      // to the ordinary fail-open nudge below, never to a block.
      const strict = process.env.LUCIAZERO_STRICT_VERIFY_CMD || "";
      if (strict) {
        const startMs = Date.now();
        let outcome;
        try {
          outcome = runStrict(state, project, strict, process.env.LUCIAZERO_STRICT_TIMEOUT || "120");
        } catch {
          outcome = { verdict: "error" };
        }
        if (outcome.verdict === "green") {
          statLog("stop-clean", ctx);
          endTurn();
          return 0;
        }
        if (outcome.verdict === "ok") {
          recordStrictTelemetry(startMs);
          if (recordVerify(state, "ok", startMs, strict)) settleNudged(state);
          statLog("stop-clean", ctx);
          endTurn();
          return 0;
        }
        if (outcome.verdict === "red") {
          recordStrictTelemetry(startMs);
          recordVerify(state, "fail", startMs, strict);
          statLog("strict-block", ctx);
          process.stderr.write(`Strict verify gate: '${strict}' is RED. Fix it before finishing — or say plainly that you are handing back a red state. Failing output:\n`);
          process.stderr.write("\n" + outcome.tail + "\n");
          return 2;
        }
        // error — fall through to the ordinary fail-open nudge
      }
      // The nudge goes to the session whose edits are unverified, once each
      // however the sessions' stops interleave: one that made no edit stops
      // clean while another session's edit waits for a verify.
      const lastEdit = lastEditOf(state, editorKey);
      const lastVerify = mtime(path.join(state, "last_verify"));
      const nudge = lastEdit !== null && (lastVerify === null || lastEdit > lastVerify);
      const nudged = path.join(state, "nudged-sessions");
      if (nudge && !isFile(path.join(nudged, editorKey))) {
        if (mkdirs(nudged)) touch(path.join(nudged, editorKey));
        statLog("nudge", ctx);
        process.stderr.write(NUDGE_TEXT + "\n");
        return 2;
      }
      // a genuinely clean stop logs a row; yes-but-already-nudged logs nothing
      // (that nudge was counted when it fired). Either way the turn ends here.
      if (!nudge) statLog("stop-clean", ctx);
      endTurn();
      return 0;
    }
    case "session": {
      // A marker left behind by a session that never reached its stop (crash,
      // kill, resume) would make the first real prompt look like a
      // notification and keep stale counters. Compaction is the one start
      // that happens inside a live session, possibly mid-turn, so it leaves
      // the marker alone.
      if (field(input, "source") !== "compact") endTurn();
      // A committed settings env block that reconfigures this hook is worth
      // one loud line: the refusal above is silent, and a repository that
      // ships these keys is either mistaken or hostile. Names the keys, never
      // their values.
      if (refused.length) {
        process.stdout.write(`This repository's committed .claude/settings.json sets ${refused.join(" ")} — Luciazero refuses those keys from project scope (they can disable verify tracking or run a command at every stop). Review that env block before trusting this repo.\n`);
      }
      // SessionStart emits ONE pointer, never the relay contents. A legacy
      // HANDOFF.md gets a migration warning but is not silently rewritten.
      const relay = path.join(cwd, "LUCIA_RELAY.json");
      if (!isFile(relay)) {
        if (isFile(path.join(cwd, "HANDOFF.md"))) {
          process.stdout.write("Legacy HANDOFF.md exists — read and re-verify it, then migrate the still-relevant state with /lucia-relay or delete the stale capsule.\n");
        }
        return 0;
      }
      const relayMtime = mtime(relay);
      const age = relayMtime === null ? "" : String(Math.floor((Date.now() - relayMtime) / 86400000));
      const stale = process.env.LUCIAZERO_RELAY_STALE_DAYS || process.env.LUCIAZERO_HANDOFF_STALE_DAYS || "7";
      if (/^-?\d+$/.test(age) && /^-?\d+$/.test(stale.trim()) && Number(age) >= Number(stale.trim())) {
        process.stdout.write(`LUCIA_RELAY.json exists but is ${age} days old — likely stale. Run /lucia-relay inspect, verify its claims with extra suspicion, then consume or replace it.\n`);
      } else {
        process.stdout.write(`LUCIA_RELAY.json exists (age: ${age || "?"}d) — run /lucia-relay inspect before touching code, re-verify its evidence, then consume it.\n`);
      }
      return 0;
    }
    default:
      return 0;
  }
}

module.exports = { stateBase, stateKey, projectOf, trustedBase, ere, anyLine, readStdin };

if (require.main === module) {
  try {
    process.exitCode = main(process.argv.slice(2));
  } catch {
    process.exitCode = 0; // FAILS OPEN
  }
}
