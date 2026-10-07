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

test("the status line runs from an awkward path through the shells Claude Code uses", (t) => {
  // Claude Code hands a status line to Git Bash when it is installed and to
  // PowerShell otherwise on Windows, and to sh elsewhere. The config path
  // holds what those shells treat specially, and Thai; the model name on
  // stdin is not ASCII either. (The cmd.exe run in the test above is Node's
  // own shell, not one Claude Code picks.)
  const box = sandbox(t);
  const config = path.join(box.box, "Claude cfg & ไทย 'q' (x) %PATH% !x! $HOME");
  const hooks = path.join(config, "hooks");
  fs.mkdirSync(hooks, { recursive: true });
  for (const name of ["luciazero-verify.cjs", "luciazero-statusline.cjs"]) {
    fs.copyFileSync(path.join(ROOT, "claude", "hooks", name), path.join(hooks, name));
  }
  const file = path.join(config, "settings.json");
  const r = node(box.env, [WIRING, "wire", "write", file, hooks]);
  assert.strictEqual(r.status, 0, r.stderr);
  const command = JSON.parse(fs.readFileSync(file, "utf8")).statusLine.command;
  assert.strictEqual(wiring.statusScript(command), path.join(hooks, "luciazero-statusline.cjs"));

  const model = "โมเดล Ünïcode";
  const input = JSON.stringify({ cwd: box.box, model: { display_name: model } });
  const runs = [];
  if (WINDOWS) {
    const gitBash = [process.env.CLAUDE_CODE_GIT_BASH_PATH,
      path.join(process.env.ProgramFiles || "C:\\Program Files", "Git", "bin", "bash.exe")].find((p) => p && fs.existsSync(p));
    if (gitBash) runs.push(["Git Bash", command, [], { shell: gitBash }]);
    else t.diagnostic("Git Bash is not installed here; its case did not run");
    runs.push(["Windows PowerShell", "powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", command], {}]);
    if (spawnSync("pwsh", ["-NoProfile", "-Command", "exit 0"], { windowsHide: true }).status === 0) {
      runs.push(["PowerShell 7", "pwsh", ["-NoProfile", "-NonInteractive", "-Command", command], {}]);
    } else {
      t.diagnostic("pwsh is not installed here; its case did not run");
    }
  } else {
    runs.push(["sh", "/bin/sh", ["-c", command], {}]);
  }
  for (const [label, program, args, options] of runs) {
    const shown = spawnSync(program, args, { env: box.env, input, encoding: "utf8", windowsHide: true, ...options });
    assert.strictEqual(shown.status, 0, `${label}: ${shown.stderr || shown.error}`);
    assert.ok(shown.stdout.startsWith(`${model} | `), `${label} printed ${JSON.stringify(shown.stdout)}`);
  }
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

// The config dir may come with a trailing separator, or doubled ones, and the
// installers join it as given: what one spelling wired, another must still
// find, so a second install does not wire every hook twice and uninstall does
// not leave entries naming files it deleted.
test("a hooks path spelled another way is still ours", (t) => {
  const box = sandbox(t);
  hooksDir(box);
  const file = path.join(box.claude, "settings.json");
  const sep = path.sep;
  const doubled = box.claude + sep + sep + "hooks";
  assert.strictEqual(node(box.env, [WIRING, "wire", "write", file, doubled]).status, 0);
  const again = node(box.env, [WIRING, "wire", "write", file, path.join(box.claude, "hooks")]);
  assert.strictEqual(again.status, 0, again.stderr);
  const wired = JSON.parse(fs.readFileSync(file, "utf8"));
  for (const [event, , sub] of wiring.WIRING) {
    const ours = wired.hooks[event].flatMap((e) => e.hooks).filter((h) => h.command === "node" && h.args[1] === sub);
    assert.strictEqual(ours.length, 1, `${event} ${sub} is wired ${ours.length} times`);
  }
  assert.strictEqual(node(box.env, [WIRING, "wire", "write", file, doubled]).status, 0);
  const status = node(box.env, [WIRING, "status", file, box.claude + sep + "hooks" + sep]);
  assert.strictEqual(status.stdout, "", "status called a wired hook missing");
  const cleaned = node(box.env, [WIRING, "clean", file, box.claude + sep]);
  assert.strictEqual(cleaned.status, 10, cleaned.stderr);
  const after = JSON.parse(fs.readFileSync(file, "utf8"));
  assert.deepStrictEqual(after.hooks, {}, "clean left entries of ours");
  assert.strictEqual(after.statusLine, undefined, "clean left the status line");
});

// The installers back settings.json up only when the wiring will change it,
// so check must say which, and write nothing either way.
test("wire check says whether write would change the file", (t) => {
  const box = sandbox(t);
  const hooks = hooksDir(box);
  const file = path.join(box.claude, "settings.json");
  fs.writeFileSync(file, '{"model": "opus"}\n');
  const check = () => {
    const r = node(box.env, [WIRING, "wire", "check", file, hooks]);
    assert.strictEqual(r.status, 0, r.stderr);
    return r.stdout;
  };
  assert.strictEqual(check(), "changes\n");
  assert.strictEqual(fs.readFileSync(file, "utf8"), '{"model": "opus"}\n', "check wrote the file");
  assert.strictEqual(node(box.env, [WIRING, "wire", "write", file, hooks]).status, 0);
  assert.strictEqual(check(), "unchanged\n");
});

// Windows PowerShell 5 saves UTF-8 with a byte order mark, which JSON.parse
// refuses; the file is still the user's settings, and is wired and cleaned.
test("a settings.json saved with a byte order mark is wired and cleaned", (t) => {
  const box = sandbox(t);
  const hooks = hooksDir(box);
  const file = path.join(box.claude, "settings.json");
  fs.writeFileSync(file, '\ufeff{\r\n  "model": "opus"\r\n}\r\n');
  const wired = node(box.env, [WIRING, "wire", "write", file, hooks]);
  assert.strictEqual(wired.status, 0, wired.stderr);
  const after = fs.readFileSync(file, "utf8");
  assert.strictEqual(JSON.parse(after).model, "opus");
  assert.deepStrictEqual(wiring.missing(JSON.parse(after), hooks), []);
  fs.writeFileSync(file, "\ufeff" + after);
  const status = node(box.env, [WIRING, "status", file, hooks]);
  assert.strictEqual(status.status, 0, status.stderr);
  assert.strictEqual(status.stdout, "");
  assert.strictEqual(node(box.env, [WIRING, "clean", file, box.claude]).status, 10);
  assert.deepStrictEqual(JSON.parse(fs.readFileSync(file, "utf8")), { model: "opus", hooks: {} });
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
  // status cannot say what is wired in a file it cannot read: not "nothing"
  for (const unreadable of [() => {}, () => { fs.rmdirSync(file); fs.writeFileSync(file, "{ not json"); }]) {
    unreadable();
    const r = node(box.env, [WIRING, "status", file, hooks]);
    assert.strictEqual(r.status, 1, `status answered for an unreadable settings.json: ${JSON.stringify(r.stdout)}`);
    assert.strictEqual(r.stdout, "");
  }
  fs.rmSync(file);
  fs.mkdirSync(file);
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
