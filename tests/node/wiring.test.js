"use strict";
// bin/lib/settings-wiring.js on whatever platform runs this file. What it
// writes must run there: the hooks in exec form, the status line through
// whichever shell Claude Code hands it to, every path as the platform
// spells it. And what it refuses -- a settings.json it cannot read -- it
// must refuse with nothing written.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { ROOT, WINDOWS, sandbox, node } = require("./sandbox.js");

const WIRING = path.join(ROOT, "bin", "lib", "settings-wiring.js");
const wiring = require(WIRING);

function hooksDir(box) {
  const dir = path.join(box.claude, "hooks");
  fs.mkdirSync(dir, { recursive: true });
  for (const name of ["luciazero-verify.cjs", "luciazero-statusline.cjs"]) {
    fs.copyFileSync(path.join(ROOT, "claude", "hooks", name), path.join(dir, name));
  }
  return dir;
}

test("wire writes exec-form hooks and a status line that runs", (t) => {
  const box = sandbox(t);
  const hooks = hooksDir(box);
  const file = path.join(box.claude, "settings.json");
  fs.writeFileSync(file, JSON.stringify({ model: "opus", hooks: { Stop: [{ hooks: [{ type: "command", command: "echo mine" }] }] } }));
  const r = node(box.env, [WIRING, "wire", "write", file, hooks]);
  assert.strictEqual(r.status, 0, r.stderr);
  const settings = JSON.parse(fs.readFileSync(file, "utf8"));
  assert.strictEqual(settings.model, "opus");
  assert.ok(settings.hooks.Stop.some((e) => e.hooks.some((h) => h.command === "echo mine")), "a hook of the user's was lost");
  const verify = path.join(hooks, "luciazero-verify.cjs");
  for (const [event, matcher, sub] of wiring.WIRING) {
    const entry = settings.hooks[event].find((e) => e.hooks.some((h) => h.command === "node" && h.args[0] === verify && h.args[1] === sub));
    assert.ok(entry, `${event} ${sub} is not wired in exec form`);
    if (matcher) assert.strictEqual(entry.matcher, matcher);
  }
  assert.strictEqual(wiring.statusScript(settings.statusLine.command), path.join(hooks, "luciazero-statusline.cjs"));

  // the status line as a shell runs it: the platform's own (cmd.exe on
  // Windows, sh elsewhere), and PowerShell on Windows too
  const input = JSON.stringify({ cwd: box.box, model: { display_name: "Shelled" } });
  const runs = [["the default shell", settings.statusLine.command, [], { shell: true }]];
  if (WINDOWS) runs.push(["PowerShell", "powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", settings.statusLine.command], {}]);
  for (const [label, command, args, options] of runs) {
    const shown = spawnSync(command, args, { env: box.env, input, encoding: "utf8", windowsHide: true, ...options });
    assert.strictEqual(shown.status, 0, `${label}: ${shown.stderr || shown.error}`);
    assert.match(shown.stdout, /^Shelled \| /, `${label} did not run the status line`);
  }

  const again = node(box.env, [WIRING, "wire", "write", file, hooks]);
  assert.strictEqual(again.status, 0, again.stderr);
  assert.match(again.stdout, /hooks already wired/);
});

test("clean removes only ours and keeps a backup", (t) => {
  const box = sandbox(t);
  const hooks = hooksDir(box);
  const file = path.join(box.claude, "settings.json");
  fs.writeFileSync(file, JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: "command", command: "echo mine" }] }] } }, null, 2) + "\n");
  const before = fs.readFileSync(file);
  assert.strictEqual(node(box.env, [WIRING, "wire", "write", file, hooks]).status, 0);
  const r = node(box.env, [WIRING, "clean", file, box.claude]);
  assert.strictEqual(r.status, 10, r.stderr);
  const after = JSON.parse(fs.readFileSync(file, "utf8"));
  assert.deepStrictEqual(after.hooks.Stop, [{ hooks: [{ type: "command", command: "echo mine" }] }]);
  assert.strictEqual(after.statusLine, undefined);
  const backups = fs.readdirSync(box.claude).filter((n) => n.startsWith("settings.json.bak."));
  assert.strictEqual(backups.length, 1);
  assert.notDeepStrictEqual(fs.readFileSync(path.join(box.claude, backups[0])), before, "the backup is of the wired file");
});

test("a settings.json that cannot be read is refused, not replaced", (t) => {
  const box = sandbox(t);
  const hooks = hooksDir(box);
  const file = path.join(box.claude, "settings.json");
  fs.mkdirSync(file); // a directory where the file belongs
  for (const mode of ["check", "write"]) {
    const r = node(box.env, [WIRING, "wire", mode, file, hooks]);
    assert.notStrictEqual(r.status, 0, `wire ${mode} accepted a directory as settings.json`);
  }
  assert.ok(fs.statSync(file).isDirectory());
  fs.rmdirSync(file);

  const loop = path.join(box.box, "loop");
  try {
    fs.symlinkSync(loop, file, "file");
    fs.symlinkSync(file, loop, "file");
  } catch (error) {
    if (WINDOWS && error.code === "EPERM") return t.skip("symlinks need Developer Mode or an elevated prompt here");
    throw error;
  }
  for (const mode of ["check", "write"]) {
    const r = node(box.env, [WIRING, "wire", mode, file, hooks]);
    assert.notStrictEqual(r.status, 0, `wire ${mode} accepted a settings.json symlink loop`);
    assert.strictEqual(fs.readlinkSync(file), loop);
    assert.strictEqual(fs.readlinkSync(loop), file);
  }
});
