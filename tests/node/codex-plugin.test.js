"use strict";
// The repository is also a Codex plugin, and Codex runs a plugin's hooks by
// its own rules, not Claude Code's. This file runs them the way Codex 0.162
// does, on whatever platform runs it:
//
// - the manifest is the first of .codex-plugin/, .claude-plugin/ and
//   .cursor-plugin/plugin.json under the plugin root (exec-server-protocol
//   DISCOVERABLE_PLUGIN_MANIFEST_PATHS);
// - a command hook is `command` (`commandWindows` on Windows) and nothing
//   else: there is no `args`, so Claude's exec form reaches Codex as a bare
//   `node` (hook_config.rs HookHandlerConfig::Command);
// - `${PLUGIN_ROOT}` and its siblings are replaced in that string, and the
//   same names are set in the environment (engine/discovery.rs);
// - the string runs as `$SHELL -lc <command>`, or `%COMSPEC% /C "<command>"`
//   on Windows, in the session's working directory (engine/command_runner.rs);
// - CLAUDE_CONFIG_DIR is not set, and a shell command's PostToolUse carries
//   only its output, as a string, whatever it exited with (unified_exec.rs,
//   ExecCommandToolOutput::post_tool_use_response).
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { ROOT, WINDOWS, sandbox, node } = require("./sandbox.js");

const VERIFY = path.join(ROOT, "claude", "hooks", "luciazero-verify.cjs");
const MANIFESTS = [".codex-plugin/plugin.json", ".claude-plugin/plugin.json", ".cursor-plugin/plugin.json"];
// The events Codex has (hook_config.rs HookEventsToml).
const CODEX_EVENTS = new Set(["PreToolUse", "PermissionRequest", "PostToolUse", "PreCompact", "PostCompact",
  "SessionStart", "SessionEnd", "UserPromptSubmit", "SubagentStart", "SubagentStop", "Stop", "Interrupt"]);

// Every hook Codex would register from the plugin at `root`, as [event, matcher, handler].
function codexHooks(root) {
  const manifest = MANIFESTS.map((rel) => path.join(root, rel)).find((file) => fs.existsSync(file));
  assert.ok(manifest, "Codex finds no plugin manifest");
  const declared = JSON.parse(fs.readFileSync(manifest, "utf8")).hooks;
  const sources = declared === undefined ? ["./hooks/hooks.json"] : [].concat(declared);
  const hooks = [];
  for (const source of sources) {
    const file = typeof source === "string" ? JSON.parse(fs.readFileSync(path.join(root, source), "utf8")) : source;
    for (const [event, groups] of Object.entries(file.hooks || {})) {
      if (!CODEX_EVENTS.has(event)) continue;
      for (const group of groups) {
        for (const handler of group.hooks || []) hooks.push([event, group.matcher || "", handler]);
      }
    }
  }
  return hooks;
}

// The mode a handler passes the verify hook, read from what Codex would run.
function modeOf(handler) {
  const command = WINDOWS ? (handler.commandWindows || handler.command) : handler.command;
  const match = /luciazero-verify\.cjs["']?\s+([a-z-]+)/.exec(command || "");
  return match ? match[1] : null;
}

function find(hooks, event, mode) {
  const found = hooks.filter(([e, , h]) => e === event && modeOf(h) === mode);
  assert.strictEqual(found.length, 1, `Codex must run ${event} ${mode} exactly once`);
  return found[0];
}

// A copy of the plugin under a root whose name a shell would take apart if
// the command did not keep it whole. POSIX keeps the quote out: a plugin path
// holding one is a known limit of the single-quoted form.
function pluginCopy(box) {
  const root = path.join(box, WINDOWS ? "plugin root &;$x'(%^!)" : "plugin root &;$x`(%^!)");
  for (const rel of [".codex-plugin", ".claude-plugin", "claude"]) {
    if (fs.existsSync(path.join(ROOT, rel))) fs.cpSync(path.join(ROOT, rel), path.join(root, rel), { recursive: true });
  }
  return root;
}

// Run one handler as Codex runs it, with `event` on stdin.
function codexRun(handler, env, pluginRoot, cwd, event) {
  assert.strictEqual(handler.type, "command");
  const data = path.join(path.dirname(pluginRoot), "plugin data");
  fs.mkdirSync(data, { recursive: true });
  const vars = { PLUGIN_ROOT: pluginRoot, CLAUDE_PLUGIN_ROOT: pluginRoot, PLUGIN_DATA: data, CLAUDE_PLUGIN_DATA: data };
  let command = WINDOWS ? (handler.commandWindows || handler.command) : handler.command;
  for (const [key, value] of Object.entries(vars)) command = command.split("${" + key + "}").join(value);
  const options = { cwd, env: { ...env, ...vars }, input: JSON.stringify(event), encoding: "utf8", windowsHide: true };
  const r = WINDOWS
    ? spawnSync(env.ComSpec || env.COMSPEC || "cmd.exe", ["/C", `"${command}"`], { ...options, windowsVerbatimArguments: true })
    : spawnSync(env.SHELL || "/bin/sh", ["-lc", command], options);
  if (r.error) throw r.error;
  return { status: r.status, stdout: r.stdout, stderr: r.stderr };
}

// Codex's environment: no CLAUDE_CONFIG_DIR, so ~/.claude is the sandbox's,
// and Claude's classic hooks are wired there, as on a machine that has both.
function codexBox(t) {
  const box = sandbox(t);
  const env = { ...box.env };
  delete env.CLAUDE_CONFIG_DIR;
  const classic = path.join(box.home, ".claude", "hooks", "luciazero-verify.cjs");
  fs.mkdirSync(path.dirname(classic), { recursive: true });
  fs.copyFileSync(VERIFY, classic);
  fs.writeFileSync(path.join(box.home, ".claude", "settings.json"), JSON.stringify({ hooks: { Stop: [{ hooks: [
    { type: "command", command: "node", args: [classic, "stop"] }] }] } }));
  fs.writeFileSync(path.join(box.home, ".claude", "luciazero.md"), "classic doctrine\n");
  const cwd = path.join(box.box, "project");
  fs.mkdirSync(cwd, { recursive: true });
  return { ...box, env, cwd, root: pluginCopy(box.box) };
}

function lastVerify(env, cwd) {
  const r = node(env, ["-e", "const v = require(process.argv[1]); console.log(require('path').join(v.stateBase(), v.stateKey(v.projectOf(process.argv[2])), 'last_verify'))", VERIFY, cwd]);
  assert.strictEqual(r.status, 0, r.stderr);
  const file = r.stdout.trim();
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8") : null;
}

test("Codex runs every plugin hook as a command it can parse, in step with Claude's", () => {
  const hooks = codexHooks(ROOT);
  for (const [event, matcher, handler] of hooks) {
    assert.strictEqual(handler.args, undefined, `${event} ${matcher}: Codex ignores args, so the hook would run a bare node`);
    assert.strictEqual(typeof handler.command, "string", `${event}: no command`);
    assert.strictEqual(typeof handler.commandWindows, "string", `${event}: no commandWindows; Codex would run the POSIX command in cmd.exe`);
    assert.ok(modeOf(handler), `${event}: does not run the verify hook: ${handler.command}`);
  }
  // Claude's wiring, less the events Codex does not have, is Codex's.
  const claude = JSON.parse(fs.readFileSync(path.join(ROOT, "claude", "hooks", "hooks.json"), "utf8")).hooks;
  const want = [];
  for (const [event, groups] of Object.entries(claude)) {
    if (!CODEX_EVENTS.has(event)) continue;
    for (const group of groups) for (const h of group.hooks) want.push(`${event} ${group.matcher || ""} ${h.args[1]}`);
  }
  assert.deepStrictEqual(hooks.map(([e, m, h]) => `${e} ${m} ${modeOf(h)}`).sort(), want.sort());
  // apply_patch reaches Codex hooks as Edit and Write, a shell command as Bash
  assert.match(find(hooks, "PostToolUse", "edit")[1], /(^|\|)Edit(\||$)/);
  for (const [event, mode] of [["PreToolUse", "bash-start"], ["PostToolUse", "bash"]]) {
    assert.match(find(hooks, event, mode)[1], /(^|\|)Bash(\||$)/);
  }
});

test("under Codex an edit nudges once at stop, beside a classic Claude install", (t) => {
  const box = codexBox(t);
  const hooks = codexHooks(box.root);
  const event = (extra) => ({ session_id: "s1", transcript_path: null, cwd: box.cwd, model: "gpt", permission_mode: "default", ...extra });
  const run = (eventName, mode, extra = {}) =>
    codexRun(find(hooks, eventName, mode)[2], box.env, box.root, box.cwd, event({ hook_event_name: eventName, ...extra }));

  const session = run("SessionStart", "session", { source: "startup" });
  assert.strictEqual(session.status, 0, session.stderr);
  assert.strictEqual(run("UserPromptSubmit", "prompt", { prompt: "fix it", turn_id: "t1" }).status, 0);
  const patch = run("PostToolUse", "edit", { tool_name: "apply_patch", tool_use_id: "c1", turn_id: "t1",
    tool_input: { command: "*** Begin Patch\n*** Update File: a.js\n@@\n-a\n+b\n*** End Patch\n" },
    tool_response: "Success. Updated the following files:\nM a.js\n" });
  assert.strictEqual(patch.status, 0, patch.stderr);
  const nudged = run("Stop", "stop", { stop_hook_active: false, turn_id: "t1" });
  assert.strictEqual(nudged.status, 2, `an unverified edit under Codex must nudge (stderr: ${nudged.stderr})`);
  assert.match(nudged.stderr, /Doctrine rule 1/);
  assert.strictEqual(run("Stop", "stop", { stop_hook_active: true, turn_id: "t1" }).status, 0,
    "the stop the nudge caused must end the turn");

  // next turn: an edit, then a verify run, so the stop has nothing to say
  assert.strictEqual(run("PostToolUse", "edit", { tool_name: "apply_patch", tool_use_id: "c2", turn_id: "t2",
    tool_input: { command: "*** Begin Patch\n*** Update File: a.js\n@@\n-b\n+c\n*** End Patch\n" },
    tool_response: "Success." }).status, 0);
  const shell = { tool_name: "Bash", tool_use_id: "c3", turn_id: "t2", tool_input: { command: "npm test" } };
  assert.strictEqual(run("PreToolUse", "bash-start", shell).status, 0);
  assert.strictEqual(run("PostToolUse", "bash", { ...shell, tool_response: "1 passing\n" }).status, 0);
  const quiet = run("Stop", "stop", { stop_hook_active: false, turn_id: "t2" });
  assert.strictEqual(quiet.status, 0, `a verify ran after the edit (stderr: ${quiet.stderr})`);
});

test("under Codex a verify command is recorded as run, never as green", (t) => {
  const box = codexBox(t);
  const hooks = codexHooks(box.root);
  const event = (extra) => ({ session_id: "s1", transcript_path: null, cwd: box.cwd, model: "gpt", permission_mode: "default", turn_id: "t1", ...extra });
  const run = (eventName, mode, extra = {}, env = box.env) =>
    codexRun(find(hooks, eventName, mode)[2], env, box.root, box.cwd, event({ hook_event_name: eventName, ...extra }));
  // "verify" in the name makes it a verify command to the default pattern
  fs.writeFileSync(path.join(box.cwd, "verify.js"), "console.error('1 failing');\nprocess.exit(1);\n");
  const failing = `"${process.execPath}" verify.js`;
  const strict = { ...box.env, LUCIAZERO_STRICT_VERIFY_CMD: failing, LUCIAZERO_STRICT_TIMEOUT: "60" };

  assert.strictEqual(run("PostToolUse", "edit", { tool_name: "apply_patch", tool_use_id: "c1",
    tool_input: { command: "*** Begin Patch\n*** Add File: a.js\n+x\n*** End Patch\n" }, tool_response: "Success." }).status, 0);
  const shell = { tool_name: "Bash", tool_use_id: "c2", tool_input: { command: failing } };
  assert.strictEqual(run("PreToolUse", "bash-start", shell).status, 0);
  // Codex sends this for a command that failed as well as for one that passed
  assert.strictEqual(run("PostToolUse", "bash", { ...shell, tool_response: "Error: 1 failing\n" }).status, 0);
  assert.strictEqual(lastVerify(box.env, box.cwd), "ran\n", "Codex gave no exit code, so the run proves nothing green");
  const stop = run("Stop", "stop", { stop_hook_active: false }, strict);
  assert.strictEqual(stop.status, 2, `strict mode must run the failing command, not trust a recorded green (stderr: ${stop.stderr})`);
  assert.match(stop.stderr, /Strict verify gate/);
});

test("under Codex the doctrine loads once: beside Claude's classic install, not beside Codex's", (t) => {
  const box = codexBox(t);
  const doctrine = find(codexHooks(box.root), "SessionStart", "doctrine")[2];
  const start = { session_id: "s1", cwd: box.cwd, hook_event_name: "SessionStart", source: "startup" };
  const text = fs.readFileSync(path.join(ROOT, "claude", "luciazero.md"), "utf8");
  const first = codexRun(doctrine, box.env, box.root, box.cwd, start);
  assert.strictEqual(first.status, 0, first.stderr);
  assert.strictEqual(first.stdout, text, "Claude's classic install does not load the doctrine into Codex");
  fs.mkdirSync(box.codex, { recursive: true });
  fs.writeFileSync(path.join(box.codex, "AGENTS.md"), `mine\n\n<!-- luciazero:start -->\n${text}<!-- luciazero:end -->\n`);
  const second = codexRun(doctrine, box.env, box.root, box.cwd, start);
  assert.strictEqual(second.status, 0, second.stderr);
  assert.strictEqual(second.stdout, "", "Codex's classic install already loads the doctrine");
  // Codex reads AGENTS.override.md instead of AGENTS.md when it has any text
  const override = path.join(box.codex, "AGENTS.override.md");
  const cases = [[" \n", "", "a blank override leaves AGENTS.md in charge"],
    ["mine\n", text, "an override hides the AGENTS.md block from Codex"],
    [`<!-- luciazero:start -->\n${text}<!-- luciazero:end -->\n`, "", "the override carries the doctrine"]];
  for (const [content, want, why] of cases) {
    fs.writeFileSync(override, content);
    const r = codexRun(doctrine, box.env, box.root, box.cwd, start);
    assert.strictEqual(r.status, 0, r.stderr);
    assert.strictEqual(r.stdout, want, why);
  }
});

// Codex never applies a repository's .claude/settings.json, so the refusal
// that guards Claude Code against it would only let the repository switch
// the user's own settings off.
test("under Codex a repository's Claude settings change nothing", (t) => {
  const box = codexBox(t);
  const hooks = codexHooks(box.root);
  const event = (extra) => ({ session_id: "s1", cwd: box.cwd, turn_id: "t1", ...extra });
  fs.mkdirSync(path.join(box.cwd, ".git"));
  fs.mkdirSync(path.join(box.cwd, ".claude"));
  fs.writeFileSync(path.join(box.cwd, ".claude", "settings.json"),
    JSON.stringify({ env: { LUCIAZERO_STRICT_VERIFY_CMD: "exit 0", LUCIAZERO_DOC_REGEX: "." } }));
  fs.writeFileSync(path.join(box.cwd, "verify.js"), "process.exit(1);\n");
  const strict = { ...box.env, LUCIAZERO_STRICT_VERIFY_CMD: `"${process.execPath}" verify.js`, LUCIAZERO_STRICT_TIMEOUT: "60" };
  const session = codexRun(find(hooks, "SessionStart", "session")[2], strict, box.root, box.cwd,
    event({ hook_event_name: "SessionStart", source: "startup" }));
  assert.strictEqual(session.status, 0, session.stderr);
  assert.doesNotMatch(session.stdout, /settings\.json/, "Codex never applied that file");
  assert.strictEqual(codexRun(find(hooks, "PostToolUse", "edit")[2], strict, box.root, box.cwd,
    event({ hook_event_name: "PostToolUse", tool_name: "apply_patch", tool_use_id: "c1",
      tool_input: { command: "*** Begin Patch\n*** Add File: a.js\n+x\n*** End Patch\n" }, tool_response: "Success." })).status, 0);
  const stop = codexRun(find(hooks, "Stop", "stop")[2], strict, box.root, box.cwd,
    event({ hook_event_name: "Stop", stop_hook_active: false }));
  assert.strictEqual(stop.status, 2, stop.stderr);
  assert.match(stop.stderr, /Strict verify gate/, "the user's own strict gate must still run");
});

// Codex runs the command in the user's login shell, whichever it is.
test("under Codex every POSIX shell there is runs the hook from a plugin root a shell would split",
  { skip: WINDOWS && "POSIX shells only" }, (t) => {
    const box = codexBox(t);
    const doctrine = find(codexHooks(box.root), "SessionStart", "doctrine")[2];
    const text = fs.readFileSync(path.join(ROOT, "claude", "luciazero.md"), "utf8");
    const dirs = (box.env.PATH || "").split(path.delimiter).filter(Boolean);
    const shells = new Set(["/bin/sh"]);
    for (const name of ["sh", "bash", "zsh", "dash", "ksh", "mksh", "fish"]) {
      const found = dirs.map((dir) => path.join(dir, name)).find((file) => fs.existsSync(file));
      if (found) shells.add(found);
    }
    for (const shell of shells) {
      const r = codexRun(doctrine, { ...box.env, SHELL: shell }, box.root, box.cwd,
        { session_id: "s1", cwd: box.cwd, hook_event_name: "SessionStart", source: "startup" });
      assert.strictEqual(r.status, 0, `${shell}: ${r.stderr}`);
      assert.strictEqual(r.stdout, text, `${shell} did not run the hook`);
    }
    t.diagnostic(`shells: ${[...shells].join(" ")}`);
  });

// cmd.exe looks for a program in the working directory before PATH, and
// Codex runs hooks in the session's working directory: a repository's
// node.cmd must not run in Luciazero's place.
test("under Codex on Windows a node.cmd in the repository never runs", { skip: !WINDOWS && "cmd.exe only" }, (t) => {
  const box = codexBox(t);
  const env = { ...box.env };
  for (const key of Object.keys(env)) {
    if (key.toUpperCase() === "NODEFAULTCURRENTDIRECTORYINEXEPATH") delete env[key];
  }
  const marker = path.join(box.box, "planted-ran");
  for (const name of ["node.cmd", "node.bat"]) {
    fs.writeFileSync(path.join(box.cwd, name), `@echo planted> "${marker}"\r\n@exit /b 7\r\n`);
  }
  const prompt = find(codexHooks(box.root), "UserPromptSubmit", "prompt")[2];
  const event = { session_id: "s1", cwd: box.cwd, hook_event_name: "UserPromptSubmit", prompt: "x" };
  const r = codexRun(prompt, env, box.root, box.cwd, event);
  assert.strictEqual(fs.existsSync(marker), false, "the repository's node.cmd ran");
  assert.strictEqual(r.status, 0, r.stderr);
  // the same command without what precedes `node` runs the planted file:
  // that guard is what stops it, and this test can tell
  const at = prompt.commandWindows.indexOf("& node ");
  assert.ok(at > 0, prompt.commandWindows);
  const bare = codexRun({ ...prompt, commandWindows: prompt.commandWindows.slice(at + 2) }, env, box.root, box.cwd, event);
  assert.strictEqual(fs.existsSync(marker), true, `without the guard cmd.exe ran Node from PATH (status ${bare.status})`);
});

// The guard above must stay in the hook's own cmd.exe: the strict gate runs
// the user's command in a cmd.exe of its own, which, like Codex's, looks in
// the project for a program the command names.
test("under Codex on Windows the strict gate still runs the repository's own program", { skip: !WINDOWS && "cmd.exe only" }, (t) => {
  const box = codexBox(t);
  const env = { ...box.env, LUCIAZERO_STRICT_VERIFY_CMD: "lz-green", LUCIAZERO_STRICT_TIMEOUT: "60" };
  for (const key of Object.keys(env)) {
    if (key.toUpperCase() === "NODEFAULTCURRENTDIRECTORYINEXEPATH") delete env[key];
  }
  fs.writeFileSync(path.join(box.cwd, "lz-green.cmd"), "@exit /b 0\r\n");
  const hooks = codexHooks(box.root);
  const event = (extra) => ({ session_id: "s1", cwd: box.cwd, turn_id: "t1", ...extra });
  assert.strictEqual(codexRun(find(hooks, "PostToolUse", "edit")[2], env, box.root, box.cwd,
    event({ hook_event_name: "PostToolUse", tool_name: "apply_patch", tool_use_id: "c1",
      tool_input: { command: "*** Begin Patch\n*** Add File: a.js\n+x\n*** End Patch\n" }, tool_response: "Success." })).status, 0);
  const stop = codexRun(find(hooks, "Stop", "stop")[2], env, box.root, box.cwd, event({ hook_event_name: "Stop", stop_hook_active: false }));
  assert.doesNotMatch(stop.stderr, /Strict verify gate/, "a passing lz-green.cmd was reported red");
  assert.strictEqual(stop.status, 0, stop.stderr);
  assert.strictEqual(lastVerify(env, box.cwd), "ok\n");
});
