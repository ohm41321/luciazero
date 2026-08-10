#!/usr/bin/env node
// Thin router to the bundled bash installers. Everything happens only when the
// user explicitly runs `npx luciazero` — this package has no lifecycle scripts.
//
//   npx luciazero [--with-hooks|--status]   -> install.sh (Claude Code)
//   npx luciazero codex                     -> install-codex.sh
//   npx luciazero uninstall                 -> uninstall.sh
//   npx luciazero uninstall-codex           -> uninstall-codex.sh
const { spawnSync } = require("node:child_process");
const path = require("node:path");

if (process.platform === "win32") {
  console.error(
    "luciazero needs bash (macOS, Linux, or WSL). On Windows, run it inside WSL: bash install.sh"
  );
  process.exit(1);
}

const ROUTES = {
  install: "install.sh",
  codex: "install-codex.sh",
  uninstall: "uninstall.sh",
  "uninstall-codex": "uninstall-codex.sh",
};

const args = process.argv.slice(2);
const route = Object.prototype.hasOwnProperty.call(ROUTES, args[0]) ? args.shift() : "install";
const script = path.join(__dirname, "..", ROUTES[route]);

const result = spawnSync("bash", [script, ...args], { stdio: "inherit" });
if (result.error) {
  console.error("luciazero: could not run bash: " + result.error.message);
  process.exit(1);
}
process.exit(result.status === null ? 1 : result.status);
