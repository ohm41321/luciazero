"use strict";
// A throwaway home for one test: every directory an installer or hook may
// write -- the Claude and Codex config, HOME and USERPROFILE, the temporary
// directory the hooks keep state in, the service root -- points inside it,
// and every LUCIAZERO_* setting of the machine running the tests is dropped,
// as ./test.sh drops them. Nothing here may resolve a path under the real
// home directory.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");

const ROOT = path.resolve(__dirname, "..", "..");
const WINDOWS = process.platform === "win32";

function sandbox(t) {
  const box = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "lz-node-")));
  const dirs = {
    box,
    home: path.join(box, "home"),
    claude: path.join(box, "home", ".claude"),
    codex: path.join(box, "home", ".codex"),
    tmp: path.join(box, "tmp"),
    services: path.join(box, "no-service"),
  };
  for (const dir of [dirs.home, dirs.tmp]) fs.mkdirSync(dir, { recursive: true });
  const env = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (!key.startsWith("LUCIAZERO_")) env[key] = value;
  }
  Object.assign(env, {
    HOME: dirs.home,
    USERPROFILE: dirs.home,
    CLAUDE_CONFIG_DIR: dirs.claude,
    CODEX_HOME: dirs.codex,
    TMPDIR: dirs.tmp,
    TEMP: dirs.tmp,
    TMP: dirs.tmp,
    LUCIAZERO_SERVICE_ROOT: dirs.services,
  });
  if (t) t.after(() => fs.rmSync(box, { recursive: true, force: true }));
  return { ...dirs, env };
}

// Run `node <args>` to completion with `input` on stdin.
function node(env, args, input = "") {
  const r = spawnSync(process.execPath, args, { env, input, encoding: "utf8", windowsHide: true });
  if (r.error) throw r.error;
  return { status: r.status, stdout: r.stdout, stderr: r.stderr };
}

// Run `node <args>`, writing `input` only after `delayMs`: a hook must wait
// for input that arrives after it starts.
function nodeLate(env, args, input, delayMs) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, { env, stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => (stdout += d));
    child.stderr.on("data", (d) => (stderr += d));
    child.stdin.on("error", () => {}); // a reader that quit early is the failure under test
    child.on("error", reject);
    child.on("close", (status) => resolve({ status, stdout, stderr }));
    setTimeout(() => {
      const bytes = Buffer.from(input, "utf8");
      // split inside the input, so a reader must join chunks
      const cut = Math.floor(bytes.length / 2);
      child.stdin.write(bytes.subarray(0, cut));
      setTimeout(() => child.stdin.end(bytes.subarray(cut)), 100);
    }, delayMs);
  });
}

module.exports = { ROOT, WINDOWS, sandbox, node, nodeLate };
