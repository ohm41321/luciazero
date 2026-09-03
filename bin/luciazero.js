#!/usr/bin/env node
// Thin router to the bundled bash installers. Everything happens only when the
// user explicitly runs `npx luciazero` — this package has no lifecycle scripts.
//
//   npx luciazero [--with-hooks|--status]   -> install.sh (Claude Code)
//   npx luciazero codex                     -> install-codex.sh
//   npx luciazero uninstall                 -> uninstall.sh
//   npx luciazero uninstall-codex           -> uninstall-codex.sh
//   npx luciazero discipline [options]       -> local stats report
//   npx luciazero check-update [--json]       -> explicit npm version check
//   npx luciazero update                      -> update detected classic installs
//   npx luciazero bus status [--json]         -> Agent Bus queue summary (beta)
const { spawnSync } = require("node:child_process");
const path = require("node:path");

const ROUTES = {
  install: { runtime: "bash", script: "install.sh" },
  codex: { runtime: "bash", script: "install-codex.sh" },
  uninstall: { runtime: "bash", script: "uninstall.sh" },
  "uninstall-codex": { runtime: "bash", script: "uninstall-codex.sh" },
  discipline: { runtime: process.execPath, script: "bin/discipline-report.js" },
  "check-update": { runtime: process.execPath, script: "bin/update.js", args: ["check"] },
  update: { runtime: process.execPath, script: "bin/update.js", args: ["update"] },
  bus: { runtime: process.execPath, script: "bin/bus.js" },
};

const args = process.argv.slice(2);
let route = "install";
if (args[0] && !args[0].startsWith("-")) {
  if (!Object.prototype.hasOwnProperty.call(ROUTES, args[0])) {
    console.error(
      `luciazero: unknown command '${args[0]}' ` +
      "(install, codex, discipline, check-update, update, bus, uninstall, uninstall-codex)"
    );
    process.exit(64);
  }
  route = args.shift();
}
const selected = ROUTES[route];
const script = path.join(__dirname, "..", selected.script);

if (process.platform === "win32" && selected.runtime === "bash") {
  console.error(
    "luciazero installers need bash. On Windows, run them inside WSL; 'luciazero discipline' works in native Node."
  );
  process.exit(1);
}

const result = spawnSync(selected.runtime, [script, ...(selected.args || []), ...args], { stdio: "inherit" });
if (result.error) {
  console.error("luciazero: could not run bash: " + result.error.message);
  process.exit(1);
}
process.exit(result.status === null ? 1 : result.status);
