"use strict";
// The skills' bundled helpers -- ready's detect, done's revert-probe and
// bisect's safe-bisect -- are Node scripts so that they run natively on
// Windows. These cases run them the way a skill does, `node <file>`, on every
// platform the suite runs on, in throwaway git repositories whose fixtures
// are themselves Node, so the same case means the same thing everywhere. The
// Bash gates (core, eval 4d3, bisect) cover the same helpers through their
// .sh names on macOS and Linux.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { ROOT, WINDOWS, sandbox } = require("./sandbox.js");

const DETECT = path.join(ROOT, "skills", "ready", "scripts", "detect.cjs");
const PROBE = path.join(ROOT, "skills", "done", "scripts", "revert-probe.cjs");
const BISECT = path.join(ROOT, "skills", "bisect", "scripts", "safe-bisect.cjs");

function box(t) {
  const b = sandbox(t);
  Object.assign(b.env, {
    GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.invalid",
    GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.invalid",
    GIT_CONFIG_NOSYSTEM: "1",
  });
  return b;
}

function run(env, cwd, args) {
  const r = spawnSync(process.execPath, args, { cwd, env, encoding: "utf8", windowsHide: true, timeout: 120000 });
  if (r.error) throw r.error;
  return { status: r.status, out: r.stdout + r.stderr };
}

function git(env, cwd, ...args) {
  const r = spawnSync("git", args, { cwd, env, encoding: "utf8", windowsHide: true });
  assert.strictEqual(r.status, 0, `git ${args.join(" ")}: ${r.stderr}`);
  return r.stdout.trim();
}

function write(dir, files) {
  for (const [name, text] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(dir, name)), { recursive: true });
    fs.writeFileSync(path.join(dir, name), text);
  }
}

// A repository as the eval fixtures plant it: a committed bug and a test that
// does not see it, before any fix.
function repo(b, name, files) {
  const dir = path.join(b.box, name);
  fs.mkdirSync(dir);
  git(b.env, dir, "init", "-q");
  write(dir, files);
  git(b.env, dir, "add", "-A");
  git(b.env, dir, "commit", "-qm", "plant");
  return dir;
}

const worktrees = (b, dir) => git(b.env, dir, "worktree", "list", "--porcelain").split("\n").filter((l) => l.startsWith("worktree ")).length;

test("detect lists CI run lines and test locations, and refuses a missing directory", (t) => {
  const b = box(t);
  const dir = path.join(b.box, "proj ü");
  write(dir, {
    ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: npm run canary-cmd\n",
    "package.json": '{"scripts":{"test":"node --test"},"workspaces":["a"]}',
    "tests/x.test.js": "",
  });
  const r = run(b.env, b.box, [DETECT, dir]);
  assert.strictEqual(r.status, 0, r.out);
  assert.match(r.out, /^git repo: NO/m);
  assert.match(r.out, /^ {2}4: {6}- run: npm run canary-cmd$/m);
  assert.match(r.out, /^ {2}test: node --test$/m);
  assert.match(r.out, /^ {2}\.\/tests$/m);
  assert.match(r.out, /^ {2}\.\/tests\/x\.test\.js$/m);
  assert.match(r.out, /^package\.json declares workspaces$/m);
  const missing = run(b.env, b.box, [DETECT, path.join(b.box, "nope")]);
  assert.strictEqual(missing.status, 1, missing.out);
  assert.match(missing.out, /no such directory/);
});

const BUGGY = "module.exports = (a, b) => (a === 2 ? a - b : a + b);\n";
const FIXED = "module.exports = (a, b) => a + b;\n";
const check = (...cases) => `const add = require("../calc");\n${cases.map(([a, b, sum]) =>
  `if (add(${a}, ${b}) !== ${sum}) { console.error("tests/calc.test.js: add(${a}, ${b}) is not ${sum}"); process.exit(1); }\n`).join("")}console.log("ok");\n`;

test("revert-probe: a test that bites passes, a vacuous one fails, and neither touches the caller's tree", (t) => {
  const b = box(t);
  const bites = repo(b, "bites", { "calc.js": BUGGY, "tests/calc.test.js": check([0, 0, 0]) });
  write(bites, { "calc.js": FIXED, "tests/calc.test.js": check([0, 0, 0], [2, 2, 4]) });
  const before = git(b.env, bites, "status", "--porcelain");
  const r = run(b.env, bites, [PROBE, "node tests/calc.test.js"]);
  assert.strictEqual(r.status, 0, r.out);
  assert.match(r.out, /^PASS: regression tests bite/m);
  assert.match(r.out, /evidence \(exit 1 on HEAD\): tests\/calc\.test\.js: add\(2, 2\) is not 4/);
  assert.strictEqual(git(b.env, bites, "status", "--porcelain"), before, "the caller's working tree changed");
  assert.strictEqual(worktrees(b, bites), 1, "a worktree was left behind");

  const vacuous = repo(b, "vacuous", { "calc.js": BUGGY, "tests/calc.test.js": check([0, 0, 0]) });
  write(vacuous, { "calc.js": FIXED, "tests/calc.test.js": check([0, 0, 0], [1, 1, 2]) });
  const v = run(b.env, vacuous, [PROBE, "node tests/calc.test.js"]);
  assert.strictEqual(v.status, 1, v.out);
  assert.match(v.out, /stay green against the old code/);
});

test("revert-probe: what cannot be attributed to the change is UNASSESSABLE", (t) => {
  const b = box(t);
  const plant = { "calc.js": BUGGY, "tests/calc.test.js": check([0, 0, 0]) };

  const outside = path.join(b.box, "not-a-repo");
  fs.mkdirSync(outside);
  const nogit = run(b.env, outside, [PROBE, "node -e 0"]);
  assert.strictEqual(nogit.status, 2, nogit.out);
  assert.match(nogit.out, /^UNASSESSABLE: not a git repo/m);

  // the platform's shell cannot find the command: sh exits 127; cmd.exe
  // exits 1, as a failing test would, and says so in a line of its own
  const nocmd = repo(b, "nocmd", plant);
  write(nocmd, { "calc.js": FIXED, "tests/calc.test.js": check([2, 2, 4]) });
  const missing = run(b.env, nocmd, [PROBE, "luciazero-not-a-real-command tests/calc.test.js"]);
  assert.strictEqual(missing.status, 2, missing.out);
  assert.match(missing.out, WINDOWS
    ? /could not be run on HEAD \(exit 1\): 'luciazero-not-a-real-command' is not recognized/
    : /could not be run on HEAD \(exit 127\)/);

  // a runner the change itself adds is missing from the old tree, while the
  // control tree has it and passes: the old run judged nothing
  const runner = repo(b, "runner", plant);
  write(runner, { "calc.js": FIXED, "tests/calc.test.js": check([2, 2, 4]) });
  if (WINDOWS) write(runner, { "run-tests.cmd": "@node %*\r\n" });
  else fs.writeFileSync(path.join(runner, "run-tests.sh"), '#!/bin/sh\nexec node "$@"\n', { mode: 0o755 });
  const added = run(b.env, runner, [PROBE, `${WINDOWS ? "run-tests.cmd" : "./run-tests.sh"} tests/calc.test.js`]);
  assert.strictEqual(added.status, 2, added.out);
  assert.match(added.out, /^UNASSESSABLE: the verify command could not be run on HEAD/m);

  // the old tree cannot load a module the change adds
  const newmod = repo(b, "newmod", { "main.js": "" });
  write(newmod, { "helper.js": "module.exports = (n) => n * 2;\n",
    "tests/helper.test.js": 'if (require("../helper")(2) !== 4) process.exit(1);\n' });
  const loader = run(b.env, newmod, [PROBE, "node tests/helper.test.js"]);
  assert.strictEqual(loader.status, 2, loader.out);
  assert.match(loader.out, /never loaded the tests: .*Cannot find module/);

  // red on the current code as well
  const bothred = repo(b, "bothred", plant);
  write(bothred, { "calc.js": FIXED, "tests/calc.test.js": check([2, 2, 5]) });
  const both = run(b.env, bothred, [PROBE, "node tests/calc.test.js"]);
  assert.strictEqual(both.status, 2, both.out);
  assert.match(both.out, /also fails on the current code \(exit 1\)/);

  // an untargeted suite whose failure belongs to an unrelated test
  const suite = 'for (const f of require("fs").readdirSync("tests")) { const r = require("child_process").spawnSync(process.execPath, ["tests/" + f], { stdio: "inherit" }); if (r.status) process.exit(1); }\n';
  const unrelated = repo(b, "unrelated", { ...plant, "tests/broken.test.js": 'console.error("unrelated breakage"); process.exit(1);\n', "run-all.js": suite });
  write(unrelated, { "calc.js": FIXED, "tests/calc.test.js": check([2, 2, 4]) });
  const blame = run(b.env, unrelated, [PROBE, "node run-all.js"]);
  assert.strictEqual(blame.status, 2, blame.out);
  assert.match(blame.out, /cannot be attributed/);
  for (const dir of [nocmd, newmod, bothred, unrelated]) assert.strictEqual(worktrees(b, dir), 1, `${dir} kept a worktree`);
});

// The old tree may have a link where the working tree has a directory: here
// tests/ was a link to a directory outside the repository, and the change made
// it a real one. The overlay must replace the link inside the throwaway
// worktree, never write through it.
test("revert-probe writes nothing through a link the old tree has above a changed file", (t) => {
  const b = box(t);
  const outside = path.join(b.box, "outside");
  const sentinel = "console.log('outside, must stay as it is');\n";
  write(outside, { "test_probe.cjs": sentinel });
  const dir = path.join(b.box, "linked");
  fs.mkdirSync(dir);
  git(b.env, dir, "init", "-q");
  git(b.env, dir, "config", "core.symlinks", "true");
  write(dir, { "value.txt": "old\n" });
  try {
    fs.symlinkSync(outside, path.join(dir, "tests"), "dir");
  } catch (error) {
    if (WINDOWS && error.code === "EPERM") return t.skip("creating a symbolic link needs a privilege this account lacks");
    throw error;
  }
  git(b.env, dir, "add", "-A");
  git(b.env, dir, "commit", "-qm", "linked tests");
  fs.unlinkSync(path.join(dir, "tests"));
  write(dir, {
    "value.txt": "new\n",
    "tests/test_probe.cjs": 'if (require("fs").readFileSync("value.txt", "utf8").trim() !== "new") { console.error("tests/test_probe.cjs: value is not new"); process.exit(1); }\n',
  });
  const r = run(b.env, dir, [PROBE, "node tests/test_probe.cjs"]);
  assert.strictEqual(fs.readFileSync(path.join(outside, "test_probe.cjs"), "utf8"), sentinel, "a file outside the worktree was overwritten");
  assert.deepStrictEqual(fs.readdirSync(outside), ["test_probe.cjs"], "something was written outside the worktree");
  assert.strictEqual(r.status, 0, r.out);
  assert.match(r.out, /^PASS: regression tests bite/m);
  assert.strictEqual(worktrees(b, dir), 1, "a worktree was left behind");
});

test("revert-probe stops rather than copy onto a path it could not inspect", (t) => {
  const b = box(t);
  const outside = path.join(b.box, "outside");
  const sentinel = "console.log('outside, must stay as it is');\n";
  write(outside, { "test_probe.cjs": sentinel });
  const dir = path.join(b.box, "leaf");
  fs.mkdirSync(dir);
  git(b.env, dir, "init", "-q");
  git(b.env, dir, "config", "core.symlinks", "true");
  write(dir, { "value.txt": "old\n" });
  fs.mkdirSync(path.join(dir, "tests"));
  try {
    fs.symlinkSync(path.join(outside, "test_probe.cjs"), path.join(dir, "tests", "test_probe.cjs"), "file");
  } catch (error) {
    if (WINDOWS && error.code === "EPERM") return t.skip("creating a symbolic link needs a privilege this account lacks");
    throw error;
  }
  git(b.env, dir, "add", "-A");
  git(b.env, dir, "commit", "-qm", "linked test");
  fs.unlinkSync(path.join(dir, "tests", "test_probe.cjs"));
  write(dir, {
    "value.txt": "new\n",
    "tests/test_probe.cjs": 'if (require("fs").readFileSync("value.txt", "utf8").trim() !== "new") { console.error("tests/test_probe.cjs: value is not new"); process.exit(1); }\n',
  });
  // the leaf in the throwaway worktree cannot be inspected: a denied lstat,
  // injected into the probe's own process only
  const deny = path.join(b.box, "deny-lstat.cjs");
  fs.writeFileSync(deny, `const fs = require("fs");
const lstatSync = fs.lstatSync;
fs.lstatSync = function (p, ...rest) {
  const s = String(p);
  if (/[\\\\/]revert-probe-[^\\\\/]*[\\\\/]/.test(s) && /[\\\\/]test_probe\\.cjs$/.test(s)) {
    throw Object.assign(new Error("EACCES: permission denied, lstat '" + s + "'"), { code: "EACCES" });
  }
  return lstatSync.call(this, p, ...rest);
};
`);
  const r = run(b.env, dir, ["--require", deny, PROBE, "node tests/test_probe.cjs"]);
  assert.strictEqual(fs.readFileSync(path.join(outside, "test_probe.cjs"), "utf8"), sentinel, "a file outside the worktree was overwritten");
  assert.strictEqual(r.status, 2, r.out);
  assert.match(r.out, /^UNASSESSABLE: revert-probe failed: EACCES/m);
  assert.strictEqual(worktrees(b, dir), 1, "a worktree was left behind");
});

// The criterion lives outside the repository, so every revision runs the same
// one, and takes arguments a shell would split or act on: they must arrive
// exactly as given. It also refuses to run in a tree the last run dirtied.
const CRITERION = `const fs = require("fs");
if (JSON.stringify(process.argv.slice(2)) !== JSON.stringify(["a b", "x&y", "q\\"uote", "100%"])) { console.error("argv", process.argv.slice(2)); process.exit(3); }
if (fs.existsSync(".criterion-state")) process.exit(9);
fs.writeFileSync(".criterion-state", "");
if (fs.existsSync("skip.flag") && process.env.LZ_SKIP === "1") process.exit(125);
process.exit(fs.readFileSync("value.txt", "utf8").trim() === "good" ? 0 : 1);
`;

function history(b) {
  const dir = repo(b, "history", { "value.txt": "good\n" });
  const good = git(b.env, dir, "rev-parse", "HEAD");
  const commit = (files, message) => {
    write(dir, files);
    git(b.env, dir, "add", "-A");
    git(b.env, dir, "commit", "-qm", message);
  };
  commit({ "note.txt": "neutral\n" }, "neutral");
  commit({ "skip.flag": "skip\n" }, "untestable");
  fs.rmSync(path.join(dir, "skip.flag"));
  commit({ "value.txt": "bad\n" }, "regression");
  const first = git(b.env, dir, "rev-parse", "HEAD");
  commit({ "note.txt": "neutral\nlater\n" }, "later");
  const bad = git(b.env, dir, "rev-parse", "HEAD");
  write(dir, { "untracked.txt": "mine\n" });
  return { dir, good, bad, first };
}

test("safe-bisect finds the first bad commit with the command's arguments intact, and leaves the caller alone", (t) => {
  const b = box(t);
  const h = history(b);
  const criterion = path.join(b.box, "criterion dir", "check.js");
  write(path.dirname(criterion), { "check.js": CRITERION });
  const argv = [process.execPath, criterion, "a b", "x&y", 'q"uote', "100%"];

  const r = run(b.env, h.dir, [BISECT, "--good", h.good, "--bad", h.bad, "--", ...argv]);
  assert.strictEqual(r.status, 0, r.out);
  assert.match(r.out, new RegExp(`^FIRST_BAD ${h.first}$`, "m"));
  assert.match(r.out, /^SUMMARY [0-9a-f]+ t — regression$/m);
  assert.strictEqual(git(b.env, h.dir, "rev-parse", "HEAD"), h.bad, "the caller's HEAD moved");
  assert.strictEqual(git(b.env, h.dir, "status", "--porcelain"), "?? untracked.txt", "the caller's tree changed");
  assert.strictEqual(worktrees(b, h.dir), 1, "a worktree was left behind");

  // 125 at the only commit that could decide leaves bisect ambiguous
  const skipped = run({ ...b.env, LZ_SKIP: "1" }, h.dir, [BISECT, "--good", h.good, "--bad", h.bad, "--", ...argv]);
  assert.strictEqual(skipped.status, 2, skipped.out);
  assert.match(skipped.out, /could not identify a unique first bad commit/);

  // a command that cannot be started is not a bad revision
  const missing = run(b.env, h.dir, [BISECT, "--good", h.good, "--bad", h.bad, "--", path.join(b.box, "missing-verify")]);
  assert.strictEqual(missing.status, 66, missing.out);
  assert.match(missing.out, /good endpoint could not be evaluated \(exit 128\)/);

  const usage = run(b.env, h.dir, [BISECT, "--good", h.good, "--bad", h.bad]);
  assert.strictEqual(usage.status, 64, usage.out);
  assert.strictEqual(worktrees(b, h.dir), 1, "a worktree was left behind");
});

// An executable script with no #! line is the shell's to run, as it was under
// the Bash runner: by path, and by a name found on PATH.
test("safe-bisect hands an executable script with no #! line to /bin/sh", { skip: WINDOWS && "POSIX only: Windows has no #! line" }, (t) => {
  const b = box(t);
  const h = history(b);
  const dir = path.join(b.box, "plain criterion");
  fs.mkdirSync(dir);
  fs.writeFileSync(path.join(dir, "lz-plain-check"), '[ "$(cat value.txt)" = good ]\n', { mode: 0o755 });
  const byName = { ...b.env, PATH: `${dir}${path.delimiter}${b.env.PATH || ""}` };
  for (const [env, criterion] of [[b.env, path.join(dir, "lz-plain-check")], [byName, "lz-plain-check"]]) {
    const r = run(env, h.dir, [BISECT, "--good", h.good, "--bad", h.bad, "--", criterion]);
    assert.strictEqual(r.status, 0, r.out);
    assert.match(r.out, new RegExp(`^FIRST_BAD ${h.first}$`, "m"));
  }
  assert.strictEqual(worktrees(b, h.dir), 1, "a worktree was left behind");
});

// A criterion that always passes is wrong at the bad endpoint, which only the
// endpoint samples can tell: any spelling of zero samples is refused.
test("safe-bisect refuses zero samples however it is written", (t) => {
  const b = box(t);
  const h = history(b);
  const green = [process.execPath, "-e", "process.exit(0)"];
  for (const retries of ["0", "00", "000"]) {
    const r = run(b.env, h.dir, [BISECT, "--good", h.good, "--bad", h.bad, "--retries", retries, "--", ...green]);
    assert.strictEqual(r.status, 64, `--retries ${retries}: ${r.out}`);
    assert.doesNotMatch(r.out, /FIRST_BAD/);
  }
  const one = run(b.env, h.dir, [BISECT, "--good", h.good, "--bad", h.bad, "--retries", "01", "--", ...green]);
  assert.strictEqual(one.status, 67, one.out);
  assert.match(one.out, /known-bad endpoint passed on sample 1/);
  assert.strictEqual(worktrees(b, h.dir), 1, "a worktree was left behind");
});

// Windows looks for a bare command name in the working directory before PATH.
// Each helper works inside the repository it is given, so a git.exe there
// must never run: here it is a copy of node that, run as `git rev-parse ...`,
// loads the file ./rev-parse, which leaves a mark.
test("on Windows, no helper runs a git.exe found in the repository", { skip: !WINDOWS && "Windows only: POSIX never looks in the working directory" }, (t) => {
  const b = box(t);
  const poison = (dir) => {
    fs.copyFileSync(process.execPath, path.join(dir, "git.exe"));
    write(dir, { "rev-parse": 'require("fs").writeFileSync(require("path").join(__dirname, "POISONED"), process.argv.join(" ")); process.exit(1);\n' });
    return path.join(dir, "POISONED");
  };
  const scanned = repo(b, "scanned", { "README.md": "" });
  const mark = poison(scanned);
  // the fixture bites: a bare name started from this directory finds it
  spawnSync("git", ["rev-parse", "--git-dir"], { cwd: scanned, env: b.env, windowsHide: true });
  assert.ok(fs.existsSync(mark), "Windows did not look in the working directory; this case proves nothing");
  fs.rmSync(mark);

  const d = run(b.env, scanned, [DETECT, scanned]);
  assert.strictEqual(d.status, 0, d.out);
  assert.match(d.out, /^git repo: yes/m);
  assert.ok(!fs.existsSync(mark), `detect ran the repository's git.exe: ${fs.existsSync(mark) && fs.readFileSync(mark, "utf8")}`);

  const bites = repo(b, "bites", { "calc.js": BUGGY, "tests/calc.test.js": check([0, 0, 0]) });
  write(bites, { "calc.js": FIXED, "tests/calc.test.js": check([0, 0, 0], [2, 2, 4]) });
  const probeMark = poison(bites);
  const p = run(b.env, bites, [PROBE, "node tests/calc.test.js"]);
  assert.ok(!fs.existsSync(probeMark), "revert-probe ran the repository's git.exe");
  assert.strictEqual(p.status, 0, p.out);

  const h = history(b);
  const bisectMark = poison(h.dir);
  const criterion = path.join(b.box, "criterion", "check.js");
  write(path.dirname(criterion), { "check.js": CRITERION });
  const r = run(b.env, h.dir, [BISECT, "--good", h.good, "--bad", h.bad, "--", process.execPath, criterion, "a b", "x&y", 'q"uote', "100%"]);
  assert.ok(!fs.existsSync(bisectMark), "safe-bisect ran the repository's git.exe");
  assert.strictEqual(r.status, 0, r.out);
  assert.match(r.out, new RegExp(`^FIRST_BAD ${h.first}$`, "m"));
});

test("on Windows, safe-bisect runs a .cmd criterion by path and from PATH with its arguments intact", { skip: !WINDOWS && "Windows only: a .cmd runs through cmd.exe" }, (t) => {
  const b = box(t);
  const h = history(b);
  const bin = path.join(b.box, "bin (x86) & co");
  write(bin, {
    "check.js": CRITERION,
    "lz-criterion.cmd": `@"${process.execPath}" "%~dp0check.js" %*\r\n`,
  });
  const args = ["a b", "x&y", 'q"uote', "100%"];
  const key = Object.keys(b.env).find((name) => name.toUpperCase() === "PATH") || "Path";
  const env = { ...b.env, [key]: `${bin};${b.env[key] || ""}` };
  for (const name of [path.join(bin, "lz-criterion.cmd"), "lz-criterion"]) {
    const r = run(env, h.dir, [BISECT, "--good", h.good, "--bad", h.bad, "--", name, ...args]);
    assert.strictEqual(r.status, 0, `${name}: ${r.out}`);
    assert.match(r.out, new RegExp(`^FIRST_BAD ${h.first}$`, "m"));
  }
  assert.strictEqual(worktrees(b, h.dir), 1, "a worktree was left behind");
});
