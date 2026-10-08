#!/usr/bin/env node
// Read-only evidence scan for ready Phase 1.
// Prints what exists in a repo — docs, manifests, script/target names, CI run
// lines, test dirs, workspace markers. It surfaces candidates only; it never
// picks the verify command. Judgment stays with the agent.
//
// Usage: node detect.cjs [repo-root]   (default: current directory)
// Exits 0 unless the target directory does not exist; absence of a section
// means nothing was found.
//
// Node and git only, so it runs the same on Windows, macOS and Linux. It is
// self-contained: a skill is installed as a directory of its own, so nothing
// outside this file can be required.
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const out = [];
const say = (line) => out.push(line);
const hr = (title) => out.push("", `== ${title} ==`);

const isFile = (p) => {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
};
const read = (p) => fs.readFileSync(p, "utf8");
const lines = (text) => text.split("\n").map((line) => line.replace(/\r$/, ""));
// git by its full path on Windows, where a bare name would be looked for
// first in the working directory: the repository being scanned. Only absolute
// PATH entries are searched, and a batch file needs a shell to start, so only
// a program counts.
function gitExecutable() {
  if (process.platform !== "win32") return "git";
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
const git = (...args) => (GIT === null
  ? { status: 127, stdout: "" }
  : spawnSync(GIT, args, { encoding: "utf8", windowsHide: true }));

// The directory as the caller's shell names it: through the symlink it was
// reached by, as `pwd` would print it, when the shell's own record agrees.
function callerCwd() {
  const pwd = process.env.PWD;
  if (pwd && process.platform !== "win32" && path.isAbsolute(pwd)) {
    try {
      if (fs.realpathSync(pwd) === fs.realpathSync(process.cwd())) return pwd;
    } catch {
      // fall through to the physical directory
    }
  }
  return process.cwd();
}

const given = process.argv[2] ? process.argv[2] : ".";
const repo = path.resolve(callerCwd(), given);
try {
  process.chdir(repo);
} catch {
  process.stderr.write(`detect: no such directory: ${given}\n`);
  process.exit(1);
}

hr(`repo: ${repo}`);
if (GIT === null) {
  say("git repo: UNKNOWN — git is not on PATH");
} else if (git("rev-parse", "--git-dir").status === 0) {
  const top = git("rev-parse", "--show-toplevel");
  say(`git repo: yes (toplevel: ${top.status === 0 ? top.stdout.replace(/\r?\n$/, "") : ""})`);
  const tracked = git("ls-files", "-z", "--", ".");
  if (!tracked.stdout) {
    say("  WARNING: no tracked files under this dir — it may just sit inside an unrelated repo; revert/stash will not protect it");
  }
} else {
  say("git repo: NO — no safe revert, stash, or bisect until 'git init' (ask first)");
}

hr("docs");
for (const f of ["README", "README.md", "README.rst", "CONTRIBUTING.md", "AGENTS.md", "CLAUDE.md", "docs"]) {
  if (fs.existsSync(f)) say(`exists: ${f}`);
}

hr("manifests");
for (const f of ["package.json", "pyproject.toml", "setup.py", "tox.ini", "noxfile.py", "Makefile",
  "justfile", "Justfile", "Cargo.toml", "go.mod", "build.gradle", "build.gradle.kts",
  "pom.xml", "composer.json", "Gemfile", "mix.exs", "CMakeLists.txt", "Package.swift"]) {
  if (isFile(f)) say(`exists: ${f}`);
}

if (isFile("package.json")) {
  hr("package.json scripts");
  try {
    const scripts = JSON.parse(read("package.json")).scripts ?? {};
    if (typeof scripts !== "object" || Array.isArray(scripts)) throw new Error("scripts is not an object");
    for (const [name, command] of Object.entries(scripts)) {
      say(`  ${name}: ${typeof command === "string" ? command : JSON.stringify(command)}`);
    }
  } catch {
    say("  (unparseable package.json)");
  }
}

if (isFile("Makefile")) {
  hr("Makefile targets");
  lines(read("Makefile"))
    .filter((line) => /^[A-Za-z0-9_.-]+:/.test(line))
    .slice(0, 30)
    .forEach((line) => say(`  ${line.split(":")[0]}`));
}

for (const j of ["justfile", "Justfile"]) {
  if (isFile(j)) {
    hr(`${j} recipes`);
    lines(read(j))
      .filter((line) => /^[A-Za-z0-9_-]+.*:/.test(line))
      .slice(0, 30)
      .forEach((line) => say(`  ${line}`));
  }
}

// A shell glob: sorted, and blind to names that start with a dot.
function glob(dir, ext) {
  let names;
  try {
    names = fs.readdirSync(dir);
  } catch {
    return [];
  }
  return names.filter((n) => !n.startsWith(".") && n.endsWith(ext)).sort().map((n) => `${dir}/${n}`);
}

hr("ci — whatever CI runs is the honest verify command; read these files yourself");
for (const c of [...glob(".github/workflows", ".yml"), ...glob(".github/workflows", ".yaml"),
  ".gitlab-ci.yml", ".circleci/config.yml"]) {
  if (!isFile(c)) continue;
  say(`file: ${c}`);
  lines(read(c))
    .map((line, i) => [i + 1, line])
    .filter(([, line]) => /^[ \t\v\f\r]*(-[ \t\v\f\r]+)?(run|script)[ \t\v\f\r]*:/.test(line))
    .slice(0, 30)
    .forEach(([n, line]) => say(`  ${n}:${line}`));
}

// `find . -maxdepth 2`, never entering or reporting the pruned names, and
// never following a link: depth-first, each directory's entries in order.
const PRUNED = new Set([".git", "node_modules", ".venv", "vendor"]);
function walk(dir, depth, visit) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  entries.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  for (const entry of entries) {
    if (PRUNED.has(entry.name)) continue;
    const shown = `${dir}/${entry.name}`;
    visit(entry, shown);
    if (entry.isDirectory() && depth < 2) walk(shown, depth + 1, visit);
  }
}

hr("test dirs / files (top two levels)");
const testDirs = [];
const testFiles = [];
walk(".", 1, (entry, shown) => {
  if (entry.isDirectory() && ["tests", "test", "spec", "__tests__"].includes(entry.name)) testDirs.push(shown);
  if (entry.isFile() && /^(.*_test\..*|test_.*\..*|.*\.test\..*|.*\.spec\..*)$/s.test(entry.name)) testFiles.push(shown);
});
testDirs.slice(0, 10).forEach((p) => say(`  ${p}`));
testFiles.slice(0, 10).forEach((p) => say(`  ${p}`));

hr("workspace / monorepo markers");
for (const f of ["pnpm-workspace.yaml", "turbo.json", "nx.json", "lerna.json", "go.work"]) {
  if (isFile(f)) say(`exists: ${f}`);
}
if (isFile("package.json") && read("package.json").includes('"workspaces"')) say("package.json declares workspaces");
if (isFile("Cargo.toml") && lines(read("Cargo.toml")).some((line) => line.startsWith("[workspace]"))) {
  say("Cargo.toml declares [workspace]");
}

process.stdout.write(`${out.join("\n")}\n`);
