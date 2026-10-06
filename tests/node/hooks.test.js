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
const { ROOT, sandbox, node, nodeLate } = require("./sandbox.js");

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
