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

// The default detection counts what a simple command runs, not a word it
// reads. Each read below once counted as a verify, and after an edit it
// silenced the stop nudge (docs/experiments.md, 2026-11-03). Every run below
// must still count, Windows paths and PowerShell's call operator included.
test("default verify detection counts what a command runs, not what it reads", () => {
  const { defaultVerify } = require(VERIFY);
  const reads = [
    "cat test.sh", "grep -n pytest README.md", "sed -n 1,40p build/verify.py", "wc -l verify.py",
    "git grep -n verify", "/usr/bin/grep -n \"a\\|pytest\" x.py | head", "python3 -c \"print('verify')\"",
    "cat > notes.txt <<'EOF'\nrun pytest later\nEOF", "python3 - <<'EOF'\nopen('verify.log', 'w')\nEOF",
    "echo \"verify deeply\" >> notes.md", "for f in verify.py; do wc -l \"$f\"; done", "bash -n test.sh",
    "gpg --verify x.sig", "python -m py_compile build/verify-join.py", "npm install verify-thing",
    "/x/.venv/bin/python -I -c \"from PIL import Image\nImage.new('RGB', (1, 1)).save('/s/verify/a.png')\"",
    "echo hi # then pytest", "scripts/test-timings.sh --report | head -20", "command -v pytest",
    "cat <<\\EOF\npytest\nEOF", "cmd /c dir verify",
    // a commit body is data, even with an unpaired quote in it
    "git commit -m \"$(cat <<'EOF'\nfix 5\" screen\n./test.sh passes\nEOF\n)\"",
    "cat <<EOF\n\tEOF\n./test.sh\nEOF", "$GREP -n pytest README.md", "$EDITOR verify.py",
    "python -Bc \"import verify\"", "go build ./cmd/verify", "cargo add verify-crate",
    "make -C verify-tools build", "./gradlew build -x test",
  ];
  const runs = [
    "./test.sh", "npm test", "pytest", "cd sub && .venv/bin/python -m pytest -q 2>&1 | tail -5",
    "HF_HUB_OFFLINE=1 timeout 600 python -m pytest tests", "npm run -s verify:plan",
    "caffeinate -i node build/verify-seek.mjs", "uv run pytest -q", "npx vitest run", "make -C sub check",
    "bash -lc './test.sh --fast'", "grep -n x a.py; ./test.sh --fast",
    "python3 - <<'EOF'\nprint(1)\nEOF\n./test.sh --fast", "$PY -m pytest -q", "docker compose run --rm app pytest",
    "bash <<'EOF'\n./test.sh\nEOF", "{ pytest -q; } 2>&1", "& \"C:\\Py\\python.exe\" -m pytest",
    "C:\\Py\\Scripts\\pytest.exe -q", "$env:CI=\"1\"; npm test", "pwsh -NoProfile -Command \"npm test\"",
    "cargo test --release", "go test ./...", "./gradlew test", "poetry run pytest", "pnpm exec vitest",
    "yarn jest", "bun run verify", "tox -e py311", "env -i PATH=/bin ./test.sh", "x=$((1<<2))\n./test.sh",
    "bash -euo pipefail -c './test.sh'", "cmd /c npm test", "uv tool run pytest",
    "R=\"$(./test.sh --fast 2>&1)\"; echo \"$R\" | tail", "out=`pytest -q`", "wc -l <<< hello\n./test.sh --fast",
    "npm --prefix video run verify", "pnpm -C video run verify", "yarn --cwd sub test", "source scripts/verify.sh",
    ". ./test.sh", "nix develop -c pytest", "sudo -u ci ./test.sh", "timeout --signal KILL 60 ./test.sh",
    "cat <<'EOF' | bash\n./test.sh\nEOF", "cargo +nightly test",
  ];
  for (const command of reads) assert.strictEqual(defaultVerify(command), false, `read as a verify run: ${command}`);
  for (const command of runs) assert.strictEqual(defaultVerify(command), true, `not read as a verify run: ${command}`);
});

// Test runners, type checkers, linters and a project's own check scripts are
// verify runs too: in ten days of local transcripts 20 of 93 stop nudges came
// after one of them (docs/experiments.md, 2026-11-03). A program asked only
// for --version or --help, a syntax check, a formatter and a script whose name
// merely starts with "check" run none.
test("default verify detection counts checks, type checkers and linters", () => {
  const { defaultVerify } = require(VERIFY);
  const checks = [
    "node --test --test-timeout=8000 tests/a.test.cjs > /tmp/out.log 2>&1", "node -r ts-node/register --test x.ts",
    "npx tsc --noEmit -p . 2>&1 | head", "npx vue-tsc --noEmit", "npx playwright test e2e/03.spec.ts",
    "npx eslint src/a.ts", "uv run ruff check .", "shellcheck install.sh", "python -m mypy src", "pyright",
    "cargo clippy -- -D warnings", "go vet ./...", "bun test", "deno test -A", "npm run check",
    "npm run check:1 > logs/check.log 2>&1", "pnpm lint", "yarn typecheck", "bun run lint", "npm run -s lint:fix",
    "python3 ~/.claude/skills/x/scripts/check-skill.py 2>&1", "node build/check.mjs 2", "python build/stt-check.py",
    "node tools/check-package.mjs ui --code", "./scripts/check-site.py", "bash scripts/check.sh",
    "python3 tools/check_script.py", "python validate_schema.py x.json", "pytest -v",
  ];
  const others = [
    "shellcheck --version", "npx tsc --version", "eslint --help", "./test.sh --help", "pytest --version",
    "python -m pytest --help", "python3 scripts/check-run.py -h", "node --check build/check.mjs", "node -c verify.mjs",
    "git checkout -b check", "python checkout.py", "python precheck.py", "npm ci", "npm install eslint",
    "npm run checkout-flow", "ruff format .", "playwright install chromium", "node script.js --test",
    "node tsconfig-gen.js", "cat check.py", "grep -n tsc README.md", "shellcheck -V", "npx tsc -v", "eslint -v",
    "mypy -V", "npx tsc --init", "npx eslint --init", "bash test.sh --help", "sh ./verify.sh -h",
  ];
  for (const command of checks) assert.strictEqual(defaultVerify(command), true, `not read as a verify run: ${command}`);
  for (const command of others) assert.strictEqual(defaultVerify(command), false, `read as a verify run: ${command}`);
});

// An agent's scratch file in a temporary directory is not the project's code:
// editing one does not re-arm the stop nudge (docs/experiments.md,
// 2026-11-03). A project that itself lives in a temporary directory still
// counts, through its cwd or through CLAUDE_PROJECT_DIR.
test("an edit in a temporary directory outside the project does not re-arm the nudge", (t) => {
  const box = sandbox(t);
  const stopAfter = (cwd, file, env = box.env) => {
    const event = (extra = {}) => JSON.stringify({ cwd, session_id: "s1", ...extra });
    assert.strictEqual(node(env, [VERIFY, "prompt"], event({ prompt: "go" })).status, 0);
    const edit = node(env, [VERIFY, "edit"], event({ tool_name: "Write", tool_input: { file_path: file } }));
    assert.strictEqual(edit.status, 0, edit.stderr);
    return node(env, [VERIFY, "stop"], event()).status;
  };
  const project = path.join(box.box, "project");
  const scratch = path.join(box.tmp, "claude-1", "session", "scratchpad", "probe.py");
  fs.mkdirSync(path.dirname(scratch), { recursive: true });
  fs.writeFileSync(scratch, "");
  assert.strictEqual(stopAfter(project, scratch), 0, "a scratchpad edit nudged");
  assert.strictEqual(stopAfter(project, path.join(project, "a.py")), 2, "a project edit after it did not nudge");

  const inTmp = path.join(box.tmp, "repo");
  assert.strictEqual(stopAfter(inTmp, path.join(inTmp, "a.py")), 2, "an edit in a project under the temporary directory did not nudge");
  const env = { ...box.env, CLAUDE_PROJECT_DIR: path.join(box.tmp, "repo2") };
  assert.strictEqual(stopAfter(path.join(box.tmp, "repo2", "sub"), path.join(box.tmp, "repo2", "lib", "a.py"), env), 2,
    "an edit in CLAUDE_PROJECT_DIR outside the cwd did not nudge");
  // the session moved into its scratchpad, outside the project
  const env3 = { ...box.env, CLAUDE_PROJECT_DIR: path.join(box.tmp, "repo3") };
  assert.strictEqual(stopAfter(path.dirname(scratch), path.join(box.tmp, "repo3", "a.py"), env3), 2,
    "an edit in CLAUDE_PROJECT_DIR from a cwd outside it did not nudge");
  // a git worktree or clone under the temporary directory holds code
  const worktree = path.join(box.tmp, "wt");
  fs.mkdirSync(path.join(worktree, "src"), { recursive: true });
  fs.writeFileSync(path.join(worktree, ".git"), "gitdir: /elsewhere/.git/worktrees/wt\n");
  fs.writeFileSync(path.join(worktree, "src", "a.py"), "");
  assert.strictEqual(stopAfter(path.join(box.box, "main"), path.join(worktree, "src", "a.py")), 2,
    "an edit in a git worktree under the temporary directory did not nudge");
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

// The same holds for the strict gate's own run: here its command records an
// edit halfway through, as another session sharing the project's state would.
test("an edit made while the strict gate runs is still unverified", (t) => {
  const box = sandbox(t);
  const cwd = path.join(box.box, "strict-during");
  fs.mkdirSync(cwd, { recursive: true });
  const event = (extra = {}) => JSON.stringify({ cwd, session_id: "s1", ...extra });
  const editEvent = event({ tool_name: "Edit", tool_input: { file_path: path.join(cwd, "a.js") } });
  fs.writeFileSync(path.join(cwd, "edit.json"), editEvent);
  fs.writeFileSync(path.join(cwd, "mid.js"), `const { spawnSync } = require("child_process");
const input = require("fs").readFileSync(${JSON.stringify(path.join(cwd, "edit.json"))}, "utf8");
const r = spawnSync(process.execPath, [${JSON.stringify(VERIFY)}, "edit"], { input });
process.exit(r.status === 0 ? 0 : 3);
`);
  assert.strictEqual(node(box.env, [VERIFY, "edit"], editEvent).status, 0);
  const strict = { ...box.env, LUCIAZERO_STRICT_VERIFY_CMD: `"${process.execPath}" mid.js`, LUCIAZERO_STRICT_TIMEOUT: "60" };
  const first = node(strict, [VERIFY, "stop"], event());
  assert.strictEqual(first.status, 0, first.stderr);
  assert.strictEqual(lastVerify(box.env, cwd), "ok\n");
  assert.strictEqual(node(box.env, [VERIFY, "stop"], event()).status, 2, "the edit made during the strict run was taken as verified");
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

const pause = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
const HAS_GIT = spawnSync("git", ["--version"], { encoding: "utf8", windowsHide: true }).status === 0;

// A git repository holding `files`, committed; returns a runner for more git.
function gitRepo(dir, files) {
  fs.mkdirSync(dir, { recursive: true });
  const git = (...args) => {
    const r = spawnSync("git", ["-C", dir, "-c", "user.name=lz", "-c", "user.email=lz@example.invalid",
      "-c", "commit.gpgsign=false", ...args], { encoding: "utf8", windowsHide: true });
    assert.strictEqual(r.status, 0, r.stderr);
    return r.stdout;
  };
  git("init", "-q");
  for (const [rel, text] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(dir, rel)), { recursive: true });
    fs.writeFileSync(path.join(dir, rel), text);
  }
  git("add", "-A");
  git("commit", "-qm", "init");
  return git;
}

// Doctrine rule 3: a failing check means not done. A stop whose last verify
// of the session's own edits came back red -- a command that was not found
// included -- is nudged once, like an unverified one; a green clears it, and
// a red in another session does not reach edits a green already covered.
test("a red verify after an edit nudges once at stop, and a green clears it", (t) => {
  const box = sandbox(t);
  const cwd = path.join(box.box, "red");
  const hook = (session, mode, extra = {}) => node(box.env, [VERIFY, mode], JSON.stringify({ cwd, session_id: session, ...extra }));
  const edit = (session) => assert.strictEqual(hook(session, "edit",
    { tool_name: "Edit", tool_input: { file_path: path.join(cwd, "a.js") } }).status, 0);
  const verify = (session, id, error) => {
    const call = { tool_name: "Bash", tool_use_id: id, tool_input: { command: "npm test" } };
    assert.strictEqual(hook(session, "bash-start", call).status, 0);
    const done = hook(session, error ? "bash-failure" : "bash", error ? { ...call, error } : call);
    assert.strictEqual(done.status, 0, done.stderr);
  };
  edit("s1");
  verify("s1", "v1", "Exit code 1");
  const red = hook("s1", "stop");
  assert.strictEqual(red.status, 2, "a stop on a red verify of the session's own edit did not nudge");
  assert.match(red.stderr, /failed/);
  assert.strictEqual(hook("s1", "stop", { stop_hook_active: true }).status, 0, "the stop the nudge caused must end the turn");
  assert.strictEqual(hook("s1", "stop").status, 0, "the red nudge is not one-shot");
  verify("s1", "v2", "Exit code 1");
  assert.strictEqual(hook("s1", "stop").status, 0, "a second red run of the same edit nudged again");

  edit("s1");
  verify("s1", "v3", "Exit code 127\nsh: npm: command not found");
  assert.strictEqual(hook("s1", "stop").status, 2, "a verify command that was not found counted as a check");
  verify("s1", "v4", null);
  assert.strictEqual(hook("s1", "stop").status, 0, "a green run after the red did not clear it");

  edit("s2");
  verify("s2", "v5", null);
  verify("s3", "v6", "Exit code 1");
  assert.strictEqual(hook("s2", "stop").status, 0, "another session's red reached edits a green had covered");
  assert.strictEqual(hook("s3", "stop").status, 0, "a session that edited nothing was nudged for its red run");
});

// An edit need not go through Edit or Write: `sed -i`, a heredoc, a formatter
// or a commit hook changes files through the shell. At stop the hook asks git
// which files changed while this session's shell commands ran after its last
// verify, documentation and ignored files aside.
test("a file a shell command changes after the last verify nudges at stop", { skip: !HAS_GIT && "needs git" }, (t) => {
  const box = sandbox(t);
  const session = (cwd, id = "s1") => {
    const hook = (mode, extra = {}) => node(box.env, [VERIFY, mode], JSON.stringify({ cwd, session_id: id, ...extra }));
    // a shell command: its start, what it does to the tree, its end
    const shell = (toolId, command, act, error = null) => {
      const call = { tool_name: "Bash", tool_use_id: toolId, tool_input: { command } };
      assert.strictEqual(hook("bash-start", call).status, 0);
      pause(20);
      if (act) act();
      pause(20);
      const done = hook(error ? "bash-failure" : "bash", error ? { ...call, error } : call);
      assert.strictEqual(done.status, 0, done.stderr);
    };
    return { hook, shell, stop: () => hook("stop").status };
  };
  const files = { "a.js": "a\n", "README.md": "# r\n", ".gitignore": "build/\n" };

  const p1 = path.join(box.box, "p1");
  gitRepo(p1, files);
  const s1 = session(p1);
  s1.shell("v1", "npm test");
  s1.shell("e1", "sed -i s/a/b/ a.js", () => fs.writeFileSync(path.join(p1, "a.js"), "b\n"));
  assert.strictEqual(s1.stop(), 2, "a file sed changed after the last verify was taken as verified");
  assert.strictEqual(s1.hook("stop", { stop_hook_active: true }).status, 0);
  s1.shell("v2", "npm test");
  assert.strictEqual(s1.stop(), 0, "a green run after the shell edit did not cover it");
  s1.shell("e2", "sed -i s/b/c/ a.js", () => fs.writeFileSync(path.join(p1, "a.js"), "c\n"), "Exit code 1");
  assert.strictEqual(s1.stop(), 2, "a shell command that failed after changing a file was not counted");

  const p2 = path.join(box.box, "p2");
  gitRepo(p2, files);
  const s2 = session(p2);
  s2.shell("v1", "npm test", () => {
    // what a verify run itself writes is no edit after it
    fs.writeFileSync(path.join(p2, "coverage.txt"), "92%\n");
  });
  s2.shell("e1", "notes", () => {
    fs.writeFileSync(path.join(p2, "README.md"), "# r\nmore\n");
    fs.mkdirSync(path.join(p2, "build"));
    fs.writeFileSync(path.join(p2, "build", "out.js"), "x\n");
  });
  s2.shell("e2", "ls");
  assert.strictEqual(s2.stop(), 0, "documentation, an ignored file or a verify's own output re-armed the nudge");

  const p3 = path.join(box.box, "p3");
  const git3 = gitRepo(p3, files);
  const s3 = session(p3);
  s3.shell("v1", "npm test");
  s3.shell("e1", "sed -i s/a/b/ a.js && git commit -am wip", () => {
    fs.writeFileSync(path.join(p3, "a.js"), "b\n");
    git3("commit", "-qam", "wip");
  });
  assert.strictEqual(s3.stop(), 2, "a shell edit committed before the stop was taken as verified");

  // the session that ran the command is the one nudged
  const p4 = path.join(box.box, "p4");
  gitRepo(p4, files);
  const a = session(p4, "a");
  const b = session(p4, "b");
  a.shell("v1", "npm test");
  b.shell("e1", "sed -i s/a/b/ a.js", () => fs.writeFileSync(path.join(p4, "a.js"), "b\n"));
  assert.strictEqual(a.stop(), 0, "a session that ran no command since its verify was nudged for another's shell edit");
  assert.strictEqual(b.stop(), 2, "the session whose shell command changed the file was not nudged");

  // only what changed while the session's own commands ran: another session's
  // Edit between two of them is that session's edit
  const p6 = path.join(box.box, "p6");
  gitRepo(p6, files);
  const a6 = session(p6, "a");
  const b6 = session(p6, "b");
  a6.shell("v1", "npm test");
  a6.shell("e1", "ls");
  // further from either command than the slack a coarse file time gets
  pause(1100);
  fs.writeFileSync(path.join(p6, "a.js"), "b\n");
  assert.strictEqual(b6.hook("edit", { tool_name: "Edit", tool_input: { file_path: path.join(p6, "a.js") } }).status, 0);
  pause(1100);
  a6.shell("e2", "git status");
  assert.strictEqual(a6.stop(), 0, "an edit made between two of a session's commands was charged to it");
  assert.strictEqual(b6.stop(), 2, "the session that made the edit was not nudged");

  // a shell edit tested by a red run is red, as an Edit would be
  const p7 = path.join(box.box, "p7");
  gitRepo(p7, files);
  const s7 = session(p7);
  s7.shell("e1", "sed -i s/a/b/ a.js", () => fs.writeFileSync(path.join(p7, "a.js"), "b\n"));
  s7.shell("v1", "npm test", null, "Exit code 1");
  const red7 = s7.hook("stop");
  assert.strictEqual(red7.status, 2, "a shell edit whose verify failed stopped clean");
  assert.match(red7.stderr, /failed/);

  // documentation in a new folder, and documentation beside a file removed
  // before the last verify, are no code edits; a file removed after it is one
  const p8 = path.join(box.box, "p8");
  gitRepo(p8, { ...files, "old.js": "o\n", "src/gone.js": "g\n" });
  const s8 = session(p8);
  fs.rmSync(path.join(p8, "old.js"));
  s8.shell("v1", "npm test");
  s8.shell("e1", "mkdir notes && echo x > notes/plan.md && echo n > NOTES.md", () => {
    fs.mkdirSync(path.join(p8, "notes"));
    fs.writeFileSync(path.join(p8, "notes", "plan.md"), "x\n");
    fs.writeFileSync(path.join(p8, "NOTES.md"), "n\n");
  });
  assert.strictEqual(s8.stop(), 0, "documentation in a new folder or beside an old deletion counted as code");
  s8.shell("e2", "rm src/gone.js", () => fs.rmSync(path.join(p8, "src", "gone.js")));
  assert.strictEqual(s8.stop(), 2, "a code file removed by the shell after the last verify did not count");

  // what a green run writes is no edit, even right after a shell edit it tested
  const p9 = path.join(box.box, "p9");
  gitRepo(p9, files);
  const s9 = session(p9);
  s9.shell("e1", "sed -i s/a/b/ a.js", () => fs.writeFileSync(path.join(p9, "a.js"), "b\n"));
  s9.shell("v1", "npm test", () => fs.writeFileSync(path.join(p9, "report.js"), "x\n"));
  assert.strictEqual(s9.stop(), 0, "a file the green run wrote was taken for an edit after it");

  // one command that edits and then tests: red when it fails, covered when not
  const p11 = path.join(box.box, "p11");
  gitRepo(p11, files);
  const s11 = session(p11);
  s11.shell("v1", "sed -i s/a/b/ a.js && npm test", () => fs.writeFileSync(path.join(p11, "a.js"), "b\n"), "Exit code 1");
  const red11 = s11.hook("stop");
  assert.strictEqual(red11.status, 2, "an edit made inside a failing verify command stopped clean");
  assert.match(red11.stderr, /failed/);
  assert.strictEqual(s11.hook("stop", { stop_hook_active: true }).status, 0);
  s11.shell("v2", "sed -i s/b/c/ a.js && npm test", () => fs.writeFileSync(path.join(p11, "a.js"), "c\n"));
  assert.strictEqual(s11.stop(), 0, "an edit a green verify command made and tested was not covered");
  // ...and one that tests and then edits leaves that edit unverified
  s11.shell("v3", "npm test && sed -i s/c/d/ a.js", () => fs.writeFileSync(path.join(p11, "a.js"), "d\n"));
  assert.strictEqual(s11.stop(), 2, "an edit made after the test step of a green verify command was covered");

  // a failing run of a session that edited nothing stays its own: what the
  // run writes, and another session's edit while it runs, make no red
  const p12 = path.join(box.box, "p12");
  gitRepo(p12, files);
  const a12 = session(p12, "a");
  const b12 = session(p12, "b");
  a12.shell("v1", "npm test", () => {
    fs.writeFileSync(path.join(p12, "junit.xml"), "<x/>\n");
    fs.writeFileSync(path.join(p12, "a.js"), "b\n");
    assert.strictEqual(b12.hook("edit", { tool_name: "Edit", tool_input: { file_path: path.join(p12, "a.js") } }).status, 0);
  }, "Exit code 1");
  assert.strictEqual(a12.stop(), 0, "a session that edited nothing was made red by what changed during its failing run");
  a12.shell("v2", "cd . && npm test 2>&1 | tee test.log", () => {
    fs.writeFileSync(path.join(p12, "junit.xml"), "<y/>\n");
    fs.writeFileSync(path.join(p12, "test.log"), "1 failed\n");
  }, "Exit code 1");
  assert.strictEqual(a12.stop(), 0, "a cd before the test, or the test's own log, was taken for an edit");
  assert.strictEqual(b12.stop(), 2, "the session that made the edit was not nudged");

  // one session's look at a removal does not make it old for the session
  // that removed it
  const p10 = path.join(box.box, "p10");
  gitRepo(p10, { ...files, "src/x.js": "x\n" });
  const a10 = session(p10, "a");
  const b10 = session(p10, "b");
  a10.shell("v1", "npm test");
  b10.shell("e1", "rm src/x.js", () => fs.rmSync(path.join(p10, "src", "x.js")));
  pause(1100);
  a10.shell("e2", "ls");
  assert.strictEqual(a10.stop(), 0, "a session was nudged for a removal another session made");
  assert.strictEqual(b10.stop(), 2, "another session's look hid this session's removal");

  // outside a git work tree there is nothing to ask, and nothing breaks
  const p5 = path.join(box.box, "p5");
  fs.mkdirSync(p5);
  const s5 = session(p5);
  s5.shell("v1", "npm test");
  s5.shell("e1", "sed -i s/a/b/ a.js", () => fs.writeFileSync(path.join(p5, "a.js"), "b\n"));
  assert.strictEqual(s5.stop(), 0, "outside git the stop must behave as before");
});

// .claude/settings.local.json is the user's own file, gitignored by Claude
// Code. One a repository commits is project scope, and refused like
// .claude/settings.json.
test("a committed .claude/settings.local.json cannot configure the hook; the user's own can", { skip: !HAS_GIT && "needs git" }, (t) => {
  const box = sandbox(t);
  for (const committed of [true, false]) {
    const cwd = path.join(box.box, committed ? "committed" : "personal");
    const git = gitRepo(cwd, { "a.js": "a\n" });
    const local = path.join(cwd, ".claude", "settings.local.json");
    fs.mkdirSync(path.dirname(local), { recursive: true });
    fs.writeFileSync(local, JSON.stringify({ env: { LUCIAZERO_DOC_REGEX: ".*" } }));
    if (committed) {
      git("add", "-f", ".claude/settings.local.json");
      git("commit", "-qm", "ship local settings");
    }
    // Claude Code applies that env block; the hook decides whether to believe it
    const env = { ...box.env, LUCIAZERO_DOC_REGEX: ".*" };
    const event = (extra = {}) => JSON.stringify({ cwd, session_id: "s1", ...extra });
    const start = node(env, [VERIFY, "session"], event({ source: "startup" }));
    assert.strictEqual(start.status, 0, start.stderr);
    assert.strictEqual(node(env, [VERIFY, "edit"], event({ tool_name: "Edit", tool_input: { file_path: path.join(cwd, "a.js") } })).status, 0);
    const stop = node(env, [VERIFY, "stop"], event()).status;
    if (committed) {
      assert.match(start.stdout, /settings\.local\.json.*LUCIAZERO_DOC_REGEX/, "a committed settings.local.json was not named");
      assert.strictEqual(stop, 2, "a committed settings.local.json switched the nudge off");
    } else {
      assert.doesNotMatch(start.stdout, /LUCIAZERO_DOC_REGEX/, "the user's own settings.local.json was refused");
      assert.strictEqual(stop, 0, "the user's own settings.local.json was not honored");
    }
  }
});

// The plugin's doctrine stands down for a classic install, so it never loads
// twice. A doctrine file alone is not one: uninstall keeps a customized copy
// and removes the import, and a plugin installed after that loaded nothing.
test("the plugin's doctrine stands down only for a classic install that still imports it", (t) => {
  const box = sandbox(t);
  fs.mkdirSync(box.claude, { recursive: true });
  const doctrine = () => {
    const r = node({ ...box.env, PWD: box.box }, [VERIFY, "doctrine"]);
    assert.strictEqual(r.status, 0, r.stderr);
    return r.stdout;
  };
  const text = fs.readFileSync(path.join(ROOT, "claude", "luciazero.md"), "utf8");
  assert.strictEqual(doctrine(), text, "with no classic install the plugin must load the doctrine");
  fs.writeFileSync(path.join(box.claude, "luciazero.md"), "a customized copy uninstall kept\n");
  assert.strictEqual(doctrine(), text, "a doctrine file nothing imports silenced the plugin's doctrine");
  fs.writeFileSync(path.join(box.claude, "CLAUDE.md"), "# mine\n@luciazero.md.old\n");
  assert.strictEqual(doctrine(), text, "a line that only begins like the import counted as one");
  for (const md of ["# mine\n\n@luciazero.md\n", "# mine\r\n@luciazero.md\r\n", "  @~/.claude/luciazero.md\n"]) {
    fs.writeFileSync(path.join(box.claude, "CLAUDE.md"), md);
    assert.strictEqual(doctrine(), "", `the doctrine loaded twice beside a classic import (${JSON.stringify(md)})`);
  }
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
