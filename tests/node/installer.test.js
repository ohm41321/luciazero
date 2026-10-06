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
