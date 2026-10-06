"use strict";
// bin/lib/installer.js -- the installer Windows runs -- on whatever platform
// runs this file. On macOS and Linux the parity gate already holds it to the
// Bash installers step by step; here it must also stand on its own: install,
// report itself healthy, wire hooks that run as Claude Code runs them, and
// leave a user's CRLF CLAUDE.md and AGENTS.md byte for byte as they were.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { ROOT, WINDOWS, sandbox, node } = require("./sandbox.js");

const INSTALLER = path.join(ROOT, "bin", "lib", "installer.js");
const ROUTER = path.join(ROOT, "bin", "luciazero.js");

function ok(r, label) {
  assert.strictEqual(r.status, 0, `${label} exited ${r.status}\n${r.stdout}\n${r.stderr}`);
}

test("claude: install with hooks, status, the wired hook runs, uninstall restores CLAUDE.md", (t) => {
  const box = sandbox(t);
  fs.mkdirSync(box.claude, { recursive: true });
  const mine = Buffer.from("# Mine\r\nline two\r\n");
  fs.writeFileSync(path.join(box.claude, "CLAUDE.md"), mine);

  ok(node(box.env, [INSTALLER, "claude", "--with-hooks"]), "install");
  assert.strictEqual(fs.readFileSync(path.join(box.claude, "CLAUDE.md"), "utf8"), "# Mine\r\nline two\r\n\r\n@luciazero.md\r\n",
    "the import line must follow the file's own line ending");
  const status = node(box.env, [INSTALLER, "claude", "--status"]);
  ok(status, "status");
  assert.doesNotMatch(status.stdout, /MISS/);

  // the PostToolUse shell hook, run exactly as wired: command and args, no shell
  const settings = JSON.parse(fs.readFileSync(path.join(box.claude, "settings.json"), "utf8"));
  const entry = settings.hooks.PostToolUse.find((e) => e.matcher === "Bash|PowerShell");
  const hook = entry.hooks[0];
  assert.strictEqual(hook.command, "node");
  const cwd = path.join(box.box, "project");
  const ran = spawnSync(hook.command, hook.args, {
    env: box.env, encoding: "utf8", windowsHide: true,
    input: JSON.stringify({ cwd, tool_name: "PowerShell", tool_input: { command: "npm test" } }),
  });
  assert.strictEqual(ran.status, 0, ran.stderr || String(ran.error));
  const state = node(box.env, ["-e", "const v = require(process.argv[1]); console.log(require('path').join(v.stateBase(), v.stateKey(process.argv[2])))", hook.args[0], cwd]);
  assert.strictEqual(fs.readFileSync(path.join(state.stdout.trim(), "last_verify"), "utf8"), "ok\n",
    "the installed hook did not record the verify run");

  ok(node(box.env, [INSTALLER, "claude", "--with-hooks"]), "second install");
  ok(node(box.env, [INSTALLER, "claude-uninstall"]), "uninstall");
  assert.deepStrictEqual(fs.readFileSync(path.join(box.claude, "CLAUDE.md")), mine, "uninstall did not restore CLAUDE.md byte for byte");
  assert.ok(!fs.existsSync(path.join(box.claude, "luciazero.md")), "the doctrine was left behind");
  assert.ok(!fs.existsSync(path.join(box.claude, "hooks", "luciazero-verify.cjs")), "a hook was left behind");
  const left = JSON.parse(fs.readFileSync(path.join(box.claude, "settings.json"), "utf8"));
  assert.ok(!JSON.stringify(left).includes("luciazero-"), "settings.json still names a hook of ours");
});

// Take read access to a file away from this user, for real: mode 0200 on
// POSIX, a deny-read-data ACE on Windows. Returns the undo, or a reason the
// platform cannot do it here (root reads anything).
function denyRead(file) {
  if (WINDOWS) {
    const who = spawnSync("whoami", ["/user", "/fo", "csv", "/nh"], { encoding: "utf8", windowsHide: true });
    const sid = who.status === 0 ? (who.stdout.match(/"(S-1-[0-9-]+)"/) || [])[1] : undefined;
    if (!sid) return "whoami did not name this user's SID";
    const icacls = (args) => spawnSync("icacls", [file, ...args], { encoding: "utf8", windowsHide: true });
    const denied = icacls(["/deny", `*${sid}:(RD)`]);
    if (denied.status !== 0) return `icacls could not deny reading: ${denied.stdout}${denied.stderr}`;
    return () => icacls(["/remove:d", `*${sid}`]);
  }
  if (process.getuid && process.getuid() === 0) return "root reads a mode 0200 file anyway";
  fs.chmodSync(file, 0o200);
  return () => fs.chmodSync(file, 0o600);
}

// A CLAUDE.md that is there but cannot be read belongs to the user. The
// installer must stop with nothing changed: no rewrite, no backup, and no
// provenance record that would let the uninstaller delete the file.
function assertRefusedClaudeMd(box, run, file, mine) {
  assert.strictEqual(run.status, 1, `install exited ${run.status}\n${run.stdout}\n${run.stderr}`);
  assert.match(run.stderr, /FAIL: cannot read .*CLAUDE\.md/);
  assert.deepStrictEqual(fs.readFileSync(file), mine, "the user's file was changed");
  const names = fs.readdirSync(box.claude);
  assert.ok(!names.some((n) => n.startsWith("CLAUDE.md.bak.")), `a backup was made: ${names}`);
  assert.ok(!names.includes(".luciazero-import"), "the user's file was recorded as the installer's");
}

test("claude: a CLAUDE.md that cannot be read is refused, never replaced", (t) => {
  const mine = Buffer.from("# Mine\r\nnot readable by the installer\r\n");

  // On every platform, as any user: the installer's own read fails.
  const box = sandbox(t);
  fs.mkdirSync(box.claude, { recursive: true });
  const md = path.join(box.claude, "CLAUDE.md");
  fs.writeFileSync(md, mine);
  const preload = path.join(box.box, "deny-claude-md.js");
  fs.writeFileSync(preload, `"use strict";
const fs = require("fs");
const path = require("path");
const read = fs.readFileSync;
fs.readFileSync = function (file, ...rest) {
  if (typeof file === "string" && path.resolve(file) === ${JSON.stringify(md)}) {
    const error = new Error("EACCES: permission denied, open '" + file + "'");
    error.code = "EACCES";
    throw error;
  }
  return read.call(this, file, ...rest);
};
`);
  assertRefusedClaudeMd(box, node(box.env, ["--require", preload, INSTALLER, "claude"]), md, mine);

  // The file itself unreadable, then a symlink to an unreadable file.
  for (const linked of [false, true]) {
    const real = sandbox(t);
    fs.mkdirSync(real.claude, { recursive: true });
    const target = linked ? path.join(real.box, "notes", "CLAUDE.md") : path.join(real.claude, "CLAUDE.md");
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, mine);
    if (linked) {
      try {
        fs.symlinkSync(target, path.join(real.claude, "CLAUDE.md"), "file");
      } catch (error) {
        if (WINDOWS && error.code === "EPERM") { t.diagnostic("symlinked case skipped: this account may not create symlinks"); continue; }
        throw error;
      }
    }
    const undo = denyRead(target);
    if (typeof undo === "string") { t.diagnostic(`unreadable-file case skipped: ${undo}`); continue; }
    let run;
    try {
      run = node(real.env, [INSTALLER, "claude"]);
    } finally {
      undo();
    }
    assertRefusedClaudeMd(real, run, target, mine);
  }
});

test("codex: install and uninstall keep a CRLF AGENTS.md byte for byte", (t) => {
  const box = sandbox(t);
  fs.mkdirSync(box.codex, { recursive: true });
  const mine = Buffer.from("# Agents\r\nkeep\r\n");
  fs.writeFileSync(path.join(box.codex, "AGENTS.md"), mine);
  ok(node(box.env, [INSTALLER, "codex"]), "codex install");
  const agents = fs.readFileSync(path.join(box.codex, "AGENTS.md"), "utf8");
  assert.ok(agents.startsWith("# Agents\r\nkeep\r\n<!-- luciazero:start -->\r\n"), "the doctrine block is not in CRLF after the user's text");
  assert.doesNotMatch(agents.replace(/\r\n/g, ""), /\n/, "the doctrine block mixes line endings");
  ok(node(box.env, [INSTALLER, "codex"]), "second codex install");
  ok(node(box.env, [INSTALLER, "codex-uninstall"]), "codex uninstall");
  assert.deepStrictEqual(fs.readFileSync(path.join(box.codex, "AGENTS.md")), mine, "uninstall did not restore AGENTS.md byte for byte");
});

test("on Windows, npx luciazero runs the Node installer", { skip: !WINDOWS && "Windows only; the packaging gate fakes win32 elsewhere" }, (t) => {
  const box = sandbox(t);
  const status = node(box.env, [ROUTER, "--status"]);
  assert.strictEqual(status.status, 1, "status of a config dir with nothing installed must be red");
  assert.match(status.stdout, /^Status of /m);
  assert.doesNotMatch(status.stdout + status.stderr, /WSL|need bash/i);
  ok(node(box.env, [ROUTER, "--with-hooks"]), "npx luciazero --with-hooks");
  ok(node(box.env, [ROUTER, "--status"]), "npx luciazero --status");
  ok(node(box.env, [ROUTER, "codex"]), "npx luciazero codex");
  ok(node(box.env, [ROUTER, "uninstall-codex"]), "npx luciazero uninstall-codex");
  ok(node(box.env, [ROUTER, "uninstall"]), "npx luciazero uninstall");
});
