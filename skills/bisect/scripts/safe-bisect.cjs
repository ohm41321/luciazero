#!/usr/bin/env node
// Locate a first bad commit in a detached temporary worktree. The caller's
// branch, index, and untracked files are never checked out or mutated.
//
// Usage: node safe-bisect.cjs --good REV --bad REV [--retries N] -- COMMAND [ARG ...]
// COMMAND runs with its arguments exactly as given, through no shell. A bare
// name is looked up on PATH; a file in the repository is named by a path
// (./verify.sh, or .\verify.cmd on Windows). On Windows a .cmd or .bat runs
// through cmd.exe with each argument quoted for it.
//
// Exit: 0 first bad commit found · 64 usage · 65 a revision is not a commit,
// or good is not an ancestor of bad · 66 an endpoint could not be evaluated ·
// 67 an endpoint gave the wrong answer · 69 not in a git repository · 70 the
// temporary worktree could not be set up · otherwise `git bisect run`'s own
// status when it could not name a unique first bad commit.
// Node and git only, self-contained.
"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");

const WINDOWS = process.platform === "win32";
const RUNNER_FLAG = "--run-criterion";

class Exit {
  constructor(code) {
    this.code = code;
  }
}

const say = (line) => process.stdout.write(`${line}\n`);
const warn = (line) => process.stderr.write(`${line}\n`);
const firstLine = (result) => (result.stdout || "").replace(/\r?\n$/, "");

function usage() {
  warn("usage: safe-bisect --good REV --bad REV [--retries N] -- COMMAND [ARG ...]");
  throw new Exit(64);
}

// The exit status a shell would report: 128 + n for a signal.
function status(code, signal) {
  if (code !== null) return code;
  return 128 + (os.constants.signals[signal] || 0);
}

// ---------------------------------------------------------------------------
// Starting COMMAND [ARG ...] with its argument boundaries intact.

function isFile(p) {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

// Windows: the absolute PATH entries. The working directory is not one of
// them, though Windows looks there first for a bare name.
function pathDirs() {
  const key = Object.keys(process.env).find((k) => k.toUpperCase() === "PATH");
  return (key ? process.env[key] : "").split(path.delimiter)
    .map((dir) => dir.replace(/^"(.*)"$/, "$1")).filter((dir) => dir && path.isAbsolute(dir));
}

// Windows: the PATHEXT extensions among `allowed`, in PATHEXT's order.
function pathExts(allowed) {
  return (process.env.PATHEXT || ".COM;.EXE;.BAT;.CMD").split(";")
    .map((ext) => ext.toLowerCase()).filter((ext) => allowed.includes(ext));
}

// Windows: the file `name` means, or null. A path is taken relative to the
// working directory; a bare name only from absolute PATH entries, as on POSIX,
// never from the working directory. Each candidate is tried as given and with
// the PATHEXT extensions this can start.
function resolveWindows(name, cwd) {
  const startable = [".com", ".exe", ".bat", ".cmd"];
  const exts = pathExts(startable);
  const within = (dir) => {
    const base = path.resolve(dir, name);
    if (startable.includes(path.extname(base).toLowerCase()) && isFile(base)) return base;
    for (const ext of exts) if (isFile(base + ext)) return base + ext;
    return null;
  };
  if (/[\\/]/.test(name) || path.isAbsolute(name)) return within(cwd);
  for (const dir of pathDirs()) {
    const found = within(dir);
    if (found) return found;
  }
  return null;
}

// git by its full path on Windows, where a bare name would be looked for
// first in the working directory: the repository under test, or one of its
// old revisions. A batch file needs a shell to start, so only a program counts.
const GIT = WINDOWS
  ? pathDirs().flatMap((dir) => pathExts([".com", ".exe"]).map((ext) => path.join(dir, `git${ext}`))).find(isFile) || null
  : "git";
const git = (args, options = {}) => (GIT === null
  ? { status: 127, stdout: "", stderr: "" }
  : spawnSync(GIT, args, { encoding: "utf8", windowsHide: true, ...options }));

// cmd.exe reads a batch file's command line twice, so each argument is quoted
// for the program and every cmd.exe metacharacter escaped twice
// (https://qntm.org/cmd).
const CMD_META = /([()\][%!^"`<>&|;, *?])/g;
function cmdQuote(arg) {
  const quoted = `"${arg.replace(/(\\*)"/g, '$1$1\\"').replace(/(\\*)$/, "$1$1")}"`;
  return quoted.replace(CMD_META, "^$1").replace(CMD_META, "^$1");
}

// [file, args, extra spawn options] for argv, or null when nothing runs it.
function command(argv, cwd) {
  if (!WINDOWS) return [argv[0], argv.slice(1), {}];
  const file = resolveWindows(argv[0], cwd);
  if (file === null) return null;
  if (!/\.(bat|cmd)$/i.test(file)) return [file, argv.slice(1), {}];
  const line = [file.replace(CMD_META, "^$1"), ...argv.slice(1).map(cmdQuote)].join(" ");
  return [process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", `"${line}"`], { windowsVerbatimArguments: true }];
}

// Run the criterion once in `cwd`, then put the worktree back exactly as the
// revision has it, so one run cannot leave anything behind for the next. A
// command that cannot be started (127, like a shell's) or executed (126) is
// reported as 128, which `git bisect run` takes as "stop", not as "bad".
function finish(rc, cwd, quiet) {
  git(["reset", "--hard", "-q", "HEAD"], { cwd, stdio: "ignore" });
  git(["clean", "-ffdqx"], { cwd, stdio: "ignore" });
  if (rc === 126 || rc === 127) {
    if (!quiet) warn("safe-bisect: verify command is missing or not executable");
    return 128;
  }
  return rc;
}

// POSIX: a file the kernel will not run (ENOEXEC, an executable script with
// no #! line) goes to /bin/sh, as execvp and the Bash runner this replaces
// would have done. A bare name is found on PATH first, as exec found it.
function viaShell(spec) {
  const runnable = (p) => {
    try {
      fs.accessSync(p, fs.constants.X_OK);
      return isFile(p);
    } catch {
      return false;
    }
  };
  const file = spec[0].includes("/") ? spec[0]
    : (process.env.PATH || "").split(":").map((dir) => path.join(dir || ".", spec[0])).find(runnable) || spec[0];
  return ["/bin/sh", [file, ...spec[1]], spec[2]];
}

function startError(argv, error, quiet) {
  if (!quiet) warn(`${argv[0]}: ${error && error.code === "EACCES" ? "permission denied" : "command not found"}`);
  return error && error.code === "EACCES" ? 126 : 127;
}

// The criterion as `git bisect run` calls it: a process of its own.
function runCriterion(file) {
  const argv = JSON.parse(fs.readFileSync(file, "utf8"));
  const cwd = process.cwd();
  const spec = command(argv, cwd);
  let rc;
  if (spec === null) {
    rc = startError(argv, null, false);
  } else {
    const start = (s) => spawnSync(s[0], s[1], { cwd, stdio: "inherit", windowsHide: true, ...s[2] });
    let done = start(spec);
    if (!WINDOWS && done.error && done.error.code === "ENOEXEC") done = start(viaShell(spec));
    rc = done.error ? startError(argv, done.error, false) : status(done.status, done.signal);
  }
  return finish(rc, cwd, false);
}

// ---------------------------------------------------------------------------

// A signal waits for the command running at the time, as it would in a shell
// script, and then ends the bisect through its cleanup with 128 + the signal.
let stopped = 0;
let running = null;
async function checkpoint() {
  await new Promise((resolve) => setImmediate(resolve));
  if (stopped) throw new Exit(stopped);
}

// Start spec and wait for it. spawn() throws some errors (ENOEXEC among them)
// instead of emitting them, so both ways end in onError.
function launch(spec, options, onError) {
  let child;
  try {
    child = spawn(spec[0], spec[1], { ...options, ...spec[2] });
  } catch (error) {
    if (!WINDOWS && error.code === "ENOEXEC") return launch(viaShell(spec), options, onError);
    return Promise.resolve(onError(error));
  }
  return wait(child, onError);
}

function wait(child, onError) {
  running = child;
  return new Promise((resolve) => {
    child.on("error", (error) => resolve(onError(error)));
    child.on("close", (code, signal) => resolve(status(code, signal)));
  }).finally(() => {
    running = null;
  });
}

async function main(args) {
  for (const [name, code] of [["SIGHUP", 129], ["SIGINT", 130], ["SIGTERM", 143]]) {
    process.on(name, () => {
      stopped = stopped || code;
      if (name === "SIGTERM" && running) running.kill("SIGTERM");
    });
  }

  let good = "";
  let bad = "";
  let retries = "2";
  let i = 0;
  for (; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === "--") {
      i += 1;
      break;
    }
    if (!["--good", "--bad", "--retries"].includes(arg) || i + 1 >= args.length) usage();
    i += 1;
    if (arg === "--good") good = args[i];
    else if (arg === "--bad") bad = args[i];
    else retries = args[i];
  }
  const argv = args.slice(i);
  if (!good || !bad || argv.length === 0) usage();
  // a count of samples: 00 is zero too, and would skip both endpoint checks
  if (!/^[0-9]+$/.test(retries) || !Number.isSafeInteger(Number(retries)) || Number(retries) < 1) usage();
  const samples = Number(retries);

  if (GIT === null) {
    warn("safe-bisect: git is not on PATH");
    return 69;
  }
  const top = git(["rev-parse", "--show-toplevel"]);
  if (top.status !== 0 || !firstLine(top)) {
    warn("safe-bisect: not inside a git repository");
    return 69;
  }
  const repo = firstLine(top);
  const commit = (rev, label) => {
    const found = git(["-C", repo, "rev-parse", "--verify", `${rev}^{commit}`]);
    if (found.status !== 0) {
      warn(`safe-bisect: ${label} revision is not a commit: ${rev}`);
      throw new Exit(65);
    }
    return firstLine(found);
  };
  const goodSha = commit(good, "good");
  const badSha = commit(bad, "bad");
  if (git(["-C", repo, "merge-base", "--is-ancestor", goodSha, badSha]).status !== 0) {
    warn("safe-bisect: good revision must be an ancestor of bad revision");
    return 65;
  }

  let tmpRoot;
  try {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "luciazero-bisect."));
  } catch {
    return 70;
  }
  const worktree = path.join(tmpRoot, "worktree");
  // Kept outside the bisected tree, so old revisions cannot replace it.
  const runner = path.join(tmpRoot, "run-criterion.cjs");
  const criterion = path.join(tmpRoot, "criterion.json");
  let bisectActive = false;
  let worktreeAdded = false;
  try {
    if (git(["-C", repo, "worktree", "add", "--detach", worktree, badSha]).status !== 0) {
      warn("safe-bisect: could not create temporary worktree");
      return 70;
    }
    worktreeAdded = true;
    await checkpoint();
    fs.copyFileSync(__filename, runner);
    fs.writeFileSync(criterion, JSON.stringify(argv));

    const checkout = (rev) => {
      if (git(["-C", worktree, "checkout", "--detach", "--quiet", rev], { stdio: "inherit" }).status !== 0) {
        throw new Exit(70);
      }
    };
    const sample = async (rev, expect) => {
      checkout(rev);
      for (let n = 1; n <= samples; n += 1) {
        const spec = command(argv, worktree);
        let rc = spec === null ? startError(argv, null, true)
          : await launch(spec, { cwd: worktree, stdio: ["inherit", "ignore", "ignore"], windowsHide: true },
            (error) => startError(argv, error, true));
        rc = finish(rc, worktree, true);
        await checkpoint();
        if (rc >= 128 || rc === 125) {
          warn(`safe-bisect: ${expect} endpoint could not be evaluated (exit ${rc})`);
          throw new Exit(66);
        }
        if (expect === "good" && rc !== 0) {
          warn(`safe-bisect: known-good endpoint failed on sample ${n}; criterion is unstable or the endpoint is wrong`);
          throw new Exit(67);
        }
        if (expect === "bad" && rc === 0) {
          warn(`safe-bisect: known-bad endpoint passed on sample ${n}; criterion is unstable or the endpoint is wrong`);
          throw new Exit(67);
        }
      }
    };

    await sample(goodSha, "good");
    await sample(badSha, "bad");
    checkout(badSha);

    if (git(["-C", worktree, "bisect", "start", badSha, goodSha], { stdio: ["ignore", "ignore", "inherit"] }).status !== 0) {
      return 70;
    }
    bisectActive = true;
    // `git bisect run` gets the runner and a file holding COMMAND, never
    // COMMAND itself: it passes its arguments through a shell, which on
    // Windows is Git's own and may rewrite one that looks like a path.
    const log = path.join(tmpRoot, "bisect.log");
    const fd = fs.openSync(log, "w");
    let bisectRc;
    try {
      bisectRc = await wait(
        spawn(GIT, ["-C", worktree, "bisect", "run", process.execPath, runner, RUNNER_FLAG, criterion],
          { stdio: ["inherit", fd, fd], windowsHide: true }),
        () => 127);
    } finally {
      fs.closeSync(fd);
    }
    await checkpoint();
    say(fs.readFileSync(log, "utf8").replace(/\n+$/, ""));
    if (bisectRc !== 0) {
      warn(`safe-bisect: git bisect could not identify a unique first bad commit (exit ${bisectRc})`);
      return bisectRc;
    }

    // `git bisect run` may leave HEAD at the last tested good revision. The bad
    // ref is the authoritative result after a successful run.
    const first = git(["-C", worktree, "rev-parse", "refs/bisect/bad"]);
    if (first.status !== 0) return 70;
    const firstBad = firstLine(first);
    const summary = firstLine(git(["-C", worktree, "show", "-s", "--format=%h %an — %s", firstBad]));
    say(`FIRST_BAD ${firstBad}`);
    say(`SUMMARY ${summary}`);
    return 0;
  } finally {
    if (bisectActive && fs.existsSync(worktree)) git(["-C", worktree, "bisect", "reset"], { stdio: "ignore" });
    if (worktreeAdded) git(["-C", repo, "worktree", "remove", "--force", worktree], { stdio: "ignore" });
    try {
      fs.rmSync(tmpRoot, { recursive: true, force: true });
    } catch {
      // a file still held open on Windows; the prune below forgets the tree
    }
    git(["-C", repo, "worktree", "prune"], { stdio: "ignore" });
  }
}

if (process.argv[2] === RUNNER_FLAG) {
  process.exitCode = runCriterion(process.argv[3]);
} else {
  main(process.argv.slice(2)).then(
    (code) => {
      process.exitCode = stopped || code;
    },
    (error) => {
      if (error instanceof Exit) {
        process.exitCode = error.code;
        return;
      }
      warn(`safe-bisect: ${error && error.message ? error.message : error}`);
      process.exitCode = 70;
    },
  );
}
