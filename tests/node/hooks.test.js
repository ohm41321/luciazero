"use strict";
// The enforcement hooks on whatever platform runs this file -- Windows
// included, where they are the only hooks there are. The Bash gates cover
// them in depth on macOS and Linux; this is the part that must hold
// everywhere: the state machine reaches a nudge and clears it, input that
// arrives late is still read, and the status line renders.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { ROOT, WINDOWS, sandbox, node, nodeLate } = require("./sandbox.js");

const VERIFY = path.join(ROOT, "claude", "hooks", "luciazero-verify.cjs");
const STATUS = path.join(ROOT, "claude", "hooks", "luciazero-statusline.cjs");

function stateDir(env, cwd) {
  const r = node(env, ["-e", "const v = require(process.argv[1]); console.log(require('path').join(v.stateBase(), v.stateKey(process.argv[2])))", VERIFY, cwd]);
  assert.strictEqual(r.status, 0, r.stderr);
  return r.stdout.trim();
}

test("an edit nudges once at stop, and a verify run clears it", (t) => {
  const box = sandbox(t);
  const cwd = path.join(box.box, "project");
  const event = (extra = {}) => JSON.stringify({ cwd, session_id: "s1", ...extra });
  assert.strictEqual(node(box.env, [VERIFY, "prompt"], event({ prompt: "fix it" })).status, 0);
  assert.strictEqual(node(box.env, [VERIFY, "edit"], event({ tool_name: "Edit", tool_input: { file_path: path.join(cwd, "a.js") } })).status, 0);
  const nudged = node(box.env, [VERIFY, "stop"], event());
  assert.strictEqual(nudged.status, 2, "an unverified edit must nudge at stop");
  assert.match(nudged.stderr, /verif/i);
  assert.strictEqual(node(box.env, [VERIFY, "stop"], event({ stop_hook_active: true })).status, 0,
    "the stop the nudge caused must end the turn");

  assert.strictEqual(node(box.env, [VERIFY, "edit"], event({ tool_name: "Write", tool_input: { file_path: path.join(cwd, "b.js") } })).status, 0);
  // PowerShell is the shell tool on Windows; its command is read the same way
  const ran = node(box.env, [VERIFY, "bash"], event({ tool_name: "PowerShell", tool_input: { command: "npm test" } }));
  assert.strictEqual(ran.status, 0, ran.stderr);
  assert.strictEqual(fs.readFileSync(path.join(stateDir(box.env, cwd), "last_verify"), "utf8"), "ok\n");
  assert.strictEqual(node(box.env, [VERIFY, "stop"], event()).status, 0, "a verified edit must not nudge");
});

// The strict gate runs its command through the platform's shell. A command the
// shell cannot find is no verdict: the stop gets the ordinary nudge and nothing
// records a red. cmd.exe exits 1 for it, as a failing test does, and says so
// only in the display language, so the reds that must still block matter as
// much here: a builtin, a program in the project, one that deletes itself as
// it fails, a compound command, and a program that prints cmd.exe's own
// English line.
test("the strict gate nudges for a command the shell cannot find, and blocks a real red", (t) => {
  const nodeExe = `"${process.execPath}"`;
  const missing = WINDOWS
    ? ["luciazero-no-such-cmd --x", "@luciazero-no-such-cmd", "luciazero-no-such-cmd && echo after",
      '".\\luciazero-no-such.cmd" x', "tests"]
    : ["./luciazero-no-such-cmd.sh", "luciazero-no-such-cmd --x"];
  const red = WINDOWS
    ? ["exit /b 1", "dir luciazero-no-such-file", "runner", "gone", `${nodeExe} -e "process.exit(1)"`,
      `${nodeExe} say.js`, "luciazero-no-such-cmd & exit /b 1"]
    : ["exit 1", "./gone.sh", `${nodeExe} -e "process.exit(1)"`, `${nodeExe} say.js`];
  for (const [command, blocks] of [...missing.map((c) => [c, false]), ...red.map((c) => [c, true])]) {
    const box = sandbox(t);
    const cwd = path.join(box.box, "project");
    fs.mkdirSync(path.join(cwd, "tests"), { recursive: true });
    fs.writeFileSync(path.join(cwd, "runner.cmd"), "@exit /b 1\r\n");
    fs.writeFileSync(path.join(cwd, "gone.cmd"), '@del "%~f0" & exit /b 1\r\n');
    fs.writeFileSync(path.join(cwd, "gone.sh"), '#!/bin/sh\nrm -f -- "$0"\nexit 1\n', { mode: 0o755 });
    fs.writeFileSync(path.join(cwd, "say.js"), "console.error(\"'x' is not recognized as an internal or external command,\");\nprocess.exit(1);\n");
    const event = (extra = {}) => JSON.stringify({ cwd, session_id: "s1", ...extra });
    assert.strictEqual(node(box.env, [VERIFY, "edit"], event({ tool_name: "Edit", tool_input: { file_path: path.join(cwd, "a.js") } })).status, 0);
    const stop = node({ ...box.env, LUCIAZERO_STRICT_VERIFY_CMD: command, LUCIAZERO_STRICT_TIMEOUT: "60" }, [VERIFY, "stop"], event());
    const stats = path.join(box.claude, "luciazero-stats.log");
    const events = fs.existsSync(stats)
      ? fs.readFileSync(stats, "utf8").split("\n").filter(Boolean).map((line) => JSON.parse(line).event) : [];
    const last = path.join(stateDir(box.env, cwd), "last_verify");
    const verdict = fs.existsSync(last) ? fs.readFileSync(last, "utf8") : null;
    assert.strictEqual(stop.status, 2, `${command}: ${stop.stderr}`);
    if (blocks) {
      assert.match(stop.stderr, /Strict verify gate/, `${command} is a real red and must block`);
      assert.deepStrictEqual(events, ["strict-block"], command);
      assert.strictEqual(verdict, "fail\n", command);
    } else {
      assert.match(stop.stderr, /Doctrine rule 1/, `${command} could not run, which must nudge`);
      assert.doesNotMatch(stop.stderr, /Strict verify gate/, `${command} could not run, yet a red was reported`);
      assert.deepStrictEqual(events, ["nudge"], command);
      assert.strictEqual(verdict, null, command);
    }
  }
});

test("hook input that arrives after the hook starts is read whole", async (t) => {
  const box = sandbox(t);
  const cwd = path.join(box.box, "slow");
  const ran = await nodeLate(box.env, [VERIFY, "bash"],
    JSON.stringify({ cwd, tool_input: { command: "npm test" }, note: "ข้อมูลทดสอบ" }) + "\n", 500);
  assert.strictEqual(ran.status, 0, ran.stderr);
  assert.strictEqual(fs.readFileSync(path.join(stateDir(box.env, cwd), "last_verify"), "utf8"), "ok\n",
    "the verify run in late input was dropped");
  const shown = await nodeLate(box.env, [STATUS], JSON.stringify({ cwd, model: { display_name: "LateModelทดสอบ" } }), 500);
  assert.strictEqual(shown.status, 0, shown.stderr);
  assert.match(shown.stdout, /^LateModelทดสอบ \| /);
});

test("the status line shows the model and the verify state", (t) => {
  const box = sandbox(t);
  const cwd = path.join(box.box, "status");
  const before = node(box.env, [STATUS], JSON.stringify({ cwd, model: { display_name: "Model" } }));
  assert.strictEqual(before.status, 0, before.stderr);
  assert.match(before.stdout, /no verify yet/);
  node(box.env, [VERIFY, "bash"], JSON.stringify({ cwd, tool_input: { command: "npm test" } }));
  const after = node(box.env, [STATUS], JSON.stringify({ cwd, model: { display_name: "Model" } }));
  assert.match(after.stdout, /verify/);
  assert.doesNotMatch(after.stdout, /no verify yet/);
});

// Windows looks for a bare command name in the working directory before PATH,
// and the status line runs in the project: a git.exe there -- here a copy of
// node, which cannot name a branch -- must not be the git that runs.
test("the status line names the branch with the git on PATH, never one in the project", (t) => {
  const box = sandbox(t);
  const cwd = path.join(box.box, "branchy");
  fs.mkdirSync(cwd);
  const made = spawnSync("git", ["init", "-q", "-b", "lz-branch", cwd], { env: box.env, encoding: "utf8", windowsHide: true });
  assert.strictEqual(made.status, 0, made.stderr);
  if (WINDOWS) {
    fs.copyFileSync(process.execPath, path.join(cwd, "git.exe"));
    const bare = spawnSync("git", ["-C", cwd, "branch", "--show-current"], { cwd, env: box.env, encoding: "utf8", windowsHide: true });
    assert.notStrictEqual(bare.status, 0, "the copy in the project did not run for a bare name; this case proves nothing");
  }
  const shown = spawnSync(process.execPath, [STATUS], {
    cwd, env: box.env, input: JSON.stringify({ cwd, model: { display_name: "Model" } }), encoding: "utf8", windowsHide: true,
  });
  assert.strictEqual(shown.status, 0, shown.stderr);
  assert.match(shown.stdout, /^Model \| lz-branch \| /);
});
