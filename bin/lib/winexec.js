"use strict";
// Starting a command by name on Windows without running whatever happens to
// sit in the current directory. CreateProcess, libuv's own search and cmd.exe
// all look in the working directory before PATH, so a python.exe, npm.cmd or
// claude.cmd beside the caller would be the one that runs. Here a name is
// resolved through the absolute entries of PATH alone, and a batch file is
// started by its full path through cmd.exe, the only thing that can run one.
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const WINDOWS = process.platform === "win32";

function pathValue(env) {
  const key = Object.keys(env).find((name) => name.toUpperCase() === "PATH");
  return key ? env[key] || "" : "";
}

function isFile(p) {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

// The first `name + ext` in an absolute PATH entry, trying each directory's
// extensions before the next directory as cmd.exe does, or null. A relative
// or empty entry would mean the working directory again, so it is skipped.
function onPathOnly(name, { env = process.env, exts = [""], delimiter = path.delimiter } = {}) {
  for (const dir of pathValue(env).split(delimiter)) {
    if (!dir || !path.isAbsolute(dir)) continue;
    for (const ext of exts) {
      const candidate = path.join(dir, name + ext);
      if (isFile(candidate)) return candidate;
    }
  }
  return null;
}

// spawnSync for a resolved file: an .exe directly, a .cmd or .bat through
// cmd.exe. /s takes the outer quotes off what follows /c, so the path stays
// quoted. The arguments are joined as they are, so callers pass only their
// own literals, never anything a user typed.
function runResolved(file, args, options = {}) {
  if (!/\.(cmd|bat)$/i.test(file)) return spawnSync(file, args, options);
  return spawnSync(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", `""${file}" ${args.join(" ")}"`],
    { ...options, windowsVerbatimArguments: true });
}

// Run `name` with `args`: by PATH alone on Windows, as before elsewhere. A
// name found nowhere gives the result spawnSync gives a missing program.
function runCommand(name, args, options = {}) {
  if (!WINDOWS) return spawnSync(name, args, options);
  const file = onPathOnly(name, { env: options.env || process.env, exts: [".exe", ".cmd", ".bat"] });
  if (file === null) {
    const error = Object.assign(new Error(`${name} is not on PATH`), { code: "ENOENT" });
    return { status: null, signal: null, stdout: null, stderr: null, output: null, pid: 0, error };
  }
  return runResolved(file, args, options);
}

module.exports = { onPathOnly, runResolved, runCommand };
