#!/usr/bin/env node
// Thin router to the bundled installers. Everything happens only when the
// user explicitly runs `npx luciazero` — this package has no lifecycle scripts.
// On Windows, which has no Bash to run them with, the four installer routes run
// bin/lib/installer.js instead: the same steps in Node, held to the Bash ones
// by tests/installer_parity.py.
//
//   npx luciazero [--with-hooks|--status]   -> install.sh (Claude Code)
//   npx luciazero codex                     -> install-codex.sh
//   npx luciazero uninstall                 -> uninstall.sh
//   npx luciazero uninstall-codex           -> uninstall-codex.sh
//   npx luciazero discipline [options]       -> local stats report
//   npx luciazero check-update [--json]       -> explicit npm version check
//   npx luciazero update                      -> update detected classic installs
//   npx luciazero global-install [--yes]       -> persistent user-owned CLI
//   npx luciazero bus status [--json]         -> Agent Bus queue summary (beta)
//   npx luciazero relay <subcommand> [...]    -> Lucia Relay (draft, finalize, inspect, consume, ...)
const { spawnSync } = require("node:child_process");
const { onPathOnly, windowsPython } = require("./lib/winexec.js");
const path = require("node:path");

const installer = (script, command) => process.platform === "win32"
  ? { runtime: process.execPath, script: "bin/lib/installer.js", args: [command] }
  : { runtime: "bash", script };

const ROUTES = {
  install: installer("install.sh", "claude"),
  codex: installer("install-codex.sh", "codex"),
  uninstall: installer("uninstall.sh", "claude-uninstall"),
  "uninstall-codex": installer("uninstall-codex.sh", "codex-uninstall"),
  discipline: { runtime: process.execPath, script: "bin/discipline-report.js" },
  "check-update": { runtime: process.execPath, script: "bin/update.js", args: ["check"] },
  update: { runtime: process.execPath, script: "bin/update.js", args: ["update"] },
  "global-install": { runtime: process.execPath, script: "bin/global.js", args: ["install"] },
  "global-status": { runtime: process.execPath, script: "bin/global.js", args: ["status"] },
  "global-uninstall": { runtime: process.execPath, script: "bin/global.js", args: ["uninstall"] },
  bus: { runtime: process.execPath, script: "bin/bus.js" },
  // On Windows the interpreter is probed for instead (windowsPython).
  relay: { runtime: "python3", python: 9, script: "skills/lucia-relay/scripts/relay.py" },
};

const args = process.argv.slice(2);
let route = "install";
if (args[0] && !args[0].startsWith("-")) {
  if (!Object.prototype.hasOwnProperty.call(ROUTES, args[0])) {
    console.error(
      `luciazero: unknown command '${args[0]}' ` +
      "(install, codex, discipline, check-update, update, global-install, global-status, global-uninstall, bus, relay, uninstall, uninstall-codex)"
    );
    process.exit(64);
  }
  route = args.shift();
}
const selected = ROUTES[route];
const script = path.join(__dirname, "..", selected.script);

// On Windows a bare runtime name comes from PATH's absolute entries alone:
// spawnSync would look in the working directory first, which for `relay` is
// the repository being relayed. Only a program is taken, never a batch file.
let runtime = selected.runtime;
let lead = [];
if (process.platform === "win32" && selected.python) {
  const python = windowsPython(selected.python);
  if (python === null) {
    console.error(`luciazero: ${route} needs Python 3.${selected.python} or newer, and none of python3, python or py -3 on PATH is`);
    process.exit(1);
  }
  [runtime, ...lead] = python;
} else if (process.platform === "win32" && !path.isAbsolute(runtime)) {
  runtime = onPathOnly(runtime, { exts: [".exe"] });
  if (runtime === null) {
    console.error(`luciazero: could not run ${selected.runtime}: it is not on PATH`);
    process.exit(1);
  }
}
const result = spawnSync(runtime, [...lead, script, ...(selected.args || []), ...args], { stdio: "inherit" });
if (result.error) {
  console.error(`luciazero: could not run ${path.basename(selected.runtime)}: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status === null ? 1 : result.status);
