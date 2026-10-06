#!/usr/bin/env node
// Enforcement-pack statusline (Claude Code only; installed by `install.sh
// --with-hooks` or `luciazero --with-hooks`). Shows: model | git branch |
// verify status from the state that luciazero-verify.cjs maintains — so the
// doctrine's ground truth is visible at a glance instead of remembered.
//
//   ✅ verify 3m     last verify-ish command succeeded, 3 minutes ago
//   ❌ verify RED    last verify-ish command failed
//   ✳ verify ran     a verify ran but its result was unreadable
//   ✎ unverified     edits happened after the last verify run
//   — no verify yet  nothing tracked this session
//
// Requires Node. Fails open to a minimal line.
"use strict";

const childProcess = require("child_process");
const fs = require("fs");
const path = require("path");
const { stateBase, stateKey, trustedBase, readStdin } = require("./luciazero-verify.cjs");

function age(ts) {
  const s = Math.trunc((Date.now() - ts) / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h`;
}

function line(input) {
  let d;
  try {
    d = JSON.parse(input);
  } catch {
    d = {};
  }
  if (d === null || typeof d !== "object" || Array.isArray(d)) return null;
  const pick = (value) => (typeof value === "string" && value ? value : "");
  const model = (d.model && typeof d.model === "object" && pick(d.model.display_name)) || "claude";
  const cwd = (d.workspace && typeof d.workspace === "object" && pick(d.workspace.current_dir))
    || pick(d.cwd) || process.cwd();

  const base = stateBase();
  const state = trustedBase(base) ? path.join(base, stateKey(cwd)) : null;
  const mtime = (name) => {
    if (state === null) return null;
    try {
      return fs.statSync(path.join(state, name)).mtimeMs;
    } catch {
      return null;
    }
  };

  const ve = mtime("last_verify");
  const ed = mtime("last_edit");
  let verify;
  if (ve === null && ed === null) {
    verify = "— no verify yet";
  } else if (ve === null || (ed !== null && ed > ve)) {
    verify = "✎ unverified";
  } else {
    let status;
    try {
      status = fs.readFileSync(path.join(state, "last_verify"), "utf8").trim();
    } catch {
      status = "ran";
    }
    if (status === "ok") verify = `✅ verify ${age(ve)}`;
    else if (status === "fail") verify = `❌ verify RED ${age(ve)}`;
    else verify = `✳ verify ran ${age(ve)}`;
  }

  let branch = "";
  try {
    const result = childProcess.spawnSync("git", ["-C", cwd, "branch", "--show-current"], {
      encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], windowsHide: true, timeout: 5000,
    });
    if (result.status === 0) branch = (result.stdout || "").trim();
  } catch {}
  return branch ? `${model} | ${branch} | ${verify}` : `${model} | ${verify}`;
}

let text = null;
try {
  text = line(readStdin());
} catch {}
process.stdout.write((text || "claude") + "\n");
