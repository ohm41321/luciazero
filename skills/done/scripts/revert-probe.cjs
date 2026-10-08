#!/usr/bin/env node
// revert-probe — the mechanical form of the done-skill question "would the
// new tests fail if the change were reverted?" (doctrine: red before green).
// Checks <base-ref> out into a throwaway worktree, copies ONLY the test files
// changed since <base-ref> from the working tree on top of it, and runs the
// verify command there. The result is INVERTED: old code failing the new
// tests is the PASS.
//
// A red old-code run is not proof by itself. Plenty of things fail only on the
// old tree without saying anything about the change: a module the change adds,
// a command that is not installed there, a denied execution, an unrelated
// broken test. So a red run has to survive three more checks before it counts:
//   * its fingerprint must be a test verdict, not infrastructure — a shell that
//     could not run or execute the command (exit 127/126, and cmd.exe's 9009
//     on Windows), a verify command that names a file the working tree has
//     and the old tree lacks, before the run and after it, as a command, an
//     argument or the input of a `<`, and a run that failed to load the tests
//     at all (import/collection errors) are refused. cmd.exe exits 1 for a
//     command it cannot find, as a failing test does, so on Windows its own
//     "is not recognized" line counts as well;
//   * it must be attributable to the changed tests — either the verify command
//     targets one of them, or the failure output names one;
//   * the same command must PASS against the current state (the base plus every
//     changed file), so a command that is red everywhere cannot be read as a
//     regression.
// What it still cannot see: a flake that only reproduces on the old tree; a
// command the change itself adds that the verify command does not name (one
// an `npm test` script starts, one reached after a `cd`, or one given as
// `--option=file`), when what starts it swallows the shell's exit 127 (on
// Windows, cmd.exe's line, which is matched in English only); and, in the
// other direction, a suite whose own output quotes a loader error is read as
// one (this repository's revert-probe fixtures do exactly that, so probing a
// change to this script needs the manual comparison instead).
//
// Usage: node revert-probe.cjs "<verify-cmd>" [base-ref]    (base-ref default: HEAD)
// The verify command is one string for the platform's own shell: /bin/sh on
// macOS and Linux, cmd.exe on Windows. Run it BEFORE committing — the fix and
// its new tests sit in the working tree while HEAD is still the old code. For
// an already-committed fix, pass the pre-fix ref (e.g. HEAD~1) as base-ref.
// Prefer a verify command aimed at the tests the change adds; a whole-suite
// command works but attributes the failure only through the output.
//
// Exit: 0 tests bite · 1 tests stay green on old code, or no changed test
// files · 2 UNASSESSABLE (not a git repo, no commits, invalid base, an
// infrastructure failure, a failure that cannot be attributed to the changed
// tests, or a verify command that does not pass on the current code).
// Node and git only, self-contained; never touches the caller's working tree.
"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");

const WINDOWS = process.platform === "win32";

class Exit {
  constructor(code) {
    this.code = code;
  }
}

const say = (line) => process.stdout.write(`${line}\n`);
function unassessable(reason) {
  say(`UNASSESSABLE: ${reason}`);
  throw new Exit(2);
}

function isFile(p) {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

// git by its full path on Windows, where a bare name would be looked for
// first in the working directory: the repository under test. Only absolute
// PATH entries are searched, and a batch file needs a shell to start, so only
// a program counts.
function gitExecutable() {
  if (!WINDOWS) return "git";
  const key = Object.keys(process.env).find((k) => k.toUpperCase() === "PATH");
  const exts = (process.env.PATHEXT || ".COM;.EXE").split(";").map((ext) => ext.toLowerCase())
    .filter((ext) => ext === ".com" || ext === ".exe");
  for (const dir of (key ? process.env[key] : "").split(path.delimiter)) {
    const unquoted = dir.replace(/^"(.*)"$/, "$1");
    if (!unquoted || !path.isAbsolute(unquoted)) continue;
    for (const ext of exts) {
      const file = path.join(unquoted, `git${ext}`);
      if (isFile(file)) return file;
    }
  }
  return null;
}
const GIT = gitExecutable();
const git = (args, encoding = "utf8") =>
  spawnSync(GIT, args, { encoding, windowsHide: true, maxBuffer: 1 << 30 });
const firstLine = (result) => result.stdout.replace(/\r?\n$/, "");

// A signal waits for the command running at the time, as it would in a shell
// script, and then ends the probe through its cleanup with 128 + the signal.
let stopped = 0;
let running = null;
for (const [name, code] of [["SIGHUP", 129], ["SIGINT", 130], ["SIGTERM", 143]]) {
  process.on(name, () => {
    stopped = stopped || code;
    if (name === "SIGTERM" && running) running.kill("SIGTERM");
  });
}
async function checkpoint() {
  await new Promise((resolve) => setImmediate(resolve));
  if (stopped) throw new Exit(stopped);
}

// The exit status a shell would report: 128 + n for a signal, 127 for a
// command that could not be started at all.
function status(code, signal) {
  if (code !== null) return code;
  return 128 + (os.constants.signals[signal] || 0);
}

// test-file patterns mirror ready's detect: tests-style dirs plus the common
// root `test.sh` entrypoint and test_*.*, *_test.*, *.test.*, *.spec.* names
function isTestFile(f) {
  const slashed = `/${f}`;
  if (["/tests/", "/test/", "/spec/", "/__tests__/"].some((dir) => slashed.includes(dir))) return true;
  const name = f.slice(f.lastIndexOf("/") + 1);
  return name === "test.sh" || (name.startsWith("test_") && name.slice(5).includes("."))
    || name.includes("_test.") || name.includes(".test.") || name.includes(".spec.");
}

// `rel`'s directory inside the worktree `target`, made a real directory one
// component at a time. A component the old tree has as something else — a
// file, or a link that may point anywhere, a directory outside the worktree
// included — is removed from the worktree and never followed: the working
// tree, where git listed `rel`, has a directory there.
function directoryFor(target, rel) {
  let at = target;
  for (const part of rel.split("/").slice(0, -1)) {
    at = path.join(at, part);
    let found = null;
    try {
      found = fs.lstatSync(at);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    if (found && found.isDirectory() && !found.isSymbolicLink()) continue;
    if (found) fs.unlinkSync(at);
    fs.mkdirSync(at);
  }
  return at;
}

// is every directory above `rel` inside `target` a real one, so that `rel`
// names an entry of the worktree and not one a link reaches?
function contained(target, rel) {
  let at = target;
  for (const part of rel.split("/").slice(0, -1)) {
    at = path.join(at, part);
    try {
      const found = fs.lstatSync(at);
      if (!found.isDirectory() || found.isSymbolicLink()) return false;
    } catch {
      return false;
    }
  }
  return true;
}

// copy the named files out of the working tree into the worktree `target`
function overlay(target, files) {
  for (const f of files) {
    const dest = path.join(directoryFor(target, f), path.basename(f));
    let found = null;
    try {
      found = fs.lstatSync(dest);
    } catch (error) {
      // only "nothing there yet" may skip the check; anything else stops here
      if (error.code !== "ENOENT") throw error;
    }
    // a link the old tree has at this path must not be written through
    if (found && found.isSymbolicLink()) fs.unlinkSync(dest);
    fs.copyFileSync(f, dest);
  }
}

// shortest decisive line: the last line that is not blank
function lastLine(text) {
  const kept = text.split("\n").map((line) => line.replace(/\r$/, "")).filter((line) => /\S/.test(line));
  return kept.length ? kept[kept.length - 1] : "<no output>";
}

// a run that never loaded the tests judged nothing. Only loader failures are
// matched here: an environment that cannot run the command at all shows up as
// exit 127/126 (on Windows, cmd.exe's whole not-found line, CMD_NOT_FOUND), or
// fails the current-code control run below as well. Matching other
// shell-level phrases would flag any suite whose own output quotes them.
const LOAD_MARKER = /ModuleNotFoundError|ImportError|error while loading shared libraries|[Cc]annot find module|MODULE_NOT_FOUND|ERROR collecting|errors? during collection|INTERNALERROR/;
function loadMarker(text) {
  const line = text.split("\n").find((l) => LOAD_MARKER.test(l));
  return line === undefined ? null : line.replace(/\r$/, "");
}

function couldNotRun(rc) {
  return rc === 127 || (WINDOWS && rc === 9009);
}

// cmd.exe's own line for a command it cannot find, which it ends with exit 1.
const CMD_NOT_FOUND = /^'[^'\r\n]+' is not recognized as an internal or external command,\r?$/m;

// The words of the verify command that name a file the shell, or a program
// it starts, would need in the tree: each command's own word (after `&&`,
// `;` or `|` as well, past `NAME=value` on POSIX and `@` on Windows), every
// argument that is not an option, since an option that takes a value can
// stand before the script an interpreter runs (on Windows the first is also
// the command `call` or `cmd /c` starts), and the file a `<` reads. Left out:
// what `>` writes to, a stream `>&` or `<&` duplicates, a word the shell
// would expand, an option's value joined to it with `=`, and a path outside
// the tree. sh looks a bare command up in PATH alone, so on POSIX only one
// with a / in it is a file here; cmd.exe looks in the working directory
// first, with each PATHEXT extension, which `command` marks.
function treeWords(text) {
  const ops = WINDOWS ? "&|()<>" : ";&|()<>";
  const expands = WINDOWS ? /[%!^*?]/ : /[$`\\*?[~]/;
  const words = [];
  let atCommand = true;
  let argTaken = false;
  // what the next word is to a redirection: "read" for `<`, "skip" for the rest
  let redirect = null;
  let starter = false;
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (/\s/.test(c)) {
      i += 1;
      continue;
    }
    if (ops.includes(c)) {
      if (c === "<" || c === ">") {
        let op = "";
        while (i < text.length && "<>&".includes(text[i])) op += text[i++];
        if (!WINDOWS && op === ">" && text[i] === "|") i += 1;
        redirect = op === "<" ? "read" : "skip";
        continue;
      }
      atCommand = true;
      argTaken = false;
      i += 1;
      continue;
    }
    let word = "";
    let plain = true;
    while (i < text.length && !/\s/.test(text[i]) && !ops.includes(text[i])) {
      const q = text[i];
      if (q === '"' || (!WINDOWS && q === "'")) {
        const close = text.indexOf(q, i + 1);
        if (close < 0) return words;
        const inner = text.slice(i + 1, close);
        if (q === '"' && expands.test(inner.replace(/[*?[~]/g, ""))) plain = false;
        word += inner;
        i = close + 1;
      } else {
        if (expands.test(q)) plain = false;
        word += q;
        i += 1;
      }
    }
    // the digits of `2>` name a stream, not a file
    if (/^\d+$/.test(word) && (text[i] === "<" || text[i] === ">")) continue;
    if (redirect) {
      if (redirect === "read") words.push({ word, plain, command: false });
      redirect = null;
      continue;
    }
    if (atCommand) {
      if (WINDOWS) word = word.replace(/^@+/, "");
      if (!WINDOWS && /^[A-Za-z_][A-Za-z0-9_]*=/.test(word)) continue;
      atCommand = false;
      starter = WINDOWS && /^(call|cmd(\.exe)?)$/i.test(word);
      if (WINDOWS || word.includes("/")) words.push({ word, plain, command: true });
    } else if (!/^-/.test(word) && !(WINDOWS && word.startsWith("/"))) {
      words.push({ word, plain, command: starter && !argTaken });
      argTaken = true;
    }
  }
  return words.filter(({ word, plain }) => {
    if (!plain || !word) return false;
    const rel = path.normalize(word);
    return !path.isAbsolute(rel) && rel !== ".." && !rel.startsWith(`..${path.sep}`);
  });
}

// Whether `word` names a file in `dir`: a command on Windows with each
// PATHEXT extension too.
function inTree(dir, { word, command }) {
  const exts = WINDOWS && command
    ? ["", ...(process.env.PATHEXT || ".COM;.EXE;.BAT;.CMD").split(";").filter(Boolean)] : [""];
  return exts.some((ext) => isFile(path.join(dir, word + ext)));
}

async function main(argv) {
  const verify = argv[0];
  if (!verify) {
    process.stderr.write('usage: revert-probe "<verify-cmd>" [base-ref]\n');
    return 1;
  }
  const base = argv[1] || "HEAD";

  if (GIT === null) unassessable("git is not on PATH");
  if (git(["rev-parse", "--git-dir"]).status !== 0) unassessable("not a git repo");
  if (git(["rev-parse", "--verify", "HEAD"]).status !== 0) unassessable("no commits yet");
  if (git(["rev-parse", "--verify", "--quiet", `${base}^{commit}`]).status !== 0) {
    unassessable(`invalid base ref: ${base}`);
  }
  const top = git(["rev-parse", "--show-toplevel"]);
  if (top.status !== 0 || !firstLine(top)) unassessable("no working tree (bare repo?)");
  process.chdir(firstLine(top));

  // changed vs base (tracked) plus untracked — the two sets are disjoint.
  // NUL-delimited, because git C-quotes non-ASCII/backslash names in its plain
  // output. `tests` drives the old-code overlay; `changed` and `gone` rebuild
  // the current state for the control run (a deleted test cannot bite, but a
  // deleted source file is part of the change). --no-renames: a rename is
  // listed under its new name only, and the old one must go too.
  const names = [git(["diff", "--name-only", "-z", "--no-renames", base, "--"], "buffer"),
    git(["ls-files", "--others", "--exclude-standard", "-z"], "buffer")]
    .flatMap((result) => (result.stdout ? result.stdout.toString("utf8").split("\0") : []))
    .filter(Boolean);
  const tests = [];
  const changed = [];
  const gone = [];
  for (const f of names) {
    if (!isFile(f)) {
      gone.push(f);
      continue;
    }
    changed.push(f);
    if (isTestFile(f)) tests.push(f);
  }
  if (names.length === 0) {
    // a fix committed before the probe ran: its tests are in the base
    say(`FAIL: nothing changed since ${base} — if the change is committed, pass the commit before it as base-ref (${base}~1, say)`);
    return 1;
  }
  if (tests.length === 0) {
    say(`FAIL: no test files changed since ${base} — the change ships without a test that bites`);
    return 1;
  }

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "revert-probe-"));
  const worktrees = [];
  try {
    let runs = 0;
    // the verify command in `dir` through the platform's shell, its stdout
    // and stderr interleaved in one file as `2>&1` would leave them
    const runVerify = async (dir) => {
      const log = path.join(tmp, `run-${runs += 1}.log`);
      const fd = fs.openSync(log, "w");
      let rc;
      try {
        rc = await new Promise((resolve) => {
          running = spawn(verify, { cwd: dir, shell: true, stdio: ["inherit", fd, fd], windowsHide: true });
          running.on("error", () => resolve(127));
          running.on("close", (code, signal) => resolve(status(code, signal)));
        });
      } finally {
        running = null;
        fs.closeSync(fd);
      }
      await checkpoint();
      return { rc, out: fs.readFileSync(log, "utf8") };
    };
    const checkout = async (name) => {
      const dir = path.join(tmp, name);
      const added = git(["worktree", "add", "--detach", dir, base]);
      worktrees.push(dir);
      await checkpoint();
      if (added.status !== 0) unassessable(`git worktree add failed for ${base}`);
      return dir;
    };
    // does `text` name one of the changed test files, by path or by basename?
    const namesChangedTest = (text) =>
      tests.some((f) => text.includes(f) || text.includes(f.slice(f.lastIndexOf("/") + 1)));

    // old code in a throwaway worktree, with ONLY the changed test files on it
    const oldTree = await checkout("old");
    overlay(oldTree, tests);
    // a program or input the working tree has and the old tree lacks could
    // not have run there, whatever the shell said and in whatever language.
    // Looked up before the run and after it: one the run makes for itself,
    // as a build or a report does, was there when it was needed.
    const lacking = treeWords(verify).filter((w) => inTree(process.cwd(), w) && !inTree(oldTree, w));
    const old = await runVerify(oldTree);
    const absent = lacking.find((w) => !inTree(oldTree, w));

    if (old.rc === 0) {
      say("FAIL: the changed tests stay green against the old code — they do not cover the change");
      return 1;
    }

    // --- the red run has to earn the word "regression" -----------------------
    if (absent) {
      unassessable(`the verify command could not be run on ${base} (exit ${old.rc}): ${absent.word} is not in its tree`);
    }
    const notFound = WINDOWS ? CMD_NOT_FOUND.exec(old.out) : null;
    if (couldNotRun(old.rc) || notFound) {
      const evidence = notFound ? notFound[0].replace(/\r$/, "") : lastLine(old.out);
      unassessable(`the verify command could not be run on ${base} (exit ${old.rc}): ${evidence}`);
    }
    if (old.rc === 126) {
      unassessable(`the verify command was not executable on ${base} (exit 126): ${lastLine(old.out)}`);
    }
    const mark = loadMarker(old.out);
    if (mark !== null) {
      unassessable(`the old-code run never loaded the tests: ${mark}
  that is an import failure on ${base}, not a regression — the change may
  simply add code the tests import. Point the verify command at a test that
  fails on its assertion instead.`);
    }

    let note = "";
    if (!namesChangedTest(verify)) {
      if (!namesChangedTest(old.out)) {
        unassessable(`the verify command does not target any changed test file and
  its failure output does not name one, so the failure cannot be attributed to
  the changed tests. Re-run with a command that targets them.`);
      }
      note = "note: the verify command is not targeted at the changed tests; attribution comes from the failure output";
    }

    // control: the same command must pass on the current state (base + every
    // changed file), or the failure says nothing about the change
    const newTree = await checkout("new");
    overlay(newTree, changed);
    for (const f of gone) {
      // nothing a link in the old tree reaches is removed
      if (!contained(newTree, f)) continue;
      try {
        fs.rmSync(path.join(newTree, f), { force: true });
      } catch {
        // a directory where the base had a file (a submodule, say): left as is
      }
    }

    const now = await runVerify(newTree);
    if (now.rc !== 0) {
      unassessable(`the same command also fails on the current code (exit ${now.rc}): ${lastLine(now.out)}
  the old-code failure cannot be attributed to reverting the change. Make the
  verify command pass on the current tree first.`);
    }

    say("PASS: regression tests bite — old code fails the new tests, the same command passes on the current code");
    say(`  evidence (exit ${old.rc} on ${base}): ${lastLine(old.out)}`);
    if (note) say(`  ${note}`);
    return 0;
  } finally {
    for (const dir of worktrees) git(["worktree", "remove", "--force", dir]);
    try {
      fs.rmSync(tmp, { recursive: true, force: true });
    } catch {
      // a file still held open on Windows; the prune below forgets the tree
    }
    git(["worktree", "prune"]);
  }
}

main(process.argv.slice(2)).then(
  (code) => {
    process.exitCode = stopped || code;
  },
  (error) => {
    if (error instanceof Exit) {
      process.exitCode = error.code;
      return;
    }
    say(`UNASSESSABLE: revert-probe failed: ${error && error.message ? error.message : error}`);
    process.exitCode = 2;
  },
);
