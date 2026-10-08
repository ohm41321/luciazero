"use strict";
// bin/global.js on Windows, where npm is npm.cmd, its global prefix is
// already on Path, and there is no shell config file to edit. A fake npm.cmd
// first on Path records every call and answers `npm prefix --global`, so
// nothing reaches the real npm or the real prefix. macOS and Linux keep their
// user-owned prefix and PATH block; the packaging gate covers those.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { ROOT, WINDOWS, sandbox, node } = require("./sandbox.js");

const ROUTER = path.join(ROOT, "bin", "luciazero.js");

test("on Windows, global-install, -status and -uninstall use npm's own prefix", { skip: !WINDOWS && "Windows only; the packaging gate covers the POSIX prefix and PATH block" }, (t) => {
  const box = sandbox(t);
  const fake = path.join(box.box, "fake npm");
  const prefix = path.join(box.box, "npm prefix"); // a space, as under C:\Users\First Last
  const log = path.join(box.box, "npm.log");
  fs.mkdirSync(fake);
  fs.mkdirSync(prefix);
  fs.writeFileSync(path.join(fake, "npm.cmd"), [
    "@echo off",
    'echo %*>>"%LZ_FAKE_NPM_LOG%"',
    'if "%1"=="prefix" echo %LZ_FAKE_NPM_PREFIX%',
    "exit /b 0",
    "",
  ].join("\r\n"));
  const key = Object.keys(box.env).find((name) => name.toUpperCase() === "PATH") || "Path";
  const env = { ...box.env, LZ_FAKE_NPM_LOG: log, LZ_FAKE_NPM_PREFIX: prefix, [key]: `${fake};${box.env[key] || ""}` };
  const calls = () => fs.readFileSync(log, "utf8").split(/\r?\n/).filter(Boolean).map((line) => line.trim());

  const before = node(env, [ROUTER, "global-status"]);
  assert.strictEqual(before.status, 1, `global-status with nothing installed exited ${before.status}\n${before.stderr}`);
  assert.match(before.stderr, /MISS .*luciazero\.cmd/);
  assert.deepStrictEqual(calls(), ["prefix --global"], "global-status ran more than npm prefix");

  const installed = node(env, [ROUTER, "global-install", "--yes"]);
  assert.strictEqual(installed.status, 0, installed.stderr);
  assert.deepStrictEqual(calls().slice(1), ["prefix --global", "install --global luciazero@latest"]);
  assert.match(installed.stdout, /is not on your Path/, "a prefix missing from Path went unreported");

  fs.writeFileSync(path.join(prefix, "luciazero.cmd"), "@echo off\r\n");
  const onPath = { ...env, [key]: `${env[key]};${prefix}\\` };
  const after = node(onPath, [ROUTER, "global-status"]);
  assert.strictEqual(after.status, 0, after.stderr);
  assert.match(after.stdout, /installed globally in /);

  const removed = node(onPath, [ROUTER, "global-uninstall", "--yes"]);
  assert.strictEqual(removed.status, 0, removed.stderr);
  assert.deepStrictEqual(calls().slice(-1), ["uninstall --global luciazero"]);
  for (const rc of [".zshrc", ".bashrc", ".profile"]) {
    assert.ok(!fs.existsSync(path.join(box.home, rc)), `${rc} was written on Windows`);
  }
});
