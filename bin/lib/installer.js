"use strict";
// The four installers in Node, for Windows, where there is no Bash to run
// install.sh, uninstall.sh, install-codex.sh and uninstall-codex.sh:
//
//   node installer.js claude [--with-hooks|--status]
//   node installer.js claude-uninstall
//   node installer.js codex
//   node installer.js codex-uninstall
//
// `npx luciazero` routes here on win32 only. On macOS and Linux the Bash
// scripts stay the installers; this module runs there under the parity gate
// (tests/gates/parity.sh), which installs and uninstalls the same fixtures
// both ways and compares every file, byte and line of output. So each step
// below follows its shell counterpart, message for message, and a change to
// one is a change to both.
//
// Where Windows needs something else, the difference is here and nowhere else:
// paths are joined with the native separator, a file read for its lines may
// end them in CRLF and keeps them that way, a symlink backup is made with the
// type Windows needs, the Agent Bus launcher is a .cmd, and executable bits do
// not exist.

const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");
const wiring = require("./settings-wiring.js");

const WINDOWS = process.platform === "win32";
const SEP = WINDOWS ? "\\" : "/";
const SRC = path.resolve(__dirname, "..", "..");
const DOCTRINE = "luciazero.md";
const IMPORT_LINE = "@" + DOCTRINE;
const IMPORT_MARKER = "luciazero-managed: import-provenance";
const AGENTD_MARKER = "luciazero-managed: agentd-launcher";
const AGENTD_SERVICE_MARKER = "luciazero-managed: agentd-service";
const START = "<!-- luciazero:start -->";
const END = "<!-- luciazero:end -->";
const ADDED_NL_MARK = "<!-- luciazero:added-final-newline -->";

class Exit extends Error {
  constructor(code) {
    super("exit " + code);
    this.code = code;
  }
}

const say = (line) => process.stdout.write(line + "\n");
const warn = (line) => process.stderr.write(line + "\n");

// Joined as the shell scripts join them, "${DIR}/name", so every path in a
// message reads the same on both sides of the parity gate.
function j(...parts) {
  return parts.join(SEP);
}

// The shell's file tests. `exists` is `[ -e ] || [ -L ]`: anything at all,
// a dangling symlink included.
function lstat(p) {
  try {
    return fs.lstatSync(p);
  } catch {
    return null;
  }
}
function stat(p) {
  try {
    return fs.statSync(p);
  } catch {
    return null;
  }
}
const exists = (p) => lstat(p) !== null;
const isLink = (p) => {
  const s = lstat(p);
  return s !== null && s.isSymbolicLink();
};
const isFile = (p) => {
  const s = stat(p);
  return s !== null && s.isFile();
};
const isDir = (p) => {
  const s = stat(p);
  return s !== null && s.isDirectory();
};
const nonEmpty = (p) => {
  const s = stat(p);
  return s !== null && s.size > 0;
};
// No execute bit on Windows: present is as executable as a file gets there.
function isExecutable(p) {
  if (!isFile(p)) return false;
  if (WINDOWS) return true;
  try {
    fs.accessSync(p, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function readBytes(p) {
  try {
    return fs.readFileSync(p);
  } catch {
    return null;
  }
}
// Bytes as a string, one character per byte, so a rewrite gives back every
// byte it did not mean to change whatever the encoding.
function readRaw(p) {
  const b = readBytes(p);
  return b === null ? null : b.toString("latin1");
}
function cmp(a, b) {
  const x = readBytes(a);
  const y = readBytes(b);
  return x !== null && y !== null && x.equals(y);
}
function sha256(p) {
  const b = readBytes(p);
  return b === null ? "" : crypto.createHash("sha256").update(b).digest("hex");
}

// Lines as `grep -x` sees them, except that a CRLF line is the same line: a
// file saved on Windows says the same thing as one saved anywhere else.
function lines(text) {
  if (text === "") return [];
  const out = text.split("\n");
  if (out[out.length - 1] === "") out.pop();
  return out.map((l) => (l.endsWith("\r") ? l.slice(0, -1) : l));
}
function countLine(p, want) {
  const t = readRaw(p);
  return t === null ? 0 : lines(t).filter((l) => l === want).length;
}

function catalog(file) {
  return lines(fs.readFileSync(file, "utf8")).filter((l) => !/^[ \t\v\f]*#/.test(l) && !/^[ \t\v\f]*$/.test(l));
}
function skillInventory() {
  return [...catalog(j(SRC, "skills", "catalog.txt")), ...catalog(j(SRC, "skills", "aliases.txt"))];
}
function versionOf() {
  const t = readRaw(j(SRC, "package.json"));
  if (t === null) return "";
  for (const l of lines(t)) {
    if (/^[ \t]*"version"[ \t]*:/.test(l)) return l.split('"')[3] || "";
  }
  return "";
}

function stamp() {
  const d = new Date();
  const p = (v) => String(v).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

function umask() {
  if (WINDOWS) return 0;
  const u = process.umask(0o022);
  process.umask(u);
  return u;
}

function mkdirp(dir) {
  fs.mkdirSync(dir, { recursive: true });
}
function chmodX(p) {
  if (WINDOWS) return;
  fs.chmodSync(p, fs.statSync(p).mode | (0o111 & ~umask()));
}

// `rm -f`: one name, never followed, never a directory.
function rmFile(p) {
  try {
    fs.unlinkSync(p);
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
}
// `rm -rf`: a symlink is removed as itself and never entered -- on Windows a
// directory link or junction answers unlink with EPERM and goes with rmdir.
function rmTree(p) {
  const s = lstat(p);
  if (s === null) return;
  if (s.isSymbolicLink()) {
    try {
      fs.unlinkSync(p);
    } catch (error) {
      if (!WINDOWS) throw error;
      fs.rmdirSync(p);
    }
  } else if (s.isDirectory()) {
    for (const name of fs.readdirSync(p)) rmTree(path.join(p, name));
    fs.rmdirSync(p);
  } else {
    fs.unlinkSync(p);
  }
}
function rmdirQuiet(...dirs) {
  for (const d of dirs) {
    try {
      fs.rmdirSync(d);
    } catch {}
  }
}

function symlinkType(target, linkPath) {
  if (!WINDOWS) return undefined;
  return isDir(path.resolve(path.dirname(linkPath), target)) ? "dir" : "file";
}

// A new file at `dst`, which must be free: `wx` refuses anything there,
// a dangling symlink included, without following it.
function copyFileNew(src, dst, preserve) {
  const info = fs.statSync(src);
  const fd = fs.openSync(dst, "wx", info.mode & 0o777);
  try {
    fs.writeFileSync(fd, fs.readFileSync(src));
    if (preserve && !WINDOWS) {
      fs.fchmodSync(fd, info.mode & 0o7777);
    }
    if (preserve) fs.futimesSync(fd, info.atime, info.mtime);
  } finally {
    fs.closeSync(fd);
  }
}

// The entries of directory `src` into directory `dst`, as `cp -RP src/. dst/`
// writes them, except that every entry is created exactly: one already there
// fails the copy rather than being overwritten or followed.
function copyInto(src, dst, preserve) {
  for (const name of fs.readdirSync(src)) {
    const from = path.join(src, name);
    const to = path.join(dst, name);
    const s = fs.lstatSync(from);
    if (s.isSymbolicLink()) {
      const target = fs.readlinkSync(from);
      fs.symlinkSync(target, to, symlinkType(target, from));
    } else if (s.isDirectory()) {
      fs.mkdirSync(to, s.mode & 0o777);
      copyInto(from, to, preserve);
    } else {
      copyFileNew(from, to, preserve);
    }
  }
}
// `cp -R src dst` with nothing at dst.
function copyTree(src, dst) {
  fs.mkdirSync(dst, fs.statSync(src).mode & 0o777);
  copyInto(src, dst, false);
}

// `diff -qr a b` agrees: both real directories, the same names all the way
// down, and the same bytes in every file. Entries are followed as diff
// follows them.
function sameTree(a, b) {
  const sa = lstat(a);
  const sb = lstat(b);
  if (!sa || !sb || sa.isSymbolicLink() || sb.isSymbolicLink() || !sa.isDirectory() || !sb.isDirectory()) return false;
  const walk = (x, y) => {
    let nx;
    let ny;
    try {
      nx = fs.readdirSync(x).sort();
      ny = fs.readdirSync(y).sort();
    } catch {
      return false;
    }
    if (nx.length !== ny.length || nx.some((n, i) => n !== ny[i])) return false;
    for (const n of nx) {
      const px = path.join(x, n);
      const py = path.join(y, n);
      const tx = stat(px);
      const ty = stat(py);
      if (!tx || !ty) return false;
      if (tx.isDirectory() && ty.isDirectory()) {
        if (!walk(px, py)) return false;
      } else if (tx.isFile() && ty.isFile()) {
        if (!cmp(px, py)) return false;
      } else {
        return false;
      }
    }
    return true;
  };
  return walk(a, b);
}

// install.sh's `bakcopy`: a copy of `src` at the first free
// `<base>.bak.<stamp>[.n]`. The name is taken by the call that creates it --
// `mkdir`, a `wx` open, or `symlink` -- which fails when anything at all is
// there and never follows it, so a name planted before or after it was chosen
// is skipped, not written through. `follow` backs up what a symlink points at;
// without it a symlink is backed up as itself. A tree is copied into the
// directory `mkdir` made with every entry created exactly, so an entry
// already there stops the copy instead of being replaced.
function bakcopy(follow, src, base) {
  const st = stamp();
  let kind = "file";
  if (!follow && isLink(src)) kind = "link";
  else if (isDir(src)) kind = "tree";
  let target = null;
  let fd = null;
  let name = base + ".bak." + st;
  for (let n = 0; ; ) {
    try {
      if (kind === "tree") fs.mkdirSync(name);
      else if (kind === "link") {
        target = fs.readlinkSync(src);
        fs.symlinkSync(target, name, symlinkType(target, src));
      } else {
        fd = fs.openSync(name, "wx", 0o600);
      }
      break;
    } catch (error) {
      if (error.code === "EEXIST" && n < 100) {
        n++;
        name = base + ".bak." + st + "." + n;
        continue;
      }
      if (kind === "link" && WINDOWS && error.code === "EPERM") {
        warn(`FAIL: could not back up the symlink ${src}, so it was left as it is: creating a symlink needs Developer Mode or an elevated prompt on Windows`);
      } else {
        warn(`FAIL: could not reserve a backup name for ${src} (${error.code || error.message})`);
      }
      warn(`FAIL: could not back up ${src}`);
      throw new Exit(1);
    }
  }
  try {
    if (kind === "tree") copyInto(src, name, false);
    if (kind === "file") {
      const info = fs.statSync(src);
      fs.writeFileSync(fd, fs.readFileSync(src));
      if (!WINDOWS) fs.fchmodSync(fd, info.mode & 0o7777);
      fs.futimesSync(fd, info.atime, info.mtime);
    }
  } catch {
    warn(`FAIL: could not back up ${src}`);
    throw new Exit(1);
  } finally {
    if (fd !== null) fs.closeSync(fd);
  }
  return name;
}

function claudeDir() {
  return process.env.CLAUDE_CONFIG_DIR || j(os.homedir(), ".claude");
}
function codexDir() {
  return process.env.CODEX_HOME || j(os.homedir(), ".codex");
}

function stripPrefix(p, prefix) {
  return p.startsWith(prefix) ? p.slice(prefix.length) : p;
}

function onPath(dir) {
  const entries = (process.env.PATH || "").split(path.delimiter);
  if (!WINDOWS) return entries.includes(dir);
  const norm = (d) => d.replace(/[\\/]+$/, "").toLowerCase();
  return entries.some((e) => norm(e) === norm(dir));
}

// The tree and file installs both installers share, labelled for messages
// relative to `home`.
function installers(home, backupDir) {
  function backupTree(src, label) {
    const base = j(backupDir, label);
    mkdirp(path.dirname(base));
    const dst = bakcopy(false, src, base);
    say(`  ok  backed up existing ${label} -> ${stripPrefix(dst, home + SEP)}`);
  }
  function installTree(src, dst, snapshot, label) {
    if (exists(dst)) {
      if (!sameTree(dst, snapshot) && !sameTree(dst, src)) backupTree(dst, label);
      rmTree(dst);
    }
    mkdirp(path.dirname(dst));
    mkdirp(path.dirname(snapshot));
    copyTree(src, dst);
    rmTree(snapshot);
    copyTree(src, snapshot);
  }
  function installFile(src, dst, snapshot, label) {
    if (exists(dst)) {
      let ours = false;
      if (isFile(dst) && !isLink(dst)) {
        if ((isFile(snapshot) && cmp(dst, snapshot)) || cmp(dst, src)) ours = true;
      }
      if (!ours) {
        const base = j(backupDir, label);
        mkdirp(path.dirname(base));
        const saved = bakcopy(false, dst, base);
        say(`  ok  backed up existing ${label} -> ${stripPrefix(saved, home + SEP)}`);
      }
      rmFile(dst);
    }
    mkdirp(path.dirname(dst));
    mkdirp(path.dirname(snapshot));
    copyFileNew(src, dst, false);
    rmFile(snapshot);
    copyFileNew(src, snapshot, false);
  }
  function removeLegacyTree(dst, snapshot, label) {
    if (!exists(dst)) {
      if (!isLink(path.dirname(snapshot))) rmTree(snapshot);
      return;
    }
    if (isLink(path.dirname(dst)) || isLink(path.dirname(snapshot))) {
      warn(`  !!  ${label} has a symlinked parent; left untouched`);
    } else if (sameTree(dst, snapshot)) {
      rmTree(dst);
      rmTree(snapshot);
      say(`  ok  migrated ${label}`);
    } else {
      warn(`  !!  ${label} is customized or not Luciazero-owned; left untouched`);
    }
  }
  function migrateHandoff(dir) {
    const legacy = j(dir, "skills", "handoff");
    if (isFile(j(legacy, "SKILL.md"))) {
      if (cmp(j(SRC, "migrations", "handoff-v1.5.0.SKILL.md"), j(legacy, "SKILL.md"))) {
        rmTree(legacy);
        say("  ok  migrated skill handoff -> lucia-relay");
      } else {
        warn("  !!  skills/handoff is customized; left untouched (Luciazero now uses /lucia-relay)");
      }
    }
  }
  return { installTree, installFile, removeLegacyTree, migrateHandoff };
}

// A symlink anywhere between the config dir and a path about to be deleted
// can redirect the delete outside it; the config dir itself may be a symlink.
function parentsSafe(root, p) {
  const top = root.replace(/[\\/]+$/, "");
  let dir = path.dirname(p);
  while (dir !== top && dir !== path.parse(dir).root && dir !== ".") {
    if (isLink(dir)) return false;
    const next = path.dirname(dir);
    if (next === dir) break;
    dir = next;
  }
  return true;
}

function removers(home) {
  function removeManagedTree(dst, snapshot, shipped, label, allowShipped = true) {
    if (!parentsSafe(home, dst) || !parentsSafe(home, snapshot)) {
      warn(`  !!  ${label} has a symlinked parent; left untouched`);
      return;
    }
    if (!exists(dst)) {
      say(`  ok  ${label} (already absent)`);
    } else if (sameTree(dst, snapshot) || (allowShipped && !exists(snapshot) && sameTree(dst, shipped))) {
      rmTree(dst);
      say(`  ok  ${label}`);
    } else {
      warn(`  !!  ${label} is not the exact Luciazero-managed copy; left untouched`);
    }
    rmTree(snapshot);
  }
  function removeManagedFile(dst, snapshot, shipped, label) {
    if (!parentsSafe(home, dst) || !parentsSafe(home, snapshot)) {
      warn(`  !!  ${label} has a symlinked parent; left untouched`);
      return;
    }
    if (!exists(dst)) {
      say(`  ok  ${label} (already absent)`);
    } else if (
      isFile(dst) &&
      !isLink(dst) &&
      ((isFile(snapshot) && cmp(dst, snapshot)) || (!exists(snapshot) && cmp(dst, shipped)))
    ) {
      rmFile(dst);
      say(`  ok  ${label}`);
    } else {
      warn(`  !!  ${label} is not the exact Luciazero-managed copy; left untouched`);
    }
    rmFile(snapshot);
  }
  return { removeManagedTree, removeManagedFile };
}

// ---------------------------------------------------------------- Claude Code

function agentdLayout(dir) {
  const binDir = process.env.LUCIAZERO_BIN_DIR || j(dir, "bin");
  // Windows runs a launcher by its extension; the same .cmd goes in twice,
  // as install.sh puts its shell launcher in twice.
  const ext = WINDOWS ? ".cmd" : "";
  return {
    binDir,
    names: ["luciazero-agentd" + ext, "lucia" + ext],
    source: j(SRC, "bin", "luciazero-agentd" + ext),
    launcher: j(binDir, "luciazero-agentd" + ext),
    homeFile: j(dir, ".luciazero-agentd-home"),
  };
}

function launcherKind(p) {
  if (isLink(p)) {
    const t = readRaw(p);
    return t !== null && t.includes(AGENTD_MARKER) ? "symlink" : "foreign";
  }
  if (exists(p)) {
    const t = isFile(p) ? readRaw(p) : null;
    return t !== null && t.includes(AGENTD_MARKER) ? "ours" : "foreign";
  }
  return "absent";
}

function pathHint(dir) {
  return WINDOWS ? `add ${dir} to your user Path (System Properties > Environment Variables)` : `export PATH="${dir}:$PATH"`;
}

function pluginDoubleInstallNote(dir) {
  const registry = j(dir, "plugins", "installed_plugins.json");
  const t = isFile(registry) ? readRaw(registry) : null;
  if (t === null || !t.includes('"luciazero@')) return;
  say("  !!    Luciazero is also installed as a Claude Code plugin: every skill and the");
  say("        reviewer agent load twice per session. Keep one channel — /plugin uninstall");
  say("        luciazero@luciazero for the plugin, or ./uninstall.sh for this copy.");
}

function nodeOk() {
  return Number(process.versions.node.split(".")[0]) >= 18;
}

function claudeVersionNote(indent) {
  const r = spawnSync("claude", ["--version"], { encoding: "utf8", shell: WINDOWS, windowsHide: true });
  const first = r.status === 0 && typeof r.stdout === "string" ? r.stdout.split("\n")[0] : "";
  const m = /^([0-9]+\.[0-9]+\.[0-9]+)/.exec(first);
  if (!m) {
    say(`${indent}--    Claude Code version unknown — the hooks need 2.1.139 or newer`);
    return;
  }
  const v = m[1].split(".").map(Number);
  const want = [2, 1, 139];
  let newer = true;
  for (let i = 0; i < 3; i++) {
    if (v[i] !== want[i]) {
      newer = v[i] > want[i];
      break;
    }
  }
  if (newer) say(`${indent}ok    Claude Code ${m[1]} (the hooks need 2.1.139 or newer)`);
  else say(`${indent}!!    Claude Code ${m[1]} is older than 2.1.139 — it cannot run the hooks' exec-form entries; update Claude Code`);
}

function claudeStatus(dir) {
  say(`Status of ${dir} (read-only)`);
  let rc = 0;
  const check = (ok, label) => {
    if (ok) say(`  ok    ${label}`);
    else {
      say(`  MISS  ${label}`);
      rc = 1;
    }
  };
  check(isFile(j(dir, DOCTRINE)), `doctrine ${DOCTRINE}`);
  for (const skill of skillInventory()) check(isFile(j(dir, "skills", skill, "SKILL.md")), `skill ${skill}`);
  check(isExecutable(j(dir, "skills", "ready", "scripts", "detect.sh")), "detect.sh executable");
  check(isExecutable(j(dir, "skills", "done", "scripts", "revert-probe.sh")), "revert-probe.sh executable");
  check(isExecutable(j(dir, "skills", "bisect", "scripts", "safe-bisect.sh")), "safe-bisect.sh executable");
  check(isExecutable(j(dir, "skills", "lucia-relay", "scripts", "relay.py")), "relay.py executable");
  for (const agent of catalog(j(SRC, "claude", "agents", "catalog.txt"))) check(isFile(j(dir, "agents", agent + ".md")), `agent ${agent}`);
  const ad = agentdLayout(dir);
  if (isFile(j(SRC, "agentd", "luciazero_agentd", "__init__.py"))) {
    let any = false;
    for (const name of ad.names) {
      const kind = launcherKind(j(ad.binDir, name));
      if (kind === "ours" || kind === "symlink") {
        say(`  ok    agent bus launcher ${j(ad.binDir, name)}`);
        any = true;
      } else if (kind === "foreign") {
        say(`  MISS  ${j(ad.binDir, name)} is not the Luciazero launcher (left untouched)`);
        rc = 1;
      } else {
        say(`  --    ${name} not installed (optional; ./install.sh installs it)`);
      }
    }
    if (any) {
      if (!onPath(ad.binDir)) say(`        (not on PATH: ${pathHint(ad.binDir)})`);
      const home = isFile(ad.homeFile) ? readRaw(ad.homeFile).replace(/\n+$/, "") : null;
      if (home !== null && isDir(j(home, "luciazero_agentd"))) say(`  ok    agentd package recorded at ${home}`);
      else {
        say(`  MISS  ${ad.homeFile} does not point at an agentd package — re-run ./install.sh`);
        rc = 1;
      }
    }
  }
  const n = countLine(j(dir, "CLAUDE.md"), IMPORT_LINE);
  if (n === 1) say("  ok    CLAUDE.md imports the doctrine");
  else {
    say(`  MISS  CLAUDE.md import line (${IMPORT_LINE} exactly once; found ${n})`);
    rc = 1;
  }
  pluginDoubleInstallNote(dir);
  const vSrc = versionOf();
  const sidecar = readRaw(j(dir, ".luciazero-version"));
  const vInst = sidecar === null ? "" : sidecar.replace(/\n+$/, "");
  if (vInst === "") say("  --    installed version unknown (no sidecar — installed by an older version)");
  else if (vInst === vSrc) say(`  ok    version ${vInst} (matches this checkout)`);
  else say(`  !!    installed ${vInst}, checkout ${vSrc || "?"} — re-run ./install.sh to update`);
  const hooks = j(dir, "hooks");
  if (isFile(j(hooks, "luciazero-verify.cjs"))) {
    for (const h of ["luciazero-verify.cjs", "luciazero-statusline.cjs"]) {
      if (cmp(j(hooks, h), j(SRC, "claude", "hooks", h))) say(`  ok    hooks/${h} matches this checkout`);
      else {
        say(`  MISS  hooks/${h} differs from this checkout (stale or customized) — re-run ./install.sh --with-hooks`);
        rc = 1;
      }
    }
    // As `settings-wiring.js status` answers install.sh: a file it cannot
    // read is a file with nothing wired.
    let settings;
    try {
      const file = j(dir, "settings.json");
      settings = fs.existsSync(file) ? wiring.readSettings(file) : {};
    } catch {
      settings = {};
    }
    let missing = null;
    try {
      missing = wiring.missing(settings, hooks);
    } catch {
      missing = null;
    }
    if (missing === null) {
      say("  MISS  hook wiring not checked — settings.json could not be read");
      rc = 1;
    } else if (missing.length === 0) {
      say("  ok    hooks wired in settings.json (prompt/skill-prompt/bash-start/edit/bash/bash-failure/skill/stop/session)");
    } else {
      say(`  MISS  settings.json missing hook entries:${missing.map((s) => " " + s).join("")} (re-run ./install.sh --with-hooks)`);
      rc = 1;
    }
    if (nodeOk()) say("  ok    node >= 18 available (the hooks need it)");
    else {
      say("  MISS  node is older than 18 — the hooks fail (doing nothing)");
      rc = 1;
    }
    claudeVersionNote("  ");
  } else if (isFile(j(hooks, "luciazero-verify.sh"))) {
    say("  MISS  enforcement pack is the older Bash version (needs python3) — re-run ./install.sh --with-hooks to move it to Node");
    rc = 1;
  } else if (isFile(j(dir, "settings.json")) && mentions(readRaw(j(dir, "settings.json")), j(dir, "hooks", "luciazero-"))) {
    say("  MISS  settings.json references hook files that do not exist (dangling — re-run ./install.sh --with-hooks or ./uninstall.sh)");
    rc = 1;
  } else {
    say("  --    enforcement pack not installed (optional: ./install.sh --with-hooks)");
  }
  return rc;
}

// The provenance record install.sh leaves for the uninstaller: ours only by
// the marker on its first line, never by being a regular file at the name.
function provenanceIsOurs(file) {
  if (!isFile(file) || isLink(file)) return false;
  const t = readRaw(file);
  return t !== null && lines(t)[0] === IMPORT_MARKER;
}

function writeProvenance(dir, file, record) {
  if (exists(file) && !provenanceIsOurs(file)) {
    warn(`  !!  ${file} exists and is not ours; left untouched`);
    warn("      uninstall will remove the import line and nothing else");
    return;
  }
  let tmp = null;
  try {
    tmp = j(dir, ".luciazero-import." + crypto.randomBytes(6).toString("hex"));
    fs.writeFileSync(tmp, IMPORT_MARKER + "\n" + record + "\n", { flag: "wx", mode: 0o600 });
    fs.renameSync(tmp, file);
  } catch {
    if (tmp !== null) {
      try {
        rmFile(tmp);
      } catch {}
    }
  }
}

// The line ending a file already uses, so a line added to it matches its
// neighbours: CRLF when its first line ends in one.
function eolOf(text) {
  const i = text.indexOf("\n");
  return i > 0 && text[i - 1] === "\r" ? "\r\n" : "\n";
}

function claudeInstall(args) {
  let withHooks = false;
  let statusOnly = false;
  for (const a of args) {
    if (a === "--with-hooks") withHooks = true;
    else if (a === "--status") statusOnly = true;
    else {
      warn(`unknown option: ${a} (supported: --with-hooks, --status)`);
      return 1;
    }
  }
  const dir = claudeDir();
  if (statusOnly) return claudeStatus(dir);
  const managed = j(dir, ".luciazero-managed");
  const { installTree, installFile, removeLegacyTree, migrateHandoff } = installers(dir, j(dir, ".luciazero-backups"));

  say(`Installing into ${dir}`);
  mkdirp(j(dir, "skills"));

  installFile(j(SRC, "claude", DOCTRINE), j(dir, DOCTRINE), j(managed, DOCTRINE), DOCTRINE);
  say(`  ok  ${DOCTRINE}`);

  for (const skill of skillInventory()) {
    installTree(j(SRC, "skills", skill), j(dir, "skills", skill), j(managed, "skills", skill), `skills/${skill}`);
    say(`  ok  skills/${skill}`);
  }
  removeLegacyTree(j(dir, "skills", "luciazero-bootstrap"), j(managed, "skills", "luciazero-bootstrap"), "skills/luciazero-bootstrap");
  migrateHandoff(dir);

  mkdirp(j(dir, "agents"));
  for (const agent of catalog(j(SRC, "claude", "agents", "catalog.txt"))) {
    installFile(j(SRC, "claude", "agents", agent + ".md"), j(dir, "agents", agent + ".md"), j(managed, "agents", agent + ".md"), `agents/${agent}.md`);
    say(`  ok  agents/${agent}.md`);
  }

  const ad = agentdLayout(dir);
  if (isFile(j(SRC, "agentd", "luciazero_agentd", "__init__.py")) && isFile(ad.source)) {
    let kindAll = "absent";
    for (const name of ad.names) {
      const target = j(ad.binDir, name);
      const kind = launcherKind(target);
      if (kind === "foreign") {
        warn(`  !!  ${target} exists and is not the Luciazero launcher; left untouched`);
        warn(`      install it elsewhere with: LUCIAZERO_BIN_DIR=<dir> ./install.sh`);
      } else if (kind === "symlink") {
        say(`  ok  bin/${name} (symlink to a Luciazero launcher; left as is)`);
        kindAll = "ours";
      } else {
        mkdirp(ad.binDir);
        if (kind === "ours" && cmp(ad.source, target)) say(`  ok  bin/${name} (unchanged)`);
        else {
          fs.writeFileSync(target, fs.readFileSync(ad.source), { mode: fs.statSync(ad.source).mode & 0o777 });
          say(`  ok  bin/${name} -> ${target}`);
        }
        chmodX(target);
        kindAll = "ours";
      }
    }
    if (kindAll !== "absent") {
      fs.writeFileSync(ad.homeFile, j(SRC, "agentd") + "\n");
      if (!onPath(ad.binDir)) say(`      add to PATH:  ${pathHint(ad.binDir)}`);
    }
  }

  const vNew = versionOf();
  const old = readRaw(j(dir, ".luciazero-version"));
  const vOld = old === null ? "" : old.replace(/\n+$/, "");
  if (vNew) {
    if (vOld && vOld !== vNew) say(`  ok  updating ${vOld} -> ${vNew}`);
    fs.writeFileSync(j(dir, ".luciazero-version"), vNew + "\n");
  }

  const globalMd = j(dir, "CLAUDE.md");
  const provenance = j(dir, ".luciazero-import");
  const current = isFile(globalMd) ? readRaw(globalMd) : null;
  if (current !== null && current.includes(IMPORT_LINE)) {
    say(`  ok  CLAUDE.md already imports ${DOCTRINE}`);
  } else {
    if (current !== null) {
      const saved = bakcopy(true, globalMd, globalMd);
      say(`  ok  backed up CLAUDE.md -> ${path.basename(saved)}`);
      const eol = eolOf(current);
      fs.appendFileSync(globalMd, Buffer.from(eol + IMPORT_LINE + eol, "latin1"));
      writeProvenance(dir, provenance, "appended " + sha256(globalMd));
    } else {
      fs.writeFileSync(globalMd, IMPORT_LINE + "\n");
      writeProvenance(dir, provenance, "created " + sha256(globalMd));
    }
    say(`  ok  CLAUDE.md imports ${DOCTRINE}`);
  }

  if (withHooks) {
    if (!nodeOk()) {
      warn(`FAIL: --with-hooks requires Node 18+ (found ${process.version})`);
      return 1;
    }
    const settings = j(dir, "settings.json");
    const hooks = j(dir, "hooks");
    if (wiring.main(["wire", "check", settings, hooks]) !== 0) {
      warn("FAIL: settings.json cannot be wired (see above) — hook files not copied, settings.json untouched");
      return 1;
    }
    mkdirp(hooks);
    for (const h of ["luciazero-verify.cjs", "luciazero-statusline.cjs"]) {
      const dst = j(hooks, h);
      const src = j(SRC, "claude", "hooks", h);
      if (isFile(dst) && !cmp(src, dst)) {
        bakcopy(true, dst, dst);
        say(`  ok  backed up existing hooks/${h}`);
      }
      if (exists(dst)) fs.writeFileSync(dst, fs.readFileSync(src));
      else copyFileNew(src, dst, false);
      chmodX(dst);
    }
    if (isFile(settings)) bakcopy(true, settings, settings);
    if (wiring.main(["wire", "write", settings, hooks]) !== 0) {
      warn("FAIL: could not update settings.json (see above) — hook files copied but not wired");
      return 1;
    }
    const legacy = readLines(j(SRC, "claude", "hooks", "legacy-hooks.sha256"));
    for (const h of ["luciazero-verify.sh", "luciazero-statusline.sh"]) {
      const f = j(hooks, h);
      if (!isFile(f)) continue;
      if (isFile(settings) && readRaw(settings).includes(h)) {
        say(`  !!  hooks/${h} kept — settings.json still names it`);
      } else if (legacy.includes(sha256(f))) {
        rmFile(f);
        say(`  ok  retired hooks/${h} (the Bash hooks before Node)`);
      } else {
        const saved = bakcopy(true, f, f);
        rmFile(f);
        say(`  ok  retired edited hooks/${h} (backup: ${path.basename(saved)})`);
      }
    }
    claudeVersionNote("  ");
  }

  say("");
  say("Done. Verify:");
  say(`  ${installerName("install")} --status`);
  say("");
  const skills = catalog(j(SRC, "skills", "catalog.txt")).map((s) => "/" + s).join(", ");
  const agents = catalog(j(SRC, "claude", "agents", "catalog.txt")).join(", ");
  say(`Skills: ${skills}. Agents: ${agents}.`);
  const hasAgentd = isFile(j(SRC, "agentd", "luciazero_agentd", "__init__.py"));
  const lucia = j(ad.binDir, ad.names[1]);
  if (hasAgentd && isExecutable(lucia) && launcherKind(lucia) !== "foreign") {
    say(`Agent Bus: lucia claude in one window, lucia codex in another (${lucia}).`);
    say("           the long name luciazero-agentd answers to every subcommand as before.");
  } else if (hasAgentd && isExecutable(ad.launcher) && launcherKind(ad.launcher) !== "foreign") {
    say(`Agent Bus: luciazero-agentd next | watch | chat | run (${ad.launcher}).`);
  }
  if (withHooks) say("Enforcement pack installed: verify-tracking hooks + statusline (see settings.json).");
  else say(`Optional: ${installerName("install")} --with-hooks adds the verify-nudge hooks + statusline.`);
  pluginDoubleInstallNote(dir);
  say("The doctrine applies from the next Claude Code session.");
  return 0;
}

// The command a user runs again, as they would type it here: the shell
// script on macOS and Linux, the npx route on Windows.
function installerName(which) {
  if (!WINDOWS) return which === "install" ? "./install.sh" : "./uninstall.sh";
  return which === "install" ? "npx luciazero" : "npx luciazero uninstall";
}

// A path as it appears in JSON text: as is, or with its backslashes escaped.
function mentions(json, p) {
  return json.includes(p) || json.includes(JSON.stringify(p).slice(1, -1));
}

function readLines(file) {
  const t = readRaw(file);
  return t === null ? [] : lines(t);
}

function claudeUninstall(args) {
  if (args.length) {
    warn(`unknown option: ${args[0]} (uninstall.sh takes no options)`);
    return 1;
  }
  const dir = claudeDir();
  const managed = j(dir, ".luciazero-managed");
  const globalMd = j(dir, "CLAUDE.md");
  const provenance = j(dir, ".luciazero-import");
  const { removeManagedTree, removeManagedFile } = removers(dir);

  say(`Removing from ${dir}`);
  removeManagedFile(j(dir, DOCTRINE), j(managed, DOCTRINE), j(SRC, "claude", DOCTRINE), DOCTRINE);
  rmFile(j(dir, ".luciazero-version"));
  for (const skill of skillInventory()) {
    removeManagedTree(j(dir, "skills", skill), j(managed, "skills", skill), j(SRC, "skills", skill), `skills/${skill}`);
  }
  removeManagedTree(
    j(dir, "skills", "luciazero-bootstrap"),
    j(managed, "skills", "luciazero-bootstrap"),
    j(SRC, "migrations", "luciazero-bootstrap-v2.2.0"),
    "skills/luciazero-bootstrap (retired alias)",
    false
  );
  for (const agent of catalog(j(SRC, "claude", "agents", "catalog.txt"))) {
    removeManagedFile(j(dir, "agents", agent + ".md"), j(managed, "agents", agent + ".md"), j(SRC, "claude", "agents", agent + ".md"), `agents/${agent}.md`);
  }
  rmdirQuiet(j(managed, "skills"), j(managed, "agents"), managed);

  // The service is stopped before the launcher it runs is removed, or the
  // service manager keeps restarting a file that is gone.
  const ad = agentdLayout(dir);
  let keep = false;
  const serviceRoot = process.env.LUCIAZERO_SERVICE_ROOT || os.homedir();
  for (const svc of [
    j(serviceRoot, "Library", "LaunchAgents", "com.luciazero.agentd.plist"),
    j(serviceRoot, ".config", "systemd", "user", "luciazero-agentd.service"),
  ]) {
    if (!isFile(svc) || !readRaw(svc).includes(AGENTD_SERVICE_MARKER)) continue;
    const launcherOurs = isFile(ad.launcher) && readRaw(ad.launcher).includes(AGENTD_MARKER);
    const viaLauncher = launcherOurs && spawnSync(ad.launcher, ["service", "uninstall"], { stdio: "ignore" }).status === 0;
    const viaPackage =
      !viaLauncher &&
      isDir(j(SRC, "agentd", "luciazero_agentd")) &&
      spawnSync("python3", ["-m", "luciazero_agentd", "service", "uninstall"], {
        stdio: "ignore",
        env: { ...process.env, PYTHONPATH: j(SRC, "agentd") },
      }).status === 0;
    if (viaLauncher || viaPackage) say("  ok  agent bus service stopped and removed");
    else {
      warn(`  !!  the Agent Bus service is still installed (${svc})`);
      warn("      stop it first:  luciazero-agentd service uninstall");
      warn("      the launcher is left in place so the service does not restart a missing file");
      keep = true;
    }
  }
  if (!keep) {
    for (const name of ad.names) {
      const target = j(ad.binDir, name);
      if (isLink(target)) warn(`  !!  ${target} is a symlink you made; left untouched`);
      else if (isFile(target)) {
        if (readRaw(target).includes(AGENTD_MARKER)) {
          rmFile(target);
          say(`  ok  bin/${name}`);
        } else {
          warn(`  !!  ${target} is not the Luciazero launcher; left untouched`);
        }
      } else if (exists(target)) {
        warn(`  !!  ${target} is not a regular file; left untouched`);
      }
    }
    rmdirQuiet(ad.binDir);
    rmFile(ad.homeFile);
  }

  const legacyHandoff = j(dir, "skills", "handoff");
  if (isFile(j(legacyHandoff, "SKILL.md"))) {
    if (cmp(j(SRC, "migrations", "handoff-v1.5.0.SKILL.md"), j(legacyHandoff, "SKILL.md"))) {
      rmTree(legacyHandoff);
      say("  ok  legacy skills/handoff");
    } else {
      warn("  !!  customized legacy skills/handoff left untouched");
    }
  }

  // settings.json first, and the hook files only once nothing names them.
  const settings = j(dir, "settings.json");
  let hooksClean = true;
  if (isFile(settings)) {
    if (nodeOk()) {
      const rc = wiring.main(["clean", settings, dir]);
      if (rc === 0) say("  ok  no enforcement-pack entries in settings.json");
      else if (rc === 10) say("  ok  removed hook entries from settings.json");
      else {
        hooksClean = false;
        warn(`  !!  could not clean settings.json (invalid JSON?) — hook files kept so nothing dangles; remove the luciazero-* entries manually, then delete ${j(dir, "hooks", "luciazero-*")}`);
      }
    } else {
      hooksClean = false;
      warn("  !!  Node 18+ not found — settings.json untouched; hook files kept so nothing dangles");
    }
  } else {
    say("  ok  no settings.json to clean");
  }
  if (hooksClean) {
    for (const h of ["luciazero-verify.cjs", "luciazero-statusline.cjs"]) {
      const f = j(dir, "hooks", h);
      if (!isFile(f)) continue;
      if (cmp(f, j(SRC, "claude", "hooks", h))) {
        rmFile(f);
        say(`  ok  hooks/${h}`);
      } else {
        warn(`  !!  hooks/${h} differs from the shipped version (customized or newer?) — left in place`);
      }
    }
    const legacy = readLines(j(SRC, "claude", "hooks", "legacy-hooks.sha256"));
    for (const h of ["luciazero-verify.sh", "luciazero-statusline.sh"]) {
      const f = j(dir, "hooks", h);
      if (!isFile(f)) continue;
      if (legacy.includes(sha256(f))) {
        rmFile(f);
        say(`  ok  hooks/${h}`);
      } else {
        warn(`  !!  hooks/${h} differs from every shipped version (customized?) — left in place`);
      }
    }
  }

  const md = isFile(globalMd) ? readRaw(globalMd) : null;
  if (md !== null && md.includes(IMPORT_LINE)) {
    const saved = bakcopy(true, globalMd, globalMd);
    // Everything below reads the backup, so the decision and the rewrite see
    // one file; the live file must still match it when the result goes in.
    const snapshot = readRaw(saved);
    const prov = provenanceIsOurs(provenance) ? lines(readRaw(provenance))[1] || "" : "";
    const appended = prov.startsWith("appended ") && prov.slice(9) !== "" && prov.slice(9) === sha256(saved);
    const out = appended ? dropImportAndSeparator(snapshot) : dropLine(snapshot, IMPORT_LINE);
    let rewritten = false;
    if (cmp(saved, globalMd)) {
      const info = fs.statSync(saved);
      const tmp = j(dir, ".luciazero-claude-md." + crypto.randomBytes(6).toString("hex"));
      fs.writeFileSync(tmp, Buffer.from(out, "latin1"), { flag: "wx", mode: info.mode & 0o777 });
      if (!WINDOWS) fs.chmodSync(tmp, info.mode & 0o7777);
      fs.renameSync(tmp, globalMd);
      if (!nonEmpty(globalMd)) rmFile(globalMd);
      rewritten = true;
    } else {
      warn(`  !!  CLAUDE.md changed while this was running; left exactly as it is now (backup: ${path.basename(saved)})`);
    }
    if (rewritten) {
      if (snapshot === IMPORT_LINE + "\n" || snapshot === IMPORT_LINE + "\r\n") {
        rmFile(saved);
        say("  ok  removed import line (its backup held only that line; removed)");
      } else {
        say(`  ok  removed import line (backup: ${path.basename(saved)})`);
      }
    }
  } else {
    say("  ok  no import line in CLAUDE.md");
  }
  if (provenanceIsOurs(provenance)) rmFile(provenance);

  for (const keep of ["luciazero-stats.log", "luciazero-heuristics.md"]) {
    if (isFile(j(dir, keep))) say(`  kept ${keep} (learned data) — delete manually if unwanted`);
  }
  if (isDir(j(dir, ".luciazero-backups"))) {
    say("  kept .luciazero-backups/ (pre-existing or customized components) — review and delete manually when no longer needed");
  }
  rmdirQuiet(j(dir, "skills"), j(dir, "agents"));
  rmdirQuiet(dir);

  say("");
  say("Done. Other CLAUDE.md content was left untouched.");
  say("The Agent Bus state directory (~/.luciazero/agent-bus) is data and was not touched.");
  return 0;
}

// A file as a list of [line, terminator] pairs, so a rewrite keeps every line
// ending exactly as it found it, LF, CRLF or none on the last line.
function splitKeep(text) {
  const out = [];
  let at = 0;
  while (at < text.length) {
    const nl = text.indexOf("\n", at);
    if (nl === -1) {
      out.push([text.slice(at), ""]);
      break;
    }
    let body = text.slice(at, nl);
    let eol = "\n";
    if (body.endsWith("\r")) {
      body = body.slice(0, -1);
      eol = "\r\n";
    }
    out.push([body, eol]);
    at = nl + 1;
  }
  return out;
}
const joinKeep = (pairs) => pairs.map(([l, e]) => l + e).join("");

// `grep -vxF line`, keeping the other lines' own endings. grep ends what it
// prints with a newline, so a kept last line without one gains it.
function dropLine(text, want) {
  const kept = splitKeep(text).filter(([l]) => l !== want);
  if (kept.length && kept[kept.length - 1][1] === "") kept[kept.length - 1][1] = "\n";
  return joinKeep(kept);
}

// uninstall.sh's awk: drop the import line, and a blank line directly above
// it with it, keeping every other blank line.
function dropImportAndSeparator(text) {
  const out = [];
  let pending = null;
  for (const [l, e] of splitKeep(text)) {
    if (l === IMPORT_LINE) {
      pending = null;
      continue;
    }
    if (pending !== null) {
      out.push(pending);
      pending = null;
    }
    if (l === "") {
      pending = ["", e];
      continue;
    }
    out.push([l, e === "" ? "\n" : e]);
  }
  if (pending !== null) out.push(pending);
  return joinKeep(out);
}

// --------------------------------------------------------------------- Codex

// Exactly one marker pair, start before end, or none at all.
function markerBlockOk(file) {
  const t = readRaw(file);
  if (t === null || !isFile(file)) return true;
  const ls = lines(t);
  const s = ls.filter((l) => l === START).length;
  const e = ls.filter((l) => l === END).length;
  if (s === 0 && e === 0) return true;
  return s === 1 && e === 1 && ls.indexOf(START) < ls.indexOf(END);
}

// install-codex.sh's strip_marker_block: the block goes, every other byte
// stays, and the newline the install added above the start marker goes with
// the block while the block is still the last thing in the file.
function stripMarkerBlock(text) {
  const pairs = splitKeep(text);
  const kept = [];
  let inBlock = false;
  let head = false;
  let added = false;
  let blockEnd = -1;
  pairs.forEach(([l, e], i) => {
    if (l === START) {
      inBlock = true;
      head = true;
      blockEnd = i;
    } else if (l === END) {
      inBlock = false;
      blockEnd = i;
    } else if (inBlock) {
      if (head && l === ADDED_NL_MARK) added = true;
      head = false;
      blockEnd = i;
    } else {
      kept.push([l, e]);
    }
  });
  if (kept.length === 0) return "";
  // Only the file's own last line can lack an ending, and it keeps that.
  if (added && blockEnd === pairs.length - 1) kept[kept.length - 1][1] = "";
  return joinKeep(kept);
}

// A Claude agent as a Codex skill: the same file minus the front matter's
// Claude-only `tools:` and `model:` lines.
function agentAsSkill(text) {
  const out = [];
  let front = false;
  splitKeep(text).forEach(([l, e], i) => {
    if (i === 0) front = l === "---";
    if (front && /^(tools|model): /.test(l)) return;
    out.push(l + (e === "" ? "\n" : e));
    if (front && i > 0 && l === "---") front = false;
  });
  return out.join("");
}

function stageAgents(agents) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "luciazero-agents-"));
  for (const agent of agents) {
    mkdirp(path.join(root, agent));
    fs.writeFileSync(path.join(root, agent, "SKILL.md"), Buffer.from(agentAsSkill(readRaw(j(SRC, "claude", "agents", agent + ".md"))), "latin1"));
  }
  return root;
}

function codexInstall(args) {
  if (args.length) {
    warn(`unknown option: ${args[0]} (install-codex.sh takes no options)`);
    return 1;
  }
  const dir = codexDir();
  const agentsMd = j(dir, "AGENTS.md");
  const managed = j(dir, ".luciazero-managed");
  const { installTree, removeLegacyTree, migrateHandoff } = installers(dir, j(dir, ".luciazero-backups"));
  if (!markerBlockOk(agentsMd)) {
    warn("AGENTS.md carries ambiguous Luciazero markers; nothing was installed");
    warn(`  expected exactly one '${START}' ... '${END}' pair, on their own lines`);
    warn(`  fix ${agentsMd} and run this again`);
    return 1;
  }
  say(`Installing into ${dir}`);
  mkdirp(j(dir, "skills"));

  let kept = "";
  if (isFile(agentsMd)) {
    bakcopy(true, agentsMd, agentsMd);
    kept = stripMarkerBlock(readRaw(agentsMd));
  }
  const eol = kept ? eolOf(kept) : "\n";
  const addedNl = kept !== "" && !kept.endsWith("\n");
  const doctrine = readRaw(j(SRC, "claude", DOCTRINE));
  let block = "";
  if (addedNl) block += eol;
  block += START + eol;
  if (addedNl) block += ADDED_NL_MARK + eol;
  block += eol;
  block += eol === "\n" ? doctrine : doctrine.replace(/\r?\n/g, "\r\n");
  block += END + eol;
  fs.writeFileSync(agentsMd, Buffer.from(kept + block, "latin1"));
  say("  ok  AGENTS.md doctrine block");

  for (const skill of skillInventory()) {
    installTree(j(SRC, "skills", skill), j(dir, "skills", skill), j(managed, "skills", skill), `skills/${skill}`);
    say(`  ok  skills/${skill}`);
  }
  removeLegacyTree(j(dir, "skills", "luciazero-bootstrap"), j(managed, "skills", "luciazero-bootstrap"), "skills/luciazero-bootstrap");
  migrateHandoff(dir);

  const agents = catalog(j(SRC, "claude", "agents", "catalog.txt"));
  const stage = stageAgents(agents);
  try {
    for (const agent of agents) {
      installTree(path.join(stage, agent), j(dir, "skills", agent), j(managed, "skills", agent), `skills/${agent}`);
      say(`  ok  skills/${agent}`);
    }
  } finally {
    rmTree(stage);
  }

  const vNew = versionOf();
  if (vNew) fs.writeFileSync(j(dir, ".luciazero-version"), vNew + "\n");

  say("");
  say("Done. Verify:");
  say(`  grep -c 'luciazero:start' ${agentsMd}   # expect 1`);
  say(`  ls ${j(dir, "skills")}${SEP}`);
  say("");
  say("The doctrine applies from the next Codex session.");
  return 0;
}

function codexUninstall(args) {
  if (args.length) {
    warn(`unknown option: ${args[0]} (uninstall-codex.sh takes no options)`);
    return 1;
  }
  const dir = codexDir();
  const agentsMd = j(dir, "AGENTS.md");
  const managed = j(dir, ".luciazero-managed");
  const { removeManagedTree } = removers(dir);

  say(`Removing from ${dir}`);
  rmFile(j(dir, ".luciazero-version"));
  for (const skill of skillInventory()) {
    removeManagedTree(j(dir, "skills", skill), j(managed, "skills", skill), j(SRC, "skills", skill), `skills/${skill}`);
  }
  removeManagedTree(
    j(dir, "skills", "luciazero-bootstrap"),
    j(managed, "skills", "luciazero-bootstrap"),
    j(SRC, "migrations", "luciazero-bootstrap-v2.2.0"),
    "skills/luciazero-bootstrap (retired alias)",
    false
  );
  const agents = catalog(j(SRC, "claude", "agents", "catalog.txt"));
  const stage = stageAgents(agents);
  try {
    for (const agent of agents) {
      removeManagedTree(j(dir, "skills", agent), j(managed, "skills", agent), path.join(stage, agent), `skills/${agent}`);
    }
  } finally {
    rmTree(stage);
  }
  rmdirQuiet(j(managed, "skills"), managed);

  const legacyHandoff = j(dir, "skills", "handoff");
  if (isFile(j(legacyHandoff, "SKILL.md"))) {
    if (cmp(j(SRC, "migrations", "handoff-v1.5.0.SKILL.md"), j(legacyHandoff, "SKILL.md"))) {
      rmTree(legacyHandoff);
      say("  ok  legacy skills/handoff");
    } else {
      warn("  !!  customized legacy skills/handoff left untouched");
    }
  }

  const text = isFile(agentsMd) ? readRaw(agentsMd) : null;
  const hasStart = text !== null && lines(text).includes(START);
  if (hasStart && !markerBlockOk(agentsMd)) {
    warn("  !!  AGENTS.md carries ambiguous Luciazero markers; left untouched");
    warn(`      expected exactly one '${START}' ... '${END}' pair, on their own lines`);
  } else if (hasStart) {
    const saved = bakcopy(true, agentsMd, agentsMd);
    const info = fs.statSync(saved);
    const tmp = j(dir, ".luciazero-agents-md." + crypto.randomBytes(6).toString("hex"));
    fs.writeFileSync(tmp, Buffer.from(stripMarkerBlock(readRaw(agentsMd)), "latin1"), { flag: "wx", mode: info.mode & 0o777 });
    if (!WINDOWS) fs.chmodSync(tmp, info.mode & 0o7777);
    fs.renameSync(tmp, agentsMd);
    if (!nonEmpty(agentsMd)) rmFile(agentsMd);
    say(`  ok  removed doctrine block (backup: ${path.basename(saved)})`);
  } else {
    say("  ok  no doctrine block in AGENTS.md");
  }

  if (isFile(j(dir, "luciazero-heuristics.md"))) say("  kept luciazero-heuristics.md (learned data) — delete manually if unwanted");
  if (isDir(j(dir, ".luciazero-backups"))) {
    say("  kept .luciazero-backups/ (pre-existing or customized components) — review and delete manually when no longer needed");
  }
  say("");
  say("Done. Other AGENTS.md content was left untouched.");
  return 0;
}

const COMMANDS = {
  claude: claudeInstall,
  "claude-uninstall": claudeUninstall,
  codex: codexInstall,
  "codex-uninstall": codexUninstall,
};

function main(argv) {
  const [command, ...args] = argv;
  const run = COMMANDS[command];
  if (!run) {
    warn("usage: installer.js claude [--with-hooks|--status] | claude-uninstall | codex | codex-uninstall");
    return 64;
  }
  try {
    return run(args);
  } catch (error) {
    if (error instanceof Exit) return error.code;
    warn(`FAIL: ${error && error.message ? error.message : String(error)}`);
    return 1;
  }
}

if (require.main === module) process.exitCode = main(process.argv.slice(2));

module.exports = { main, bakcopy, sameTree, stripMarkerBlock, dropImportAndSeparator, dropLine, agentAsSkill, markerBlockOk, splitKeep };
