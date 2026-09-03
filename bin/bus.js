#!/usr/bin/env node
// `npx luciazero bus status [--json]`: show what is waiting on whom in the
// local Agent Bus. Talks to the running luciazero-agentd over loopback with
// the capability token; never starts a daemon and works without one
// installed (it just reports that none is running).
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

function stateDir() {
  const env = process.env.LUCIAZERO_AGENT_BUS_HOME;
  return env ? env : path.join(os.homedir(), ".luciazero", "agent-bus");
}

// Peer-supplied strings never reach the terminal unfiltered.
const clean = (value) => String(value).replace(/[\x00-\x1f\x7f-\x9f]/g, "?");

function usage(code) {
  const out = code === 0 ? console.log : console.error;
  out("usage: luciazero bus status [--json]");
  out("  Reads endpoint.json and token from " + stateDir() + " (LUCIAZERO_AGENT_BUS_HOME).");
  process.exit(code);
}

async function status(json) {
  const dir = stateDir();
  let endpoint;
  try {
    endpoint = JSON.parse(fs.readFileSync(path.join(dir, "endpoint.json"), "utf8"));
  } catch (err) {
    console.error(`luciazero bus: no running daemon recorded in ${dir}`);
    console.error("  start one with: python3 -m luciazero_agentd serve   (from the agentd package)");
    process.exit(2);
  }
  let token;
  try {
    token = fs.readFileSync(path.join(dir, "token"), "utf8").trim();
  } catch (err) {
    console.error(`luciazero bus: cannot read the capability token in ${dir}`);
    process.exit(2);
  }
  const base = endpoint.url.replace(/\/mcp$/, "");
  let response;
  try {
    response = await fetch(base + "/status", { headers: { Authorization: `Bearer ${token}` } });
  } catch (err) {
    console.error(`luciazero bus: daemon at ${endpoint.url} is not answering (${err.message})`);
    process.exit(2);
  }
  if (!response.ok) {
    console.error(`luciazero bus: daemon answered HTTP ${response.status}`);
    process.exit(2);
  }
  const body = await response.json();
  if (json) {
    console.log(JSON.stringify(body, null, 2));
    return;
  }
  const tasks = Object.entries(body.tasks).map(([k, v]) => `${clean(k)} ${Number(v)}`).join(", ");
  console.log(`agent bus: ${clean(body.server.name)} ${clean(body.server.version)} since ${clean(body.server.started_at)}`);
  console.log(`queued deliveries: ${Number(body.queued_deliveries)}   tasks: ${tasks}`);
  for (const agent of body.agents) {
    const wt = agent.worktree;
    const where = wt ? `  on ${clean(wt.branch)}${wt.dirty ? " (dirty)" : ""}` : "";
    console.log(
      `  ${clean(agent.id).padEnd(24)} ${clean(agent.provider).padEnd(7)} ${clean(agent.role).padEnd(14)} ` +
      `inbox ${String(Number(agent.queued_deliveries)).padStart(3)}  claimed ${String(Number(agent.claimed_tasks)).padStart(3)}  seen ${clean(agent.last_seen_at)}${where}`
    );
  }
  for (const task of body.open_tasks) {
    const needs = task.requires_worktree ? "  needs worktree" : "";
    console.log(`  open task ${clean(task.id)}  p${Number(task.priority)}  ${clean(task.assigned_to || "unassigned")}: ${clean(task.title)}${needs}`);
  }
  if (Number(body.approvals_pending) > 0) {
    console.log(`approvals pending: ${Number(body.approvals_pending)} (unused nonces; each is bound to one task and operation)`);
  }
  if (body.queued_deliveries > 0 || body.tasks.open > 0) {
    console.log("next: start the agent's session and run /lucia-bus (Codex: $lucia-bus)");
  }
}

const args = process.argv.slice(2);
if (args.length === 0 || args[0] === "--help" || args[0] === "-h") usage(args.length === 0 ? 64 : 0);
if (args[0] !== "status") {
  console.error(`luciazero bus: unknown subcommand '${args[0]}'`);
  usage(64);
}
const extra = args.slice(1).filter((a) => a !== "--json");
if (extra.length > 0) {
  console.error(`luciazero bus: unknown option '${extra[0]}'`);
  usage(64);
}
if (typeof fetch !== "function") {
  console.error("luciazero bus: needs Node 18+ (global fetch)");
  process.exit(1);
}
status(args.includes("--json")).catch((err) => {
  console.error("luciazero bus: " + err.message);
  process.exit(1);
});
