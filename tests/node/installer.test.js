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
  assert.deepStrictEqual(fs.readdirSync(box.claude).filter((n) => n.startsWith("settings.json.bak.")), [],
    "a second install with nothing to change backed up settings.json");
  ok(node(box.env, [INSTALLER, "claude-uninstall"]), "uninstall");
  assert.deepStrictEqual(fs.readFileSync(path.join(box.claude, "CLAUDE.md")), mine, "uninstall did not restore CLAUDE.md byte for byte");
  assert.ok(!fs.existsSync(path.join(box.claude, "luciazero.md")), "the doctrine was left behind");
  assert.ok(!fs.existsSync(path.join(box.claude, "hooks", "luciazero-verify.cjs")), "a hook was left behind");
  const left = JSON.parse(fs.readFileSync(path.join(box.claude, "settings.json"), "utf8"));
  assert.ok(!JSON.stringify(left).includes("luciazero-"), "settings.json still names a hook of ours");
});

test("claude: status finds the agentd package at a path that is not ASCII", (t) => {
  const box = sandbox(t);
  ok(node(box.env, [INSTALLER, "claude"]), "install");
  const before = node(box.env, [INSTALLER, "claude", "--status"]);
  ok(before, "status");
  if (!/agentd package recorded/.test(before.stdout)) return t.skip("no Agent Bus launcher was installed here");
  // the home file, as the installer writes it, for a checkout under a Thai name
  const home = path.join(box.box, "โค้ด ü", "agentd");
  fs.mkdirSync(path.join(home, "luciazero_agentd"), { recursive: true });
  fs.writeFileSync(path.join(box.claude, ".luciazero-agentd-home"), home + "\n");
  const status = node(box.env, [INSTALLER, "claude", "--status"]);
  ok(status, "status");
  assert.ok(status.stdout.includes(`agentd package recorded at ${home}`), status.stdout);
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

test("rmTree removes a link to a directory, never what it points at", (t) => {
  const { rmTree } = require(INSTALLER);
  // a junction on Windows (no privilege needed), then a directory symlink
  // where this account may make one; a symlink everywhere else
  const kinds = WINDOWS ? ["junction", "dir"] : ["dir"];
  for (const kind of kinds) {
    const box = sandbox(t);
    const outside = path.join(box.box, "outside");
    fs.mkdirSync(outside);
    fs.writeFileSync(path.join(outside, "sentinel"), "keep me");
    const tree = path.join(box.box, "tree");
    fs.mkdirSync(path.join(tree, "inner"), { recursive: true });
    fs.writeFileSync(path.join(tree, "inner", "file"), "ours");
    try {
      fs.symlinkSync(outside, path.join(tree, "inner", "link"), kind);
    } catch (error) {
      if (WINDOWS && error.code === "EPERM") { t.diagnostic(`${kind} case skipped: this account may not create one`); continue; }
      throw error;
    }
    rmTree(tree);
    assert.ok(!fs.existsSync(tree), `the tree holding a ${kind} was not removed`);
    assert.deepStrictEqual(fs.readdirSync(outside), ["sentinel"], `removing a ${kind} reached into its target`);
    assert.strictEqual(fs.readFileSync(path.join(outside, "sentinel"), "utf8"), "keep me");
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

// Run a .cmd the way a user's shell does. Node will not start a batch file
// without a shell; /s takes the outer quotes off what follows /c, so the
// file's path stays quoted.
function runCmd(file, args, options) {
  const r = spawnSync(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", `""${file}" ${args}"`],
    { encoding: "utf8", windowsHide: true, windowsVerbatimArguments: true, ...options });
  if (r.error) throw r.error;
  return { status: r.status, stdout: r.stdout, stderr: r.stderr };
}

test("on Windows, luciazero-agentd.cmd and lucia.cmd run the Agent Bus from anywhere", { skip: !WINDOWS && "Windows only; tests/gates/install.sh covers the POSIX launcher" }, (t) => {
  const box = sandbox(t);
  // Where a batch file breaks: a space, parentheses that end a block, an
  // ampersand that ends a command, and a name outside the console code page.
  const bin = path.join(box.box, "bin (x86) & ลูเซีย");
  const env = { ...box.env, LUCIAZERO_BIN_DIR: bin };
  ok(node(env, [INSTALLER, "claude"]), "install");
  for (const name of ["luciazero-agentd.cmd", "lucia.cmd"]) {
    assert.match(fs.readFileSync(path.join(bin, name), "latin1"), /luciazero-managed: agentd-launcher/, `${name} not installed`);
  }
  assert.strictEqual(fs.readFileSync(path.join(box.claude, ".luciazero-agentd-home"), "utf8"), path.join(ROOT, "agentd") + "\n");

  const state = path.join(box.box, "bus state ü");
  fs.mkdirSync(state);
  fs.writeFileSync(path.join(state, "bus.sqlite3"), ""); // an empty file is an empty database
  // Started from a directory holding a package of the same name, below one
  // laid out like a checkout: the launcher must import neither. A quoted name
  // found on PATH is where cmd.exe reports the working directory as the
  // batch file's own, which would make ..\agentd look like the checkout.
  const elsewhere = path.join(box.box, "decoy", "work");
  for (const decoy of [path.join(elsewhere, "luciazero_agentd"), path.join(box.box, "decoy", "agentd", "luciazero_agentd")]) {
    fs.mkdirSync(decoy, { recursive: true });
    fs.writeFileSync(path.join(decoy, "__init__.py"), "");
    fs.writeFileSync(path.join(decoy, "__main__.py"), 'print("HIJACKED")\n');
  }
  const pathKey = Object.keys(env).find((key) => key.toUpperCase() === "PATH") || "PATH";
  const onPath = { ...env, [pathKey]: `${bin};${env[pathKey] || ""}` };
  const run = (name, args) => runCmd(name.endsWith(".cmd") ? path.join(bin, name) : name, args, { cwd: elsewhere, env: onPath });

  const added = run("luciazero-agentd.cmd", `roster add lb-architect codex architect --state-dir "${state}"`);
  ok(added, "roster add");
  // The short name says its own name back, as the POSIX launcher does.
  const usage = run("lucia.cmd", "claude --help");
  ok(usage, "lucia claude --help");
  assert.match(usage.stdout, /^usage: lucia claude/m, "lucia printed another name back at the user");
  const next = run("lucia.cmd", `next --state-dir "${state}"`);
  ok(next, "next");
  assert.match(next.stdout, /^ {4}luciazero-agentd /m, "next did not render the launcher found on PATH");
  const byName = run("lucia", "claude --help");
  ok(byName, '"lucia" claude --help');
  assert.match(byName.stdout, /^usage: lucia claude/m);
  for (const r of [added, usage, next, byName]) assert.doesNotMatch(r.stdout + r.stderr, /HIJACKED/);

  ok(node(env, [INSTALLER, "claude-uninstall"]), "uninstall");
  for (const name of ["luciazero-agentd.cmd", "lucia.cmd"]) {
    assert.ok(!fs.existsSync(path.join(bin, name)), `${name} was left behind`);
  }
  assert.ok(!fs.existsSync(path.join(box.claude, ".luciazero-agentd-home")), "the package pointer was left behind");
});

test("on Windows, the launchers take Python from PATH's full-path entries, never the working directory", { skip: !WINDOWS && "Windows only; tests/gates/install.sh covers the POSIX launcher" }, (t) => {
  const box = sandbox(t);
  const bin = path.join(box.box, "bin");
  const env = { ...box.env, LUCIAZERO_BIN_DIR: bin };
  ok(node(env, [INSTALLER, "claude"]), "install");
  // A stand-in for Python that answers every question with 0, as a 3.10 or
  // newer would, and records that it ran. Nothing on a bare Windows does
  // both, so it is compiled here with the C# compiler of .NET Framework 4.
  const work = path.join(box.box, "work");
  fs.mkdirSync(work);
  const mark = path.join(box.box, "stand-in ran.txt");
  const csc = path.join(process.env.SystemRoot || "C:\\Windows", "Microsoft.NET", "Framework64", "v4.0.30319", "csc.exe");
  const source = path.join(box.box, "standin.cs");
  fs.writeFileSync(source, 'class StandIn { static int Main() { System.IO.File.AppendAllText(System.Environment.GetEnvironmentVariable("LZ_STANDIN_MARK"), System.Environment.CommandLine + "\\n"); return 0; } }\n');
  const built = spawnSync(csc, ["/nologo", `/out:${path.join(work, "python3.exe")}`, source], { encoding: "utf8", windowsHide: true });
  assert.strictEqual(built.status, 0, `csc: ${built.stdout}${built.stderr}${built.error || ""}`);
  for (const name of ["python.exe", "py.exe"]) fs.copyFileSync(path.join(work, "python3.exe"), path.join(work, name));
  const pathKey = Object.keys(env).find((key) => key.toUpperCase() === "PATH") || "PATH";
  const trusted = env[pathKey] || "";
  const withEntries = (value) => ({ ...env, [pathKey]: value, LZ_STANDIN_MARK: mark });
  const ran = () => (fs.existsSync(mark) ? fs.readFileSync(mark, "utf8") : "");

  // The hazard is real: the for command's own PATH search, which the
  // launcher used to rely on, reads "." as the working directory.
  const before = path.join(box.box, "for-path-search.cmd");
  fs.writeFileSync(before, '@for %%P in (python3.exe) do @if not "%%~$PATH:P"=="" "%%~$PATH:P" -c "import sys"\r\n');
  runCmd(before, "", { cwd: work, env: withEntries(`.;${trusted}`) });
  assert.match(ran(), /python3\.exe/i, "the PATH modifier did not run the stand-in, so this case proves nothing");
  fs.rmSync(mark);

  const quoted = trusted.split(";").filter(Boolean).map((dir) => `"${dir.replace(/"/g, "")}"`).join(";");
  for (const [label, value] of [["a dot first", `.;${trusted}`], ["an empty entry first", `;${trusted}`],
    ["relative entries first", `work;..\\work;${trusted}`], ["no relative entry", trusted], ["every entry quoted", quoted]]) {
    const r = runCmd(path.join(bin, "lucia.cmd"), "claude --help", { cwd: work, env: withEntries(value) });
    assert.strictEqual(r.status, 0, `${label}: ${r.stdout}${r.stderr}`);
    assert.match(r.stdout, /^usage: lucia claude/m, label);
    assert.strictEqual(ran(), "", `${label}: the launcher ran a Python from the working directory`);
  }
  // Only relative entries left: nothing to run, and nothing run.
  const none = runCmd(path.join(bin, "lucia.cmd"), "claude --help", { cwd: work, env: withEntries(".;work;..\\work") });
  assert.strictEqual(none.status, 127, none.stdout + none.stderr);
  assert.match(none.stderr, /needs Python 3\.10 or newer/);
  assert.strictEqual(ran(), "", "the launcher ran a Python from the working directory");
});

test("on Windows, uninstall removes the Agent Bus task through the installed launcher", {
  skip: (!WINDOWS && "Windows only") ||
    (process.env.LUCIAZERO_TEST_TASK_SCHEDULER !== "1" &&
      "ends and deletes \\Luciazero\\agentd in the real Task Scheduler; set LUCIAZERO_TEST_TASK_SCHEDULER=1 on a throwaway machine"),
}, (t) => {
  const box = sandbox(t);
  const bin = path.join(box.box, "bin");
  const env = { ...box.env, LUCIAZERO_BIN_DIR: bin };
  ok(node(env, [INSTALLER, "claude"]), "install");
  // The definition `service install` leaves, as far as uninstall reads it:
  // UTF-16 with a byte order mark, as Task Scheduler takes it, and the marker.
  const task = path.join(box.services, "AppData", "Local", "Luciazero", "agentd-task.xml");
  fs.mkdirSync(path.dirname(task), { recursive: true });
  fs.writeFileSync(task, Buffer.concat([Buffer.from([0xff, 0xfe]),
    Buffer.from('<?xml version="1.0" encoding="UTF-16"?>\r\n<!-- luciazero-managed: agentd-service -->\r\n<Task/>\r\n', "utf16le")]));
  const removed = node(env, [INSTALLER, "claude-uninstall"]);
  ok(removed, "uninstall");
  assert.match(removed.stdout, /agent bus service stopped and removed/, removed.stdout + removed.stderr);
  assert.ok(!fs.existsSync(task), "the task definition was left behind");
  assert.ok(!fs.existsSync(path.join(bin, "lucia.cmd")), "the launcher was left behind");
});

const WINEXEC = path.join(ROOT, "bin", "lib", "winexec.js");

function withPath(env, value) {
  const key = Object.keys(env).find((name) => name.toUpperCase() === "PATH") || "PATH";
  return { ...env, [key]: value };
}

test("a command is found through absolute PATH entries alone, never the working directory", (t) => {
  const { onPathOnly } = require(WINEXEC);
  const box = sandbox(t);
  // CreateProcess, libuv and cmd.exe all look here first on Windows.
  const here = path.join(box.box, "here");
  const real = path.join(box.box, "real bin");
  for (const dir of [here, real]) {
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, "python3.exe"), "");
  }
  fs.writeFileSync(path.join(real, "claude.cmd"), "");
  const d = path.delimiter;
  const cwd = process.cwd();
  process.chdir(here);
  try {
    // An empty or relative entry is the working directory again.
    assert.strictEqual(onPathOnly("python3.exe", { env: withPath({}, `${d}.${d}..${path.sep}here${d}${real}`) }),
      path.join(real, "python3.exe"));
    assert.strictEqual(onPathOnly("python3.exe", { env: withPath({}, `.${d}${d}..${path.sep}here`) }), null);
    assert.strictEqual(onPathOnly("python3.exe", { env: {} }), null);
    // Quotes around an entry are not part of the directory; a quoted relative
    // entry is still relative.
    assert.strictEqual(onPathOnly("python3.exe", { env: withPath({}, `"."${d}"${real}"`) }),
      path.join(real, "python3.exe"));
    assert.strictEqual(onPathOnly("python3.exe", { env: withPath({}, `""${d}"..${path.sep}here"`) }), null);
    // Each directory's extensions before the next directory, as cmd.exe.
    assert.strictEqual(onPathOnly("claude", { env: withPath({}, `${here}${d}${real}`), exts: [".exe", ".cmd"] }),
      path.join(real, "claude.cmd"));
  } finally {
    process.chdir(cwd);
  }
});

test("on Windows, a command by name runs from PATH, not from the working directory", { skip: !WINDOWS && "Windows only" }, (t) => {
  const { runCommand } = require(WINEXEC);
  const box = sandbox(t);
  const here = path.join(box.box, "here");
  const bin = path.join(box.box, "path bin (x86)");
  for (const dir of [here, bin]) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(here, "lz-probe.cmd"), "@echo HIJACKED\r\n");
  fs.writeFileSync(path.join(bin, "lz-probe.cmd"), "@echo from PATH %1\r\n");
  const r = runCommand("lz-probe", ["--version"], { cwd: here, env: withPath(box.env, bin), encoding: "utf8", windowsHide: true });
  assert.strictEqual(r.status, 0, `${r.stdout}\n${r.stderr}\n${r.error}`);
  assert.match(r.stdout, /^from PATH --version/m);
  assert.doesNotMatch(r.stdout, /HIJACKED/);
  // An entry in quotes, as Windows allows, around a directory with a space
  // and parentheses: the program still starts, a .cmd and an .exe alike.
  const quoted = path.join(box.box, "quoted bin (x86)");
  fs.mkdirSync(quoted);
  fs.writeFileSync(path.join(quoted, "lz-quoted.cmd"), "@echo quoted %1\r\n");
  fs.copyFileSync(process.execPath, path.join(quoted, "lz-quoted-node.exe"));
  const pathKey = Object.keys(box.env).find((key) => key.toUpperCase() === "PATH") || "PATH";
  const quotedEnv = withPath(box.env, `"${quoted}";${box.env[pathKey] || ""}`);
  const batch = runCommand("lz-quoted", ["--version"], { cwd: here, env: quotedEnv, encoding: "utf8", windowsHide: true });
  assert.strictEqual(batch.status, 0, `${batch.stdout}\n${batch.stderr}\n${batch.error}`);
  assert.match(batch.stdout, /^quoted --version/m);
  const exe = runCommand("lz-quoted-node", ["-e", "console.log('quoted exe')"], { cwd: here, env: quotedEnv, encoding: "utf8", windowsHide: true });
  assert.strictEqual(exe.status, 0, `${exe.stdout}\n${exe.stderr}\n${exe.error}`);
  assert.match(exe.stdout, /^quoted exe/m);
  const missing = runCommand("lz-nowhere", ["--version"], { cwd: here, env: withPath(box.env, bin) });
  assert.strictEqual(missing.status, null);
  assert.strictEqual(missing.error.code, "ENOENT");
});
