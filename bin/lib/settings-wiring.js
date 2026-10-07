"use strict";
// Wires, checks and removes the enforcement pack's entries in a Claude Code
// settings.json. One implementation for every installer: install.sh and
// uninstall.sh call it as a program on macOS and Linux, and the Node installer
// requires it on Windows, so the rules for what is ours never differ by
// platform.
//
//   node settings-wiring.js wire <check|write> <settings.json> <hooks dir>
//       exit 0 wired (or would be), 1 cannot be wired -- nothing written;
//       `check` prints `changes` or `unchanged`: whether `write` would write
//   node settings-wiring.js status <settings.json> <hooks dir>
//       prints the subcommands not wired, space-led; exit 1 if unreadable
//   node settings-wiring.js clean <settings.json> <config dir>
//       exit 0 nothing of ours, 10 ours removed (backup written first),
//       anything else: settings.json left exactly as it was
//
// The hooks are wired in exec form -- `"command": "node"` with the script and
// subcommand in `args` -- so no shell ever parses the path, on any platform.
// The status line has no exec form, so its command names the script only as
// base64 inside a fixed `node -e` program: the command holds no character any
// shell (sh, Git Bash, PowerShell, cmd.exe) treats specially, whatever the
// path contains. Entries older versions wrote -- the Bash hooks, as a quoted
// or bare shell string -- are recognised and migrated or removed exactly.

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const WINDOWS = process.platform === "win32";
const SUBS = ["prompt", "skill-prompt", "bash-start", "edit", "bash", "bash-failure", "skill", "stop", "session"];
// PowerShell is the shell tool on Windows wherever it is enabled, and the only
// one when Git Bash is missing; a matcher of Bash alone never fires there.
const SHELL_TOOLS = "Bash|PowerShell";
const WIRING = [
  ["PostToolUse", "Edit|Write|NotebookEdit", "edit"],
  ["PostToolUse", SHELL_TOOLS, "bash"],
  ["PostToolUse", "Skill", "skill"],
  ["PostToolUseFailure", SHELL_TOOLS, "bash-failure"],
  ["PreToolUse", SHELL_TOOLS, "bash-start"],
  ["UserPromptSubmit", null, "prompt"],
  ["UserPromptExpansion", null, "skill-prompt"],
  ["Stop", null, "stop"],
  ["SessionStart", null, "session"],
];

// The directory joined as the shell scripts always joined it: unnormalized,
// so a path written by an older install is found byte for byte.
function join(dir, name) {
  return /[\\/]$/.test(dir) ? dir + name : dir + (WINDOWS ? "\\" : "/") + name;
}

// Whether two paths name the same script however each was spelled: a config
// dir given with a trailing or doubled separator is joined as given, and an
// install, a reinstall and an uninstall need not have been given it alike.
function samePath(a, b) {
  if (a === b) return true;
  if (typeof a !== "string" || typeof b !== "string" || !path.isAbsolute(a) || !path.isAbsolute(b)) return false;
  const canon = (p) => (WINDOWS ? path.resolve(p).toLowerCase() : path.resolve(p));
  return canon(a) === canon(b);
}

function names(hooksDir) {
  return {
    verify: join(hooksDir, "luciazero-verify.cjs"),
    status: join(hooksDir, "luciazero-statusline.cjs"),
    legacyVerify: join(hooksDir, "luciazero-verify.sh"),
    legacyStatus: join(hooksDir, "luciazero-statusline.sh"),
  };
}

function statusCommand(script) {
  const encoded = Buffer.from(script, "utf8").toString("base64");
  return `node -e "require(Buffer.from('${encoded}','base64').toString('utf8'))"`;
}

// The script a status-line command of that exact shape runs, or null.
function statusScript(command) {
  const match = /^node -e "require\(Buffer\.from\('([A-Za-z0-9+/]*={0,2})','base64'\)\.toString\('utf8'\)\)"$/.exec(command);
  return match ? Buffer.from(match[1], "base64").toString("utf8") : null;
}

// POSIX shell words, as Python's shlex.split read the commands older installs
// wrote: quotes, backslash escapes, whitespace. null when it does not parse.
function shellWords(text) {
  const words = [];
  let word = null;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "'") {
      const end = text.indexOf("'", i + 1);
      if (end < 0) return null;
      word = (word || "") + text.slice(i + 1, end);
      i = end;
    } else if (c === '"') {
      word = word || "";
      for (i++; ; i++) {
        if (i >= text.length) return null;
        if (text[i] === '"') break;
        // shlex: inside double quotes a backslash escapes only `"` and itself
        if (text[i] === "\\" && i + 1 < text.length && (text[i + 1] === '"' || text[i + 1] === "\\")) i++;
        word += text[i];
      }
    } else if (c === "\\") {
      if (i + 1 >= text.length) return null;
      word = (word || "") + text[++i];
    } else if (c === " " || c === "\t" || c === "\r" || c === "\n") {
      if (word !== null) words.push(word);
      word = null;
    } else {
      word = (word || "") + c;
    }
  }
  if (word !== null) words.push(word);
  return words;
}

// [script, subcommand] for a shell-string command naming one of `scripts`,
// in either spelling older installs wrote: shell-quoted, or the bare path --
// including a bare path with a space in it, which never parsed back.
function legacyCommand(command, scripts) {
  if (typeof command !== "string") return null;
  for (const script of scripts) {
    if (command === script) return [script, ""];
    if (command.startsWith(script + " ")) return [script, command.slice(script.length + 1).trim()];
  }
  const words = shellWords(command);
  const script = words && words.length ? scripts.find((s) => samePath(s, words[0])) : undefined;
  if (script !== undefined) return [script, words.slice(1).join(" ")];
  return null;
}

// What a hook object runs, as [script, subcommand], when it is one of ours;
// the script as `n` spells it. Wiring looks for the verify hook only; removal
// (`broad`) takes anything that runs either script, since both are about to
// be deleted and an entry left naming one would run a file that is gone.
function ourHook(hook, n, broad) {
  if (hook === null || typeof hook !== "object" || Array.isArray(hook)) return null;
  const scripts = broad ? [n.verify, n.status] : [n.verify];
  if (Array.isArray(hook.args)) {
    const script = hook.command === "node" && hook.args.length >= 1 && hook.args.every((a) => typeof a === "string")
      ? scripts.find((s) => samePath(s, hook.args[0])) : undefined;
    return script === undefined ? null : [script, hook.args.slice(1).join(" ")];
  }
  return legacyCommand(hook.command, broad ? [n.verify, n.status, n.legacyVerify, n.legacyStatus]
    : [n.verify, n.legacyVerify]);
}

function ourStatusLine(statusLine, n, broad) {
  if (statusLine === null || typeof statusLine !== "object" || Array.isArray(statusLine)) return false;
  if (typeof statusLine.command !== "string") return false;
  const script = statusScript(statusLine.command);
  if (samePath(script, n.status) || (broad && samePath(script, n.verify))) return true;
  const legacy = legacyCommand(statusLine.command, broad
    ? [n.legacyStatus, n.legacyVerify, n.status, n.verify] : [n.legacyStatus]);
  return legacy !== null && (broad || legacy[1] === "");
}

function shapeError(message) {
  const error = new Error(message);
  error.shape = true;
  return error;
}

// Only a settings.json that is not there, or a symlink to nothing, reads as
// empty. Any other failure to read it -- a symlink loop, a directory, no
// permission -- is an error, never a file to write fresh over it.
function readSettings(file) {
  let text;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch (error) {
    if (error.code === "ENOENT") return {};
    throw error;
  }
  // Windows PowerShell 5 saves UTF-8 with a byte order mark; JSON has none
  const settings = JSON.parse(text.charCodeAt(0) === 0xfeff ? text.slice(1) : text);
  if (settings === null || typeof settings !== "object" || Array.isArray(settings)) {
    throw shapeError("settings.json is valid JSON but not the shape hooks live in");
  }
  const hooks = settings.hooks;
  if (hooks !== undefined && (hooks === null || typeof hooks !== "object" || Array.isArray(hooks))) {
    throw shapeError("settings.json is valid JSON but not the shape hooks live in");
  }
  return settings;
}

// Every hook object of ours under `hooks`, with where it sits.
function* ours(hooks, n, broad) {
  for (const event of Object.keys(hooks)) {
    const entries = hooks[event];
    if (!Array.isArray(entries)) continue; // callers decide which events must be lists
    for (const entry of entries) {
      if (entry === null || typeof entry !== "object" || Array.isArray(entry)) continue;
      if (entry.hooks === undefined) continue;
      if (!Array.isArray(entry.hooks)) throw shapeError(`settings.json hooks.${event} holds an entry whose hooks are not a list`);
      for (const hook of entry.hooks) {
        const found = ourHook(hook, n, broad);
        if (found) yield { event, entry, hook, script: found[0], sub: found[1] };
      }
    }
  }
}

function dropHook(hooks, event, entry, hook) {
  entry.hooks = entry.hooks.filter((h) => h !== hook);
  if (!entry.hooks.length) hooks[event] = hooks[event].filter((e) => e !== entry);
  if (!hooks[event].length) delete hooks[event];
}

// Make `settings` carry exactly one current entry per subcommand. Returns
// whether anything changed and what the status line did.
function wire(settings, hooksDir) {
  const n = names(hooksDir);
  let changed = false;
  if (settings.hooks === undefined) settings.hooks = {};
  const hooks = settings.hooks;
  for (const [event, matcher, sub] of WIRING) {
    if (hooks[event] !== undefined && !Array.isArray(hooks[event])) {
      throw shapeError(`settings.json hooks.${event} is not a list`);
    }
    const found = [...ours(hooks, n)].filter((o) => o.event === event && o.sub === sub);
    let keep = found[0];
    // a second copy of ours would run the hook twice: only the first stays
    for (const extra of found.slice(1)) {
      dropHook(hooks, extra.event, extra.entry, extra.hook);
      changed = true;
    }
    if (keep && (keep.entry.matcher === undefined ? null : keep.entry.matcher) !== matcher) {
      if (keep.entry.hooks.length === 1) {
        if (matcher === null) delete keep.entry.matcher;
        else keep.entry.matcher = matcher;
        changed = true;
      } else {
        // the entry holds the user's hooks too: theirs keep their matcher
        dropHook(hooks, keep.event, keep.entry, keep.hook);
        keep = undefined;
        changed = true;
      }
    }
    if (keep) {
      const hook = keep.hook;
      if (hook.command !== "node" || !Array.isArray(hook.args) || hook.args.length !== 2
          || hook.args[0] !== n.verify || hook.args[1] !== sub || hook.type !== "command") {
        // an older install's Bash entry, migrated in place; the user's other
        // fields on it (a timeout) stay
        hook.type = "command";
        hook.command = "node";
        hook.args = [n.verify, sub];
        delete hook.shell;
        changed = true;
      }
      continue;
    }
    const entry = { hooks: [{ type: "command", command: "node", args: [n.verify, sub] }] };
    if (matcher !== null) entry.matcher = matcher;
    if (hooks[event] === undefined) hooks[event] = [];
    hooks[event].push(entry);
    changed = true;
  }

  const want = statusCommand(n.status);
  const statusLine = settings.statusLine;
  let statusNote;
  if (statusLine === undefined || statusLine === null) {
    settings.statusLine = { type: "command", command: want };
    changed = true;
    statusNote = "wired";
  } else if (ourStatusLine(statusLine, n)) {
    if (statusLine.command !== want || statusLine.type !== "command") {
      statusLine.type = "command";
      statusLine.command = want;
      changed = true;
      statusNote = "rewritten";
    } else {
      statusNote = "already";
    }
  } else {
    statusNote = "skipped";
  }
  return { changed, statusNote, statusWant: want };
}

// Subcommands not wired in the current form, in SUBS order.
function missing(settings, hooksDir) {
  const n = names(hooksDir);
  const wired = new Set();
  const hooks = settings.hooks || {};
  for (const event of Object.keys(hooks)) {
    const entries = Array.isArray(hooks[event]) ? hooks[event] : [];
    for (const entry of entries) {
      const inner = entry && typeof entry === "object" && Array.isArray(entry.hooks) ? entry.hooks : [];
      for (const hook of inner) {
        const found = ourHook(hook, n);
        if (found && found[0] === n.verify && Array.isArray(hook.args)) wired.add(found[1]);
      }
    }
  }
  return SUBS.filter((s) => !wired.has(s));
}

// Remove every entry of ours, current or legacy. Returns whether anything
// changed.
function clean(settings, configDir) {
  const n = names(join(configDir, "hooks"));
  let changed = false;
  const hooks = settings.hooks || {};
  for (const event of Object.keys(hooks)) {
    if (!Array.isArray(hooks[event])) throw shapeError(`settings.json hooks.${event} is not a list`);
  }
  for (const found of [...ours(hooks, n, true)]) {
    dropHook(hooks, found.event, found.entry, found.hook);
    changed = true;
  }
  if (ourStatusLine(settings.statusLine, n, true)) {
    delete settings.statusLine;
    changed = true;
  }
  return changed;
}

function render(settings) {
  return JSON.stringify(settings, null, 2) + "\n";
}

// Replace a file whole: the new bytes go to a fresh name beside it and are
// renamed over it, so a failed write leaves every old byte (roadmap R14).
// Windows can refuse a rename while another program holds the file open (a
// virus scanner, an editor); that is retried briefly, nothing else is.
function replaceFile(target, text, mode) {
  const dir = path.dirname(target);
  let tmp;
  let fd = null;
  for (let attempt = 0; ; attempt++) {
    tmp = path.join(dir, "." + path.basename(target) + "." + crypto.randomBytes(6).toString("hex"));
    try {
      fd = fs.openSync(tmp, "wx", 0o600);
      break;
    } catch (error) {
      if (error.code !== "EEXIST" || attempt > 100) throw error;
    }
  }
  try {
    fs.writeFileSync(fd, text, "utf8");
    fs.closeSync(fd);
    fd = null;
    if (mode !== null) fs.chmodSync(tmp, mode);
    for (let attempt = 0; ; attempt++) {
      try {
        fs.renameSync(tmp, target);
        break;
      } catch (error) {
        if (!WINDOWS || !["EBUSY", "EPERM", "EACCES"].includes(error.code) || attempt >= 20) throw error;
        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 50);
      }
    }
  } catch (error) {
    if (fd !== null) {
      try {
        fs.closeSync(fd);
      } catch {}
    }
    try {
      fs.rmSync(tmp, { force: true });
    } catch {}
    throw error;
  }
}

function defaultMode() {
  if (WINDOWS) return null;
  const umask = process.umask();
  return 0o666 & ~umask;
}

// A symlinked settings.json (a dotfiles repository) is read and written at
// the file it points at, so the link survives. Not writable is refused, since
// replacing the file whole would otherwise go around its permission bits, and
// so is a directory that cannot take the new file beside it. A symlink loop,
// or any failure to resolve other than a name that is not there, is refused
// too: the write would replace one of the links with a file.
function writableTarget(file) {
  let target = path.resolve(file);
  // a dangling link is written at the name it points to, which makes it whole
  let resolved = false;
  for (let hops = 0; hops < 40; hops++) {
    try {
      target = fs.realpathSync(target);
      resolved = true;
      break;
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    let link;
    try {
      link = fs.readlinkSync(target);
    } catch (error) {
      // not there, or not a link: this is the name the file is made at
      if (error.code !== "ENOENT" && error.code !== "EINVAL") throw error;
      resolved = true;
      break;
    }
    target = path.resolve(path.dirname(target), link);
  }
  if (!resolved) throw new Error("settings.json is a chain of more than 40 symlinks: " + file);
  if (fs.existsSync(file)) fs.accessSync(target, fs.constants.W_OK);
  fs.accessSync(path.dirname(target), fs.constants.W_OK | (WINDOWS ? 0 : fs.constants.X_OK));
  return target;
}

function stamp() {
  const d = new Date();
  const p = (v) => String(v).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

// A complete copy of `file` under `<file>.bak.<stamp>[.n]`, a name nothing
// else holds. The open that takes the name is O_CREAT|O_EXCL, which refuses
// anything already there -- a dangling symlink included -- without following
// it, and the bytes go through that descriptor, so the name is never resolved
// a second time. A copy that fails part way is removed.
function backup(file) {
  const base = file + ".bak." + stamp();
  let name = base;
  let fd = null;
  for (let n = 1; fd === null; n++) {
    try {
      fd = fs.openSync(name, "wx", 0o600);
    } catch (error) {
      if (error.code !== "EEXIST" || n > 100) throw error;
      name = base + "." + n;
    }
  }
  try {
    fs.writeFileSync(fd, fs.readFileSync(file));
    const info = fs.statSync(file);
    fs.fchmodSync(fd, info.mode & 0o7777);
    fs.futimesSync(fd, info.atime, info.mtime);
    fs.closeSync(fd);
    fd = null;
  } catch (error) {
    if (fd !== null) {
      try {
        fs.closeSync(fd);
      } catch {}
    }
    try {
      fs.rmSync(name, { force: true });
    } catch {}
    throw error;
  }
  return name;
}

function modeOf(target) {
  if (WINDOWS) return null;
  try {
    return fs.statSync(target).mode & 0o7777;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
    return defaultMode();
  }
}

// Whether wiring `file` would change it, or null when it cannot be wired
// (the reason printed). Writes nothing.
function wireCheck(file, hooksDir) {
  try {
    const settings = readSettings(file);
    writableTarget(file);
    return wire(settings, hooksDir).changed;
  } catch (error) {
    console.error("      " + (error.shape ? error.message : (error && error.message) || String(error)));
    return null;
  }
}

function main(argv) {
  const [command, ...rest] = argv;
  if (command === "wire") {
    const [mode, file, hooksDir] = rest;
    if (mode !== "write") {
      const changes = wireCheck(file, hooksDir);
      if (changes === null) return 1;
      console.log(changes ? "changes" : "unchanged");
      return 0;
    }
    const say = (text) => console.log(text);
    let settings;
    let target;
    let result;
    try {
      settings = readSettings(file);
      target = writableTarget(file);
      result = wire(settings, hooksDir);
    } catch (error) {
      console.error("      " + (error.shape ? error.message : (error && error.message) || String(error)));
      return 1;
    }
    if (result.statusNote === "wired") say("  ok  statusline wired");
    else if (result.statusNote === "rewritten") say("  ok  statusline rewritten to the Node status line");
    else if (result.statusNote === "already") say("  ok  statusline already wired");
    else {
      say("  !!  statusline SKIPPED — a custom statusLine exists; to use ours, set");
      say("      settings.json statusLine.command to: " + result.statusWant);
    }
    if (!result.changed) {
      console.log("  ok  hooks already wired");
      return 0;
    }
    try {
      replaceFile(target, render(settings), modeOf(target));
    } catch (error) {
      console.error("      " + error.message);
      return 1;
    }
    console.log("  ok  hooks wired into settings.json");
    return 0;
  }
  if (command === "status") {
    const [file, hooksDir] = rest;
    let gaps;
    try {
      gaps = missing(fs.existsSync(file) ? readSettings(file) : {}, hooksDir);
    } catch {
      // what is wired in a file that cannot be read is unknown, not nothing
      return 1;
    }
    process.stdout.write(gaps.map((s) => " " + s).join(""));
    return 0;
  }
  if (command === "clean") {
    const [file, configDir] = rest;
    let settings;
    let changed;
    try {
      settings = readSettings(file);
      changed = clean(settings, configDir);
    } catch (error) {
      console.error("      " + error.message);
      return 1;
    }
    if (!changed) return 0;
    let saved;
    try {
      saved = backup(file);
    } catch (error) {
      console.error("      " + error.message);
      return 1;
    }
    try {
      const target = writableTarget(file);
      replaceFile(target, render(settings), modeOf(target));
    } catch (error) {
      console.error("      " + error.message);
      return 1;
    }
    console.log("  ok  backup: " + path.basename(saved));
    return 10;
  }
  console.error("usage: settings-wiring.js wire <check|write> <settings> <hooks dir> | status <settings> <hooks dir> | clean <settings> <config dir>");
  return 64;
}

module.exports = { SUBS, WIRING, names, statusCommand, statusScript, shellWords, legacyCommand, wire, wireCheck, missing, clean, render, replaceFile, backup, readSettings, writableTarget, modeOf, main };

if (require.main === module) {
  try {
    process.exitCode = main(process.argv.slice(2));
  } catch (error) {
    console.error("      " + ((error && error.message) || String(error)));
    process.exitCode = 1;
  }
}
