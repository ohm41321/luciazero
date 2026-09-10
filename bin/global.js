#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");
const { spawnSync } = require("node:child_process");

const START = "# luciazero:start global-npm-path";
const END = "# luciazero:end global-npm-path";
const BODY = `${START}\nexport PATH="$HOME/.local/npm/bin:$PATH"\n${END}\n`;

function locations(env = process.env) {
  const home = env.HOME || os.homedir();
  if (!path.isAbsolute(home)) throw new Error("HOME must be an absolute path");
  const shell = path.basename(env.SHELL || "");
  const rcName = shell === "zsh" ? ".zshrc" : shell === "bash" ? ".bashrc" : null;
  if (!rcName) throw new Error("supported shells are zsh and bash; set SHELL to the shell whose PATH should be updated");
  return { home, prefix: path.join(home, ".local", "npm"), rc: path.join(home, rcName) };
}

function readRc(file) {
  try {
    const stat = fs.lstatSync(file);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`${file} is not a regular file; left untouched`);
    return { text: fs.readFileSync(file, "utf8"), mode: stat.mode & 0o777 };
  } catch (error) {
    if (error.code === "ENOENT") return { text: "", mode: 0o600 };
    throw error;
  }
}

function nextRc(current, remove = false) {
  const starts = current.split(START).length - 1;
  const ends = current.split(END).length - 1;
  if (starts !== ends || starts > 1) throw new Error("shell config has malformed Luciazero PATH markers; left untouched");
  if (starts === 1) {
    const begin = current.indexOf(START);
    const finish = current.indexOf("\n", current.indexOf(END, begin));
    const owned = current.slice(begin, finish < 0 ? current.length : finish + 1);
    if (owned !== BODY) throw new Error("shell config has a customized Luciazero PATH block; left untouched");
    if (remove) return current.slice(0, begin) + current.slice(begin + owned.length);
    return current;
  }
  if (remove) return current;
  const separator = current.length && !current.endsWith("\n") ? "\n" : "";
  return current + separator + BODY;
}

function writeRc(file, text, mode) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const tmp = path.join(path.dirname(file), `.${path.basename(file)}.luciazero-${process.pid}-${Date.now()}`);
  const fd = fs.openSync(tmp, "wx", mode);
  try {
    // open(2)'s requested mode is filtered by umask.  This is a replacement
    // for an existing user file, so restore its exact permission bits before
    // publishing the temporary file with rename(2).
    fs.fchmodSync(fd, mode);
    fs.writeFileSync(fd, text, "utf8");
    fs.fsyncSync(fd);
    fs.closeSync(fd);
    fs.renameSync(tmp, file);
  } catch (error) {
    try { fs.closeSync(fd); } catch {}
    try { fs.unlinkSync(tmp); } catch {}
    throw error;
  }
}

function npm(args, env = process.env) {
  const result = spawnSync("npm", args, { stdio: "inherit", env });
  if (result.error) throw new Error(`could not run npm: ${result.error.message}`);
  if (result.status !== 0) throw new Error(`npm exited ${result.status === null ? "without a status" : result.status}`);
}

function confirm(question) {
  if (!process.stdin.isTTY) return Promise.resolve(false);
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => rl.question(`${question} [y/N] `, (answer) => {
    rl.close();
    resolve(/^y(?:es)?$/i.test(answer.trim()));
  }));
}

async function install(args) {
  if (args.includes("--help")) {
    console.log("Usage: luciazero global-install [--yes]\nInstalls luciazero@latest under ~/.local/npm and adds its bin to PATH.");
    return 0;
  }
  const unknown = args.filter((arg) => arg !== "--yes");
  if (unknown.length) throw new Error(`unknown option: ${unknown[0]}`);
  const place = locations();
  const before = readRc(place.rc);
  const after = nextRc(before.text);
  if (!args.includes("--yes") && !await confirm(`Install luciazero@latest globally in ${place.prefix}?`)) {
    console.error("global install cancelled; nothing changed");
    return 1;
  }
  npm(["install", "--global", "--prefix", place.prefix, "luciazero@latest"]);
  if (after !== before.text) {
    try {
      writeRc(place.rc, after, before.mode);
    } catch (error) {
      throw new Error(
        `the package was installed, but PATH was not changed: ${error.message}. ` +
        `Run ${path.join(place.prefix, "bin", "luciazero")} directly or retry global-install`
      );
    }
  }
  console.log(`luciazero installed globally in ${place.prefix}`);
  console.log(`PATH recorded in ${place.rc}; start a new shell or source that file`);
  return 0;
}

function status(args) {
  if (args.includes("--help")) {
    console.log("Usage: luciazero global-status\nChecks the user-owned global command and its shell PATH block.");
    return 0;
  }
  if (args.length) throw new Error(`unknown option: ${args[0]}`);
  const place = locations();
  const command = path.join(place.prefix, "bin", "luciazero");
  let commandOk = false;
  try {
    const commandStat = fs.statSync(command);
    commandOk = commandStat.isFile() && Boolean(commandStat.mode & 0o111);
  } catch {}
  let pathOk = false;
  try {
    const current = readRc(place.rc).text;
    pathOk = nextRc(current) === current;
  } catch (error) {
    console.error(`luciazero: ${error.message}`);
    return 1;
  }
  if (!commandOk || !pathOk) {
    if (!commandOk) console.error(`MISS  ${command}`);
    if (!pathOk) console.error(`MISS  Luciazero PATH block in ${place.rc}`);
    return 1;
  }
  console.log(`luciazero is installed globally in ${place.prefix}`);
  console.log(`PATH is recorded in ${place.rc}`);
  return 0;
}

async function uninstall(args) {
  if (args.includes("--help")) {
    console.log("Usage: luciazero global-uninstall [--yes]\nRemoves the global npm package and only Luciazero's exact PATH block.");
    return 0;
  }
  const unknown = args.filter((arg) => arg !== "--yes");
  if (unknown.length) throw new Error(`unknown option: ${unknown[0]}`);
  const place = locations();
  const before = readRc(place.rc);
  const after = nextRc(before.text, true);
  if (!args.includes("--yes") && !await confirm(`Uninstall global luciazero from ${place.prefix}?`)) {
    console.error("global uninstall cancelled; nothing changed");
    return 1;
  }
  npm(["uninstall", "--global", "--prefix", place.prefix, "luciazero"]);
  if (after !== before.text) {
    try {
      writeRc(place.rc, after, before.mode);
    } catch (error) {
      throw new Error(
        `the package was removed, but its PATH block remains in ${place.rc}: ${error.message}. ` +
        `Remove only the lines from '${START}' through '${END}'`
      );
    }
  }
  console.log(`global luciazero removed from ${place.prefix}`);
  return 0;
}

async function main(argv) {
  const [command, ...args] = argv;
  if (command === "install") return install(args);
  if (command === "status") return status(args);
  if (command === "uninstall") return uninstall(args);
  throw new Error(`${command || "command"} is not implemented`);
}

if (require.main === module) {
  main(process.argv.slice(2)).then((code) => { process.exitCode = code; }).catch((error) => {
    console.error(`luciazero: ${error.message}`);
    process.exitCode = 1;
  });
}

module.exports = { BODY, locations, nextRc, readRc, writeRc };
