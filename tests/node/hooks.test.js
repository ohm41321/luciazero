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
  const r = node(env, ["-e", "const v = require(process.argv[1]); console.log(require('path').join(v.stateBase(), v.stateKey(v.projectOf(process.argv[2]))))", VERIFY, cwd]);
  assert.strictEqual(r.status, 0, r.stderr);
  return r.stdout.trim();
}

const lastVerify = (env, cwd) => {
  const file = path.join(stateDir(env, cwd), "last_verify");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8") : null;
};

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
// it fails, one found only through PATH and PATHEXT, forms cmd.exe takes
// apart differently (a leading redirection or delimiter, a quote inside the
// word, a drive change), a compound command, and a program that prints
// cmd.exe's own English line.
test("the strict gate nudges for a command the shell cannot find, and blocks a real red", (t) => {
  const nodeExe = `"${process.execPath}"`;
  const missing = WINDOWS
    ? ["luciazero-no-such-cmd --x", "@luciazero-no-such-cmd", "luciazero-no-such-cmd && echo after",
      '".\\luciazero-no-such.cmd" x', "tests"]
    : ["./luciazero-no-such-cmd.sh", "luciazero-no-such-cmd --x"];
  const red = WINDOWS
    ? ["exit /b 1", "dir luciazero-no-such-file", "runner", "gone", "lz-red", "2>nul lz-red", ";lz-red", "lz-red,x",
      '"%BIN%"\\lz-red.cmd', "%DRIVE% && lz-red", `${nodeExe} -e "process.exit(1)"`, `${nodeExe} say.js`,
      "luciazero-no-such-cmd & exit /b 1"]
    : ["exit 1", "./gone.sh", "lz-red", `${nodeExe} -e "process.exit(1)"`, `${nodeExe} say.js`];
  for (const [command, blocks] of [...missing.map((c) => [c, false]), ...red.map((c) => [c, true])]) {
    const box = sandbox(t);
    const cwd = path.join(box.box, "project");
    const bin = path.join(box.box, "bin");
    fs.mkdirSync(bin);
    if (WINDOWS) fs.writeFileSync(path.join(bin, "lz-red.cmd"), "@exit /b 1\r\n");
    else fs.writeFileSync(path.join(bin, "lz-red"), "#!/bin/sh\nexit 1\n", { mode: 0o755 });
    const pathKey = Object.keys(box.env).find((key) => key.toUpperCase() === "PATH") || "PATH";
    const env = { ...box.env, [pathKey]: `${bin}${path.delimiter}${box.env[pathKey] || ""}` };
    const verify = command.replace("%BIN%", bin).replace("%DRIVE%", path.parse(cwd).root.slice(0, 2));
    fs.mkdirSync(path.join(cwd, "tests"), { recursive: true });
    fs.writeFileSync(path.join(cwd, "runner.cmd"), "@exit /b 1\r\n");
    fs.writeFileSync(path.join(cwd, "gone.cmd"), '@del "%~f0" & exit /b 1\r\n');
    fs.writeFileSync(path.join(cwd, "gone.sh"), '#!/bin/sh\nrm -f -- "$0"\nexit 1\n', { mode: 0o755 });
    fs.writeFileSync(path.join(cwd, "say.js"), "console.error(\"'x' is not recognized as an internal or external command,\");\nprocess.exit(1);\n");
    const event = (extra = {}) => JSON.stringify({ cwd, session_id: "s1", ...extra });
    assert.strictEqual(node(box.env, [VERIFY, "edit"], event({ tool_name: "Edit", tool_input: { file_path: path.join(cwd, "a.js") } })).status, 0);
    const stop = node({ ...env, LUCIAZERO_STRICT_VERIFY_CMD: verify, LUCIAZERO_STRICT_TIMEOUT: "60" }, [VERIFY, "stop"], event());
    const stats = path.join(box.claude, "luciazero-stats.log");
    const events = fs.existsSync(stats)
      ? fs.readFileSync(stats, "utf8").split("\n").filter(Boolean).map((line) => JSON.parse(line).event) : [];
    const last = path.join(stateDir(box.env, cwd), "last_verify");
    const verdict = fs.existsSync(last) ? fs.readFileSync(last, "utf8") : null;
    assert.strictEqual(stop.status, 2, `${verify}: ${stop.stderr}`);
    if (blocks) {
      assert.match(stop.stderr, /Strict verify gate/, `${verify} is a real red and must block`);
      assert.deepStrictEqual(events, ["strict-block"], verify);
      assert.strictEqual(verdict, "fail\n", verify);
    } else {
      assert.match(stop.stderr, /Doctrine rule 1/, `${verify} could not run, which must nudge`);
      assert.doesNotMatch(stop.stderr, /Strict verify gate/, `${verify} could not run, yet a red was reported`);
      assert.deepStrictEqual(events, ["nudge"], verify);
      assert.strictEqual(verdict, null, verify);
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

// A verify started in the background has no result yet when its PostToolUse
// arrives, and a failure later comes back as a notice, never as a failed
// tool call: the launch is not a green.
test("a verify run in the background is not recorded as green", (t) => {
  const box = sandbox(t);
  const cwd = path.join(box.box, "bg");
  const event = (extra = {}) => JSON.stringify({ cwd, session_id: "s1", ...extra });
  assert.strictEqual(node(box.env, [VERIFY, "edit"], event({ tool_name: "Edit", tool_input: { file_path: path.join(cwd, "a.js") } })).status, 0);
  const ran = node(box.env, [VERIFY, "bash"], event({
    tool_name: "Bash", tool_input: { command: "npm test", run_in_background: true }, tool_response: { backgroundTaskId: "b1" },
  }));
  assert.strictEqual(ran.status, 0, ran.stderr);
  assert.strictEqual(lastVerify(box.env, cwd), null, "a background launch was recorded as a verify result");
  assert.strictEqual(node(box.env, [VERIFY, "stop"], event()).status, 2, "the edit is still unverified");
});

// A verify proves the code as it was when the run started: an edit that
// lands while it runs -- another session, a background agent -- is after it.
test("an edit made while a verify runs is still unverified", (t) => {
  const box = sandbox(t);
  const cwd = path.join(box.box, "during");
  const event = (extra = {}) => JSON.stringify({ cwd, session_id: "s1", ...extra });
  const edit = () => assert.strictEqual(node(box.env, [VERIFY, "edit"],
    event({ tool_name: "Edit", tool_input: { file_path: path.join(cwd, "a.js") } })).status, 0);
  const verify = (id, mode) => assert.strictEqual(node(box.env, [VERIFY, mode],
    event({ tool_name: "Bash", tool_use_id: id, tool_input: { command: "npm test" } })).status, 0);
  edit();
  verify("t1", "bash-start");
  verify("t1", "bash");
  assert.strictEqual(node(box.env, [VERIFY, "stop"], event()).status, 0, "a verify started after the edit covers it");
  verify("t2", "bash-start");
  edit();
  verify("t2", "bash");
  assert.strictEqual(node(box.env, [VERIFY, "stop"], event()).status, 2, "the edit made during the run was taken as verified");
});

// The session's project is where Claude Code started; a `cd` into a
// subdirectory persists between tool calls and must not move the session to
// state that has none of its edits, nor stop the refusal walk at a checkout
// nested inside the project.
test("state and refusals follow the project, not the directory the session moved to", (t) => {
  const box = sandbox(t);
  const project = path.join(box.box, "proj");
  const sub = path.join(project, "vendor", "lib");
  fs.mkdirSync(path.join(sub, ".git"), { recursive: true });
  fs.mkdirSync(path.join(project, ".claude"));
  fs.writeFileSync(path.join(project, ".claude", "settings.json"), JSON.stringify({ env: { LUCIAZERO_VERIFY_REGEX: ".*" } }));
  const env = { ...box.env, CLAUDE_PROJECT_DIR: project };
  const event = (cwd, extra = {}) => JSON.stringify({ cwd, session_id: "s1", ...extra });
  assert.strictEqual(node(env, [VERIFY, "edit"], event(project, { tool_name: "Edit", tool_input: { file_path: path.join(project, "a.js") } })).status, 0);
  assert.strictEqual(node(env, [VERIFY, "stop"], event(sub)).status, 2, "a stop from a subdirectory escaped the nudge");
  // the committed regex makes any command a verify; refused, `ls` is none
  const ran = node({ ...env, LUCIAZERO_VERIFY_REGEX: ".*" }, [VERIFY, "bash"], event(sub, { tool_name: "Bash", tool_input: { command: "ls" } }));
  assert.strictEqual(ran.status, 0, ran.stderr);
  assert.strictEqual(lastVerify(env, sub), null, "the project's committed settings went unrefused below a nested checkout");
  const shown = node(env, [STATUS], JSON.stringify({ model: { display_name: "M" }, workspace: { current_dir: sub, project_dir: project } }));
  assert.match(shown.stdout, /unverified/, shown.stdout);
});

// Windows reads environment names without regard to case, so a committed
// lowercase name sets the same variable and must be refused the same way.
test("on Windows a committed knob in lowercase is refused too", { skip: !WINDOWS && "Windows only" }, (t) => {
  const box = sandbox(t);
  const cwd = path.join(box.box, "lower");
  fs.mkdirSync(path.join(cwd, ".claude"), { recursive: true });
  fs.mkdirSync(path.join(cwd, ".git"));
  fs.writeFileSync(path.join(cwd, ".claude", "settings.json"), JSON.stringify({ env: { luciazero_verify_regex: ".*" } }));
  const ran = node({ ...box.env, luciazero_verify_regex: ".*" }, [VERIFY, "bash"],
    JSON.stringify({ cwd, tool_name: "Bash", tool_input: { command: "ls" } }));
  assert.strictEqual(ran.status, 0, ran.stderr);
  assert.strictEqual(lastVerify(box.env, cwd), null, "a lowercase committed knob was not refused");
});

// A strict verify that outlives its timeout is stopped whole: what the shell
// started must not run on after the stop, beside the model's next command.
test("a strict verify that times out leaves nothing running", { skip: WINDOWS && "POSIX process groups" }, (t) => {
  const box = sandbox(t);
  const cwd = path.join(box.box, "slow");
  fs.mkdirSync(cwd);
  const marker = `lz-strict-orphan-${process.pid}-${Date.now()}`;
  t.after(() => spawnSync("pkill", ["-f", marker]));
  const event = (extra = {}) => JSON.stringify({ cwd, session_id: "s1", ...extra });
  assert.strictEqual(node(box.env, [VERIFY, "edit"], event({ tool_name: "Edit", tool_input: { file_path: path.join(cwd, "a.js") } })).status, 0);
  const strict = `"${process.execPath}" -e "setTimeout(() => {}, 30000)" ${marker}; echo done`;
  const stop = node({ ...box.env, LUCIAZERO_STRICT_VERIFY_CMD: strict, LUCIAZERO_STRICT_TIMEOUT: "1" }, [VERIFY, "stop"], event());
  assert.strictEqual(stop.status, 2, stop.stderr);
  assert.doesNotMatch(stop.stderr, /Strict verify gate/, "a timeout is no red");
  const left = spawnSync("pgrep", ["-f", marker], { encoding: "utf8" });
  assert.strictEqual(left.stdout.trim(), "", "the timed-out verify's program is still running");
});

// CLAUDE_CONFIG_DIR from a repository's committed settings moves the config
// directory the hook checks for a classic install; refused there, it cannot
// make a plugin's doctrine or hooks stand down for one that is not installed.
test("a committed CLAUDE_CONFIG_DIR cannot silence the doctrine or the hooks", (t) => {
  const box = sandbox(t);
  const project = path.join(box.box, "cfgproj");
  const planted = path.join(project, "cfg");
  fs.mkdirSync(path.join(planted, "hooks"), { recursive: true });
  fs.mkdirSync(path.join(project, ".git"));
  fs.mkdirSync(path.join(project, ".claude"));
  fs.writeFileSync(path.join(project, ".claude", "settings.json"), JSON.stringify({ env: { CLAUDE_CONFIG_DIR: planted } }));
  fs.writeFileSync(path.join(planted, "luciazero.md"), "decoy\n");
  // a classic install there, as far as the hook can tell
  fs.copyFileSync(VERIFY, path.join(planted, "hooks", "luciazero-verify.cjs"));
  fs.writeFileSync(path.join(planted, "settings.json"), JSON.stringify({
    hooks: { Stop: [{ hooks: [{ type: "command", command: "node", args: [path.join(planted, "hooks", "luciazero-verify.cjs"), "stop"] }] }] },
  }));
  const env = { ...box.env, CLAUDE_CONFIG_DIR: planted, PWD: project };
  const doctrine = spawnSync(process.execPath, [VERIFY, "doctrine"], { cwd: project, env, encoding: "utf8", windowsHide: true });
  assert.strictEqual(doctrine.status, 0, doctrine.stderr);
  assert.match(doctrine.stdout, /Ground truth/, "the doctrine was silenced");
  const prompt = node(env, [VERIFY, "prompt"], JSON.stringify({ cwd: project, session_id: "s1", prompt: "go" }));
  assert.strictEqual(prompt.status, 0, prompt.stderr);
  const turn = path.join(stateDir(box.env, project), "telemetry");
  assert.ok(fs.existsSync(turn), "the prompt hook stood down for a classic install that is not there");
});

test("a Node that refuses md5 still names the state directory, with sha256", (t) => {
  // FIPS mode makes createHash("md5") throw; the tracker must not fail open
  const probe = [
    "const crypto = require('node:crypto');",
    "const real = crypto.createHash;",
    "crypto.createHash = (name, ...rest) => {",
    "  if (String(name).toLowerCase() === 'md5') throw new Error('md5 is disabled (FIPS)');",
    "  return real.call(crypto, name, ...rest);",
    "};",
    "const v = require(process.argv[1]);",
    "console.log(v.stateKey(process.argv[2]));",
  ].join("\n");
  const project = path.join(sandbox(t).box, "project");
  const r = spawnSync(process.execPath, ["-e", probe, VERIFY, project], { encoding: "utf8" });
  assert.strictEqual(r.status, 0, r.stderr);
  const expected = require("node:crypto").createHash("sha256").update(project, "utf8").digest("hex").slice(0, 12);
  assert.strictEqual(r.stdout.trim(), expected);
});
