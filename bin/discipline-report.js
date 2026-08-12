#!/usr/bin/env node
"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

function usage(message) {
  if (message) console.error(`luciazero discipline: ${message}`);
  console.error("usage: luciazero discipline [--days N] [--project PATH_OR_ID] [--json] [--log FILE] [--now ISO]");
  process.exit(64);
}

const options = { days: 30, project: null, json: false, log: null, now: new Date() };
const argv = process.argv.slice(2);
for (let index = 0; index < argv.length; index += 1) {
  const arg = argv[index];
  if (arg === "--json") options.json = true;
  else if (arg === "--days") {
    const value = argv[++index];
    if (!value || !/^\d+$/.test(value) || Number(value) < 1) usage("--days requires a positive integer");
    options.days = Number(value);
  } else if (arg === "--project") {
    options.project = argv[++index];
    if (!options.project) usage("--project requires a value");
  } else if (arg === "--log") {
    options.log = argv[++index];
    if (!options.log) usage("--log requires a file");
  } else if (arg === "--now") {
    const value = argv[++index];
    options.now = new Date(value || "");
    if (Number.isNaN(options.now.valueOf())) usage("--now requires an ISO-8601 timestamp");
  } else usage(`unknown option: ${arg}`);
}

const configDir = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
options.log = path.resolve(options.log || path.join(configDir, "luciazero-stats.log"));

function projectId(projectPath) {
  let normalized = path.resolve(projectPath);
  try { normalized = fs.realpathSync(normalized); } catch (_) { /* path may be remote */ }
  return crypto.createHash("sha256").update(normalized).digest("hex").slice(0, 12);
}

function parseLine(line) {
  const trimmed = line.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("{")) {
    let row;
    try { row = JSON.parse(trimmed); } catch (_) { return { malformed: true }; }
    if (row.schema !== 2 || !["stop-clean", "nudge", "strict-block"].includes(row.event)) {
      return { malformed: true };
    }
    const timestamp = new Date(row.timestamp);
    if (Number.isNaN(timestamp.valueOf()) || typeof row.project_id !== "string" || typeof row.project !== "string") {
      return { malformed: true };
    }
    return {
      timestamp,
      event: row.event,
      project: row.project,
      projectId: row.project_id,
      verifyMode: ["regex", "exact", "strict"].includes(row.verify_mode) ? row.verify_mode : "unknown",
      legacy: false,
    };
  }
  const match = trimmed.match(/^(\S+)\s+(stop-clean|nudge|strict-block)\s+(.+)$/);
  if (!match) return { malformed: true };
  const timestamp = new Date(match[1]);
  if (Number.isNaN(timestamp.valueOf())) return { malformed: true };
  return {
    timestamp,
    event: match[2],
    project: match[3],
    projectId: `legacy-${crypto.createHash("sha256").update(match[3]).digest("hex").slice(0, 12)}`,
    verifyMode: "unknown",
    legacy: true,
  };
}

let content = "";
try {
  content = fs.readFileSync(options.log, "utf8");
} catch (error) {
  if (error.code !== "ENOENT") {
    console.error(`luciazero discipline: cannot read ${options.log}: ${error.message}`);
    process.exit(1);
  }
}

const cutoff = new Date(options.now.valueOf() - options.days * 86400 * 1000);
let malformed = 0;
let legacyRecords = 0;
let rows = [];
for (const line of content.split(/\r?\n/)) {
  const row = parseLine(line);
  if (!row) continue;
  if (row.malformed) { malformed += 1; continue; }
  if (row.timestamp < cutoff || row.timestamp > options.now) continue;
  if (row.legacy) legacyRecords += 1;
  rows.push(row);
}

if (options.project) {
  const raw = options.project;
  const looksLikePath = raw === "." || raw.includes(path.sep) || fs.existsSync(raw);
  const id = looksLikePath ? projectId(raw) : raw;
  rows = rows.filter((row) => row.projectId === id || row.project === raw);
}

const counts = { "stop-clean": 0, nudge: 0, "strict-block": 0 };
const modes = { regex: 0, exact: 0, strict: 0, unknown: 0 };
const projects = new Map();
for (const row of rows) {
  counts[row.event] += 1;
  modes[row.verifyMode] = (modes[row.verifyMode] || 0) + 1;
  const current = projects.get(row.projectId) || {
    project: row.project,
    project_id: row.projectId,
    clean: 0,
    nudges: 0,
    strict_blocks: 0,
  };
  if (row.event === "stop-clean") current.clean += 1;
  if (row.event === "nudge") current.nudges += 1;
  if (row.event === "strict-block") current.strict_blocks += 1;
  projects.set(row.projectId, current);
}

const total = rows.length;
const topNudged = [...projects.values()]
  .filter((item) => item.nudges > 0)
  .sort((a, b) => b.nudges - a.nudges || a.project_id.localeCompare(b.project_id));
const recommendations = [];
if (counts.nudge > 0) {
  if (modes.regex > 0) {
    recommendations.push(
      `Likely: establish a fast repo-owned verify command and run it after edits. ${counts.nudge} nudge(s) occurred, including sessions using regex detection; set LUCIAZERO_VERIFY_CMD only after the command is proven.`
    );
  } else {
    recommendations.push(`Likely: make the configured verify command faster or easier to run; ${counts.nudge} edit session(s) ended without a recognized later verification.`);
  }
}
if (counts["strict-block"] > 0) {
  recommendations.push(`Investigate the configured strict command: it returned red at ${counts["strict-block"]} stop attempt(s).`);
}
if (total > 0 && recommendations.length === 0) {
  recommendations.push("No recurring gap is supported by the selected records.");
}

const report = {
  schema: 1,
  generated_at: options.now.toISOString(),
  period: { days: options.days, from: cutoff.toISOString(), to: options.now.toISOString() },
  filter: { project: options.project },
  source: options.log,
  records: total,
  malformed_records_ignored: malformed,
  legacy_records: legacyRecords,
  outcomes: counts,
  verify_modes: modes,
  top_nudged_projects: topNudged,
  recommendations,
};

if (options.json) {
  console.log(JSON.stringify(report, null, 2));
  process.exit(0);
}

function percent(value) {
  return total === 0 ? "0.0%" : `${(value * 100 / total).toFixed(1)}%`;
}

console.log("=== Luciazero Discipline Report ===");
console.log(`Period: Last ${options.days} days (${total} session stops)`);
if (options.project) console.log(`Project filter: ${options.project}`);
console.log("");
console.log("Stop Outcomes:");
console.log(`  Clean stops:   ${String(counts["stop-clean"]).padStart(5)} (${percent(counts["stop-clean"])})`);
console.log(`  Nudges:        ${String(counts.nudge).padStart(5)} (${percent(counts.nudge)})`);
console.log(`  Strict blocks: ${String(counts["strict-block"]).padStart(5)} (${percent(counts["strict-block"])})`);
console.log("");
console.log("Top Nudged Repositories:");
if (topNudged.length === 0) console.log("  None in the selected period.");
for (const [index, item] of topNudged.entries()) {
  console.log(`  ${index + 1}. ${item.project} [${item.project_id}] — ${item.nudges} nudge(s)`);
}
console.log("");
console.log("Actionable Recommendations:");
if (recommendations.length === 0) console.log("  No evidence yet; collect more stop outcomes.");
for (const item of recommendations) console.log(`  - ${item}`);
if (legacyRecords || malformed) {
  console.log("");
  console.log(`Data notes: ${legacyRecords} legacy record(s); ${malformed} malformed record(s) ignored.`);
}
